"""Desired-trajectory generator for the RISE controller.

Each trajectory is a fixed spatial curve pos = phi(phase), traced out by a
scalar phase variable whose own dynamics are a TIME-INVARIANT (autonomous)
ODE: d(phase)/dt = g(phase), with g depending only on phase, never on t
directly. That's the same formulation used in the controller's source paper,
and it's deliberate: an autonomous phase ODE is what lets a single closed-form
spatial map phi(.) fully determine the trajectory, with no separate explicit
time-dependence to track.

Implementation-wise, phase(t) is precomputed once (via `solve_ivp`, in
`_precompute_phases`) over the whole run and cached as a lookup table -- pure
performance/convenience, not a change to the underlying math. At evaluation
time (`_get_traj1_jax`/`_get_traj2_jax`):
  1. `jnp.interp` looks up phase(t) from that table.
  2. `phase_dot` and `phase_ddot` are computed ANALYTICALLY from g and its own
     derivative (via the chain rule), not by differentiating the lookup
     table numerically.
  3. `jax.jacfwd` differentiates the closed-form phi(.) with respect to
     phase, exactly (to floating-point precision, no finite differences).
  4. The chain rule combines (2) and (3) into exact velocity/acceleration:
       vel = phi'(phase) * phase_dot
       acc = phi''(phase) * phase_dot**2 + phi'(phase) * phase_ddot
"""
import jax
import jax.numpy as jnp
import numpy as np
from scipy.integrate import solve_ivp
import math
from typing import Tuple, Any
from functools import partial

