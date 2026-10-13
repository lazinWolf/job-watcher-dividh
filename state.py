"""Strict, atomic JSON state for completed listing decisions."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import tempfile

STATE_VERSION = 1


@dataclass
class State:
    processed: set[str] = field(default_factory=set)


def load_state(path: Path, *, initialize: bool = False) -> State:
    if not path.exists():
        if initialize:
            return State()
        raise FileNotFoundError(f"State file missing: {path}; use --init-state only for a new watcher")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not read valid state at {path}") from exc
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        raise ValueError("State has an unsupported version or shape")
    ids = data.get("processed")
    if not isinstance(ids, list) or not all(isinstance(item, str) and item for item in ids):
        raise ValueError("State.processed must be a list of nonempty IDs")
    return State(set(ids))


def save_state(path: Path, state: State) -> None:
    write_atomic(path, json.dumps({"version": STATE_VERSION, "processed": sorted(state.processed)}, indent=2) + "\n")


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
