import os
import gc
import sys
import math
import time
import csv
import argparse
from functools import partial
import numpy as np
import yaml
from typing import Optional, List, Tuple, Dict, Any

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from rclpy.utilities import remove_ros_args

from mavros_msgs.msg import State, PositionTarget
from mavros_msgs.srv import CommandBool, SetMode
from geometry_msgs.msg import PoseStamped, TwistStamped

import jax
import jax.numpy as jnp
jax.config.update("jax_platform_name", "cpu") # Force use of CPU since quad has no GPU
jax.config.update("jax_enable_x64", True) # Use 64 bit since all floats to be used are doubles; otherwise XLA recompilation will occur mid-flight
jax.config.update("jax_compilation_cache_dir", "/tmp/jax_cache")

from jax_resnet import resnet_network
from apark_rise_controller.proj import discrete_projection, discrete_rate_projection
from apark_rise_controller.desired_trajectory import TrajectoryGenerator

class ExperimentState:
    STATE_INIT: int = 0
    STATE_TAKEOFF: int = 1
    STATE_FOLLOW_TRAJ: int = 2

class JaxLatencyError(Exception):
    pass

class OdomTimeoutError(Exception):
    pass

class FailsafeTriggeredError(Exception):
    pass

class BoundaryBreachError(Exception):
    pass

class ExperimentFinished(Exception):
    pass

class ControlLoopOverrunError(Exception):
    pass

# --- Parameter loading ------------------------------------------------------
# This node does NOT use ROS 2 parameters. Config is a plain dict read from one
# or more YAML files named on the command line (--params-file, repeatable;
# rise_controller.launch.py passes this package's tuning YAML plus the two
# shared files from px4_telemetry / px4_safety_lib). Rules:
#   * a key the node asks for and can't find  -> hard failure at startup
#     (see AparkRiseNode._get_param)
#   * a key present in a file but never asked for -> silently ignored
# so no allow-list / exemption bookkeeping is needed the way it used to be.

def _flatten_params(mapping: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    # Nested YAML maps -> dotted keys, matching how the node names them
    # (safety_config.yaml's `safety: {min_x: ...}` -> "safety.min_x").
    flat: Dict[str, Any] = {}
    for key, value in mapping.items():
        full_key: str = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten_params(mapping=value, prefix=f"{full_key}."))
        else:
            flat[full_key] = value
    return flat

def _load_param_file(path: str) -> Dict[str, Any]:
    # One YAML file -> flat {name: value}. Accepts a plain mapping, or the ROS
    # params-file layout ({<node-glob>: {ros__parameters: {...}}}) -- the
    # latter only so the files borrowed from other packages, which those
    # packages still load the ROS way, work unmodified. No rclpy involved.
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Parameter file not found: {path}")
    with open(file=path) as handle:
        document: Any = yaml.safe_load(stream=handle) or {}
    if not isinstance(document, dict):
        raise ValueError(f"Parameter file {path} must have a YAML mapping at the top level.")

    ros_sections: List[dict] = [
        value["ros__parameters"] for value in document.values()
        if isinstance(value, dict) and isinstance(value.get("ros__parameters"), dict)
    ]
    raw: Dict[str, Any] = {}
    for section in ros_sections:
        raw.update(section)
    if not ros_sections:
        raw = document
    return _flatten_params(mapping=raw)

def load_params(paths: List[str]) -> Dict[str, Any]:
    # Layer several files into one dict; later files win (matches the old
    # multi-file ROS param merge order in rise_controller.launch.py).
    merged: Dict[str, Any] = {}
    for path in paths:
        merged.update(_load_param_file(path=path))
    return merged

# Fraction of control_period_s a single control_timer_callback tick is allowed to consume
# before it's treated as a real-time violation. Kept as a code constant (not a YAML param):
# it's a property of the control-loop deadline itself, not something a given experiment
# should be tuning per run.
CONTROL_TICK_BUDGET_FRACTION: float = 0.90

