import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

if len(sys.argv) != 3:
    raise SystemExit("Usage: python3 scripts/deploy.py NAMESPACE IMAGE_TAG")

namespace, tag = sys.argv[1:]
if namespace not in {"dev", "qa", "staging", "prod"}:
    raise SystemExit("Unsupported namespace")

root = Path(__file__).resolve().parents[1]

def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)

# Preserve credentials already associated with existing database volumes.
existing = subprocess.check_output([
    "kubectl", "-n", namespace, "get", "secret", "jenkins-exam-db",
    "--ignore-not-found", "-o", "name",
], text=True).strip()

if not existing:
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "jenkins-exam-db", "namespace": namespace},
        "type": "Opaque",
        "stringData": {
            "movie-password": secrets.token_hex(24),
            "cast-password": secrets.token_hex(24),
        },
    }
    run(
        "kubectl", "create", "-f", "-",
        input=json.dumps(secret), text=True,
    )

run(
    "helm", "upgrade", "--install", "jenkins-exam", str(root / "charts"),
    "--namespace", namespace,
    "--set-string", f"image.tag={tag}",
    "--wait", "--timeout", "10m",
)

# Use an available local port for this test.
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]

with tempfile.TemporaryFile(mode="w+") as log:
    forward = subprocess.Popen([
        "kubectl", "-n", namespace, "port-forward",
        "service/jenkins-exam-nginx", f"{port}:8080",
        "--address", "127.0.0.1",
    ], stdout=log, stderr=subprocess.STDOUT)

    try:
        base = f"http://127.0.0.1:{port}"
        for attempt in range(60):
            if forward.poll() is not None:
                log.seek(0)
                raise RuntimeError("Port-forward failed:\n" + log.read())
            try:
                with urlopen(base + "/health", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Timed out waiting for the gateway")

        for path in (
            "/api/v1/movies/openapi.json",
            "/api/v1/casts/openapi.json",
            "/api/v1/movies/",
        ):
            with urlopen(base + path, timeout=20) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP check failed: {path}")
                json.load(response)
            print(f"PASS: {namespace} GET {path}", flush=True)

        if namespace != "prod":
            environment = os.environ.copy()
            environment["API_BASE_URL"] = base
            run(
                sys.executable, str(root / "scripts/integration_test.py"),
                env=environment,
            )

        print(f"Deployment and verification PASSED: {namespace}", flush=True)
    finally:
        forward.terminate()
        try:
            forward.wait(timeout=10)
        except subprocess.TimeoutExpired:
            forward.kill()
            forward.wait()
