import pytest

import telegram
from models import Evaluation, Job
from telegram import DeliveryError, format_digest, send_text, to_plain


class Response:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self.body = body
        self.ok = 200 <= status < 300

    def json(self):
        return self.body


def _job(number: int = 1, **changes) -> Job:
    return Job(**(dict(id=f"test:{number}", source="linkedin", title="Backend Intern",
                       url=f"https://example.com/job/{number}", company="Example", location="Pune")
                  | changes))


def test_telegram_requires_api_confirmation_and_sends_html(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    calls = []
    def post(url, *, json, timeout):
        calls.append((url, json))
        return Response(200, {"ok": True, "result": {"message_id": 1}})
    monkeypatch.setattr("telegram.requests.post", post)
    (text, _), = format_digest([(_job(), Evaluation(70, ("preferred role",)))])
    send_text(text, markup=True)
    assert len(calls) == 1
    assert calls[0][1]["chat_id"] == "123" and calls[0][1]["parse_mode"] == "HTML"
    assert "Backend Intern" in calls[0][1]["text"]
    send_text("plain health message")
    assert "parse_mode" not in calls[1][1]


def test_telegram_failure_does_not_expose_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setattr("telegram.requests.post", lambda *a, **k: Response(400, {"ok": False}))
    with pytest.raises(DeliveryError) as error:
        send_text("hello")
    assert "400" in str(error.value)
    assert "secret-token" not in str(error.value)


def test_digest_groups_companies_and_escapes_markup():
    selected = [
        (_job(1, title="Backend <Intern> & Co", company="Acme", url='https://example.com/a?x=1&y="2"'), Evaluation(90)),
        (_job(2, company="Other", source="indeed", compensation="INR 10,000"), Evaluation(85)),
        (_job(3, title="Python Intern", company="ACME "), Evaluation(80)),
        (_job(4, company=None), Evaluation(75)),
        (_job(5, company=None), Evaluation(70)),
    ]
    (text, ids), = format_digest(selected, more=3)
    assert ids == ["test:1", "test:3", "test:2", "test:4", "test:5"]  # Acme's two jobs share a heading
    assert text.count("<b>Acme</b>") == 1 and text.count("Company unknown") == 2
    assert "Backend &lt;Intern&gt; &amp; Co" in text
    assert 'href="https://example.com/a?x=1&amp;y=&quot;2&quot;"' in text
    assert text.startswith("🟢 <b>5 new matches</b> · LinkedIn 4, Indeed 1")
    assert "Pune · Indeed · INR 10,000" in text and text.endswith("<i>+3 more next run</i>")
    plain = to_plain(text)
    assert 'Backend <Intern> & Co (https://example.com/a?x=1&y="2")' in plain and "<b>" not in plain


def test_digest_splits_long_runs_within_telegram_limit():
    selected = [(_job(i, company=f"Company {i}", title="Backend Engineer Intern " + "x" * 100), Evaluation(80))
                for i in range(60)]
    messages = format_digest(selected)
    assert len(messages) > 1
    assert [job_id for _, ids in messages for job_id in ids] == [job.id for job, _ in selected]
    assert all(telegram._visible_length(text) <= 4096 for text, _ in messages)
    assert messages[0][0].startswith(f"🟢 <b>60 new matches</b>") and f"(1/{len(messages)})" in messages[0][0]
    assert messages[1][0].startswith("🟢 <b>Matches continued</b> (2/")
