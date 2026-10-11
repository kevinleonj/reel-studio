"""Speech (STEP-05, docs/EDITOR.md §5): words from a transcription, the packed transcript the
editor reads, the speech-cut rules write_edl enforces (D41, F59) and the QA word check.

A transcription arrives as word_info annotations with offsets such as "0.100s" (F212). The packed
transcript puts one phrase on each line, splits phrases at gaps of clean_gap_ms or more and marks
shorter gaps that still allow a cut with a visual check: `c03 [13.80-16.20] ‖0.62‖ brown the
butter ‖0.18‖ until`. A cut inside speech must land in a clean gap, or in a shorter one with
`visual_check: true`; the error names the nearest clean gap.
"""

import itertools
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from reel_studio.core import constants, ports
from reel_studio.core.config import Speech
from reel_studio.editor.media.edl_models import Edl

WORD_TYPE = "word_info"
SECONDS = "s"  # the offset suffix
GAP = "‖"  # marks a gap inside the packed transcript
FOLDER = "transcript"  # under the order's work folder
WORDS_JSON = ".words.json"
TEXT = ".txt"
TOKEN = re.compile(r"[\w']+")


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


def _seconds(value: object) -> float | None:
    if not isinstance(value, str) or not value.endswith(SECONDS):
        return None
    try:
        return float(value[: -len(SECONDS)])
    except ValueError:
        return None


def words_from(record: Mapping[str, Any]) -> list[Word]:  # Any: interaction JSON
    """Every word_info annotation with readable offsets, in time order."""
    words = []
    for step in record.get("steps") or []:
        for content in step.get("content") or []:
            for note in content.get("annotations") or []:
                start, end = _seconds(note.get("start_offset")), _seconds(note.get("end_offset"))
                if note.get("type") == WORD_TYPE and start is not None and end is not None:
                    words.append(Word(str(note.get("text", "")), start, end))
    return sorted(words, key=lambda w: w.start)


def _gaps(cfg: Speech) -> tuple[float, float]:
    return cfg.clean_gap_ms / constants.MS_PER_S, cfg.visual_check_gap_ms / constants.MS_PER_S


def pack(clip: str, words: Sequence[Word], cfg: Speech) -> str:
    clean, check = _gaps(cfg)
    lines: list[str] = []
    phrase: list[str] = []
    first = previous = None
    for word in words:
        gap = word.start - previous.end if previous is not None else 0.0
        if previous is not None and gap >= clean:
            lines.append(_line(clip, first, previous, phrase))
            phrase, first = [f"{GAP}{gap:.2f}{GAP}"], None
        elif previous is not None and gap >= check:
            phrase.append(f"{GAP}{gap:.2f}{GAP}")
        first = first if first is not None else word
        phrase.append(word.text)
        previous = word
    if first is not None and previous is not None:
        lines.append(_line(clip, first, previous, phrase))
    return "".join(lines)


def _line(clip: str, first: Word | None, last: Word, phrase: list[str]) -> str:
    start = first.start if first is not None else last.start
    return f"{clip} [{start:.2f}-{last.end:.2f}] {' '.join(phrase)}\n"


def _cut(t: float, words: Sequence[Word], visual_check: bool, cfg: Speech) -> str | None:
    """Why a cut at `t` breaks the speech rules, or None."""
    clean, check = _gaps(cfg)
    inside = next((w for w in words if w.start < t < w.end), None)
    if inside is None:
        pairs = itertools.pairwise(words)
        gap = next(((a, b) for a, b in pairs if a.end <= t <= b.start), None)
        if gap is None:
            return None  # before the first word or after the last
        size = gap[1].start - gap[0].end
        if size >= clean or (size >= check and visual_check):
            return None
        if size >= check:
            return f"lands in a {size:.2f} s gap: set visual_check: true, or use a clean gap"
        return f"lands in a {size:.2f} s gap, too short to cut"
    return f"falls inside '{inside.text}'"


def _nearest(t: float, words: Sequence[Word], cfg: Speech) -> str:
    clean, _ = _gaps(cfg)
    gaps = [(a.end, b.start) for a, b in itertools.pairwise(words) if b.start - a.end >= clean]
    if not gaps:
        return f"cut before {words[0].start:.2f} s or after {words[-1].end:.2f} s"
    a, b = min(gaps, key=lambda g: min(abs(t - g[0]), abs(t - g[1])))
    return f"nearest clean gap {a:.2f}-{b:.2f} s"


def cut_problems(edl: Edl, words: Mapping[str, Sequence[Word]], cfg: Speech) -> list[str]:
    """Every cut in or out that breaks D41 on a clip with speech."""
    problems = []
    for version in edl.versions:
        for number, seg in enumerate(version.segments, 1):
            spoken = words.get(seg.clip)
            if not spoken:
                continue
            for t in (seg.in_, seg.out):
                why = _cut(t, spoken, bool(seg.visual_check), cfg)
                if why is not None:
                    where = f"segment {number} ({seg.clip}) cut at {t:.2f} s"
                    problems.append(f"{where} {why}; {_nearest(t, spoken, cfg)}")
    return problems


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in TOKEN.findall(text)]


def quote_differences(edl: Edl, heard: Iterable[Word]) -> list[str]:
    """Words the edit list quotes but the render does not say, and words it says that no quote
    has, in order (a longest-common-subsequence alignment)."""
    quotes = [s.quote for v in edl.versions for s in v.segments if s.quote]
    want = [t for q in quotes for t in _tokens(q)]
    got = [t for w in heard for t in _tokens(w.text)]
    table = [[0] * (len(got) + 1) for _ in range(len(want) + 1)]
    for i in range(len(want) - 1, -1, -1):
        for j in range(len(got) - 1, -1, -1):
            same = want[i] == got[j]
            table[i][j] = table[i + 1][j + 1] + 1 if same else max(table[i + 1][j], table[i][j + 1])
    out, i, j = [], 0, 0
    while i < len(want) or j < len(got):
        if i < len(want) and j < len(got) and want[i] == got[j]:
            i, j = i + 1, j + 1
        elif i < len(want) and (j == len(got) or table[i + 1][j] >= table[i][j + 1]):
            out.append(f"missing: {want[i]}")
            i += 1
        else:
            out.append(f"extra: {got[j]}")
            j += 1
    return out


def transcribe_all(
    transcriber: ports.Transcriber, audio: Mapping[str, Path], folder: Path, cfg: Speech
) -> dict[str, str]:
    """One request per clip (EDITOR §5); clips with words get <clip>.txt (packed, what
    read_transcript returns) and <clip>.words.json (what the cut check reads)."""
    folder.mkdir(parents=True, exist_ok=True)
    packed = {}
    for clip, path in audio.items():
        words = words_from(transcriber.transcribe(path, timestamps=True))
        if not words:
            continue
        packed[clip] = pack(clip, words, cfg)
        (folder / f"{clip}{TEXT}").write_text(packed[clip], encoding="utf-8")
        data = json.dumps([asdict(w) for w in words])
        (folder / f"{clip}{WORDS_JSON}").write_text(data, encoding="utf-8")
    return packed


def load_words(folder: Path) -> dict[str, list[Word]]:
    if not folder.is_dir():
        return {}
    found = {}
    for path in sorted(folder.glob(f"*{WORDS_JSON}")):
        clip = path.name.removesuffix(WORDS_JSON)
        found[clip] = [Word(**w) for w in json.loads(path.read_text(encoding="utf-8"))]
    return found
