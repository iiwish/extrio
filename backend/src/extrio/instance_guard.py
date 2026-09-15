import fcntl
import os
from contextlib import contextmanager
from pathlib import Path


def restore_marker(artifact_path: Path) -> Path:
    return artifact_path.parent / f".extrio-{artifact_path.name}.restore-pending"


@contextmanager
def instance_lock(artifact_path: Path, *, exclusive: bool = False):
    """Coordinate the supported same-host API/Worker and offline maintenance."""
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    path = artifact_path.parent / f".extrio-{artifact_path.name}.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a+b") as lock:
        try:
            fcntl.flock(lock, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("instance is running or offline maintenance is in progress") from exc
        if restore_marker(artifact_path).exists():
            raise RuntimeError("an incomplete restore requires operator recovery before startup")
        if not exclusive:
            if artifact_path.is_symlink():
                raise RuntimeError("artifact directory must not be a symbolic link")
            artifact_path.mkdir(parents=True, exist_ok=True)
        yield