class TrajectoryGenerator:
    def __init__(self, config: dict[str, Any]) -> None:
        self.desired_traj = config['desired_trajectory']
        self.run_length_s = config['run_length_s'] + 1.0

        match self.desired_traj:
            case 1:
                self.traj1_center_x_m_enu = config['traj1_center_x_m_enu']
                self.traj1_center_y_m_enu = config['traj1_center_y_m_enu']
                self.traj1_center_z_m_enu = config['traj1_center_z_m_enu']
                self.traj1_period_s = config['traj1_period_s']
                self.traj1_x_amp_m_enu = config['traj1_x_amp_m_enu']
                self.traj1_y_amp_m_enu = config['traj1_y_amp_m_enu']
                self.traj1_z_amp_m_enu = config['traj1_z_amp_m_enu']
                self.traj1_alpha_warp = config['traj1_alpha_warp']
                self.traj1_warp_c = 1.0 / math.sqrt(1.0 - self.traj1_alpha_warp) if self.traj1_alpha_warp < 1.0 else 1.0
                self._precompute_phases()
                _ = self._get_traj1_jax(0.0)
            case 2:
                self.traj2_center_x_m_enu = config['traj2_center_x_m_enu']
                self.traj2_center_y_m_enu = config['traj2_center_y_m_enu']
                self.traj2_center_z_m_enu = config['traj2_center_z_m_enu']
                self.traj2_petal_radius_m = config['traj2_petal_radius_m']
                self.traj2_target_speed_mps = config['traj2_target_speed_mps']
                self._precompute_phases()
                _ = self._get_traj2_jax(0.0)
            case _:
                raise ValueError("INVALID DESIRED TRAJECTORY SELECTED.")

    def _precompute_phases(self) -> None:
        """Solve each trajectory's autonomous phase ODE once, tabulate the result.

        Both ODEs below are time-invariant: the RHS is a function of the
        phase alone (tau or theta), never of t. `solve_ivp` still needs a
        function of (t, y) per its own calling convention, so t is accepted
        and simply ignored inside each RHS closure.
        """
        match self.desired_traj:
            # Trajectory 1 (figure-eight): integrate d(tau)/dt = g_1(tau).
            case 1:
                w = (2.0 * math.pi) / self.traj1_period_s # rad/s, nominal (unwarped) phase rate

                # traj1_alpha_warp in [0, 1) periodically slows tau's advance
                # (via the sin^2 term) to bias dwell time toward the figure-
                # eight's crossing region; traj1_warp_c is a gain compensating
                # for that average slowdown so the phase still advances close
                # to the nominal rate w over a full period. alpha_warp=0
                # recovers dtau/dt = w exactly (no warping).
                def dtau_dt(t: float, tau: np.ndarray) -> float:
                    return self.traj1_warp_c * (1.0 - self.traj1_alpha_warp * math.sin(w * tau[0])**2) # type: ignore

                initial_tau_1 = 0.0 #self.traj1_period_s / 4.0 # Start traj1 1/4 of a period ahead (initial phase tau for that is T/4)
                sol1 = solve_ivp(dtau_dt, [0, self.run_length_s], [initial_tau_1], max_step=0.01)
                self.t_grid_1 = jnp.array(sol1.t)
                self.tau_grid = jnp.array(sol1.y[0])

            # Trajectory 2 (rose/petal): integrate d(theta)/dt = g_2(theta),
            # chosen so the vehicle traces the rose at ~constant linear speed
            # traj2_target_speed_mps despite the petals' varying curvature.
            case 2:
                initial_tau_2 = 0.0
                def dtheta_dt(t: float, theta: np.ndarray) -> float:
                    f_theta = 1.0 + 3.0 * math.sin(2.0 * theta[0])**2
                    return self.traj2_target_speed_mps / (self.traj2_petal_radius_m * math.sqrt(f_theta)) # type: ignore

                sol2 = solve_ivp(dtheta_dt, [0, self.run_length_s], [initial_tau_2], max_step=0.01)
                self.t_grid_2 = jnp.array(sol2.t)
                self.theta_grid = jnp.array(sol2.y[0])

    @partial(jax.jit, static_argnums=(0,))
    def _get_traj1_jax(self, t: float) -> Tuple[jax.Array, jax.Array, jax.Array]:
        """Figure-eight: phi(tau) in ENU, tau(t) from the warped-time ODE above."""
        # 1. Look up the exact phase (tau) for the current time
        tau = jnp.interp(t, self.t_grid_1, self.tau_grid)

        w = (2.0 * jnp.pi) / self.traj1_period_s # rad/s, nominal (unwarped) phase rate

        # 2. Analytical temporal derivatives of tau, straight from the ODE
        # RHS g_1 (tau_dot) and its own tau-derivative via the chain rule
        # (tau_ddot = g_1'(tau) * tau_dot).
        tau_dot = self.traj1_warp_c * (1.0 - self.traj1_alpha_warp * (jnp.sin(w * tau)**2))
        tau_ddot = -2.0 * self.traj1_warp_c * self.traj1_alpha_warp * w * jnp.sin(w * tau) * jnp.cos(w * tau) * tau_dot

        # phi(tau): a standard Lissajous figure-eight, directly in ENU -- no
        # separate axis-rotation step. X traces the single-loop (long) axis
        # at rate w; Y traces the double-loop (short) axis at rate 2w, with
        # the sign below fixing the figure-eight's orientation (crossing at
        # the center, lobes opening toward +/-X). Z gets an independent
        # out-of-plane wobble at 4w. jax.jacfwd differentiates this closed
        # form exactly, so vel/acc come out already in ENU too.
        def pos_fn(tau_val: jax.Array) -> jax.Array:
            x_enu = self.traj1_x_amp_m_enu * jnp.sin(w * tau_val) + self.traj1_center_x_m_enu
            y_enu = -self.traj1_y_amp_m_enu * jnp.sin(2.0 * w * tau_val) + self.traj1_center_y_m_enu
            z_enu = self.traj1_z_amp_m_enu * jnp.sin(4.0 * w * tau_val) + self.traj1_center_z_m_enu
            return jnp.array([x_enu, y_enu, z_enu])

        # 3. Apply the exact chain rule
        pos = pos_fn(tau)
        dp_dtau = jax.jacfwd(pos_fn)(tau)
        d2p_dtau2 = jax.jacfwd(jax.jacfwd(pos_fn))(tau)

        vel = dp_dtau * tau_dot
        acc = d2p_dtau2 * (tau_dot**2) + dp_dtau * tau_ddot
        return pos, vel, acc

    @partial(jax.jit, static_argnums=(0,))
    def _get_traj2_jax(self, t: float) -> Tuple[jax.Array, jax.Array, jax.Array]:
        """Rose/petal curve: phi(theta) in ENU, theta(t) from the constant-speed ODE above."""
        # 1. Look up the exact phase (theta) for the current time
        theta = jnp.interp(t, self.t_grid_2, self.theta_grid)

        # 2. Analytical temporal derivatives of theta, straight from the ODE
        # RHS g_2 (theta_dot) and its own theta-derivative (theta_ddot).
        f_theta = 1.0 + 3.0 * (jnp.sin(2.0 * theta)**2)
        theta_dot = self.traj2_target_speed_mps / (self.traj2_petal_radius_m * jnp.sqrt(f_theta))
        sin_4theta = jnp.sin(4.0 * theta)
        theta_ddot = - (3.0 * (self.traj2_target_speed_mps**2) * sin_4theta) / ((self.traj2_petal_radius_m**2) * (f_theta**2))

        # phi(theta): a 4-petal rose r = R*cos(2*theta) in polar form, mapped
        # into ENU as (r*sin(theta), -r*cos(theta)) so the first petal points
        # toward +X rather than the bare-polar convention's +Y.
        def pos_fn(th: jax.Array) -> jax.Array:
            r = self.traj2_petal_radius_m * jnp.cos(2.0 * th)
            return jnp.array([
                r * jnp.sin(th) + self.traj2_center_x_m_enu,
                -(r * jnp.cos(th)) + self.traj2_center_y_m_enu,
                self.traj2_center_z_m_enu
            ])

        # 3. Apply the exact chain rule
        pos = pos_fn(theta)
        dp_dth = jax.jacfwd(pos_fn)(theta)
        d2p_dth2 = jax.jacfwd(jax.jacfwd(pos_fn))(theta)

        vel = dp_dth * theta_dot
        acc = d2p_dth2 * (theta_dot**2) + dp_dth * theta_ddot
        return pos, vel, acc

    def get_desired_state(self, t: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Desired (position, velocity, acceleration) in ENU at time t, all exact."""
        match self.desired_traj:
            case 1:
                pos, vel, acc = self._get_traj1_jax(t)
            case 2:
                pos, vel, acc = self._get_traj2_jax(t)
            case _:
                return np.zeros(3), np.zeros(3), np.zeros(3)

        return np.array(pos, dtype=np.float64), np.array(vel, dtype=np.float64), np.array(acc, dtype=np.float64)
