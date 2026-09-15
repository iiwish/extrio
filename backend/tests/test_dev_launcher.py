import os
import socket
import subprocess
import sys
from pathlib import Path


def test_dev_launcher_rejects_port_conflict_before_starting_any_process(tmp_path):
    binary = tmp_path / "bin"
    binary.mkdir()
    marker = tmp_path / "started"
    uv = binary / "uv"
    uv.write_text(
        f"#!{sys.executable}\nimport os, sys, time\nfrom pathlib import Path\n"
        "if 'python' in sys.argv:\n"
        " i=sys.argv.index('python'); os.execv(sys.executable,[sys.executable,*sys.argv[i+1:]])\n"
        f"Path({str(marker)!r}).write_text('started')\ntime.sleep(1)\n"
    )
    uv.chmod(0o700)
    launcher = tmp_path / "scripts" / "dev.sh"
    launcher.parent.mkdir()
    launcher.write_text((Path(__file__).resolve().parents[2] / "scripts/dev.sh").read_text())
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        env = {
            **os.environ,
            "PATH": str(binary) + os.pathsep + os.environ["PATH"],
            "EXTRIO_INSTANCE_DIR": str(tmp_path / "instance"),
            "EXTRIO_API_PORT": str(listener.getsockname()[1]),
        }
        result = subprocess.run(["bash", str(launcher)], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert "Port conflict" in result.stderr
    assert not marker.exists(), "port conflicts must be found before API or Worker startup"


def test_dev_port_preflight_permits_immediate_restart_after_closed_connection():
    script = (Path(__file__).resolve().parents[2] / "scripts/dev.sh").read_text()
    code = script.split("python -c '\n", 1)[1].split('\n\' "${check_ports[@]}"', 1)[0]
    with socket.socket() as server, socket.socket() as client:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        server.listen()
        client.connect(("127.0.0.1", port))
        connection, _ = server.accept()
        connection.close()
        assert client.recv(1) == b""
    result = subprocess.run([sys.executable, "-c", code, str(port)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_dev_port_preflight_allows_restarting_only_a_missing_worker():
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/dev.sh").read_text()
    preflight = script.split("check_ports=()", 1)[1].split("started=()", 1)[0]
    command = (
        f'set -euo pipefail\nROOT="{root}"\nAPI_PORT=8028\nWEB_PORT=5188\n'
        "managed_process() { return 0; }\ncheck_ports=()\n" + preflight
    )
    result = subprocess.run(["/bin/bash", "-c", command], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
