"""Speech (STEP-05, docs/EDITOR.md §5): words from a transcription, the packed transcript, the
speech-cut rules write_edl enforces (D41, F59), and the QA word check against `quote`."""

from pathlib import Path
from typing import Any

import pytest

from reel_studio.core import config
from reel_studio.editor import speech
from reel_studio.editor.media.edl_models import Edl

SPEECH = config.load().limits.speech


def _word(text: str, start: float, end: float) -> dict[str, Any]:  # Any: annotation JSON
    return {
        "type": "word_info",
        "text": text,
        "start_offset": f"{start:.3f}s",
        "end_offset": f"{end:.3f}s",
    }


# A recorded-shape interaction (ai.google.dev/gemini-api/docs/transcribe, read 11 Oct 2026):
# words arrive as word_info annotations with offsets like "0.100s".
RECORDED: dict[str, Any] = {  # Any: interaction JSON
    "output_text": "so the trick is brown the butter first until it smells nutty",
    "steps": [
        {
            "content": [
                {
                    "type": "text",
                    "text": "so the trick is brown the butter first until it smells nutty",
                    "annotations": [
                        _word("so", 12.40, 12.55),
                        _word("the", 12.56, 12.70),
                        _word("trick", 12.71, 13.00),
                        _word("is", 13.02, 13.18),
                        _word("brown", 13.80, 14.10),  # 0.62 s gap before: a clean cut
                        _word("the", 14.11, 14.20),
                        _word("butter", 14.21, 14.55),
                        _word("first", 14.56, 14.92),
                        _word("until", 15.10, 15.35),  # 0.18 s gap: visual check only
                        _word("it", 15.36, 15.45),
                        _word("smells", 15.46, 15.80),
                        _word("nutty", 15.81, 16.20),
                        {"type": "citation", "text": "ignored"},
                    ],
                }
            ]
        }
    ],
}


def _words() -> list[speech.Word]:
    return speech.words_from(RECORDED)


def test_words_and_times_are_parsed_from_the_annotations() -> None:
    words = _words()

    assert [w.text for w in words][:4] == ["so", "the", "trick", "is"]
    assert (words[4].start, words[4].end) == (13.80, 14.10)
    assert len(words) == 12


def test_a_response_without_words_has_none() -> None:
    assert speech.words_from({"output_text": "", "steps": []}) == []


def test_the_packed_transcript_splits_at_clean_gaps_and_marks_short_ones() -> None:
    packed = speech.pack("c03", _words(), SPEECH)

    assert packed == (
        "c03 [12.40-13.18] so the trick is\n"
        "c03 [13.80-16.20] ‖0.62‖ brown the butter first ‖0.18‖ until it smells nutty\n"
    )


def test_no_words_pack_to_nothing() -> None:
    assert speech.pack("c03", [], SPEECH) == ""


def _edl(*segments: dict[str, Any]) -> Edl:  # Any: segment JSON
    return Edl.model_validate({"versions": [{"name": "A", "segments": list(segments)}]})


def test_cuts_in_clean_gaps_and_outside_speech_pass() -> None:
    edl = _edl({"clip": "c03", "in": 12.0, "out": 13.5}, {"clip": "c03", "in": 13.5, "out": 17.0})

    assert speech.cut_problems(edl, {"c03": _words()}, SPEECH) == []


def test_a_cut_inside_a_word_names_the_nearest_clean_gap() -> None:
    edl = _edl({"clip": "c03", "in": 12.0, "out": 14.30})

    problems = speech.cut_problems(edl, {"c03": _words()}, SPEECH)

    assert len(problems) == 1
    assert "14.30" in problems[0] and "butter" in problems[0]
    assert "13.18-13.80" in problems[0]


def test_a_short_gap_needs_a_visual_check() -> None:
    cut = {"clip": "c03", "in": 12.0, "out": 15.00}

    problems = speech.cut_problems(_edl(cut), {"c03": _words()}, SPEECH)
    checked = speech.cut_problems(_edl({**cut, "visual_check": True}), {"c03": _words()}, SPEECH)

    assert len(problems) == 1 and "visual_check" in problems[0] and checked == []


def test_clips_without_words_are_not_checked() -> None:
    edl = _edl({"clip": "c09", "in": 0.0, "out": 1.0})

    assert speech.cut_problems(edl, {"c03": _words()}, SPEECH) == []


def test_the_qa_word_check_lists_missing_and_extra_words() -> None:
    edl = _edl(
        {"clip": "c03", "in": 12.0, "out": 13.5, "quote": "so the trick is"},
        {"clip": "c03", "in": 13.5, "out": 17.0, "quote": "brown the butter first"},
    )
    heard = speech.words_from(
        {
            "steps": [
                {
                    "content": [
                        {
                            "annotations": [
                                _word("so", 0.0, 0.1),
                                _word("the", 0.1, 0.2),
                                _word("trick", 0.2, 0.4),
                                _word("brown", 0.5, 0.7),
                                _word("the", 0.7, 0.8),
                                _word("better", 0.8, 0.9),
                                _word("first", 0.9, 1.0),
                            ]
                        }
                    ]
                }
            ]
        }
    )

    differences = speech.quote_differences(edl, heard)

    assert differences == ["missing: is", "missing: butter", "extra: better"]


def test_matching_words_ignore_case_and_punctuation() -> None:
    edl = _edl({"clip": "c03", "in": 0, "out": 1, "quote": "So, the trick!"})
    heard = [speech.Word("so", 0, 1), speech.Word("The", 1, 2), speech.Word("trick", 2, 3)]

    assert speech.quote_differences(edl, heard) == []


class FakeTranscriber:
    def __init__(self, records: dict[str, dict[str, Any]]) -> None:  # Any: interaction JSON
        self.records, self.calls = records, list[Path]()

    def transcribe(self, audio_path: Path, timestamps: bool = True) -> dict[str, Any]:
        self.calls.append(audio_path)
        return self.records[audio_path.stem]


def test_transcripts_are_written_where_read_transcript_reads_them(tmp_path: Path) -> None:
    fake = FakeTranscriber({"c03": RECORDED, "c04": {"steps": []}})
    audio = {"c03": tmp_path / "c03.m4a", "c04": tmp_path / "c04.m4a"}

    packed = speech.transcribe_all(fake, audio, tmp_path / "transcript", SPEECH)

    assert set(packed) == {"c03"}  # a clip without words gets no transcript
    assert (tmp_path / "transcript" / "c03.txt").read_text(encoding="utf-8") == packed["c03"]
    assert speech.load_words(tmp_path / "transcript")["c03"] == _words()


@pytest.mark.parametrize("offset", ["1.5", "abc", None])
def test_a_word_with_a_broken_offset_is_skipped(offset: str | None) -> None:
    bad = {"type": "word_info", "text": "x", "start_offset": offset, "end_offset": "2.0s"}
    record = {"steps": [{"content": [{"annotations": [bad, _word("ok", 1.0, 1.2)]}]}]}

    assert [w.text for w in speech.words_from(record)] == ["ok"]
