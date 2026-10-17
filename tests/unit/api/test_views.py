"""The order as the page sees it (web/src/lib/types.ts `OrderView`)."""

from datetime import UTC, datetime

from reel_studio.api.views import order_view
from reel_studio.core.ports import Record
from tests.fakes.storage import FakeStorage

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)


def view_of(result: dict[str, object]) -> dict[str, object]:
    doc: Record = {"status": "done", "settings": {}, "result": result}
    view = order_view(doc, storage=FakeStorage(), now=NOW, minutes=60, queue_position=None)
    shown = view["result"]
    assert isinstance(shown, dict)
    return shown


def test_stored_nulls_reach_the_page_as_empty_values() -> None:
    # The page reads `music.mood`; a null crashed it in the STEP-07 e2e run (L303, review S3).
    names = ("versions", "duration_s", "caption", "text_lines", "music", "left_out", "wishes")
    shown = view_of(dict.fromkeys((*names, "doubts")))
    assert shown == {
        "versions": [],
        "duration_s": 0,
        "caption": "",
        "text_lines": [],
        "music": {"mood": "", "tempo": ""},
        "left_out": [],
        "wishes": [],
        "doubts": [],
    }


def test_stored_values_are_passed_through() -> None:
    music = {"mood": "calm", "tempo": "slow"}
    shown = view_of({"versions": [], "music": music, "doubts": ["check the end"]})
    assert shown["music"] == music and shown["doubts"] == ["check the end"]
