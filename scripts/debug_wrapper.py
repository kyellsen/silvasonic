import subprocess
import sys

print("Wrapper starting...")
try:
    # Run the verification script
    # Ensure PYTHONPATH includes necessary directories
    env = {"PYTHONPATH": "services/status-board/src:packages/core/src", "PATH": sys.path}

    # We use full env or just simple addition?
    # Better to just use sys.executable and rely on script's sys.path append

    cmd = [sys.executable, "scripts/verify_subscriber_standalone.py"]

    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)

    with open("verification_result.log", "wb") as f:
        f.write(b"SUCCESS:\n")
        f.write(out)

except subprocess.CalledProcessError as e:
    with open("verification_result.log", "wb") as f:
        f.write(f"FAILURE (Exit {e.returncode}):\n".encode())
        f.write(e.output)

except Exception as e:
    with open("verification_result.log", "w") as f:
        f.write(f"WRAPPER ERROR: {e}")
