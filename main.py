"""Collect, score, alert, and record completed decisions."""

import argparse
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
from typing import Callable

from config import (
    ALERT_THRESHOLD_OVERRIDE, ENABLED_SOURCES, HEALTH_ALERT_RUNS, HISTORY_KEEP_RUNS,
    MAX_ALERTS_PER_RUN, PROFILE, PROFILE_IS_EXAMPLE,
)
from profiles import parse_profile
from evaluate import evaluate
from models import Evaluation, Job, merge_jobs
from sources.internshala import fetch_internshala
from sources.indeed import fetch_indeed
from sources.linkedin import fetch_linkedin
from sources.naukri import fetch_naukri
from sources.wellfound import fetch_wellfound
from state import State, load_state, save_state
from telegram import send_telegram, send_text
from telemetry import append_history, health_changes, history_record

LOGGER = logging.getLogger("job_watcher")
FETCHERS: dict[str, Callable[[], list[Job]]] = {
    "linkedin": fetch_linkedin,
    "indeed": fetch_indeed,
    "naukri": fetch_naukri,
    "internshala": fetch_internshala,
    "wellfound": fetch_wellfound,
}


@dataclass
class RunSummary:
    sources_ok: int = 0
    sources_failed: int = 0
    collected: int = 0
    new: int = 0
    rejected: int = 0
    below_threshold: int = 0
    selected: int = 0
    delivered: int = 0
    deferred: int = 0
    evaluation_failed: int = 0
    delivery_failed: int = 0
    source_details: list[dict] = field(default_factory=list)
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    decisions: list[dict] = field(default_factory=list)
    health: list[str] = field(default_factory=list)


def _decision(job: Job, outcome: str, result: Evaluation | None = None) -> dict:
    # Enough to review a decision later; descriptions stay out of reports.
    return {"id": job.id, "source": job.source, "title": job.title, "company": job.company,
            "location": job.location, "url": job.url, "score": result.score if result else None,
            "outcome": outcome, "reasons": list(result.reasons) if result else []}


def _summary(summary: RunSummary, source_status: list[str], *, dry_run: bool,
             report_path: Path | None = None, meta: dict | None = None) -> None:
    mode = "dry run" if dry_run else "live"
    lines = [
        f"## Job watcher ({mode})",
        *[f"- {item}" for item in source_status],
        f"- Collected: {summary.collected}; new: {summary.new}",
        f"- Rejected: {summary.rejected}; below threshold: {summary.below_threshold}",
        f"- Selected: {summary.selected}; delivered: {summary.delivered}; deferred: {summary.deferred}",
        f"- Evaluation failures: {summary.evaluation_failed}; delivery failures: {summary.delivery_failed}",
    ]
    if summary.rejection_reasons:
        reasons = sorted(summary.rejection_reasons.items(), key=lambda item: (-item[1], item[0]))
        lines.append("- Rejection reasons: " + "; ".join(f"{reason} ({count})" for reason, count in reasons))
    lines.extend(f"- Health: {message}" for message in summary.health)
    report = "\n".join(lines) + "\n"
    print(report)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as output:
            output.write(report)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 2, **(meta or {}), "dry_run": dry_run, **asdict(summary)}
        report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _record_health(summary: RunSummary, history_path: Path, meta: dict,
                   notifier: Callable[[str], None]) -> None:
    """Append run history and report source health changes; never fails the run."""
    try:
        history = append_history(history_path, history_record(summary, **meta), keep=HISTORY_KEEP_RUNS)
        summary.health = health_changes(history, threshold=HEALTH_ALERT_RUNS)
    except Exception as exc:
        LOGGER.warning("Run history was not updated: %s: %s", type(exc).__name__, exc)
        return
    for message in summary.health:
        try:
            notifier(message)
        except Exception as exc:
            LOGGER.warning("Health message was not delivered: %s: %s", type(exc).__name__, exc)


