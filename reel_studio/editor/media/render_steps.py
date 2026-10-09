"""A render's ffmpeg steps: one segment, loudness pass 1, final encode (kit render.py:226-303)."""

import json
import re
from pathlib import Path

from reel_studio.core import constants
from reel_studio.core.media_config import Media
from reel_studio.editor.media.edl import resolve, seg_dur, speed_of
from reel_studio.editor.media.edl_models import Edl, Segment
from reel_studio.editor.media.render_filters import (
    TextEvent,
    atempo_chain,
    crop_filter,
    flip,
    grade_filter,
)
from reel_studio.editor.media.shots import Clip, Shots
from reel_studio.editor.media.tools import Ffmpeg

LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)  # kit render.py:259


class Steps:
    def __init__(self, work: Path, ffmpeg: Ffmpeg, shots: Shots, edl: Edl, media: Media) -> None:
        self.work, self.ffmpeg, self.shots, self.edl, self.media = work, ffmpeg, shots, edl, media
        self.rate, self.channels = str(constants.AUDIO_RATE_HZ), str(constants.AUDIO_CHANNELS)

    def segment(self, clip: Clip, seg: Segment, out: Path, lut: Path | None) -> None:
        """Kit render.py:226-247."""
        cfg = self.media.render.segment
        sp, d = speed_of(seg, self.media), seg_dur(seg, self.media)
        frame = resolve(seg, self.edl.defaults, self.media)
        vol = cfg.mute_db if seg.mute else seg.audio_db
        look = grade_filter(self.edl.grade, lut, self.media)
        tail = f"{look},setpts=(PTS-STARTPTS)/{sp},fps={constants.OUT_FPS}[v]"
        size = f"{constants.OUT_W}:{constants.OUT_H}"
        if frame.fit == "blur":  # whole frame visible, a blurred zoomed copy fills the canvas
            blur = self.media.render.blur_fit
            vchain = (
                f"[0:v]split[bgs][fgs];[bgs]scale={size}:force_original_aspect_ratio=increase,"
                f"crop={size},boxblur={blur.boxblur},eq=brightness={blur.background_brightness}[bg];"
                f"[fgs]scale={constants.OUT_W}:-2:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
                f"setsar=1{flip(frame)}{tail}"
            )
        else:
            vchain = f"[0:v]{crop_filter(clip, frame)}{tail}"
        fade_out = max(0.0, d - cfg.fade_s)
        achain = (
            f"[0:a]asetpts=PTS-STARTPTS,{atempo_chain(sp, cfg)},volume={vol}dB,"
            f"aresample={self.rate},apad,atrim=0:{d:.4f},afade=t=in:d={cfg.fade_s},"
            f"afade=t=out:st={fade_out:.4f}:d={cfg.fade_s}[a]"
        )
        args = [
            "-y",
            "-v",
            "error",
            "-ss",
            f"{seg.in_:.3f}",
            "-t",
            f"{seg.out - seg.in_:.3f}",
            "-i",
            str(self.work / clip.proxy),
            "-filter_complex",
            f"{vchain};{achain}",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            f"{d:.4f}",
            "-c:v",
            "libx264",
            "-crf",
            str(cfg.crf),
            "-preset",
            cfg.preset,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            cfg.audio_codec,
            "-ar",
            self.rate,
            "-ac",
            self.channels,
            str(out),
        ]
        self.ffmpeg.run(args, f"Rendering segment {out.name}")

    def loudness(self, parts: list[Path]) -> dict[str, str] | None:
        """Pass 1 of two-pass loudnorm, audio only (kit render.py:250-268)."""
        cfg = self.media.render.loudness
        args = ["-hide_banner", "-nostats"]
        for p in parts:
            args += ["-i", str(p)]
        inputs = "".join(f"[{i}:a]" for i in range(len(parts)))
        norm = (
            f"loudnorm=I={constants.TARGET_LUFS:g}:TP={cfg.true_peak_db:g}:LRA={cfg.lra}"
            ":print_format=json"
        )
        args += [
            "-filter_complex",
            f"{inputs}concat=n={len(parts)}:v=0:a=1,{norm}[a]",
            "-map",
            "[a]",
            "-f",
            "null",
            "-",
        ]
        found = LOUDNORM_JSON.search(self.ffmpeg.measure(args, "Measuring loudness"))
        if found is None:
            return None
        data: dict[str, str] = json.loads(found.group(0))
        try:
            if float(data["input_i"]) < cfg.silence_below_lufs:  # silence: nothing to normalise
                return None
        except ValueError:
            return None
        return data

    def loud_filter(self, loud: dict[str, str] | None) -> str:
        """Linear loudnorm when it can reach the target under the peak cap, else gain + limiter."""
        cfg = self.media.render.loudness
        if loud is None:
            return "anull"
        gain = constants.TARGET_LUFS - float(loud["input_i"])
        if float(loud["input_tp"]) + gain <= cfg.true_peak_db:
            return (
                f"loudnorm=I={constants.TARGET_LUFS:g}:TP={cfg.true_peak_db:g}:LRA={cfg.lra}:"
                f"measured_I={loud['input_i']}:measured_TP={loud['input_tp']}:"
                f"measured_LRA={loud['input_lra']}:measured_thresh={loud['input_thresh']}:"
                f"offset={loud['target_offset']}:linear=true"
            )
        boost = min(
            gain + cfg.limiter_headroom_db, cfg.max_gain_db
        )  # the limiter eats some loudness
        return (
            f"volume={boost:.2f}dB,aresample={cfg.limiter_oversample_hz},"
            f"alimiter=limit={cfg.limiter_limit}:attack={cfg.limiter_attack_ms}:"
            f"release={cfg.limiter_release_ms}:level=false,aresample={self.rate}"
        )

    def finalize(
        self,
        parts: list[Path],
        loud: dict[str, str] | None,
        overlays: list[tuple[TextEvent, Path]],
        out: Path,
    ) -> None:
        """Concatenate, overlay text, normalise, encode (kit render.py:271-303)."""
        cfg = self.media.render.final
        args, n = ["-y", "-v", "error"], len(parts)
        for p in parts:
            args += ["-i", str(p)]
        for _, png in overlays:
            args += ["-loop", "1", "-i", str(png)]
        chain = ["".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v0][nat]"]
        last = "v0"
        for k, (ev, _) in enumerate(overlays):
            nxt = f"v{k + 1}"
            chain.append(
                f"[{last}][{n + k}:v]overlay=0:0:shortest=1:"
                f"enable='between(t,{ev.start:.3f},{ev.end:.3f})'[{nxt}]"
            )
            last = nxt
        chain.append(
            f"[nat]volume={self.edl.audio.natural_db}dB,{self.loud_filter(loud)},aresample={self.rate}[aout]"
        )
        fps = constants.OUT_FPS
        args += [
            "-filter_complex",
            ";".join(chain),
            "-map",
            f"[{last}]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            cfg.preset,
            "-crf",
            str(cfg.crf),
            "-profile:v",
            cfg.profile,
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-g",
            str(fps * cfg.gop_seconds),
            "-maxrate",
            cfg.maxrate,
            "-bufsize",
            cfg.bufsize,
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-c:a",
            "aac",
            "-b:a",
            f"{cfg.audio_bitrate_kbps}k",
            "-ar",
            self.rate,
            "-ac",
            self.channels,
            "-movflags",
            "+faststart",
            str(out),
        ]
        self.ffmpeg.run(args, f"Final encode {out.name}")
