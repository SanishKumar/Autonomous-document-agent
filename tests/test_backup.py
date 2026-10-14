import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.workspace.backup import create_backup, restore_backup, verify_backup
from tests.test_workspace import workspace


def test_backup_roundtrip_and_access_revocation(tmp_path):
    source = tmp_path / "outputs"
    source.mkdir()
    with sqlite3.connect(source / "workspace.sqlite3") as conn:
        for table in ("documents", "versions", "events", "sessions", "invitations"):
            conn.execute(f"CREATE TABLE {table}(value TEXT)")
            conn.execute(f"INSERT INTO {table} VALUES ('preserved')")
    (source / "sample.docx").write_bytes(b"example artifact")
    (source / ".setup-token").write_text("not-for-backup")
    backup, restored = tmp_path / "backup", tmp_path / "restored"
    manifest = create_backup(source, backup)
    assert len(manifest["files"]) == 2
    assert verify_backup(backup) == manifest
    restore_backup(backup, restored)
    assert (restored / "sample.docx").read_bytes() == b"example artifact"
    assert not (restored / ".setup-token").exists()
    with sqlite3.connect(restored / "workspace.sqlite3") as conn:
        assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM invitations").fetchone()[0] == 0
    with pytest.raises(ValueError, match="must not exist"):
        restore_backup(backup, restored)
    (backup / "sample.docx").write_bytes(b"changed")
    with pytest.raises(ValueError, match="damaged"):
        verify_backup(backup)


def test_manifest_cannot_restore_outside_target(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({
        "format": 1, "created_at": "2026-10-14T00:00:00Z",
        "files": {"../workspace.sqlite3": "0" * 64, "workspace.sqlite3": "0" * 64}
    }))
    with pytest.raises(ValueError, match="Unsafe"):
        verify_backup(tmp_path)


@pytest.mark.parametrize("manifest", [[], None, {"format": 99}, {"format": 1, "files": {}}])
def test_invalid_manifest_fails_cleanly(tmp_path, manifest):
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify_backup(tmp_path)


def test_recovered_workspace_can_open_edit_and_export(tmp_path):
    source, backup, restored = (tmp_path / name for name in ("original", "backup", "restored"))
    with TestClient(workspace(source)) as client:
        doc_id = client.get("/api/documents").json()["documents"][0]["id"]
        original = client.get(f"/api/documents/{doc_id}").json()
        export = client.get(f"/api/documents/{doc_id}/export")
        assert export.status_code == 200
    create_backup(source, backup)
    restore_backup(backup, restored)
    with TestClient(workspace(restored)) as client:
        recovered = client.get(f"/api/documents/{doc_id}").json()
        assert recovered["artifact"] == original["artifact"]
        assert client.get(f"/api/documents/{doc_id}/export").content == export.content
        result = client.put(f"/api/documents/{doc_id}/draft", json={
            "title": "Recovered working draft", "draft": recovered["artifact"]["draft"],
            "expected_version": recovered["version"], "note": "Recovery drill",
        })
        assert result.status_code == 200
        assert result.json()["version"] == original["version"] + 1
    with TestClient(workspace(source)) as client:
        assert client.get(f"/api/documents/{doc_id}").json()["title"] == original["title"]
