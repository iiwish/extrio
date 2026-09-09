import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("pid_contents", [None, "0", "-1", "not-a-pid"])
def test_stop_does_not_kill_an_unrelated_process_from_a_stale_pid(tmp_path: Path, pid_contents: str | None):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    source = Path(__file__).resolve().parents[2] / "scripts" / "stop.sh"
    shutil.copy(source, scripts / "stop.sh")
    pids = tmp_path / "backend" / "data" / "pids"
    pids.mkdir(parents=True)
    process = subprocess.Popen(["sleep", "60"])
    try:
        (pids / "api.pid").write_text(str(process.pid) if pid_contents is None else pid_contents)
        subprocess.run(["bash", str(scripts / "stop.sh")], check=True, capture_output=True)
        assert process.poll() is None
        assert not (pids / "api.pid").exists()
    finally:
        process.terminate()
        process.wait(timeout=5)
