"""Minimal, standalone MAVROS diagnostic: take off, hold, apply one open-loop
horizontal acceleration step, coast, land.

Deliberately bypasses px4_telemetry/the apark frame entirely and talks to
MAVROS's raw topics directly (local_position/pose, local_position/velocity_local,
setpoint_raw/local) -- this node only needs MAVROS running, nothing else from
this repo's custom stack, so it isolates "what does a raw acceleration
setpoint do" from any of the aero_common rotation/frame conventions.

The acceleration step is commanded via mavros_msgs/PositionTarget with
coordinate_frame=FRAME_LOCAL_NED -- that only selects the MAVLink
SET_POSITION_TARGET_LOCAL_NED message type; the x/y/z fields themselves are
still ROS ENU (MAVROS converts), and no further rotation is applied here, so
+x is raw MAVROS East, +y is raw MAVROS North, +z is up.
"""
import os
import sys
import csv
import argparse
from typing import Optional, List, Dict, Any, Tuple

import numpy as np
import yaml

import rclpy
from rclpy.node import Node
from rclpy.utilities import remove_ros_args
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy

from mavros_msgs.msg import State, PositionTarget
from mavros_msgs.srv import CommandBool, SetMode
from geometry_msgs.msg import PoseStamped, TwistStamped


class ExperimentState:
    STATE_INIT: int = 0
    STATE_TAKEOFF: int = 1
    STATE_STEP_INPUT: int = 2
    STATE_FINISH_UP: int = 3
    STATE_DONE: int = 4

class OdomTimeoutError(Exception):
    pass

class FailsafeTriggeredError(Exception):
    pass

class ExperimentFinished(Exception):
    pass

def _flatten_params(mapping: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    for key, value in mapping.items():
        full_key: str = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten_params(mapping=value, prefix=f"{full_key}."))
        else:
            flat[full_key] = value
    return flat

def _load_param_file(path: str) -> Dict[str, Any]:
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
    merged: Dict[str, Any] = {}
    for path in paths:
        merged.update(_load_param_file(path=path))
    return merged


