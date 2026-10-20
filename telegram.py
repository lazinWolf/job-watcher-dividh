"""Small Telegram Bot API delivery client with bounded retries."""

from collections import Counter
import html
import os
import re
import time

import requests

from models import Evaluation, Job

# Telegram counts message length after entity parsing, in UTF-16 code units;
# keep a margin below its 4096 limit.
MESSAGE_LIMIT = 3900
SOURCE_NAMES = {"linkedin": "LinkedIn", "internshala": "Internshala", "indeed": "Indeed",
                "naukri": "Naukri", "wellfound": "Wellfound"}


class DeliveryError(RuntimeError):
    pass


def _visible_length(markup: str) -> int:
    text = html.unescape(re.sub(r"<[^>]+>", "", markup))
    return len(text.encode("utf-16-le")) // 2


def to_plain(markup: str) -> str:
    """Readable text for terminals: links become "title (url)"."""
    text = re.sub(r'<a href="([^"]*)">(.*?)</a>', r"\2 (\1)", markup)
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def _job_lines(job: Job, evaluation: Evaluation) -> str:
    title = html.escape(job.title[:150])
    details = [job.location or "Location unknown", SOURCE_NAMES.get(job.source, job.source.title())]
    if job.compensation:
        details.append(job.compensation)
    return (f'{evaluation.score} · <a href="{html.escape(job.url, quote=True)}">{title}</a>\n'
            f"    {html.escape(' · '.join(details))}")


def format_digest(selected: list[tuple[Job, Evaluation]], *, more: int = 0) -> list[tuple[str, list[str]]]:
    """HTML digest messages, each paired with the IDs of the jobs it lists.

    Jobs from the same company share one heading; companies keep the order of
    their best-ranked job. A company is split across messages only if it does
    not fit in one.
    """
    groups: dict[str, list[tuple[Job, Evaluation]]] = {}
    for job, evaluation in selected:
        key = job.company.casefold().strip() if job.company else f"\0{job.id}"
        groups.setdefault(key, []).append((job, evaluation))
    blocks: list[tuple[str, list[str]]] = []
    for pairs in groups.values():
        heading = f"<b>{html.escape(pairs[0][0].company or 'Company unknown')}</b>"
        lines = [_job_lines(job, evaluation) for job, evaluation in pairs]
        block = "\n".join([heading, *lines])
        if _visible_length(block) <= MESSAGE_LIMIT - 200:
            blocks.append((block, [job.id for job, _ in pairs]))
        else:
            blocks.extend(("\n".join([heading, line]), [job.id]) for line, (job, _) in zip(lines, pairs))

    chunks: list[tuple[list[str], list[str]]] = []
    for block, ids in blocks:
        if not chunks or _visible_length("\n\n".join([*chunks[-1][0], block])) > MESSAGE_LIMIT - 200:
            chunks.append(([], []))
        chunks[-1][0].append(block)
        chunks[-1][1].extend(ids)

    sources = Counter(job.source for job, _ in selected)
    summary = ", ".join(f"{SOURCE_NAMES.get(name, name.title())} {count}" for name, count in sources.most_common())
    messages = []
    for number, (parts, ids) in enumerate(chunks, 1):
        if number == 1:
            header = f"🟢 <b>{len(selected)} new match{'es' if len(selected) != 1 else ''}</b> · {html.escape(summary)}"
        else:
            header = "🟢 <b>Matches continued</b>"
        if len(chunks) > 1:
            header += f" ({number}/{len(chunks)})"
        footer = [f"<i>+{more} more next run</i>"] if more and number == len(chunks) else []
        messages.append(("\n\n".join([header, *parts, *footer]), ids))
    return messages


def send_text(text: str, *, markup: bool = False) -> None:
    """Send plain text, or Telegram HTML when markup is true."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise DeliveryError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text if markup else text[:4096], "disable_web_page_preview": True}
    if markup:
        payload["parse_mode"] = "HTML"
    for attempt in range(3):
        try:
            response = requests.post(url, json=payload, timeout=(5, 15))
            result = response.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt < 2:
                time.sleep(attempt + 1)
                continue
            raise DeliveryError(f"Telegram connection failed ({type(exc).__name__})") from None
        if response.ok and isinstance(result, dict) and result.get("ok") is True:
            return
        if response.status_code == 429 and attempt < 2:
            retry_after = result.get("parameters", {}).get("retry_after", 1) if isinstance(result, dict) else 1
            try:
                delay = int(retry_after)
            except (ValueError, TypeError):
                delay = 1
            if delay > 30:
                raise DeliveryError(f"Telegram rate limited delivery for {delay} seconds")
            time.sleep(max(1, delay))
            continue
        if response.status_code >= 500 and attempt < 2:
            time.sleep(attempt + 1)
            continue
        raise DeliveryError(f"Telegram rejected delivery (HTTP {response.status_code})")
    raise DeliveryError("Telegram delivery exhausted retries")
