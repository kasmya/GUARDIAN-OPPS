import pytest

from app import store


def test_incident_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "g.db")
    store.init_db()

    inc_id = store.create_incident(
        type_="silent_failure",
        status="pending_approval",
        reasoning="test reasoning",
        evidence={"drift": {"psi": 0.31}},
        action="rollback_to_clean_mode",
    )
    assert inc_id > 0

    pending = store.list_pending_approvals()
    assert len(pending) == 1
    assert pending[0]["type"] == "silent_failure"

    store.resolve_incident(
        inc_id, action="rollback_approved", mttr_seconds=12.4, blast_radius=42
    )
    got = store.get_incident(inc_id)
    assert got["status"] == "resolved"
    assert got["mttr_seconds"] == 12.4
    assert got["blast_radius"] == 42


def test_crash_incident_is_separate_type(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "g2.db")
    store.init_db()
    inc = store.create_incident(
        type_="crash",
        status="in_progress",
        reasoning="health check failed",
        evidence={"consecutive_health_misses": 3},
        action="auto_restart",
    )
    all_i = store.list_incidents()
    assert any(i["id"] == inc and i["type"] == "crash" for i in all_i)
