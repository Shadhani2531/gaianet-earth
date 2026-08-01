import subprocess
import time
import urllib.request
import urllib.error
import sys
import os

def run_benchmark():
    # Start the FastAPI server
    backend_dir = os.path.join(os.getcwd(), "backend")
    print(f"Starting server in {backend_dir}...")
    server_process = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=backend_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server to boot up
    time.sleep(3.0)
    
    status_url = "http://localhost:8000/api/status"
    climate_url = "http://localhost:8000/climate?lat=39.80&lon=-122.95"
    prediction_url = "http://localhost:8000/prediction?scenario=1_5&lat=39.80&lon=-122.95"
    
    # Verify server is up
    try:
        urllib.request.urlopen(status_url, timeout=2)
        print("Server is online!")
    except Exception as e:
        print(f"Failed to connect to server: {e}")
        server_process.terminate()
        return

    # 1. Normal Conditions (Open-Meteo API live query)
    print("\n--- Benchmarking Normal API Fusion Latency (10 trials) ---")
    normal_latencies = []
    for i in range(10):
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(climate_url, timeout=10) as resp:
                resp.read()
            end = time.perf_counter()
            latency = (end - start) * 1000  # ms
            normal_latencies.append(latency)
            print(f"Trial {i+1}: {latency:.2f} ms")
        except Exception as e:
            print(f"Trial {i+1} failed: {e}")
        time.sleep(0.5) # Prevent aggressive querying

    # 2. Prediction CCE logic Latency
    print("\n--- Benchmarking CCE Prediction Endpoint Latency (10 trials) ---")
    prediction_latencies = []
    for i in range(10):
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(prediction_url, timeout=10) as resp:
                resp.read()
            end = time.perf_counter()
            latency = (end - start) * 1000
            prediction_latencies.append(latency)
            print(f"Trial {i+1}: {latency:.2f} ms")
        except Exception as e:
            print(f"Trial {i+1} failed: {e}")
        time.sleep(0.5)

    # 3. Throttled/Rate-limited Fallback Latency
    # We measure local fallback generation latency using python time (the database / generation part)
    # inside backend/services/climate.py: _generate_fallback_data
    sys.path.insert(0, backend_dir)
    from services.climate import _generate_fallback_data
    print("\n--- Benchmarking Rate-Limited Local Fallback Generation (1000 trials) ---")
    fallback_latencies = []
    for _ in range(1000):
        start = time.perf_counter()
        _generate_fallback_data(39.80, -122.95, 6)
        end = time.perf_counter()
        fallback_latencies.append((end - start) * 1000)
    
    # Terminate the server
    print("\nShutting down server...")
    server_process.terminate()
    server_process.wait()
    
    # Calculate stats
    avg_normal = sum(normal_latencies) / len(normal_latencies) if normal_latencies else 0
    avg_pred = sum(prediction_latencies) / len(prediction_latencies) if prediction_latencies else 0
    avg_fallback = sum(fallback_latencies) / len(fallback_latencies) if fallback_latencies else 0
    
    print("\n=== BENCHMARK RESULTS ===")
    print(f"Normal Climate API Fusion Latency (Live Open-Meteo Query): {avg_normal:.2f} ms (avg of {len(normal_latencies)} trials)")
    print(f"CCE Prediction Endpoint Latency (Formula computation): {avg_pred:.2f} ms (avg of {len(prediction_latencies)} trials)")
    print(f"Throttled Fallback Generation Latency (Local Synthesis): {avg_fallback:.4f} ms (avg of 1000 trials)")

if __name__ == "__main__":
    run_benchmark()
