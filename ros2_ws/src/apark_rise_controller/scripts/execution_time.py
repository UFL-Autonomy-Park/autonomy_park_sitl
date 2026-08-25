import jax
import jax.numpy as jnp
import time
import numpy as np

# Mocking your ResNet and Jacobian calls for the benchmark
@jax.jit
def dummy_forward_and_jacobian(x, theta):
    # Simulating a small network forward pass and jacobian computation
    y = jnp.dot(x, theta[:15, :3]) 
    jac = jnp.ones((3, len(theta))) # Mock Jacobian shape
    return y, jac

def run_benchmark():
    d_in = 15
    d_out = 3
    num_params = 1500 # Approximate size of your ResNet
    
    x = jnp.ones((d_in,))
    theta = jnp.ones((num_params,))
    
    print("Triggering JIT compilation...")
    start_jit = time.perf_counter()
    _, _ = dummy_forward_and_jacobian(x, theta)
    print(f"JIT took: {time.perf_counter() - start_jit:.4f} seconds")
    
    print("\nRunning 10,000 real-time control loops...")
    times = []
    
    for _ in range(10000):
        # Simulate dynamic state input
        x_dynamic = jax.random.normal(jax.random.PRNGKey(0), (d_in,))
        
        t0 = time.perf_counter()
        # The core JAX math that happens inside your control callback
        _, _ = dummy_forward_and_jacobian(x_dynamic, theta)
        t1 = time.perf_counter()
        
        times.append(t1 - t0)
        
    times = np.array(times) * 1000 # Convert to milliseconds
    
    print(f"Mean Execution Time: {np.mean(times):.3f} ms")
    print(f"99th Percentile:     {np.percentile(times, 99):.3f} ms")
    print(f"Worst Case (Max):    {np.max(times):.3f} ms")
    
    if np.max(times) > 5.0:
        print("\nWARNING: Max execution time consumes >50% of your 10ms budget.")

if __name__ == "__main__":
    run_benchmark()