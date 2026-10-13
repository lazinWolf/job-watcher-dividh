"""Bounded run history and source health derived from it."""

import json
import logging
from pathlib import Path

from state import write_atomic

LOGGER = logging.getLogger(__name__)
HISTORY_VERSION = 1
COUNTS = (
    "collected", "new", "rejected", "below_threshold", "selected", "delivered",
    "deferred", "evaluation_failed", "delivery_failed",
)


def history_record(summary, *, run_id: str, started_at: str, finished_at: str) -> dict:
    """Compact per-run record: counts and source status, no listing data."""
    sources = []
    for detail in summary.source_details:
        entry = {"source": detail["source"], "status": detail["status"], "seconds": detail["seconds"]}
        if detail["status"] == "ok":
            entry["listings"] = detail["listings"]
        else:
            entry["error"] = detail.get("message") or detail.get("error")
        sources.append(entry)
    return {
        "version": HISTORY_VERSION, "run_id": run_id, "started_at": started_at,
        "finished_at": finished_at, **{name: getattr(summary, name) for name in COUNTS},
        "sources": sources,
    }


def read_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            record = None
        if isinstance(record, dict):
            records.append(record)
        else:
            LOGGER.warning("Skipping unreadable history line %d in %s", number, path)
    return records


def append_history(path: Path, record: dict, *, keep: int) -> list[dict]:
    history = (read_history(path) + [record])[-keep:]
    write_atomic(path, "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in history))
    return history


def _unhealthy(entry: dict) -> bool:
    return entry.get("status") != "ok" or not entry.get("listings")


def _trailing_unhealthy(entries: list[dict]) -> int:
    count = 0
    for entry in reversed(entries):
        if not _unhealthy(entry):
            break
        count += 1
    return count


def _describe(entry: dict) -> str:
    if entry.get("status") != "ok":
        return f"failed ({entry.get('error') or 'unknown error'})"
    return "returned no listings"


def health_changes(history: list[dict], *, threshold: int) -> list[str]:
    """Messages for sources that just became unhealthy or just recovered.

    Only runs that attempted a source count toward its streak, so manual
    probes of other sources neither extend nor reset it.
    """
    if not history:
        return []
    messages = []
    for latest in history[-1].get("sources", []):
        source = latest.get("source")
        runs = [entry for record in history for entry in record.get("sources", [])
                if isinstance(entry, dict) and entry.get("source") == source]
        streak = _trailing_unhealthy(runs)
        if streak == threshold:
            messages.append(f"⚠️ Job watcher: {source} has failed or returned nothing in "
                            f"{streak} runs in a row; latest run {_describe(latest)}.")
        elif streak == 0:
            previous = _trailing_unhealthy(runs[:-1])
            if previous >= threshold:
                messages.append(f"✅ Job watcher: {source} is working again "
                                f"({latest.get('listings')} listings) after {previous} unhealthy runs.")
    return messages