class DebuggingNode(Node):
    def _get_param(self, name: str) -> Any:
        if name not in self._params:
            raise ValueError(
                f"Required parameter '{name}' is missing from the loaded parameter file(s). "
                f"Loaded keys: {sorted(self._params)}"
            )
        return self._params[name]

    def __init__(self, params: Dict[str, Any]) -> None:
        super().__init__(node_name='debugging_node')

        self._params: Dict[str, Any] = params

        # Basic timing
        control_freq_hz: float = self._get_param(name='control_freq_hz')
        self.control_period_s: float = 1.0 / control_freq_hz
        self.save_data: bool = self._get_param(name='save_data')
        self.run_length_s: float = self._get_param(name='run_length_s')
        self.init_tol_m: float = self._get_param(name='init_tol_m')
        self.init_z_m_enu: float = self._get_param(name='init_z_m_enu')
        self.n_axes: int = 3

        # Step input (open-loop acceleration applied for a fixed duration
        # after takeoff settles)
        self.step_input_delay_s: float = self._get_param(name='step_input_delay_s')
        self.step_input_duration_s: float = self._get_param(name='step_input_duration_s')
        step_input_accel_x_mps2: float = self._get_param(name='step_input_accel_x_mps2')
        step_input_accel_y_mps2: float = self._get_param(name='step_input_accel_y_mps2')
        step_input_accel_z_mps2: float = self._get_param(name='step_input_accel_z_mps2')
        self.step_input_accel_mps2: np.ndarray = np.array(
            object=[step_input_accel_x_mps2, step_input_accel_y_mps2, step_input_accel_z_mps2], dtype=np.float64
        )
        self.heartbeat_cutoff_delay_s: float = self._get_param(name='heartbeat_cutoff_delay_s')

        self.arm_timeout_s: float = self._get_param(name='arm_timeout_s')
        self.offboard_mode_heartbeat_freq_hz: float = self._get_param(name='offboard_mode_heartbeat_freq_hz')
        offboard_mode_heartbeat_period_s = 1.0 / self.offboard_mode_heartbeat_freq_hz
        self.odom_timeout_s: float = self._get_param(name='odom_timeout_s')
        odom_watchdog_freq_hz: float = self._get_param(name='odom_watchdog_freq_hz')
        odom_watchdog_period_s = 1.0 / odom_watchdog_freq_hz
        mode_publisher_freq_hz: float = self._get_param(name='mode_publisher_freq_hz')
        self.mode_publisher_period_s = 1.0 / mode_publisher_freq_hz

        # Control (position-error -> acceleration-setpoint PID, TAKEOFF only)
        self.k_p: float = self._get_param(name='k_p')
        self.k_i: float = self._get_param(name='k_i')
        self.k_d: float = self._get_param(name='k_d')

        # Internal flags
        self.is_armed: bool = False
        self.in_offboard_mode: bool = False
        self.landing_command_sent: bool = False
        self.initial_position_locked: bool = False
        self.publish_offboard_heartbeat: bool = False
        self.position_mode_requested: bool = False
        self.step_command_sent: bool = False
        self.latest_pose: Optional[PoseStamped] = None
        self.latest_velocity: Optional[TwistStamped] = None

        self.last_pose_ros_time_s: float = 0.0
        self.init_x_m_enu: float = 0.0
        self.init_y_m_enu: float = 0.0
        self.experiment_state: int = ExperimentState.STATE_INIT

        # Per-state timestamps, set as the state machine transitions
        # (last_mode_cmd_time_s is initialized below, once heartbeat_raised_time_s is known)
        self.takeoff_entry_time_s: float = 0.0
        self.step_input_entry_time_s: float = 0.0
        self.finish_up_entry_time_s: float = 0.0
        self.heartbeat_stopped_time_s: Optional[float] = None

        self.reset_integral()

        self.time_history: List[float] = []
        self.state_history: List[str] = []
        self.position_history: List[List[float]] = []
        self.velocity_history: List[List[float]] = []
        self.accel_cmd_history: List[List[float]] = []

        qos_profile: QoSProfile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            depth=1,
            history=HistoryPolicy.KEEP_LAST
        )

        # setpoint_raw/local (NOT /global -- that topic is a different
        # message type, GlobalPositionTarget, lat/lon based; this repo's
        # apark_rise_node.py currently points at /global with this same
        # PositionTarget type, which MAVROS's GlobalPositionTarget
        # subscriber there will never match -- see the chat writeup).
        self.setpoint_publisher = self.create_publisher(
            msg_type=PositionTarget, topic='setpoint_raw/local', qos_profile=qos_profile)

        self.state_sub = self.create_subscription(
            msg_type=State, topic='state', callback=self.state_callback, qos_profile=qos_profile)
        # Raw MAVROS ENU, not autonomy_park/pose -- this node deliberately
        # doesn't depend on px4_telemetry.
        self.pose_sub = self.create_subscription(
            msg_type=PoseStamped, topic='autonomy_park/pose', callback=self.pose_callback, qos_profile=qos_profile)
        self.velocity_sub = self.create_subscription(
            msg_type=TwistStamped, topic='local_position/velocity_local', callback=self.velocity_callback, qos_profile=qos_profile)

        self.arming_client = self.create_client(srv_type=CommandBool, srv_name='cmd/arming')
        self.set_mode_client = self.create_client(srv_type=SetMode, srv_name='set_mode')

        self.control_timer = self.create_timer(
            timer_period_sec=self.control_period_s,
            callback=self.control_timer_callback
        )
        self.pose_watchdog_timer = self.create_timer(
            timer_period_sec=odom_watchdog_period_s,
            callback=self.pose_watchdog_callback
        )
        self.offboard_heartbeat_timer = self.create_timer(
            timer_period_sec=offboard_mode_heartbeat_period_s,
            callback=self.offboard_heartbeat_callback
        )

        self.publish_offboard_heartbeat = False
        self.heartbeat_raised_time_s = self.get_clock().now().nanoseconds / 1e9
        # Defer the first mode-switch/arm attempt by one mode_publisher_period_s so
        # PX4 has already seen a handful of streamed setpoints -- an immediate
        # attempt races the very first setpoint and PX4 will reject the switch.
        self.last_mode_cmd_time_s = self.heartbeat_raised_time_s

        self.get_logger().info("Node Initialized Successfully. Offboard heartbeat raised; waiting for OFFBOARD mode confirmation.")

    def land_vehicle(self) -> None:
        if self.landing_command_sent:
            return
        self._request_mode(mode="AUTO.LAND")
        self.landing_command_sent = True

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

    def state_callback(self, msg: State) -> None:
        was_in_offboard_mode: bool = self.in_offboard_mode
        was_armed: bool = self.is_armed

        self.is_armed = msg.armed
        self.in_offboard_mode = (msg.mode == "OFFBOARD")

        if was_in_offboard_mode and not self.in_offboard_mode:
            now_s: float = self.get_clock().now().nanoseconds / 1e9
            if self.heartbeat_stopped_time_s is not None:
                self.get_logger().info(
                    f"PX4 exited OFFBOARD mode {now_s - self.heartbeat_stopped_time_s:.3f}s after the heartbeat was stopped."
                )
            else:
                self.get_logger().info(f"PX4 exited OFFBOARD mode at t={now_s:.3f}s (heartbeat was still active).")

        # The flight isn't actually over just because OFFBOARD was left -- PX4's
        # failsafe fallback still has to run its course. Wait for the real
        # end-of-flight signal (auto-disarm after landing) so the log
        # captures whatever that fallback actually does.
        if was_armed and not self.is_armed and self.experiment_state == ExperimentState.STATE_DONE:
            raise ExperimentFinished("PX4 disarmed after the deliberate heartbeat cutoff.")

    def pose_callback(self, msg: PoseStamped) -> None:
        self.latest_pose = msg
        self.last_pose_ros_time_s = self.get_clock().now().nanoseconds / 1e9

        if not self.initial_position_locked:
            self.init_x_m_enu = float(msg.pose.position.x)
            self.init_y_m_enu = float(msg.pose.position.y)
            self.initial_position_locked = True

    def velocity_callback(self, msg: TwistStamped) -> None:
        self.latest_velocity = msg

    def pose_watchdog_callback(self) -> None:
        if self.latest_pose is None:
            return

        elapsed_s = self.get_clock().now().nanoseconds / 1e9 - self.last_pose_ros_time_s

        if elapsed_s >= self.odom_timeout_s:
            self.publish_offboard_heartbeat = False
            raise OdomTimeoutError(f"No local_position/pose received for {elapsed_s:.1f}s.")

    def reset_integral(self) -> None:
        self.current_control_integrand = np.zeros(shape=self.n_axes, dtype=np.float64)
        self.last_control_integrand = np.zeros(shape=self.n_axes, dtype=np.float64)

    def offboard_heartbeat_callback(self) -> None:
        # Publishing PositionTarget below (every control tick) already keeps
        # OFFBOARD alive by itself; this timer exists so the deliberate
        # heartbeat cutoff (STATE_FINISH_UP -> STATE_DONE) has a single flag
        # to gate on, matching apark_rise_node's pattern. It intentionally
        # does not publish anything of its own.
        pass

    def publish_trajectory_setpoint_acceleration(self, ax: float, ay: float, az: float) -> None:
        if self.latest_pose is None:
            self.get_logger().warning("Ignoring setpoint since there has been no pose yet.")
            return

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
        msg.acceleration_or_force.x = ax
        msg.acceleration_or_force.y = ay
        msg.acceleration_or_force.z = az
        msg.yaw = 0.0
        self.setpoint_publisher.publish(msg)

        if self.save_data:
            now_s: float = self.get_clock().now().nanoseconds / 1e9
            q = self.latest_pose.pose.position
            v = self.latest_velocity.twist.linear if self.latest_velocity is not None else None
            self.time_history.append(now_s)
            self.state_history.append(
                {0: 'INIT', 1: 'TAKEOFF', 2: 'STEP_INPUT', 3: 'FINISH_UP', 4: 'DONE'}[self.experiment_state]
            )
            self.position_history.append([q.x, q.y, q.z])
            self.velocity_history.append([v.x, v.y, v.z] if v is not None else [float('nan')] * 3)
            self.accel_cmd_history.append([ax, ay, az])

    def write_csv(self) -> None:
        base_dir: str = "simulation_data/debugging_node"
        os.makedirs(name=base_dir, exist_ok=True)

        existing_files: List[str] = [f for f in os.listdir(path=base_dir) if f.endswith('.csv') and f.startswith('run_')]
        max_idx: int = 0
        for f in existing_files:
            try:
                idx = int(f.replace('run_', '').replace('.csv', ''))
                max_idx = max(max_idx, idx)
            except ValueError:
                pass
        csv_filename: str = os.path.join(base_dir, f"run_{max_idx + 1}.csv")

        try:
            with open(file=csv_filename, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([
                    "Time_s", "State", "x_m", "y_m", "z_m",
                    "vx_mps", "vy_mps", "vz_mps",
                    "ax_cmd_mps2", "ay_cmd_mps2", "az_cmd_mps2",
                ])
                for i in range(len(self.time_history)):
                    writer.writerow([
                        self.time_history[i], self.state_history[i], *self.position_history[i],
                        *self.velocity_history[i], *self.accel_cmd_history[i],
                    ])
            self.get_logger().info(f"Telemetry saved to {csv_filename}")
        except Exception as e:
            self.get_logger().error(f"Failed to write CSV: {e}")

    def get_desired_state_takeoff(self) -> np.ndarray:
        # During takeoff, hold exactly above where it initialized
        return np.array(object=[self.init_x_m_enu, self.init_y_m_enu, self.init_z_m_enu], dtype=np.float64)

    def run_pid(self, qd: np.ndarray, dt: float, axes: Tuple[int, ...] = (0, 1, 2)) -> np.ndarray:
        """Same PID (gains, trapezoidal integration) used for TAKEOFF's full 3-axis
        hold and for holding just Z during STEP_INPUT/FINISH_UP. `axes` selects
        which components actually accumulate integral this tick -- e.g. a
        Z-only call (axes=(2,)) leaves the X/Y integrator state untouched, so
        it doesn't wind up against the deliberately-large X/Y error caused by
        the open-loop step command, and isn't carrying stale windup if X/Y
        hold is ever resumed. The returned vector always has all 3 components;
        callers just take the ones they need (all 3 for a full hold, u[2] for
        Z-only).
        """
        q: np.ndarray = np.array(object=[
            self.latest_pose.pose.position.x, self.latest_pose.pose.position.y, self.latest_pose.pose.position.z
        ], dtype=np.float64)
        v = self.latest_velocity.twist.linear if self.latest_velocity is not None else None
        q_dot: np.ndarray = np.array(object=[v.x, v.y, v.z] if v is not None else [0.0, 0.0, 0.0], dtype=np.float64)

        e: np.ndarray = qd - q
        e_dot: np.ndarray = -q_dot  # qd_dot is always zero (holding a fixed point)

        # PID Controller (trapezoidal integration)
        current_integrand: np.ndarray = (self.k_i * e)
        delta_int: np.ndarray = (dt / 2.0) * (current_integrand + self.last_control_integrand)
        for axis in axes:
            self.current_control_integrand[axis] += delta_int[axis]
        self.last_control_integrand = current_integrand

        u: np.ndarray = (self.k_p * e) + (self.k_d * e_dot) + self.current_control_integrand
        return u

    def run_z_pid(self, dt: float) -> float:
        """Z-only convenience wrapper: holds init_z_m_enu via the same PID as
        TAKEOFF, without touching the X/Y integrator state."""
        qd: np.ndarray = self.get_desired_state_takeoff()
        u: np.ndarray = self.run_pid(qd=qd, dt=dt, axes=(2,))
        return float(u[2])

    def control_timer_callback(self) -> None:
        if self.latest_pose is None:
            return

        now_s: float = self.get_clock().now().nanoseconds / 1e9
        q: np.ndarray = np.array(object=[
            self.latest_pose.pose.position.x, self.latest_pose.pose.position.y, self.latest_pose.pose.position.z
        ], dtype=np.float64)

        match self.experiment_state:
            case ExperimentState.STATE_INIT:
                # Must publish setpoints with a TrajectorySetpoint otherwise transition to Offboard will be declined
                self.publish_offboard_heartbeat = True
                self.publish_trajectory_setpoint_acceleration(ax=0.0, ay=0.0, az=0.0)

                if not self.position_mode_requested:
                    # Recommended PX4 practice: enter OFFBOARD from Position mode, so that if
                    # the vehicle ever drops out of OFFBOARD it falls back to a stable hover
                    # instead of whatever mode it happened to boot into.
                    self._request_mode(mode="POSCTL")
                    self.position_mode_requested = True

                if now_s - self.heartbeat_raised_time_s > self.run_length_s:
                    raise FailsafeTriggeredError(
                        f"Vehicle did not reach ARMED + OFFBOARD within run_length_s={self.run_length_s:.1f}s of the heartbeat being raised."
                    )

                # SITL-only: there's no RC pilot / QGC operator to arm and flip the mode
                # switch, so this node has to do both itself. On real hardware this whole
                # block is unnecessary -- the node would just wait for offboard.
                #
                # NOTE: PX4 will not accept an arm command until it is already switching
                # into OFFBOARD (it rejects COMPONENT_ARM_DISARM while sitting in
                # the default AUTO mode). So both commands must be retried together, not
                # arm-then-switch -- gating the mode-switch behind is_armed deadlocks, since
                # arming itself depends on the switch being in flight.
                if not (self.is_armed and self.in_offboard_mode):
                    self.get_logger().info("Waiting for ARM + OFFBOARD mode switch...", throttle_duration_sec=2.0)
                    if now_s - self.last_mode_cmd_time_s > self.mode_publisher_period_s:
                        self._request_mode(mode="OFFBOARD")
                        if not self.is_armed:
                            self._request_arm()
                        self.last_mode_cmd_time_s = now_s
                    return

                elapsed_s: float = now_s - self.heartbeat_raised_time_s
                self.get_logger().info(f"PX4 confirmed OFFBOARD mode after {elapsed_s:.3f}s.")

                self.get_logger().info(f"ARMED & OFFBOARD validated. Initializing takeoff to z={self.init_z_m_enu:.2f}m (ENU).")
                self.reset_integral()
                self.experiment_state = ExperimentState.STATE_TAKEOFF
                self.takeoff_entry_time_s = now_s

            case ExperimentState.STATE_TAKEOFF:
                if not self.in_offboard_mode:
                    self.publish_offboard_heartbeat = False
                    raise FailsafeTriggeredError("PX4 left OFFBOARD mode during takeoff.")

                if now_s - self.heartbeat_raised_time_s > self.run_length_s:
                    self.publish_offboard_heartbeat = False
                    raise FailsafeTriggeredError(
                        f"Takeoff did not settle within run_length_s={self.run_length_s:.1f}s of the heartbeat being raised."
                    )

                qd: np.ndarray = self.get_desired_state_takeoff()
                u: np.ndarray = self.run_pid(qd=qd, dt=self.control_period_s)
                self.publish_trajectory_setpoint_acceleration(ax=u[0], ay=u[1], az=u[2])

                error_norm: float = float(np.linalg.norm(qd - q))
                if error_norm <= self.init_tol_m:
                    self.get_logger().info(
                        f"TAKEOFF SETTLED after {now_s - self.takeoff_entry_time_s:.3f}s "
                        f"(error={error_norm:.2f}m <= tol={self.init_tol_m:.2f}m)."
                    )
                    self.experiment_state = ExperimentState.STATE_STEP_INPUT
                    self.step_input_entry_time_s = now_s

            case ExperimentState.STATE_STEP_INPUT:
                if not self.in_offboard_mode:
                    self.publish_offboard_heartbeat = False
                    raise FailsafeTriggeredError("PX4 left OFFBOARD mode before/during the step input.")

                dt_since_entry: float = now_s - self.step_input_entry_time_s

                if dt_since_entry < self.step_input_delay_s:
                    # Still settling: hold position via PID like TAKEOFF.
                    qd = self.get_desired_state_takeoff()
                    u = self.run_pid(qd=qd, dt=self.control_period_s)
                    self.publish_trajectory_setpoint_acceleration(ax=u[0], ay=u[1], az=u[2])
                elif dt_since_entry < self.step_input_delay_s + self.step_input_duration_s:
                    # X/Y open-loop: stream the fixed acceleration command for
                    # its full duration (PX4 needs a continuous >2Hz OFFBOARD
                    # stream, so this is NOT a single one-shot command). Z
                    # stays closed-loop via the same PID as TAKEOFF, holding
                    # init_z_m_enu throughout the step.
                    if not self.step_command_sent:
                        self.get_logger().info(
                            f"Step input starting: accel={self.step_input_accel_mps2.tolist()} m/s^2 "
                            f"for {self.step_input_duration_s:.2f}s."
                        )
                        self.step_command_sent = True
                    ax, ay, _ = self.step_input_accel_mps2
                    az = self.run_z_pid(dt=self.control_period_s)
                    self.publish_trajectory_setpoint_acceleration(ax=ax, ay=ay, az=az)
                else:
                    self.get_logger().info("Step input complete. Coasting (zero accel) before heartbeat cutoff.")
                    self.experiment_state = ExperimentState.STATE_FINISH_UP
                    self.finish_up_entry_time_s = now_s

            case ExperimentState.STATE_FINISH_UP:
                if not self.in_offboard_mode:
                    self.publish_offboard_heartbeat = False
                    raise FailsafeTriggeredError("PX4 left OFFBOARD mode during the coast-down.")

                # X/Y open-loop coast: zero commanded acceleration, so the
                # resulting horizontal velocity/drift is purely whatever the
                # step input left behind -- no controller correcting it out.
                # Z still holds init_z_m_enu via the same PID as TAKEOFF.
                az = self.run_z_pid(dt=self.control_period_s)
                self.publish_trajectory_setpoint_acceleration(ax=0.0, ay=0.0, az=az)

                if now_s - self.finish_up_entry_time_s >= self.heartbeat_cutoff_delay_s:
                    self.publish_offboard_heartbeat = False
                    self.heartbeat_stopped_time_s = now_s
                    self.get_logger().info(
                        f"Heartbeat stopped {now_s - self.finish_up_entry_time_s:.3f}s after the step input. "
                        f"Waiting for PX4 to exit OFFBOARD."
                    )
                    self.experiment_state = ExperimentState.STATE_DONE

            case ExperimentState.STATE_DONE:
                pass


def main(args: Optional[List[str]] = None) -> None:
    rclpy.init(args=args)

    cli: argparse.ArgumentParser = argparse.ArgumentParser(prog='debugging_node')
    cli.add_argument('--params-file', action='append', dest='params_files', default=[], metavar='PATH',
                         help='YAML parameter file; repeat to layer files (later files win). At least one required.')
    parsed, _unused = cli.parse_known_args(args=remove_ros_args(args=sys.argv)[1:])
    if not parsed.params_files:
        raise SystemExit('debugging_node: at least one --params-file is required.')

    node: DebuggingNode = DebuggingNode(params=load_params(paths=parsed.params_files))

    try:
        rclpy.spin(node=node)
    except ExperimentFinished as e:
        node.get_logger().info(f"Experiment terminated: {e}")
    except KeyboardInterrupt:
        node.get_logger().info("Keyboard interrupt received.")
    except ValueError as e:
        node.get_logger().fatal(f"Value error: {e}")
    except OdomTimeoutError as e:
        node.get_logger().fatal(f"Odometry timeout: {e}")
    except FailsafeTriggeredError as e:
        node.get_logger().fatal(f"Failsafe triggered: {e}")
    finally:
        node.get_logger().info("Commanding vehicle to land.")
        node.land_vehicle()
        if rclpy.ok():
            if node.save_data:
                node.get_logger().info("Saving run data to CSV...")
                node.write_csv()

            print("[INFO] Node cleanly destroyed.")
        else:
            print("[FATAL] Node not cleanly destroyed.")

        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
