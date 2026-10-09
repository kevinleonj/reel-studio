"""The five emails of docs/UX.md §3: words, links, escaping and the 100 KB budget."""

import pytest

from reel_studio.adapters.mailer_smtp import TEMPLATES, Rendered, render
from reel_studio.core.constants import EMAIL_MAX_BYTES

LINK = "http://127.0.0.1:8080/o/" + "a" * 32 + "#t=secret"


def html(mail: Rendered) -> str:
    assert mail.html is not None
    return mail.html


COMMON = {"order_url": LINK, "max_files": 40, "max_total": "4 GB", "out_days": 30}


def test_link_email() -> None:
    mail = render("link", COMMON)
    assert mail.subject == "Your Reel Studio link"
    assert "Upload your clips" in html(mail) and LINK in html(mail)
    assert "Up to 40 files, 4 GB." in mail.text
    assert "Keep this email: the link is your access." in mail.text


def test_ready_email_quotes_the_hook_and_says_ai() -> None:
    mail = render("ready", {**COMMON, "hook": "Grandma's cheesecake"})
    assert mail.subject == 'Your Reel is ready: "Grandma\'s cheesecake"'
    assert "Watch and download" in html(mail)
    assert "Files are deleted after 30 days." in mail.text
    assert "Edited by AI (Claude). Check it before posting." in mail.text


def test_failed_and_paused_emails() -> None:
    failed = render(
        "failed",
        {
            **COMMON,
            "message": "Something broke while cutting.",
            "start_url": "http://127.0.0.1:8080/new",
        },
    )
    assert failed.subject == "Your Reel didn't finish"
    assert "Your code still works." in failed.text and "Start again" in html(failed)
    paused = render("paused", {**COMMON, "message": "We hit this month's budget."})
    assert paused.subject == "Your Reel is waiting"
    assert "We hit this month's budget." in paused.text


def test_kevin_alert_is_plain_text() -> None:
    mail = render(
        "kevin",
        {"status": "failed", "order_id": "a" * 32, "stage": "rendering", "code": "render_error"},
    )
    assert mail.subject == f"[reel-studio] failed {'a' * 32} at rendering: render_error"
    assert mail.html is None
    assert "reelctl" in mail.text


def test_html_escapes_user_text() -> None:
    mail = render("ready", {**COMMON, "hook": "<script>alert(1)</script>"})
    assert "<script>" not in html(mail)
    assert "&lt;script&gt;" in html(mail)


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_every_email_is_small_and_has_no_tracking(name: str) -> None:
    data = {
        **COMMON,
        "hook": "h",
        "message": "m",
        "start_url": LINK,
        "status": "s",
        "order_id": "o",
        "stage": "x",
        "code": "c",
    }
    mail = render(name, data)
    size = len(mail.text.encode()) + len((mail.html or "").encode())
    assert size < EMAIL_MAX_BYTES
    assert "<img" not in (mail.html or "")


def test_a_missing_value_fails_loudly() -> None:
    with pytest.raises(Exception, match="hook"):
        render("ready", COMMON)
