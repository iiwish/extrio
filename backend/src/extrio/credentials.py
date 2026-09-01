import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class CredentialCipher:
    """Encrypt provider credentials with a local, permission-restricted master key."""

    def __init__(self, key_path: Path):
        self.key_path = key_path

    def _key(self) -> bytes:
        if self.key_path.exists():
            return self.key_path.read_bytes().strip()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as key_file:
            key_file.write(key)
        return key

    def encrypt(self, value: str) -> str:
        return Fernet(self._key()).encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return Fernet(self._key()).decrypt(value.encode()).decode()

    def can_decrypt(self, value: object) -> bool:
        if not isinstance(value, str) or not value:
            return False
        try:
            self.decrypt(value)
        except (InvalidToken, ValueError):
            return False
        return True