class AparkRiseNode(Node):
    def __init__(self, params: Dict[str, Any]) -> None:
        super().__init__(node_name='apark_rise_node')

        # Flat config dict from the YAML file(s) - see load_params(). The node
        # never touches rclpy's parameter system: absent keys fail loud via
        # _get_param(), extra keys are simply never read.
        self._params: Dict[str, Any] = params

        # Basic Parameters of the Experiment
        self.desired_trajectory: int = self._get_param(name='desired_trajectory')
        self.controller_type: str = self._get_param(name='controller_type')
        control_frequency_hz: float = self._get_param(name='control_frequency_hz')
        self.control_period_s: float = 1.0 / control_frequency_hz
        self.save_data: bool = self._get_param(name='save_data')
        # The one optional key: set per-run by the Optuna orchestrator, absent for manual runs.
        self.trial_number: Optional[int] = self._params.get('trial_number')
        self.run_length_s: float = self._get_param(name='run_length_s')
        self.init_tol_m: float = self._get_param(name='init_tol_m')
        self.d_out: int = self._get_param(name='d_out')

        # Odometry frame correction -- see velocity_callback()/publish_trajectory_setpoint_acceleration().
        # Sourced from px4_telemetry's park_coordinates.yaml (passed in alongside this
        # node's own params, see launch/rise_controller.launch.py), not this package's own
        # YAML -- it's the same rotation px4_telemetry itself uses to build
        # autonomy_park/pose, and duplicating it here would just be a second value to keep
        # in sync by hand.
        self.origin_r: float = self._get_param(name='origin_r')

        # Desired Trajectory
        if self.desired_trajectory not in [1,2]:
            raise ValueError("INVALID DESIRED TRAJECTORY SELECTED.")
        self.config: Dict[str, Any] = dict(self._params)
        self.traj_gen: TrajectoryGenerator = TrajectoryGenerator(config=self.config)

        # Safety -- min/max_x/y/z sourced from px4_safety_lib's safety_config.yaml
        # (passed in alongside this node's own params, see
        # launch/rise_controller.launch.py), the same real flight-envelope bounds
        # px4_safety_lib itself enforces, rather than a second box kept in sync by hand.
        self.acc_hor_max_mps2: float = self._get_param(name='mpc_acc_hor_max_mps2')
        self.acc_vert_max_mps2: float = self._get_param(name='mpc_acc_vert_max_mps2')
        self.safe_x_min_m_enu: float = self._get_param(name='safety.min_x')
        self.safe_x_max_m_enu: float = self._get_param(name='safety.max_x')
        self.safe_y_min_m_enu: float = self._get_param(name='safety.min_y')
        self.safe_y_max_m_enu: float = self._get_param(name='safety.max_y')
        self.safe_z_min_m_enu: float = self._get_param(name='safety.min_z')
        self.safe_z_max_m_enu: float = self._get_param(name='safety.max_z')
        self.odom_timeout_s: float = self._get_param(name='odom_timeout_s')
        self.init_z_m_enu: float = self._get_param(name='init_z_m_enu')
        self.odom_watchdog_freq_hz: float = self._get_param(name='odom_watchdog_freq_hz')
        self.mode_cmd_retry_period_s: float = self._get_param(name='mode_cmd_retry_period_s')
        self.takeoff_timeout_s: float = self._get_param(name='takeoff_timeout_s')
        self.arm_timeout_s: float = self._get_param(name='arm_timeout_s')

        self._validate_trajectory_envelope()

        # Cost Function (same formula used for post-hoc gain selection in
        # unified_orchestrator.py's compute_trial_J - no t-weighting on tracking error)
        self.q_e: float = self._get_param(name='q_e')
        self.r_u: float = self._get_param(name='r_u')
        self.r_udot: float = self._get_param(name='r_udot')
        self.w_fail: float = self._get_param(name='w_fail')

        if self.controller_type == "pid":
            self.K_P: float = self._get_param(name='K_P')
            self.K_I: float = self._get_param(name='K_I')
            self.K_D: float = self._get_param(name='K_D')

        elif self.controller_type in ['baseline', 'integrated_resnet', 'resnet', 'supertwisting']:
            self.k_1: float = self._get_param(name='k_1')
            self.k_2: float = self._get_param(name='k_2')
            self.k_3: float = self._get_param(name='k_3')

            if self.controller_type in ['baseline', 'integrated_resnet', 'resnet']:
                self.K_RISE: float = self._get_param(name='k_rise')
                self.K_P: float = (self.k_1 * self.k_2) + (self.k_1 * self.k_3) + (self.k_2 * self.k_3) + 1.0
                self.K_I: float = (self.k_1 * self.k_2 * self.k_3) + self.k_1
                self.K_D: float = self.k_1 + self.k_2 + self.k_3

            if self.controller_type in ["resnet", "integrated_resnet"]:
                self.d_in: int = self._get_param(name='d_in')

                self.theta_hat: jax.Array = jnp.array(object=self._get_param(name='initial_weights'))

                self.gamma_diag: jax.Array = jnp.ones(shape=self.theta_hat.shape[0]) * self._get_param(name='gamma')
                self.sigma_mod: float = self._get_param(name='sigma_mod')
                self.theta_bar: float = self._get_param(name='theta_bar')
                self.theta_dot_bar: float = self._get_param(name='theta_dot_bar')

                self.bound_resnet = jax.jit(partial(
                    resnet_network,
                    d_in=self.d_in,
                    hidden_width=self._get_param(name='hidden_width'),
                    d_out=self.d_out,
                    b=self._get_param(name='num_blocks'),
                    k_0=self._get_param(name='k_0'),
                    k_i=self._get_param(name='k_i'),
                    h_act_func=self._get_param(name='h_act_func'),
                    o_act_func=self._get_param(name='o_act_func'),
                    shortcut_act_func=self._get_param(name='shortcut_act_func'),
                ))

                @jax.jit
                def compiled_update_step(theta_hat: jax.Array, x_vec: jax.Array, r1_vec: jax.Array, dt: float, theta_bar: float, theta_dot_bar: float, gamma_diag: jax.Array, s_mod: float, control_saturated: bool) -> Tuple[jax.Array, jax.Array, jax.Array, jax.Array, jax.Array]:
                    phi_val, vjp_fn = jax.vjp(lambda t: self.bound_resnet(t, x_vec), has_aux=False, *[theta_hat])
                    grad_term = vjp_fn(r1_vec)[0]
                    theta_dot_unprojected = gamma_diag * (grad_term - s_mod * theta_hat)
                    # theta_hat_dot = sat(proj(nominal_theta_hat_dot)): discrete_projection is
                    # the "proj" stage (ball-constrains the state), discrete_rate_projection is
                    # the "sat" stage (caps the resulting effective rate's 2-norm), applied in
                    # that order -- see proj.py for why the order matters.
                    theta_next_ball, ball_projected = discrete_projection(theta_hat=theta_hat, theta_dot_unprojected=theta_dot_unprojected, dt=dt, theta_bar=theta_bar, gamma_diag=gamma_diag)
                    theta_next_rate_capped, rate_limited = discrete_rate_projection(theta_hat=theta_hat, theta_next=theta_next_ball, dt=dt, theta_dot_bar=theta_dot_bar)
                    # Control-command saturation dominates both projections above: if the
                    # published acceleration was clamped this tick, freeze theta_hat entirely
                    # rather than merely rate-limiting it.
                    final_theta = jax.lax.select(pred=control_saturated, on_true=theta_hat, on_false=theta_next_rate_capped)
                    # Actual applied per-tick derivative (post-projection/saturation/freeze),
                    # not the nominal theta_dot_unprojected above -- this is what
                    # theta_dot_bar actually bounds. dt is a measured (not fixed) period and
                    # can be 0 on the very first FOLLOW_TRAJ tick; final_theta == theta_hat
                    # in that case too (see discrete_projection/discrete_rate_projection), so
                    # the numerator is already 0 and jnp.maximum below just avoids a 0/0 NaN.
                    theta_hat_dot = (final_theta - theta_hat) / jnp.maximum(dt, 1e-12)
                    return final_theta, phi_val, ball_projected, rate_limited, theta_hat_dot

                self.compiled_update_step = compiled_update_step
                self.precompile_jax()

        # For State callback
        self.is_armed: bool = False
        self.in_offboard_mode: bool = False

        # Init
        self.terminal_command_sent: bool = False
        self.position_mode_requested: bool = False
        self._mode_cmd_seeded: bool = False
        self.cost_started: bool = False
        self.is_control_saturated: bool = False
        self.freeze_int_xy: bool = False
        self.freeze_int_z: bool = False
        self.initial_position_locked: bool = False
        self.latest_position_m_enu: Optional[np.ndarray] = None
        self.latest_velocity_m_enu: Optional[np.ndarray] = None

        self.init_x_m_enu: float = 0.0
        self.init_y_m_enu: float = 0.0
        self.experiment_state: int = ExperimentState.STATE_INIT
        self.t_0: float = 0.0

        self.last_t_s: float = 0.0
        self.last_mode_cmd_time_s: float = 0.0
        self.takeoff_entry_time_s: float = 0.0
        # ROS clock, not time.perf_counter() -- matches current_timestamp_s in
        # _control_timer_tick(), which this is compared against below.
        self.init_entry_time_s: float = self.get_clock().now().nanoseconds / 1e9

        self.ticks_without_pose: int = 0
        self.ticks_without_velocity: int = 0
        self.reset_integral()
        self.cost_J: float = 0.0
        self.last_cost_integrand: float = 0.0
        self.error_sq_integral: float = 0.0
        self.last_error_sq: float = 0.0
        self.u_sq_integral: float = 0.0
        self.last_u_sq: float = 0.0
        self.u_dot_sq_integral: float = 0.0
        self.last_u_dot_sq: float = 0.0
        self.last_u: np.ndarray = np.zeros(shape=self.d_out, dtype=np.float64)
        self.time_history: List[float] = []
        self.control_output_norm_history: List[float] = []
        self.control_output_history: List[List[float]] = []
        self.u_dot_history: List[List[float]] = []
        self.error_norm_history: List[float] = []
        self.weight_history: List[List[float]] = []
        self.phi_history: List[List[float]] = []
        self.theta_hat_norm_history: List[float] = []
        self.theta_hat_dot_norm_history: List[float] = []
        self.ball_projected_history: List[bool] = []
        self.rate_limited_history: List[bool] = []
        self.q_history: List[List[float]] = []
        self.qd_history: List[List[float]] = []

        qos_profile: QoSProfile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1
        )

        self.setpoint_publisher = self.create_publisher(
            msg_type=PositionTarget, topic='setpoint_raw/local', qos_profile=qos_profile)

        self.state_sub = self.create_subscription(
            msg_type=State, topic='state', callback=self.state_callback, qos_profile=qos_profile)
        # Already rotated into the apark frame by px4_telemetry -- see velocity_callback()
        # for why velocity doesn't get the same treatment for free.
        self.pose_sub = self.create_subscription(
            msg_type=PoseStamped, topic='autonomy_park/pose', callback=self.pose_callback, qos_profile=qos_profile)
        self.velocity_sub = self.create_subscription(
            msg_type=TwistStamped, topic='local_position/velocity_local', callback=self.velocity_callback, qos_profile=qos_profile)

        self.arming_client = self.create_client(srv_type=CommandBool, srv_name='cmd/arming')
        self.set_mode_client = self.create_client(srv_type=SetMode, srv_name='set_mode')

        self.control_timer = self.create_timer(timer_period_sec=self.control_period_s, callback=self.control_timer_callback)

        self.odom_watchdog_timer = self.create_timer(timer_period_sec=1.0/self.odom_watchdog_freq_hz, callback=self.odom_watchdog_callback)

        self.get_logger().info(f"Node initialized successfully. Controller: {self.controller_type.upper()} | Trajectory: {self.desired_trajectory}.")

    def _get_param(self, name: str) -> Any:
        # Every experiment knob is required. A missing key means a broken config
        # (typo, stale file, or one of the layered files wasn't passed) and must
        # stop the run before anything arms - so fail loud, right here. Keys that
        # exist in the file(s) but are never requested are ignored for free.
        if name not in self._params:
            raise ValueError(
                f"Required parameter '{name}' is missing from the loaded parameter file(s). "
                f"Loaded keys: {sorted(self._params)}"
            )
        return self._params[name]

    def _validate_trajectory_envelope(self) -> None:
        # Catches a correctly-named-but-dangerously-valued config (e.g. a trajectory
        # amplitude that overruns the safety box) at startup instead of discovering it via
        # a live boundary-breach failsafe mid-flight.
        if not (self.safe_z_min_m_enu <= self.init_z_m_enu <= self.safe_z_max_m_enu):
            raise ValueError(f"init_z_m_enu={self.init_z_m_enu} falls outside safe_z bounds [{self.safe_z_min_m_enu}, {self.safe_z_max_m_enu}].")

        num_samples: int = 200
        for i in range(num_samples + 1):
            t: float = self.run_length_s * i / num_samples
            pos, _, _ = self.traj_gen.get_desired_state(t=t)
            if not (self.safe_x_min_m_enu <= pos[0] <= self.safe_x_max_m_enu):
                raise ValueError(f"Trajectory x position {pos[0]:.2f}m at t={t:.2f}s falls outside safe_x bounds [{self.safe_x_min_m_enu}, {self.safe_x_max_m_enu}].")
            if not (self.safe_y_min_m_enu <= pos[1] <= self.safe_y_max_m_enu):
                raise ValueError(f"Trajectory y position {pos[1]:.2f}m at t={t:.2f}s falls outside safe_y bounds [{self.safe_y_min_m_enu}, {self.safe_y_max_m_enu}].")
            if not (self.safe_z_min_m_enu <= pos[2] <= self.safe_z_max_m_enu):
                raise ValueError(f"Trajectory z position {pos[2]:.2f}m at t={t:.2f}s falls outside safe_z bounds [{self.safe_z_min_m_enu}, {self.safe_z_max_m_enu}].")

        self.get_logger().info("Trajectory envelope validated against safety boundaries.")

    def _log_theta_saturation(self, t: float, ball_projected: bool, rate_limited: bool) -> None:
        # Surfaced at INFO (not DEBUG) since these are meant to be visible in a normal
        # run: theta_bar/theta_dot_bar are sized to never bind in practice, so either
        # one firing is itself a signal worth seeing live, not just on request.
        if ball_projected and rate_limited:
            self.get_logger().info(f"theta_bar AND theta_dot_bar saturation both triggered at t={t:.2f}s.")
        elif ball_projected:
            self.get_logger().info(f"theta_bar (weight-norm ball) saturation triggered at t={t:.2f}s.")
        elif rate_limited:
            self.get_logger().info(f"theta_dot_bar (update-rate) saturation triggered at t={t:.2f}s.")

    def precompile_jax(self) -> None:
        dummy_x: jax.Array = jnp.zeros(shape=self.d_in)
        dummy_r1: jax.Array = jnp.zeros(shape=self.d_out)
        self.get_logger().info("Compiling XLA graph on CPU...")

        self.theta_hat, _, _, _, _ = self.compiled_update_step(
            theta_hat=self.theta_hat,
            x_vec=dummy_x,
            r1_vec=dummy_r1,
            dt=self.control_period_s,
            theta_bar=self.theta_bar,
            theta_dot_bar=self.theta_dot_bar,
            gamma_diag=self.gamma_diag,
            s_mod=self.sigma_mod,
            control_saturated=False
        )
        self.theta_hat.block_until_ready()

        start_time: float = time.perf_counter()
        self.theta_hat, _, _, _, _ = self.compiled_update_step(
            theta_hat=self.theta_hat,
            x_vec=dummy_x,
            r1_vec=dummy_r1,
            dt=self.control_period_s,
            theta_bar=self.theta_bar,
            theta_dot_bar=self.theta_dot_bar,
            gamma_diag=self.gamma_diag,
            s_mod=self.sigma_mod,
            control_saturated=False
        )
        self.theta_hat.block_until_ready()
        hot_time: float = time.perf_counter() - start_time

        # Reset the weights back to true initial conditions
        self.theta_hat = jnp.array(object=self._get_param(name='initial_weights'))
        self.theta_hat.block_until_ready()
        self.get_logger().info(f"Neural network latency: {hot_time*1000:.2f}ms.")
        if hot_time > self.control_period_s:
            self.get_logger().fatal(f"Execution time {hot_time:.4f}s exceeds control_period_s={self.control_period_s:.4f}s limit.")
            raise JaxLatencyError("ResNet latency too high for selected control frequency (init).")

    def state_callback(self, msg: State) -> None:
        self.is_armed = msg.armed
        self.in_offboard_mode = (msg.mode == "OFFBOARD")

    def pose_callback(self, msg: PoseStamped) -> None:
        self.latest_position_m_enu = np.array(
            object=[msg.pose.position.x, msg.pose.position.y, msg.pose.position.z], dtype=np.float64)
        self.ticks_without_pose = 0

        if not self.initial_position_locked:
            self.init_x_m_enu = float(msg.pose.position.x)
            self.init_y_m_enu = float(msg.pose.position.y)
            self.initial_position_locked = True

    def velocity_callback(self, msg: TwistStamped) -> None:
        # local_position/velocity_local is raw MAVROS ENU (world frame), not yet rotated
        # into the "apark" frame the way autonomy_park/pose already is by px4_telemetry --
        # origin_r replicates that same rotation here so q_dot stays consistent with q.
        # Mirrors the old mocap node's velocity_callback (see lyla_node_OLD.py) and
        # PX4Teleop's outgoing rotation in reverse.
        cos_r: float = math.cos(self.origin_r)
        sin_r: float = math.sin(self.origin_r)
        vx_enu: float = msg.twist.linear.x
        vy_enu: float = msg.twist.linear.y
        self.latest_velocity_m_enu = np.array(object=[
            (cos_r * vx_enu) - (sin_r * vy_enu),
            (sin_r * vx_enu) + (cos_r * vy_enu),
            msg.twist.linear.z
        ], dtype=np.float64)
        self.ticks_without_velocity = 0

    def odom_watchdog_callback(self) -> None:
        self.ticks_without_pose += 1
        self.ticks_without_velocity += 1
        watchdog_ticks: float = self.odom_timeout_s * self.odom_watchdog_freq_hz

        if not self.initial_position_locked:
            if self.ticks_without_pose >= watchdog_ticks:
                raise OdomTimeoutError("No pose received at boot.")
            return

        if self.ticks_without_pose >= watchdog_ticks:
            raise OdomTimeoutError("Pose feed lost during flight.")
        if self.ticks_without_velocity >= watchdog_ticks:
            raise OdomTimeoutError("Velocity feed lost during flight.")

    def reset_integral(self) -> None:
        self.current_integral_control_term = np.zeros(shape=self.d_out, dtype=np.float64)
        self.last_control_integrand = np.zeros(shape=self.d_out, dtype=np.float64)
        self.st_integral = np.zeros(shape=self.d_out, dtype=np.float64)

    def _request_arm(self) -> None:
        if not self.arming_client.service_is_ready():
            return
        request: CommandBool.Request = CommandBool.Request()
        request.value = True
        self.arming_client.call_async(request=request)

    def _request_mode(self, mode: str) -> None:
        if not self.set_mode_client.service_is_ready():
            return
        request: SetMode.Request = SetMode.Request()
        request.custom_mode = mode
        self.set_mode_client.call_async(request=request)

    def publish_trajectory_setpoint_acceleration(self, ax: float, ay: float, az: float) -> None:
        if self.latest_position_m_enu is None:
            self.get_logger().warning(f"Ignoring setpoint since there has been no pose yet.")
            return

        # Un-rotate the apark-frame acceleration command back into MAVROS's raw ENU frame
        # before publishing -- the exact inverse of velocity_callback's rotation.
        cos_r: float = math.cos(self.origin_r)
        sin_r: float = math.sin(self.origin_r)
        ax_enu: float = (cos_r * ax) + (sin_r * ay)
        ay_enu: float = -(sin_r * ax) + (cos_r * ay)

        msg: PositionTarget = PositionTarget()
        msg.header.stamp = self.get_clock().now().to_msg()
        # FRAME_LOCAL_NED here just selects the MAVLink SET_POSITION_TARGET_LOCAL_NED
        # message type -- the fields below are still ROS ENU, MAVROS converts them.
        msg.coordinate_frame = PositionTarget.FRAME_LOCAL_NED
        msg.type_mask = (
            PositionTarget.IGNORE_PX | PositionTarget.IGNORE_PY | PositionTarget.IGNORE_PZ |
            PositionTarget.IGNORE_VX | PositionTarget.IGNORE_VY | PositionTarget.IGNORE_VZ |
            PositionTarget.IGNORE_YAW_RATE
        )
        msg.acceleration_or_force.x = ax_enu
        msg.acceleration_or_force.y = ay_enu
        msg.acceleration_or_force.z = az
        msg.yaw = 0.0
        self.setpoint_publisher.publish(msg)

    def land_vehicle(self) -> None:
        if self.terminal_command_sent:
            return
        self._request_mode(mode="AUTO.LAND")
        self.terminal_command_sent = True

    def return_vehicle(self) -> None:
        # AUTO.RTL: PX4's own return-to-launch mode - flies back to the
        # home position (set at boot from PX4_HOME_LAT/LON/ALT, or the EKF
        # origin if that was set explicitly after boot - see
        # scripts/launch_one_homebrew.sh) and lands there automatically,
        # rather than landing in place like land_vehicle() does.
        if self.terminal_command_sent:
            return
        self._request_mode(mode="AUTO.RTL")
        self.terminal_command_sent = True

    def write_csv(self) -> None:
        traj_name: str = ""
        match self.desired_trajectory:
            case 1:
                traj_name = "figure_eight"
            case 2:
                traj_name = "rose"

        base_dir: str = f"simulation_data/{self.controller_type}/{traj_name}"
        os.makedirs(name=base_dir, exist_ok=True)

        if self.trial_number is not None:
            # Deterministic name tied to the Optuna trial number so a retried attempt
            # overwrites the discarded attempt's file instead of leaving an orphaned CSV
            # that can't be matched back to a trial (see item 7 in the migration writeup).
            csv_filename: str = os.path.join(base_dir, f"run_trial{self.trial_number}.csv")
        else:
            existing_files: List[str] = [f for f in os.listdir(path=base_dir) if f.endswith('.csv') and f.startswith('run_')]
            max_idx: int = 0
            for f in existing_files:
                try:
                    idx = int(f.replace('run_', '').replace('.csv', ''))
                    max_idx = max(max_idx, idx)
                except ValueError:
                    pass
            iterable: int = max_idx + 1
            csv_filename: str = os.path.join(base_dir, f"run_{iterable}.csv")
        try:
            with open(file=csv_filename, mode='w', newline='') as file:
                writer = csv.writer(file)
                headers: List[str] = [
                    "Time_s", "Error_Norm_m", "Control_Output_Norm_mps2",
                    "ux_mps2", "uy_mps2", "uz_mps2",
                    "udotx_mps3", "udoty_mps3", "udotz_mps3",
                    "x_m", "y_m", "z_m", "xd_m", "yd_m", "zd_m"
                ]
                if self.controller_type in ["resnet", "integrated_resnet"] and self.theta_hat_norm_history:
                    headers += ["ThetaHat_Norm", "ThetaHatDot_Norm", "ThetaBar_Projected", "ThetaDotBar_Saturated"]
                if self.controller_type in ["resnet", "integrated_resnet"] and self.phi_history:
                    num_phi: int = len(self.phi_history[0])
                    headers += [f"Phi{i}_mps2" for i in range(num_phi)]
                if self.controller_type in ["resnet", "integrated_resnet"] and self.weight_history:
                    num_weights: int = len(self.weight_history[0])
                    headers += [f"W{i}" for i in range(num_weights)]
                writer.writerow(headers)
                for i in range(len(self.time_history)):
                    row: List[float] = [
                        self.time_history[i], self.error_norm_history[i], self.control_output_norm_history[i],
                        self.control_output_history[i][0], self.control_output_history[i][1], self.control_output_history[i][2],
                        self.u_dot_history[i][0], self.u_dot_history[i][1], self.u_dot_history[i][2],
                        self.q_history[i][0], self.q_history[i][1], self.q_history[i][2],
                        self.qd_history[i][0], self.qd_history[i][1], self.qd_history[i][2]
                    ]
                    if self.controller_type in ["resnet", "integrated_resnet"] and self.theta_hat_norm_history:
                        row += [
                            self.theta_hat_norm_history[i], self.theta_hat_dot_norm_history[i],
                            self.ball_projected_history[i], self.rate_limited_history[i]
                        ]
                    if self.controller_type in ["resnet", "integrated_resnet"] and self.phi_history:
                        row += self.phi_history[i]
                    if self.controller_type in ["resnet", "integrated_resnet"] and self.weight_history:
                        row += self.weight_history[i]
                    writer.writerow(row)
            self.get_logger().info(f"Telemetry saved to {csv_filename}")
        except Exception as e:
            self.get_logger().error(f"Failed to write CSV: {e}")

    def check_safety_boundary(self, q: np.ndarray) -> Optional[str]:
        if not (self.safe_x_min_m_enu <= q[0] <= self.safe_x_max_m_enu):
            return f"X position {q[0]:.2f} breached bounds [{self.safe_x_min_m_enu}, {self.safe_x_max_m_enu}]."
        if not (self.safe_y_min_m_enu <= q[1] <= self.safe_y_max_m_enu):
            return f"Y position {q[1]:.2f} breached bounds [{self.safe_y_min_m_enu}, {self.safe_y_max_m_enu}]."
        if not (self.safe_z_min_m_enu <= q[2] <= self.safe_z_max_m_enu):
            return f"Z position {q[2]:.2f} breached bounds [{self.safe_z_min_m_enu}, {self.safe_z_max_m_enu}]."
        return None

    def get_desired_state(self, t: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self.experiment_state == ExperimentState.STATE_TAKEOFF:
            # During takeoff, hold exactly above where it initialized
            return (np.array(object=[self.init_x_m_enu, self.init_y_m_enu, self.init_z_m_enu], dtype=np.float64),
                    np.zeros(shape=3, dtype=np.float64), np.zeros(shape=3, dtype=np.float64))

        return self.traj_gen.get_desired_state(t=t)

    def compute_control_output(
        self,
        q: np.ndarray,
        q_dot: np.ndarray,
        qd: np.ndarray,
        qd_dot: np.ndarray,
        qd_ddot: np.ndarray,
        e: np.ndarray,
        e_dot: np.ndarray,
        r1: Optional[np.ndarray],
        dt: float,
        t: float,
    ) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray], bool, bool]:
        # Saturation clamping is deliberately NOT done here: it happens in the
        # caller, after u is recorded into history/cost tracking, so logged/cost-tracked
        # control effort stays pre-saturation while only the published setpoint is clamped
        # (matches the original combined-case ordering exactly). phi_val (the NN
        # feedforward term) is returned alongside u purely for history/CSV logging --
        # it's zero and unused for every controller_type except resnet/integrated_resnet,
        # where it's already folded into u below. theta_hat_dot/ball_projected/rate_limited
        # are likewise CSV-logging-only and stay at their None/False defaults for every
        # controller_type except resnet/integrated_resnet.
        u: np.ndarray = np.zeros(shape=self.d_out, dtype=np.float64)
        phi_val: np.ndarray = np.zeros(shape=self.d_out, dtype=np.float64)
        theta_hat_dot_val: Optional[np.ndarray] = None
        ball_projected: bool = False
        rate_limited: bool = False

        match self.controller_type:
            case "baseline":
                current_integrand: np.ndarray = (self.K_I * e) + (self.K_RISE * np.sign(r1))
                delta_int: np.ndarray = (dt / 2.0) * (current_integrand + self.last_control_integrand)
                if not self.freeze_int_xy:
                    self.current_integral_control_term[0:2] += delta_int[0:2]
                if not self.freeze_int_z:
                    self.current_integral_control_term[2] += delta_int[2]
                self.last_control_integrand = current_integrand
                u = (self.K_P * e) + (self.K_D * e_dot) + self.current_integral_control_term

            case "pid":
                current_integrand: np.ndarray = (self.K_I * e)
                delta_int: np.ndarray = (dt / 2.0) * (current_integrand + self.last_control_integrand)
                if not self.freeze_int_xy:
                    self.current_integral_control_term[0:2] += delta_int[0:2]
                if not self.freeze_int_z:
                    self.current_integral_control_term[2] += delta_int[2]
                self.last_control_integrand = current_integrand
                u = (self.K_P * e) + (self.K_D * e_dot) + self.current_integral_control_term

            case "resnet":
                if self.experiment_state == ExperimentState.STATE_FOLLOW_TRAJ:
                    x_vec: jax.Array = jnp.array(object=np.concatenate((q, q_dot, qd, qd_dot)))

                    t_start_jax: float = time.perf_counter()
                    self.theta_hat, phi_out, ball_projected, rate_limited, theta_hat_dot = self.compiled_update_step(
                        theta_hat=self.theta_hat,
                        x_vec=x_vec,
                        r1_vec=jnp.array(object=r1),
                        dt=dt,
                        theta_bar=self.theta_bar,
                        theta_dot_bar=self.theta_dot_bar,
                        gamma_diag=self.gamma_diag,
                        s_mod=self.sigma_mod,
                        control_saturated=False #self.is_control_saturated # I'm temporarily turning this off on purpose.
                    )
                    self.theta_hat.block_until_ready()
                    t_end_jax: float = time.perf_counter()
                    jax_dt: float = t_end_jax - t_start_jax
                    if jax_dt > self.control_period_s:
                        self.get_logger().warning(f"Running behind! JAX took {jax_dt*1000:.2f}ms at t={t:.2f}s.")
                    else:
                        self.get_logger().debug(f"JAX took {jax_dt*1000:.2f}ms.")

                    self._log_theta_saturation(t=t, ball_projected=bool(ball_projected), rate_limited=bool(rate_limited))

                    phi_val = np.array(object=phi_out, dtype=np.float64)
                    theta_hat_dot_val = np.array(object=theta_hat_dot, dtype=np.float64)
                    ball_projected = bool(ball_projected)
                    rate_limited = bool(rate_limited)

                current_integrand_res: np.ndarray = (self.K_I * e) + (self.K_RISE * np.sign(r1))
                delta_int_res: np.ndarray = (dt / 2.0) * (current_integrand_res + self.last_control_integrand)
                if not self.freeze_int_xy:
                    self.current_integral_control_term[0:2] += delta_int_res[0:2]
                if not self.freeze_int_z:
                    self.current_integral_control_term[2] += delta_int_res[2]
                self.last_control_integrand = current_integrand_res
                u = phi_val + (self.K_P * e) + (self.K_D * e_dot) + self.current_integral_control_term

            case "integrated_resnet":
                if self.experiment_state == ExperimentState.STATE_FOLLOW_TRAJ:
                    u_last: np.ndarray =  (self.K_P * e) + (self.K_D * e_dot) + self.current_integral_control_term
                    kappa_vec: jax.Array = jnp.array(object=np.concatenate((q, q_dot, qd, qd_dot, u_last)))

                    t_start_jax = time.perf_counter()
                    self.theta_hat, phi_out, ball_projected, rate_limited, theta_hat_dot = self.compiled_update_step(
                        theta_hat=self.theta_hat,
                        x_vec=kappa_vec,
                        r1_vec=jnp.array(object=r1),
                        dt=dt,
                        theta_bar=self.theta_bar,
                        theta_dot_bar=self.theta_dot_bar,
                        gamma_diag=self.gamma_diag,
                        s_mod=self.sigma_mod,
                        control_saturated=self.is_control_saturated
                    )
                    self.theta_hat.block_until_ready()
                    t_end_jax = time.perf_counter()
                    jax_dt = t_end_jax - t_start_jax
                    if jax_dt > self.control_period_s:
                        self.get_logger().warning(f"JAX execution took {jax_dt*1000:.2f}ms at t={t:.2f}s.")

                    self._log_theta_saturation(t=t, ball_projected=bool(ball_projected), rate_limited=bool(rate_limited))

                    phi_val = np.array(object=phi_out, dtype=np.float64)
                    theta_hat_dot_val = np.array(object=theta_hat_dot, dtype=np.float64)
                    ball_projected = bool(ball_projected)
                    rate_limited = bool(rate_limited)

                current_integrand_int: np.ndarray = (self.K_I * e) + (self.K_RISE * np.sign(r1)) + phi_val
                delta_int_int: np.ndarray = (dt / 2.0) * (current_integrand_int + self.last_control_integrand)
                if not self.freeze_int_xy:
                    self.current_integral_control_term[0:2] += delta_int_int[0:2]
                if not self.freeze_int_z:
                    self.current_integral_control_term[2] += delta_int_int[2]
                self.last_control_integrand = current_integrand_int
                u = (self.K_P * e) + (self.K_D * e_dot) + self.current_integral_control_term

            case "supertwisting":
                norm_r1: float = float(np.linalg.norm(r1))
                sgn_r1: np.ndarray = np.sign(r1)
                self.st_integral += sgn_r1 * dt
                u = qd_ddot + self.k_2 * np.sqrt(norm_r1) * sgn_r1 + self.k_3 * self.st_integral + self.k_1 * e_dot

        return u, phi_val, theta_hat_dot_val, ball_projected, rate_limited

    def control_timer_callback(self) -> None:
        # Wraps the real tick so *every* code path through it (INIT/TAKEOFF/FOLLOW_TRAJ,
        # including the JAX call and the publish itself) is covered by one end-to-end
        # deadline check -- not just the ResNet forward/backward pass. A tick that runs
        # long enough to eat into PX4's OFFBOARD signal-loss window is a real-time
        # violation regardless of which line inside the tick was slow.
        tick_start_s: float = time.perf_counter()
        self._control_timer_tick()
        elapsed_s: float = time.perf_counter() - tick_start_s
        budget_s: float = CONTROL_TICK_BUDGET_FRACTION * self.control_period_s
        if elapsed_s > budget_s:
            raise ControlLoopOverrunError(
                f"Control tick took {elapsed_s * 1000.0:.2f}ms, exceeding the "
                f"{CONTROL_TICK_BUDGET_FRACTION:.0%} budget of "
                f"{budget_s * 1000.0:.2f}ms (control_period_s={self.control_period_s * 1000.0:.2f}ms)."
            )

    def _control_timer_tick(self) -> None:
        if self.latest_position_m_enu is None or self.latest_velocity_m_enu is None: return
        current_timestamp_s: float = self.get_clock().now().nanoseconds / 1e9

        match self.experiment_state:
            case ExperimentState.STATE_INIT:
                self.cost_started = False

                if (current_timestamp_s - self.init_entry_time_s) > self.arm_timeout_s:
                    self.cost_J += self.w_fail * (self.run_length_s ** 2)
                    self.get_logger().info(f"[RESULT] Final cost = {self.cost_J:.4f} (arm timeout).")
                    raise FailsafeTriggeredError("Failed to arm and enter OFFBOARD within timeout.")

                # Always stream setpoints in INIT: continuous setpoint_raw/local publishing
                # is itself what keeps PX4 willing to accept/hold OFFBOARD over MAVROS --
                # there's no separate heartbeat message to manage here.
                self.publish_trajectory_setpoint_acceleration(ax=0.0, ay=0.0, az=0.0)

                if not self._mode_cmd_seeded:
                    # Defer the first mode-switch/arm attempt by one retry period so PX4
                    # has already seen a handful of streamed setpoints -- an immediate
                    # attempt races the very first setpoint and PX4 will reject the switch.
                    self.last_mode_cmd_time_s = current_timestamp_s
                    self._mode_cmd_seeded = True

                if not self.position_mode_requested:
                    # Recommended PX4 practice: enter OFFBOARD from Position mode, so
                    # that if the vehicle ever drops out of OFFBOARD it falls back to a
                    # stable hover instead of whatever mode it happened to boot into.
                    self._request_mode(mode="POSCTL")
                    self.position_mode_requested = True

                if not self.in_offboard_mode:
                    self.get_logger().info("Waiting for OFFBOARD mode switch...", throttle_duration_sec=2.0)

                    if current_timestamp_s - self.last_mode_cmd_time_s > self.mode_cmd_retry_period_s:
                        self._request_mode(mode="OFFBOARD")
                        if not self.is_armed:
                            self._request_arm()
                        self.last_mode_cmd_time_s = current_timestamp_s
                else:
                    if self.is_armed:
                        self.get_logger().info(f"ARMED & OFFBOARD validated. Initializing takeoff to z={self.init_z_m_enu:.2f}m (ENU).")
                        self.reset_integral()
                        self.experiment_state = ExperimentState.STATE_TAKEOFF
                        self.takeoff_entry_time_s = current_timestamp_s
                    else:
                        # Still waiting for arming to complete!
                        self.get_logger().info("OFFBOARD engaged, waiting for vehicle to arm...", throttle_duration_sec=2.0)
                        if current_timestamp_s - self.last_mode_cmd_time_s > self.mode_cmd_retry_period_s:
                            self._request_arm()
                            self.last_mode_cmd_time_s = current_timestamp_s

            case ExperimentState.STATE_TAKEOFF:
                if not self.in_offboard_mode:
                    raise FailsafeTriggeredError("PX4 left OFFBOARD mode during SITL simulation (takeoff).")

                # Check the takeoff-settled transition before anything else -- the fixed
                # hold target get_desired_state() uses during STATE_TAKEOFF doesn't depend
                # on the trajectory clock, so there's nothing else to update first.
                q: np.ndarray = self.latest_position_m_enu
                q_dot: np.ndarray = self.latest_velocity_m_enu

                if (current_timestamp_s - self.takeoff_entry_time_s) > self.takeoff_timeout_s:
                    self.cost_J += self.w_fail * (self.run_length_s ** 2)
                    self.get_logger().info(f"[RESULT] Final cost = {self.cost_J:.4f} (takeoff timeout).")
                    raise FailsafeTriggeredError("Failed to reach takeoff position within timeout.")

                e_takeoff: np.ndarray = np.array(object=[self.init_x_m_enu, self.init_y_m_enu, self.init_z_m_enu], dtype=np.float64) - q
                if np.linalg.norm(e_takeoff) <= self.init_tol_m:
                    self.experiment_state = ExperimentState.STATE_FOLLOW_TRAJ
                    # Reset t_0 so the trajectory clock starts at exactly 0.0 now
                    self.t_0 = current_timestamp_s
                    self.last_t_s = 0.0
                    self.get_logger().info(f"Takeoff settled. Step response triggered: starting trajectory {self.desired_trajectory}.")

                t: float = 0.0
                dt: float = self.control_period_s

                boundary_err: Optional[str] = None #self.check_safety_boundary(q=q)
                if boundary_err is not None:
                    self.cost_J += self.w_fail * ((self.run_length_s - t) ** 2)
                    self.get_logger().info(f"[RESULT] Final cost = {self.cost_J:.4f} (boundary failure).")
                    raise BoundaryBreachError(boundary_err)

                qd, qd_dot, qd_ddot = self.get_desired_state(t=t)
                e: np.ndarray = qd - q
                e_dot: np.ndarray = qd_dot - q_dot
                r1: Optional[np.ndarray] = (e_dot + (self.k_1 * e)) if self.controller_type in ['resnet', 'integrated_resnet', 'baseline', 'supertwisting'] else None

                u, phi_val, _, _, _ = self.compute_control_output(
                    q=q, q_dot=q_dot, qd=qd, qd_dot=qd_dot, qd_ddot=qd_ddot, e=e, e_dot=e_dot, r1=r1, dt=dt, t=t
                )

                self.is_control_saturated = False
                self.freeze_int_xy = False
                self.freeze_int_z = False

                u_xy: np.ndarray = u[0:2]
                norm_uxy: float = float(np.linalg.norm(u_xy))
                if norm_uxy > self.acc_hor_max_mps2:
                    u[0:2] = u_xy * (self.acc_hor_max_mps2 / norm_uxy)
                    self.is_control_saturated = True
                    if np.dot(a=e[0:2], b=u[0:2]) > 0.0:
                        self.freeze_int_xy = True
                    self.get_logger().debug(f"XY saturation at t={t:.2f}s.")

                if abs(u[2]) > self.acc_vert_max_mps2:
                    u[2] = self.acc_vert_max_mps2 * np.sign(u[2])
                    self.is_control_saturated = True
                    if np.sign(e[2]) == np.sign(u[2]):
                        self.freeze_int_z = True
                    self.get_logger().debug(f"Z saturation at t={t:.2f}s.")

                self.publish_trajectory_setpoint_acceleration(ax=u[0], ay=u[1], az=u[2])

            case ExperimentState.STATE_FOLLOW_TRAJ:
                if not self.in_offboard_mode:
                    raise FailsafeTriggeredError("PX4 left OFFBOARD mode during SITL simulation (following trajectory).")

                q: np.ndarray = self.latest_position_m_enu
                t: float = current_timestamp_s - self.t_0
                dt: float = t - self.last_t_s

                q_dot: np.ndarray = self.latest_velocity_m_enu

                boundary_err: Optional[str] = self.check_safety_boundary(q=q)
                if boundary_err is not None:
                    self.cost_J += self.w_fail * ((self.run_length_s - t) ** 2)
                    self.get_logger().info(f"[RESULT] Final cost = {self.cost_J:.4f} (boundary failure).")
                    raise BoundaryBreachError(boundary_err)

                qd, qd_dot, qd_ddot = self.get_desired_state(t=t)
                e: np.ndarray = qd - q
                e_dot: np.ndarray = qd_dot - q_dot
                r1: Optional[np.ndarray] = (e_dot + (self.k_1 * e)) if self.controller_type in ['resnet', 'integrated_resnet', 'baseline', 'supertwisting'] else None

                # Snapshot theta_hat as it stood when this tick's control was computed, before
                # compute_control_output's internal compiled_update_step call reassigns it --
                # matches the real-hardware CSV convention (weight_history[i] is the weight
                # actually driving tick i's phi_val/control output, not the post-update value
                # that only takes effect starting next tick). JAX arrays are immutable, so this
                # plain reference is already an independent snapshot.
                theta_hat_at_tick = self.theta_hat if self.controller_type in ["resnet", "integrated_resnet"] else None

                u, phi_val, theta_hat_dot_val, ball_projected, rate_limited = self.compute_control_output(
                    q=q, q_dot=q_dot, qd=qd, qd_dot=qd_dot, qd_ddot=qd_ddot, e=e, e_dot=e_dot, r1=r1, dt=dt, t=t
                )

                norm_e: float = float(np.linalg.norm(e))
                norm_u: float = float(np.linalg.norm(u))

                self.time_history.append(t)
                self.error_norm_history.append(norm_e)
                self.control_output_norm_history.append(norm_u)
                self.control_output_history.append(u.tolist())
                self.q_history.append(q.tolist())
                self.qd_history.append(qd.tolist())

                if self.controller_type in ["resnet", "integrated_resnet"]:
                    self.weight_history.append(np.array(object=theta_hat_at_tick).flatten().tolist())
                    self.phi_history.append(phi_val.tolist())
                    self.theta_hat_norm_history.append(float(np.linalg.norm(np.array(object=theta_hat_at_tick))))
                    self.theta_hat_dot_norm_history.append(float(np.linalg.norm(theta_hat_dot_val)) if theta_hat_dot_val is not None else 0.0)
                    self.ball_projected_history.append(bool(ball_projected))
                    self.rate_limited_history.append(bool(rate_limited))

                current_error_sq: float = float(norm_e ** 2)
                current_u_sq: float = float(norm_u ** 2)

                if not self.cost_started or dt <= 0:
                    # No previous sample to difference against yet (first tick of the
                    # trajectory) - contribute zero jerk rather than a spurious spike.
                    u_dot: np.ndarray = np.zeros(shape=3, dtype=np.float64)
                    current_u_dot_sq: float = 0.0
                else:
                    u_dot = (u - self.last_u) / dt
                    current_u_dot_sq = float(np.dot(u_dot, u_dot))

                self.u_dot_history.append(u_dot.tolist())

                current_cost_integrand: float = (
                    (self.q_e * current_error_sq) + (self.r_u * current_u_sq) + (self.r_udot * current_u_dot_sq)
                )

                if not self.cost_started:
                    # Seed the history at exact start to prevent trapezoidal integration jump
                    self.last_error_sq = current_error_sq
                    self.last_u_sq = current_u_sq
                    self.last_u_dot_sq = current_u_dot_sq
                    self.last_cost_integrand = current_cost_integrand
                    self.cost_started = True

                self.error_sq_integral += (dt / 2.0) * (current_error_sq + self.last_error_sq)
                self.last_error_sq = current_error_sq

                self.u_sq_integral += (dt / 2.0) * (current_u_sq + self.last_u_sq)
                self.last_u_sq = current_u_sq

                self.u_dot_sq_integral += (dt / 2.0) * (current_u_dot_sq + self.last_u_dot_sq)
                self.last_u_dot_sq = current_u_dot_sq

                self.cost_J += (dt / 2.0) * (current_cost_integrand + self.last_cost_integrand)
                self.last_cost_integrand = current_cost_integrand

                self.last_u = u.copy()
                self.last_t_s = t

                self.is_control_saturated = False
                self.freeze_int_xy = False
                self.freeze_int_z = False

                u_xy: np.ndarray = u[0:2]
                norm_uxy: float = float(np.linalg.norm(u_xy))
                if norm_uxy > self.acc_hor_max_mps2:
                    u[0:2] = u_xy * (self.acc_hor_max_mps2 / norm_uxy)
                    self.is_control_saturated = True
                    if np.dot(a=e[0:2], b=u[0:2]) > 0.0:
                        self.freeze_int_xy = True
                    self.get_logger().debug(f"XY saturation at t={t:.2f}s.")

                if abs(u[2]) > self.acc_vert_max_mps2:
                    u[2] = self.acc_vert_max_mps2 * np.sign(u[2])
                    self.is_control_saturated = True
                    if np.sign(e[2]) == np.sign(u[2]):
                        self.freeze_int_z = True
                    self.get_logger().debug(f"Z saturation at t={t:.2f}s.")

                self.publish_trajectory_setpoint_acceleration(ax=u[0], ay=u[1], az=u[2])

                if t >= self.run_length_s:
                    rms_error: float = math.sqrt(self.error_sq_integral / self.run_length_s) if self.run_length_s > 0 else 0.0
                    rms_u: float = math.sqrt(self.u_sq_integral / self.run_length_s) if self.run_length_s > 0 else 0.0
                    rms_u_dot: float = math.sqrt(self.u_dot_sq_integral / self.run_length_s) if self.run_length_s > 0 else 0.0
                    self.get_logger().info(f"[RESULT] Final cost = {self.cost_J:.2f}.")
                    self.get_logger().info(f"[RESULT] RMS error = {rms_error:.4f}.")
                    self.get_logger().info(f"[RESULT] RMS control effort = {rms_u:.3f}.")
                    self.get_logger().info(f"[RESULT] RMS control jerk = {rms_u_dot:.3f}.")
                    raise ExperimentFinished("Trajectory completed successfully.")

