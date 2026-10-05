"""Select a few promising, unseen jobs for public detail-page enrichment."""

import logging
from typing import Callable

from config import PROFILE, Profile
from evaluate import evaluate, role_relevant
from models import Job, merge_jobs

LOGGER = logging.getLogger(__name__)


def enrich_jobs(
    jobs: list[Job], fetch_detail: Callable[[Job], Job], *, limit: int,
    profile: Profile = PROFILE, processed_ids: set[str] | None = None,
    minimum_description_chars: int = 1,
) -> list[Job]:
    known = processed_ids or set()
    candidates = []
    for job in jobs:
        if job.id in known or len(job.description or "") >= minimum_description_chars or not role_relevant(job, profile):
            continue
        assessment = evaluate(job, profile)
        if assessment.score is not None:
            candidates.append((job, assessment.score))
    candidates.sort(key=lambda item: (-item[1], item[0].id))
    enriched: dict[str, Job] = {}
    attempted = failed = consecutive_failures = 0
    for job, _ in candidates[:limit]:
        attempted += 1
        try:
            updated = fetch_detail(job)
            if updated.id != job.id or not updated.description:
                raise ValueError("detail page did not supply a description for this listing")
            enriched[job.id] = merge_jobs(job, updated)
            consecutive_failures = 0
        except Exception as exc:
            failed += 1
            consecutive_failures += 1
            LOGGER.warning("%s detail failed for %s: %s", job.source, job.id, type(exc).__name__)
            if consecutive_failures >= 3:
                LOGGER.warning("Stopping detail requests after three consecutive failures")
                break
    LOGGER.info("Detail enrichment: %d candidates, %d attempted, %d enriched, %d failed, %d deferred",
                len(candidates), attempted, len(enriched), failed, max(0, len(candidates) - attempted))
    return [enriched.get(job.id, job) for job in jobs]
