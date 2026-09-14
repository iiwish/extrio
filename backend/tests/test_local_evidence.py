from datetime import UTC, datetime, timedelta

from extrio.local_evidence import LocalEvidence, evidence_status


def test_sampled_evidence_checks_content_and_never_claims_equivalent_replay(tmp_path):
    writer = LocalEvidence(tmp_path, "run_evidence", 30)
    writer.write("detail-001.html", "<h1>Evidence</h1>")
    digest = writer.finish(complete=True)
    run = {"id": "run_evidence", "localEvidenceDigest": digest}
    status = evidence_status(tmp_path, run)
    assert status["mode"] == "sampled"
    assert status["state"] == "available"
    assert status["fileCount"] == 1
    assert status["canReplay"] is False
    (writer.directory / "detail-001.html").write_text("tampered")
    assert evidence_status(tmp_path, run)["state"] == "invalid"


def test_zero_retention_writes_metadata_only(tmp_path):
    writer = LocalEvidence(tmp_path, "run_metadata", 0)
    writer.write("detail-001.html", "secret raw source")
    run = {"id": "run_metadata", "localEvidenceDigest": writer.finish(complete=True)}
    status = evidence_status(tmp_path, run)
    assert status["mode"] == "metadata_only"
    assert status["fileCount"] == 0
    assert not (writer.directory / "detail-001.html").exists()
    assert status["canReplay"] is False


def test_missing_expired_and_partial_evidence_is_explicit(tmp_path):
    assert evidence_status(tmp_path, {"id": "run_missing"})["state"] == "missing"
    writer = LocalEvidence(tmp_path, "run_expired", 1)
    writer.write("list-001.html", "source")
    run = {"id": "run_expired", "localEvidenceDigest": writer.finish(complete=True)}
    assert evidence_status(tmp_path, run, now=datetime.now(UTC) + timedelta(days=2))["state"] == "expired"
    writer = LocalEvidence(tmp_path, "run_partial", 30)
    writer.write("list-001.html", "source")
    run = {"id": "run_partial", "localEvidenceDigest": writer.finish(complete=False)}
    assert evidence_status(tmp_path, run)["state"] == "incomplete"


def test_changed_manifest_and_symlink_cannot_claim_verified_evidence(tmp_path):
    writer = LocalEvidence(tmp_path, "run_invalid", 1)
    writer.write("list-001.html", "source")
    run = {"id": "run_invalid", "localEvidenceDigest": writer.finish(complete=True)}
    path = writer.directory / "list-001.html"
    path.unlink()
    path.symlink_to(tmp_path / "outside")
    assert evidence_status(tmp_path, run)["state"] == "invalid"


def test_retention_prunes_only_expired_named_snapshots_and_preserves_manifest(tmp_path):
    from extrio.local_evidence import prune_expired_evidence

    writer = LocalEvidence(tmp_path, "run_expired", 1)
    writer.write("list-001.html", "source")
    manifest_digest = writer.finish(complete=True)
    (writer.directory / "unrelated.txt").write_text("preserve")
    current = LocalEvidence(tmp_path, "run_current", 30)
    current.write("list-001.html", "current")
    current.finish(complete=True)
    report = prune_expired_evidence(tmp_path, now=datetime.now(UTC) + timedelta(days=2))
    assert report["removedFiles"] == 1
    assert (writer.directory / "local-evidence.json").exists()
    assert (writer.directory / "unrelated.txt").exists()
    assert (current.directory / "list-001.html").exists()
    assert (
        evidence_status(tmp_path, {"id": "run_expired", "localEvidenceDigest": manifest_digest}, now=datetime.now(UTC) + timedelta(days=2))[
            "state"
        ]
        == "expired"
    )
