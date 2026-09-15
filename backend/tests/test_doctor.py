import pytest
from test_full_backup import setup_instance


def test_instance_startup_initializes_artifact_directory_but_rejects_symlinks(tmp_path):
    from extrio.instance_guard import instance_lock

    path = tmp_path / "instance" / "artifacts"
    with instance_lock(path):
        assert path.is_dir()
    link = tmp_path / "linked"
    link.symlink_to(path, target_is_directory=True)
    with pytest.raises(RuntimeError, match="artifact"):
        with instance_lock(link):
            pass


def test_doctor_is_read_only_and_distinguishes_missing_worker(tmp_path, monkeypatch):
    from extrio.doctor import diagnose

    settings, store, _source = setup_instance(tmp_path / "instance", monkeypatch)
    report = diagnose(settings)
    assert report["reason"] == "worker_unavailable"
    assert report["database"] == "sqlite"
    assert report["pendingMigrations"] == []
    assert report["artifactWritable"]
    assert "/Users/" not in str(report)
    assert "fixture-secret" not in str(report)


def test_doctor_does_not_initialize_a_missing_database(tmp_path, monkeypatch):
    from extrio.doctor import diagnose

    settings, store, _source = setup_instance(tmp_path / "instance", monkeypatch)
    missing = tmp_path / "missing.db"
    report = diagnose(settings.model_copy(update={"database_path": missing}))
    assert report["reason"] == "database_unavailable"
    assert not missing.exists()
