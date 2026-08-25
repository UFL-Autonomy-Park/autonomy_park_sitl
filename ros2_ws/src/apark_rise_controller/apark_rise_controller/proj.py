import jax
import jax.numpy as jnp

@jax.jit
def discrete_projection(
    theta_hat: jax.Array,
    theta_dot_unprojected: jax.Array,
    dt: float,
    theta_bar: float,
    gamma_diag: jax.Array
) -> tuple[jax.Array, jax.Array]:
    theta_temp = theta_hat + dt * theta_dot_unprojected
    # theta_bar is a norm bound on the whole weight vector (jnp.sum(theta**2) is
    # ||theta||^2), not a per-weight bound -- is_inside is False, i.e. the ball
    # projection actually shrinks theta_temp, only once ||theta_temp|| itself exceeds
    # theta_bar.
    is_inside = jnp.sum(theta_temp**2) <= theta_bar**2
    ball_projected = jnp.logical_not(is_inside)
    
    def apply_projection(_: None) -> jax.Array:
        gamma_min = jnp.min(gamma_diag)
        norm_temp = jnp.linalg.norm(theta_temp)
        eta_upper_init = (norm_temp / theta_bar - 1.0) / gamma_min
        init_state = (0.0, eta_upper_init)
        
        def bisection_step(i: int, state: tuple[jax.Array, jax.Array]) -> tuple[jax.Array, jax.Array]:
            eta_low, eta_high = state
            eta_mid = 0.5 * (eta_low + eta_high)
            theta_test = theta_temp / (1.0 + eta_mid * gamma_diag)
            val = jnp.sum(theta_test**2) - theta_bar**2
            new_low = jnp.where(val > 0, eta_mid, eta_low)
            new_high = jnp.where(val > 0, eta_high, eta_mid)
            return (new_low, new_high)
        
        final_low, final_high = jax.lax.fori_loop(0, 30, bisection_step, init_state)
        eta_opt = 0.5 * (final_low + final_high)
        return theta_temp / (1.0 + eta_opt * gamma_diag) # type: ignore

    def bypass_projection(_: None) -> jax.Array:
        return theta_temp

    theta_next: jax.Array = jax.lax.cond(is_inside, bypass_projection, apply_projection, None) # type: ignore
    return theta_next, ball_projected

@jax.jit
def discrete_rate_projection(
    theta_hat: jax.Array,
    theta_next: jax.Array,
    dt: float,
    theta_dot_bar: float
) -> tuple[jax.Array, jax.Array]:
    # Discrete analog of the continuous-time rate saturation theta_hat_dot =
    # sat(proj(nominal_theta_hat_dot)): theta_next here is ALREADY the output of
    # discrete_projection (the "proj" stage), so this only ever needs to shrink the
    # step -- never redirect it. Written in terms of the per-step DISPLACEMENT
    # (theta_next - theta_hat) rather than dividing by dt directly, since dt is a
    # measured (not fixed) control-loop period: comparing the displacement against
    # the max ALLOWED displacement (theta_dot_bar * dt) avoids ever forming
    # rate = displacement / dt as an intermediate value, so a tiny or zero dt can't
    # produce inf/NaN.
    #
    # Correctness of doing this AFTER (outside of) the ball projection, rather than
    # capping the nominal rate before it: uniformly shrinking the displacement
    # produces a point on the straight-line segment between theta_hat and
    # theta_next. Both endpoints are already guaranteed inside the theta_bar ball
    # (theta_hat inductively from the previous step, theta_next by construction of
    # discrete_projection), and the ball is convex, so every point on that segment
    # -- including this shrunk one -- is inside it too. The rate cap gets the
    # ball-safety guarantee for free, with no re-projection needed.
    displacement = theta_next - theta_hat
    disp_norm = jnp.linalg.norm(displacement)
    max_displacement = jnp.maximum(theta_dot_bar * dt, 0.0)

    rate_limited = disp_norm > max_displacement

    eps = 1e-12
    scale = jnp.where(rate_limited, max_displacement / jnp.maximum(disp_norm, eps), 1.0)

    return theta_hat + scale * displacement, rate_limited
