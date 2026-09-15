import os

import pytest
from cryptography.fernet import Fernet, InvalidToken

from extrio.credentials import CredentialCipher
from extrio.integrity import IntegrityError, LocalEd25519Signer


def test_decrypt_missing_key_does_not_create_replacement(tmp_path):
    path = tmp_path / "missing.key"
    token = Fernet(Fernet.generate_key()).encrypt(b"credential").decode()
    with pytest.raises((FileNotFoundError, ValueError)):
        CredentialCipher(path).decrypt(token)
    assert not path.exists()


def test_credential_rotation_preserves_old_decryption_and_uses_new_primary(tmp_path):
    path = tmp_path / "credential.key"
    cipher = CredentialCipher(path)
    old = cipher.encrypt("old credential")
    previous_key = path.read_bytes().strip()
    result = cipher.rotate()
    assert result["keyCount"] == 2
    assert cipher.decrypt(old) == "old credential"
    current = cipher.encrypt("new credential")
    assert cipher.decrypt(current) == "new credential"
    with pytest.raises(InvalidToken):
        Fernet(previous_key).decrypt(current.encode())
    assert (path.stat().st_mode & 0o777) == 0o600


def test_insecure_key_permissions_and_symlinks_fail_closed(tmp_path):
    path = tmp_path / "credential.key"
    cipher = CredentialCipher(path)
    token = cipher.encrypt("credential")
    os.chmod(path, 0o644)
    with pytest.raises(ValueError, match="permissions"):
        cipher.decrypt(token)
    os.chmod(path, 0o600)
    link = tmp_path / "linked.key"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="regular"):
        CredentialCipher(link).decrypt(token)


def test_signer_rejects_insecure_key_file(tmp_path):
    path = tmp_path / "signing.pem"
    LocalEd25519Signer(path, "signing_test").public_key_pem()
    path.chmod(0o644)
    with pytest.raises(IntegrityError, match="permissions"):
        LocalEd25519Signer(path, "signing_test").sign(b"record")


def test_loaded_signer_cannot_sign_after_key_is_deleted(tmp_path):
    path = tmp_path / "signing.pem"
    signer = LocalEd25519Signer(path, "signing_test")
    signer.sign(b"record")
    path.unlink()
    with pytest.raises(IntegrityError, match="missing"):
        signer.sign(b"another record")
    assert not path.exists()


def test_restarted_signer_rejects_missing_registered_key(tmp_path, monkeypatch):
    from test_full_backup import setup_instance
    settings, store, _source = setup_instance(tmp_path / "instance", monkeypatch)
    settings.signing_private_key_path.unlink()
    signer = LocalEd25519Signer(settings.signing_private_key_path, settings.signing_key_id)
    with pytest.raises(IntegrityError, match="missing"):
        signer.validate_registered_identity(store)
    assert not settings.signing_private_key_path.exists()


def test_offline_key_rotation_reencrypts_database_without_losing_credentials(tmp_path, monkeypatch):
    from test_full_backup import setup_instance

    from extrio.maintenance import rotate_credentials
    settings, store, source = setup_instance(tmp_path / "instance", monkeypatch)
    cipher = CredentialCipher(settings.credential_encryption_key_path)
    store.save_platform_setting("model-provider-credentials", {"credentials": {"provider_test": cipher.encrypt("model-fixture")}})
    previous = settings.credential_encryption_key_path.read_bytes().strip()
    result = rotate_credentials(settings, store, offline=True)
    assert result["reencryptedCredentials"] == 2
    token = store.get_platform_setting("model-provider-credentials")["credentials"]["provider_test"]
    assert cipher.decrypt(token) == "model-fixture"
    with pytest.raises(InvalidToken):
        Fernet(previous).decrypt(token.encode())
    sink = store.list_sinks_for_collector(source["id"])[0]
    assert store.get_sink(sink["id"], cipher=cipher)["secret"] == "fixture-secret"


def test_missing_key_cannot_be_replaced_by_creating_another_sink(tmp_path, monkeypatch):
    from test_full_backup import setup_instance
    settings, store, source = setup_instance(tmp_path / "instance", monkeypatch)
    settings.credential_encryption_key_path.unlink()
    with pytest.raises(ValueError, match="credential"):
        store.create_sink(source["id"], url="https://hooks.example.test/", secret="new-secret",
            cipher=CredentialCipher(settings.credential_encryption_key_path))
    assert not settings.credential_encryption_key_path.exists()


def test_material_diagnostics_detect_missing_or_rebound_signing_key_without_creating_it(tmp_path, monkeypatch):
    from test_full_backup import setup_instance

    from extrio.runtime_health import material_status
    settings, store, _source = setup_instance(tmp_path / "instance", monkeypatch)
    assert material_status(store, settings)["ready"]
    settings.signing_private_key_path.unlink()
    assert material_status(store, settings)["reason"] == "signing_key_unavailable"
    assert not settings.signing_private_key_path.exists()
    LocalEd25519Signer(settings.signing_private_key_path, settings.signing_key_id).public_key_pem()
    assert material_status(store, settings)["reason"] == "signing_key_mismatch"


def test_signing_rotation_keeps_historical_verification_and_audits_creation(tmp_path, monkeypatch):
    from test_full_backup import setup_instance

    from extrio.maintenance import create_signing_key
    settings, store, _source = setup_instance(tmp_path / "instance", monkeypatch)
    old = store.get_signing_key(settings.signing_key_id)
    import base64

    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    signed = LocalEd25519Signer(settings.signing_private_key_path, settings.signing_key_id).sign(b"historical record")
    result = create_signing_key(settings, store, "signing_next", tmp_path / "next.pem", offline=True)
    assert store.get_signing_key(settings.signing_key_id) == old
    assert store.get_signing_key(result["signingKeyId"])["publicKeyPem"] != old["publicKeyPem"]
    assert any(event["action"] == "signing_key.created" for event in store.list_audit_events())
    store.update_signing_key_status(settings.signing_key_id, "retired", actor_id="local_operator", request_id="rotate_test")
    retained = store.get_signing_key(settings.signing_key_id)
    load_pem_public_key(retained["publicKeyPem"].encode()).verify(base64.urlsafe_b64decode(signed + "=="), b"historical record")


def test_explicit_key_initialization_never_replaces_lost_material(tmp_path, monkeypatch):
    from test_full_backup import setup_instance

    from extrio.maintenance import initialize_keys
    settings, store, _source = setup_instance(tmp_path / "instance", monkeypatch)
    key = settings.credential_encryption_key_path.read_bytes()
    initialize_keys(settings, store, offline=True)
    assert settings.credential_encryption_key_path.read_bytes() == key
    settings.credential_encryption_key_path.unlink()
    with pytest.raises(ValueError, match="credential"):
        initialize_keys(settings, store, offline=True)
    assert not settings.credential_encryption_key_path.exists()
