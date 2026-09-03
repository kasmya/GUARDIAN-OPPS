"""Shared mode state for fraud-api. Persisted to a JSON file on a volume
so chaos-injector can flip it without needing a network call."""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock

STATE_FILE = Path(os.environ.get("STATE_FILE", "/shared/state.json"))
_LOCK = Lock()

DEFAULT_STATE = {
    "mode": "normal",
    "slow_ms": 0,
    "corrupt": False,
}


def _ensure_file() -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps(DEFAULT_STATE))


def read_state() -> dict:
    _ensure_file()
    with _LOCK:
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            return dict(DEFAULT_STATE)


def write_state(patch: dict) -> dict:
    _ensure_file()
    with _LOCK:
        try:
            current = json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            current = dict(DEFAULT_STATE)
        current.update(patch)
        STATE_FILE.write_text(json.dumps(current))
        return current


def reset_state() -> dict:
    return write_state(dict(DEFAULT_STATE))
