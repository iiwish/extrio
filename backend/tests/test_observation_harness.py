import json
import socket
import subprocess
import sys
from pathlib import Path


def test_observer_runs_real_pipeline_and_stops_owned_processes(tmp_path):
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "g3-observation-test"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/observe-runtime.py"),
            "--output",
            str(output),
            "--api-port",
            str(port),
            "--duration-seconds",
            "6",
            "--sample-seconds",
            "1",
            "--collectors",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((output / "state.json").read_text())
    assert state["status"] == "completed_pending_analysis"
    assert state["samples"] >= 2
    assert state["lastSample"]["runs"]["succeeded"] >= 1
    assert state["lastSample"]["deliveries"]["delivered"] >= 1
    assert state["lastSample"]["invalidSignatures"] == 0
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0
