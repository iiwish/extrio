import fcntl
import os
import stat
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class CredentialCipher:
    """Encrypt provider credentials with a local, permission-restricted master key."""

    def __init__(self, key_path: Path):
        self.key_path = key_path

    def _keys(self, *, create: bool = False) -> list[bytes]:
        if create and not self.key_path.exists():
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "wb") as key_file:
                    key_file.write(Fernet.generate_key() + b"\n")
                    key_file.flush()
                    os.fsync(key_file.fileno())
        if self.key_path.is_symlink():
            raise ValueError("credential key must be a regular file")
        descriptor = os.open(self.key_path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as key_file:
            metadata = os.fstat(key_file.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("credential key must be a regular file")
            if metadata.st_mode & 0o077:
                raise ValueError("credential key permissions must exclude group and other users")
            keys = key_file.read(16_384).splitlines()
        keys = [key.strip() for key in keys if key.strip()]
        if not keys or len(keys) > 100:
            raise ValueError("invalid credential keyring")
        for key in keys:
            Fernet(key)
        return keys

    def encrypt(self, value: str) -> str:
        return MultiFernet([Fernet(key) for key in self._keys(create=True)]).encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return MultiFernet([Fernet(key) for key in self._keys()]).decrypt(value.encode()).decode()

    def rotate(self) -> dict[str, int]:
        """Add a new primary, retaining all old decryptors. Call only offline."""
        lock_path = self.key_path.with_name(f".{self.key_path.name}.lock")
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            keys = self._keys()
            if len(keys) >= 100:
                raise ValueError("credential keyring rotation limit reached")
            keys.insert(0, Fernet.generate_key())
            descriptor, staged = tempfile.mkstemp(prefix=".credential-", dir=self.key_path.parent)
            try:
                with os.fdopen(descriptor, "wb") as target:
                    target.write(b"\n".join(keys) + b"\n")
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(staged, self.key_path)
            finally:
                Path(staged).unlink(missing_ok=True)
        return {"keyCount": len(keys)}

    def can_decrypt(self, value: object) -> bool:
        if not isinstance(value, str) or not value:
            return False
        try:
            self.decrypt(value)
        except (InvalidToken, ValueError, OSError):
            return False
        return True


def validate_stored_credentials(store, cipher, connection=None):
    target = connection or store.connect()
    try:
        rows = target.execute("SELECT secret_encrypted FROM sinks WHERE secret_encrypted IS NOT NULL").fetchall()
        setting = target.execute("SELECT data FROM platform_settings WHERE key='model-provider-credentials'").fetchone()
        tokens = [row["secret_encrypted"] for row in rows]
        if setting:
            tokens.extend(store.dialect.decode_json(setting["data"]).get("credentials", {}).values())
        if any(not cipher.can_decrypt(token) for token in tokens):
            raise ValueError("credential keyring cannot decrypt stored credentials; restore the original keyring")
        if cipher.key_path.exists() or cipher.key_path.is_symlink():
            cipher._keys()
    finally:
        if connection is None:
            target.close()
