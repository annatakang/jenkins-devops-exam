import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
tag = os.environ["IMAGE_TAG"]
build_id = os.environ.get("BUILD_TAG", tag)
project = "exam-ci-" + hashlib.sha256(build_id.encode()).hexdigest()[:12]

config = json.loads(subprocess.check_output(
    ["docker", "compose", "config", "--format", "json"],
    cwd=root, text=True,
))
config.pop("name", None)

# Let the unique Compose project determine network and volume names.
for section in ("networks", "volumes"):
    for definition in config.get(section, {}).values():
        if definition and not definition.get("external"):
            definition.pop("name", None)

services = config["services"]
for component in ("movie", "cast"):
    service = services[f"{component}_service"]
    service["image"] = f"annatakang77/jenkins-exam-{component}:{tag}"
    service["volumes"] = []
    service["ports"] = []
    service["command"] = [
        "uvicorn", "app.main:app",
        "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio",
    ]

services["nginx"]["ports"] = [{
    "target": 8080,
    "published": "0",
    "host_ip": "127.0.0.1",
    "protocol": "tcp",
}]

with tempfile.TemporaryDirectory(prefix="exam-compose-") as directory:
    filename = Path(directory) / "compose.json"
    filename.write_text(json.dumps(config))
    command = [
        "docker", "compose", "-p", project, "-f", str(filename),
    ]

    def compose(*args, **kwargs):
        return subprocess.run(command + list(args), check=True, **kwargs)

    try:
        compose("build")
        compose("up", "-d", "movie_db", "cast_db")

        for component in ("movie", "cast"):
            for attempt in range(60):
                result = subprocess.run(
                    command + [
                        "exec", "-T", f"{component}_db",
                        "pg_isready",
                        "-U", f"{component}_db_username",
                        "-d", f"{component}_db_dev",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if result.returncode == 0:
                    break
                time.sleep(2)
            else:
                raise RuntimeError(f"{component} database not ready")

        compose("up", "-d", "--no-build",
                "cast_service", "movie_service", "nginx")

        address = subprocess.check_output(
            command + ["port", "nginx", "8080"], text=True,
        ).strip()
        port = address.rsplit(":", 1)[1]
        base = f"http://127.0.0.1:{port}"

        for component in ("movie", "cast"):
            for attempt in range(60):
                try:
                    with urlopen(
                        f"{base}/api/v1/{component}s/openapi.json", timeout=2
                    ) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                time.sleep(2)
            else:
                raise RuntimeError(f"{component} API not ready")

        environment = os.environ.copy()
        environment["API_BASE_URL"] = base
        subprocess.run(
            [sys.executable, str(root / "scripts/integration_test.py")],
            env=environment, check=True,
        )
        print("Compose image integration test PASSED", flush=True)
    except BaseException:
        subprocess.run(command + ["logs", "--tail=100"])
        raise
    finally:
        compose("down", "--volumes", "--remove-orphans")
