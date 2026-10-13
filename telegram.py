"""Small Telegram Bot API delivery client with bounded retries."""

import os
import time

import requests

from models import Evaluation, Job


class DeliveryError(RuntimeError):
    pass


def format_message(job: Job, evaluation: Evaluation) -> str:
    lines = [f"🟢 {evaluation.score} — {job.title}"]
    lines.append(job.company or "Company unknown")
    lines.append(job.location or "Location unknown")
    if job.compensation:
        lines.append(job.compensation)
    lines.extend(("", job.source.title(), job.url))
    if evaluation.reasons:
        lines.extend(("", "Matched: " + "; ".join(evaluation.reasons[:3])))
    return "\n".join(lines)[:4096]


def send_telegram(job: Job, evaluation: Evaluation) -> None:
    send_text(format_message(job, evaluation))


def send_text(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise DeliveryError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": True}
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