def main(args: Optional[List[str]] = None) -> None:
    # The cyclic GC is a latency-jitter source we don't need: this process runs one
    # bounded experiment and exits, so there's no long-run leak risk to guard against,
    # and refcounting alone still reclaims everything that isn't part of a reference
    # cycle. Disabling it removes an unpredictable stop-the-world pause from the hot
    # control loop, where a single missed control_period_s can bleed into PX4's
    # COM_OF_LOSS_T offboard-signal-loss window.
    gc.disable()

    rclpy.init(args=args)

    # Config comes from YAML file(s) named on the command line, not ROS params.
    # rise_controller.launch.py passes three --params-file arguments (this
    # package's tuning YAML + the two shared files from px4_telemetry and
    # px4_safety_lib); later files win. Running the node directly, pass the
    # same set yourself.
    cli: argparse.ArgumentParser = argparse.ArgumentParser(prog='apark_rise_controller')
    cli.add_argument('--params-file', action='append', dest='params_files', default=[], metavar='PATH',
                     help='YAML parameter file; repeat to layer files (later files win). At least one required.')
    parsed, _unused = cli.parse_known_args(args=remove_ros_args(args=sys.argv)[1:])
    if not parsed.params_files:
        raise SystemExit('apark_rise_controller: at least one --params-file is required.')

    node: AparkRiseNode = AparkRiseNode(params=load_params(paths=parsed.params_files))
    experiment_succeeded: bool = False
    try:
        rclpy.spin(node=node)
    except ExperimentFinished as e:
        node.get_logger().info(f"Experiment terminated: {e}")
        experiment_succeeded = True
    except KeyboardInterrupt:
        node.get_logger().info("Keyboard interrupt received.")
    except ValueError as e:
        node.get_logger().fatal(f"Value error: {e}")
    except JaxLatencyError as e:
        node.get_logger().fatal(f"Hardware error: {e}")
    except OdomTimeoutError as e:
        node.get_logger().fatal(f"Odometry timeout: {e}")
    except FailsafeTriggeredError as e:
        node.get_logger().fatal(f"Failsafe triggered: {e}")
    except BoundaryBreachError as e:
        node.get_logger().fatal(f"Boundary breach: {e}")
    except ControlLoopOverrunError as e:
        node.get_logger().fatal(f"Control loop overrun: {e}")
    finally:
        if experiment_succeeded:
            node.get_logger().info("Commanding vehicle to return to launch.")
            node.return_vehicle()
        else:
            node.get_logger().info("Commanding vehicle to land.")
            node.land_vehicle()
        if rclpy.ok():
            if node.save_data:
                node.get_logger().info("Saving telemetry data to CSV...")
                node.write_csv()

            print("[INFO] Node cleanly destroyed.")
        else:
            print("[FATAL] Node not cleanly destroyed.")

        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
