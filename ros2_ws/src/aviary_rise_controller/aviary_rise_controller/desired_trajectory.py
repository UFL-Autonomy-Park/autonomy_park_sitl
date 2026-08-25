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
                self.traj2_center_z_m_enu = config['traj2_center_z_m_enu']
                self.traj2_petal_radius_m = config['traj2_petal_radius_m']
                self.traj2_target_speed_mps = config['traj2_target_speed_mps']
                self._precompute_phases()
                _ = self._get_traj2_jax(0.0)
            case _:
                raise ValueError("INVALID DESIRED TRAJECTORY SELECTED.")

    def _precompute_phases(self) -> None:
        match self.desired_traj:
            # Trajectory 1: Integrate d(tau)/dt
            case 1:
                w = (2.0 * math.pi) / self.traj1_period_s # rad/s
                def dtau_dt(t: float, tau: np.ndarray) -> float:
                    return self.traj1_warp_c * (1.0 - self.traj1_alpha_warp * math.sin(w * tau[0])**2) # type: ignore

                initial_tau_1 = 0.0 #self.traj1_period_s / 4.0 # Start traj1 1/4 of a period ahead (initial phase tau for that is T/4)
                sol1 = solve_ivp(dtau_dt, [0, self.run_length_s], [initial_tau_1], max_step=0.01)
                self.t_grid_1 = jnp.array(sol1.t)
                self.tau_grid = jnp.array(sol1.y[0])

            # Trajectory 2: Integrate d(theta)/dt
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
        # 1. Look up the exact phase (tau) for the current time
        tau = jnp.interp(t, self.t_grid_1, self.tau_grid)

        w = (2.0 * jnp.pi) / self.traj1_period_s # rads
        wx, wy, wz = 2.0 * w, 1.0 * w, 4.0 * w

        # 2. Compute analytical temporal derivatives of tau
        tau_dot = self.traj1_warp_c * (1.0 - self.traj1_alpha_warp * (jnp.sin(w * tau)**2))
        tau_ddot = -2.0 * self.traj1_warp_c * self.traj1_alpha_warp * w * jnp.sin(w * tau) * jnp.cos(w * tau) * tau_dot

        # x_amp/y_amp below are legacy formula-axis amplitudes (not final world
        # axes): the -90deg rotation folded directly into pos_fn below is what
        # actually places (x, y) in this park's ENU frame -- the old long axis,
        # y, becomes this park's long axis, x. z is unrotated and specified
        # directly in ENU (traj1_center_z_m_enu, positive = up), since a
        # vertical-axis rotation can't touch it anyway. jax.jacfwd differentiates
        # straight through this linear transform, so vel/acc come out already
        # in the same ENU frame as pos with no separate rotation step needed.
        def pos_fn(tau_val: jax.Array) -> jax.Array:
            x_legacy = self.traj1_x_amp_m_enu * jnp.sin(wx * tau_val)
            y_legacy = self.traj1_y_amp_m_enu * jnp.sin(wy * tau_val)
            z_enu = self.traj1_z_amp_m_enu * jnp.sin(wz * tau_val) + self.traj1_center_z_m_enu
            return jnp.array([y_legacy, -x_legacy, z_enu])

        # 3. Apply the exact chain rule
        pos = pos_fn(tau)
        dp_dtau = jax.jacfwd(pos_fn)(tau)
        d2p_dtau2 = jax.jacfwd(jax.jacfwd(pos_fn))(tau)

        vel = dp_dtau * tau_dot
        acc = d2p_dtau2 * (tau_dot**2) + dp_dtau * tau_ddot
        return pos, vel, acc

    @partial(jax.jit, static_argnums=(0,))
    def _get_traj2_jax(self, t: float) -> Tuple[jax.Array, jax.Array, jax.Array]:
        # 1. Look up the exact phase (theta) for the current time
        theta = jnp.interp(t, self.t_grid_2, self.theta_grid)

        # 2. Compute analytical temporal derivatives of theta
        f_theta = 1.0 + 3.0 * (jnp.sin(2.0 * theta)**2)
        theta_dot = self.traj2_target_speed_mps / (self.traj2_petal_radius_m * jnp.sqrt(f_theta))
        sin_4theta = jnp.sin(4.0 * theta)
        theta_ddot = - (3.0 * (self.traj2_target_speed_mps**2) * sin_4theta) / ((self.traj2_petal_radius_m**2) * (f_theta**2))

        # -90deg rotation folded directly into pos_fn, same as traj1's -- r*sin/
        # r*cos swap places (x, y). z is specified directly in ENU
        # (traj2_center_z_m_enu, positive = up).
        def pos_fn(th: jax.Array) -> jax.Array:
            r = self.traj2_petal_radius_m * jnp.cos(2.0 * th)
            return jnp.array([
                r * jnp.sin(th),
                -(r * jnp.cos(th)),
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
        match self.desired_traj:
            case 1:
                pos, vel, acc = self._get_traj1_jax(t)
            case 2:
                pos, vel, acc = self._get_traj2_jax(t)
            case _:
                return np.zeros(3), np.zeros(3), np.zeros(3)

        return np.array(pos, dtype=np.float64), np.array(vel, dtype=np.float64), np.array(acc, dtype=np.float64)