def run(
    state_path: Path, *, dry_run: bool = False, init_state: bool = False,
    fetchers: dict[str, Callable[[], list[Job]]] | None = None,
    sender: Callable[[Job, Evaluation], None] = send_telegram,
    profile_path: Path | None = None, report_path: Path | None = None,
    history_path: Path | None = None, notifier: Callable[[str], None] = send_text,
) -> tuple[int, RunSummary]:
    started_at = datetime.now(timezone.utc)
    run_id = os.getenv("GITHUB_RUN_ID") or started_at.strftime("%Y%m%dT%H%M%SZ")
    history_path = history_path or Path(os.getenv("JOB_WATCHER_HISTORY_PATH") or state_path.with_name("history.jsonl"))
    profile, is_example = PROFILE, PROFILE_IS_EXAMPLE
    configured_path = profile_path or (Path(os.environ["JOB_WATCHER_PROFILE_PATH"]) if os.getenv("JOB_WATCHER_PROFILE_PATH") else None)
    if configured_path:
        profile, is_example = parse_profile(configured_path.read_text(encoding="utf-8"))
    elif os.getenv("JOB_WATCHER_PROFILE_JSON"):
        profile, is_example = parse_profile(os.environ["JOB_WATCHER_PROFILE_JSON"])
    if report_path and report_path.resolve() in {state_path.resolve(), history_path.resolve(),
                                                 configured_path.resolve() if configured_path else None}:
        raise ValueError("Report path must be separate from state, history, and profile files")
    if is_example and not dry_run:
        LOGGER.warning("Example profile is active; running without delivery or state changes")
        dry_run = True
    state: State = load_state(state_path, initialize=init_state or dry_run)
    if fetchers is None:
        unknown = set(ENABLED_SOURCES) - set(FETCHERS)
        if unknown:
            raise ValueError("Unknown sources: " + ", ".join(sorted(unknown)))
        fetchers = {}
        for name in ENABLED_SOURCES:
            fetcher = FETCHERS[name]
            if name in {"linkedin", "internshala"}:
                fetchers[name] = lambda fetcher=fetcher: fetcher(profile=profile, processed_ids=state.processed)
            else:
                fetchers[name] = lambda fetcher=fetcher: fetcher(profile=profile)
    threshold = ALERT_THRESHOLD_OVERRIDE if ALERT_THRESHOLD_OVERRIDE is not None else profile.alert_threshold
    summary = RunSummary()
    source_status = []
    combined: dict[str, Job] = {}

    def finish(status: int) -> tuple[int, RunSummary]:
        meta = {"run_id": run_id, "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat()}
        if not dry_run:
            _record_health(summary, history_path, meta, notifier)
        _summary(summary, source_status, dry_run=dry_run, report_path=report_path,
                 meta=meta | {"profile_is_example": is_example})
        return status, summary

    for name, fetcher in fetchers.items():
        started = time.monotonic()
        try:
            jobs = fetcher()
            summary.sources_ok += 1
            detail = {"source": name, "status": "ok", "listings": len(jobs),
                      "unique": len({job.id for job in jobs}),
                      "descriptions": sum(bool(job.description) for job in jobs),
                      "companies": sum(bool(job.company) for job in jobs),
                      "locations": sum(bool(job.location) for job in jobs),
                      "skills": sum(bool(job.skills) for job in jobs),
                      "seconds": round(time.monotonic() - started, 2)}
            summary.source_details.append(detail)
            source_status.append(f"{name}: {len(jobs)} listings; descriptions {detail['descriptions']}/{len(jobs)}; {detail['seconds']}s")
            for job in jobs:
                if job.id in combined:
                    combined[job.id] = merge_jobs(combined[job.id], job)
                else:
                    combined[job.id] = job
        except Exception as exc:
            summary.sources_failed += 1
            summary.source_details.append({"source": name, "status": "failed", "error": type(exc).__name__,
                                           "message": f"{type(exc).__name__}: {exc}"[:300],
                                           "seconds": round(time.monotonic() - started, 2)})
            source_status.append(f"{name}: failed ({type(exc).__name__})")
            LOGGER.error("Source %s failed: %s: %s", name, type(exc).__name__, exc)

    summary.collected = len(combined)
    if not summary.sources_ok:
        return finish(1)

    selected: list[tuple[Job, Evaluation]] = []
    reasons: Counter[str] = Counter()
    for job in combined.values():
        if job.id in state.processed:
            continue
        summary.new += 1
        try:
            result = evaluate(job, profile)
        except Exception:
            summary.evaluation_failed += 1
            summary.decisions.append(_decision(job, "evaluation_failed"))
            LOGGER.exception("Evaluation failed for %s", job.id)
            continue
        if result.score is None:
            summary.rejected += 1
            summary.decisions.append(_decision(job, "rejected", result))
            reasons.update(re.sub(r"\d+", "N", reason) for reason in result.reasons[:1])
            LOGGER.info("Rejected %s: %s", job.id, "; ".join(result.reasons))
            if not dry_run:
                state.processed.add(job.id)
        elif result.score < threshold:
            summary.below_threshold += 1
            summary.decisions.append(_decision(job, "below_threshold", result))
            LOGGER.info("Below threshold %s: %s", job.id, result.score)
            if not dry_run:
                state.processed.add(job.id)
        else:
            selected.append((job, result))
    summary.rejection_reasons = dict(reasons)

    selected.sort(key=lambda pair: (
        -(pair[1].score or 0),
        -(pair[0].posted_at.timestamp() if pair[0].posted_at else float("-inf")),
        pair[0].id,
    ))
    summary.selected = len(selected)
    summary.deferred = max(0, len(selected) - MAX_ALERTS_PER_RUN)
    decided: set[str] = set()
    for job, result in selected[:MAX_ALERTS_PER_RUN]:
        decided.add(job.id)
        if dry_run:
            summary.decisions.append(_decision(job, "would_send", result))
            print(f"DRY RUN {result.score} {job.title} | {job.company or 'Unknown'} | {job.url}")
            print("  " + "; ".join(result.reasons))
            continue
        try:
            sender(job, result)
        except Exception as exc:
            summary.delivery_failed += 1
            summary.decisions.append(_decision(job, "delivery_failed", result))
            LOGGER.error("Delivery stopped at %s: %s: %s", job.id, type(exc).__name__, exc)
            # Later selected jobs remain unseen and can be retried if re-collected.
            break
        state.processed.add(job.id)
        summary.delivered += 1
        summary.decisions.append(_decision(job, "sent", result))
    summary.decisions.extend(_decision(job, "deferred", result) for job, result in selected if job.id not in decided)

    if not dry_run:
        summary.deferred = len(selected) - summary.delivered
        save_state(state_path, state)
    failed = summary.delivery_failed or summary.evaluation_failed
    return finish(1 if failed else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Personal public job watcher")
    parser.add_argument("--dry-run", action="store_true", help="show decisions without sending or saving")
    parser.add_argument("--init-state", action="store_true", help="allow missing state on a new watcher only")
    parser.add_argument("--profile", type=Path, help="validated JSON profile; overrides environment profile settings")
    parser.add_argument("--report", type=Path, help="write run counts and source coverage as JSON (also in dry run)")
    args = parser.parse_args()
    level_name = os.getenv("JOB_WATCHER_LOG_LEVEL", "INFO").upper()
    level = logging.getLevelNamesMapping().get(level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if level_name not in logging.getLevelNamesMapping():
        LOGGER.warning("Unknown JOB_WATCHER_LOG_LEVEL %r; using INFO", level_name)
    state_path = Path(os.getenv("JOB_WATCHER_STATE_PATH", "seen.json"))
    try:
        status, _ = run(state_path, dry_run=args.dry_run, init_state=args.init_state,
                        profile_path=args.profile, report_path=args.report)
        return status
    except (ValueError, FileNotFoundError, OSError) as exc:
        LOGGER.error("Watcher stopped before completion: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
