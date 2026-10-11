"""`reel make` (STEP-03 tasks 7, 9): arguments, voice rule, output place, summary, exit codes."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from reel_studio.cli import reel
from reel_studio.core.errors import ProviderRejected
from reel_studio.editor import make, prompt
from reel_studio.settings import EditorSettings
from tests.conftest import MakeSettings
from tests.fakes.claude import FakeClaude, response, text
from tests.fakes.clock import FrozenClock
from tests.fakes.media import FakeMedia, critic_turn, edl_turn

NO_KEY_NOTICE = "No Gemini key: natural sound only, no transcription."


def _settings(make_settings: MakeSettings, **change: object) -> EditorSettings:
    settings = make_settings(EditorSettings, **change)
    assert isinstance(settings, EditorSettings)
    return settings


class _Wiring:
    """Records what the CLI hands to `make` and runs it with fakes."""

    def __init__(self, script: list[Any]) -> None:  # Any: response JSON
        self.fake, self.media = FakeClaude(script), FakeMedia()
        self.requests: list[make.Request] = []

    def deps(self) -> reel.Deps:
        def ports(settings: EditorSettings) -> make.Ports:
            return make.Ports(self.fake, FrozenClock(datetime(2026, 10, 10, tzinfo=UTC)))

        def steps(folder: Path, settings: EditorSettings) -> make.Steps:
            return make.Steps(self.media.prepare, self.media.render)

        return reel.Deps(ports=ports, steps=steps, on_request=self.requests.append)


def _folder(tmp_path: Path) -> Path:
    folder = tmp_path / "creami"
    folder.mkdir()
    return folder


def test_make_writes_to_out_name_and_prints_the_summary_and_cost(
    tmp_path: Path,
    make_settings: MakeSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    wiring = _Wiring([edl_turn("e1"), critic_turn(5)])

    code = reel.main(
        ["make", str(_folder(tmp_path)), "--style", "montage"],
        _settings(make_settings),
        wiring.deps(),
    )

    out = capsys.readouterr().out
    assert code == 0
    assert (tmp_path / "out" / "creami" / "text.mp4").is_file()
    assert "text.mp4" in out and "clean.mp4" in out and "29/35" in out and "$" in out
    order = wiring.requests[0].order
    assert (order.length_s, order.text_lang, order.voice) == (30, "en", False)


def test_no_gemini_key_forces_the_voice_off_with_the_notice(
    tmp_path: Path, make_settings: MakeSettings, capsys: pytest.CaptureFixture[str]
) -> None:
    wiring = _Wiring([edl_turn("e1"), critic_turn(5)])
    args = ["make", str(_folder(tmp_path)), "--style", "montage", "--voice", "on"]

    settings = _settings(make_settings, gemini_api_key=None)

    code = reel.main([*args, "--out", str(tmp_path / "o")], settings, wiring.deps())

    assert code == 0 and wiring.requests[0].order.voice is False
    assert NO_KEY_NOTICE in capsys.readouterr().out


def test_with_a_gemini_key_the_voice_follows_the_request(
    tmp_path: Path, make_settings: MakeSettings, capsys: pytest.CaptureFixture[str]
) -> None:
    wiring = _Wiring([edl_turn("e1"), critic_turn(5)])
    args = ["make", str(_folder(tmp_path)), "--style", "montage", "--voice", "on"]
    settings = _settings(make_settings)  # the test values carry a Gemini key

    code = reel.main([*args, "--out", str(tmp_path / "o")], settings, wiring.deps())

    assert code == 0 and wiring.requests[0].order.voice is True
    assert NO_KEY_NOTICE not in capsys.readouterr().out


@pytest.mark.parametrize("extra", [["--length", "45"], ["--text-lang", "fr"], ["--voice", "maybe"]])
def test_values_outside_the_choices_are_refused_by_the_parser(
    tmp_path: Path, make_settings: MakeSettings, extra: list[str]
) -> None:
    wiring = _Wiring([])
    args = ["make", str(_folder(tmp_path)), "--style", "montage", *extra]

    with pytest.raises(SystemExit) as done:
        reel.main(args, _settings(make_settings), wiring.deps())

    assert done.value.code == 2 and wiring.fake.requests == []


def test_a_style_without_prompts_yet_exits_2(
    tmp_path: Path, make_settings: MakeSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prompt, "available_styles", lambda _cfg: ["montage", "recipe"])
    wiring = _Wiring([])
    args = ["make", str(_folder(tmp_path)), "--style", "long_take"]

    assert reel.main(args, _settings(make_settings), wiring.deps()) == 2
    assert wiring.fake.requests == []


def test_an_out_inside_the_input_folder_is_refused(
    tmp_path: Path, make_settings: MakeSettings
) -> None:
    folder, wiring = _folder(tmp_path), _Wiring([])
    args = ["make", str(folder), "--style", "montage", "--out", str(folder / "o")]

    assert reel.main(args, _settings(make_settings), wiring.deps()) == 2
    assert wiring.fake.requests == []


def test_a_refusal_exits_1(tmp_path: Path, make_settings: MakeSettings) -> None:
    wiring = _Wiring([response([text("No.")], "refusal")])
    args = ["make", str(_folder(tmp_path)), "--style", "montage", "--out", str(tmp_path / "o")]

    assert reel.main(args, _settings(make_settings), wiring.deps()) == 1


def test_a_rejected_request_exits_1_with_one_line_and_no_traceback(
    tmp_path: Path, make_settings: MakeSettings, capsys: pytest.CaptureFixture[str]
) -> None:
    wiring = _Wiring([ProviderRejected("claude_create: http_401 authentication_error")])
    args = ["make", str(_folder(tmp_path)), "--style", "montage", "--out", str(tmp_path / "o")]

    assert reel.main(args, _settings(make_settings), wiring.deps()) == 1

    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    failed = [x for x in lines if x.get("event") == "failed"]
    assert len(failed) == 1 and "http_401" in failed[0]["message"]
    assert "exc_info" not in failed[0] and "Traceback" not in json.dumps(failed[0])
