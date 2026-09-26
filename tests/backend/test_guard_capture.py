"""
Guard capture — persistent ffmpeg, segment ring, MJPEG framing (step 1, v3.42)
==============================================================================

Two NUC field findings drive most of this file, and both are enforced here rather than
merely intended:

  * **No audio, ever.** The camera streams pcm_alaw, which MP4 rejects outright
    ("Could not find tag for codec pcm_alaw") — without `-an` recording produced nothing
    at all. But it is a POLICY decision first: recording conversations on a pontoon is a
    separate legal question from video and must not enter the system by accident. Every
    command shape is asserted to carry `-map 0:v:0 -an -dn -sn`.
  * **mpegts, never MP4, for the ring.** An MP4 killed mid-write leaves a 0-byte file with
    no moov atom. mpegts survives SIGTERM. This matters because the watchdog is *designed*
    to stop the worker abruptly — SUSPENDED_CPU does exactly that in production — so
    TC-GCAP-14 kills ffmpeg mid-recording and asserts the result still plays.

  TC-GCAP-01  capture command drops audio, data and subtitles on EVERY output
  TC-GCAP-02  capture command is one input with two outputs (one RTSP session)
  TC-GCAP-03  segment output is mpegts with the configured duration, and NOT mp4
  TC-GCAP-04  segment naming is monotonic, NOT -segment_wrap (pinning needs that)
  TC-GCAP-05  frame output honours GUARD_FPS and goes to stdout
  TC-GCAP-06  concat command drops audio too, stream-copies, and caps duration
  TC-GCAP-07  concat list escaping survives quotes and spaces
  TC-GCAP-08  credentials never reach a log line
  TC-GCAP-09  MJPEG framing splits a clean stream into exact frames
  TC-GCAP-10  MJPEG framing resynchronises past leading garbage and split reads
  TC-GCAP-11  MJPEG framing bounds its buffer on a stream with no end marker
  TC-GCAP-12  ring keeps the newest N and deletes the rest, oldest first
  TC-GCAP-13  ring NEVER deletes a pinned segment (an in-progress alarm clip)
  TC-GCAP-14  [ffmpeg] SIGKILL mid-recording leaves a PLAYABLE file  ← the regression
  TC-GCAP-15  [ffmpeg] a real capture produces segments and frames from one process
  TC-GCAP-16  complete_segments() excludes the segment still being written
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from guard_worker.capture import (
    SEGMENT_FORMAT,
    CameraCapture,
    _redact,
    build_capture_command,
    build_concat_command,
    complete_segments,
    iter_jpeg_frames,
    list_segments,
    prune_segments,
    write_concat_list,
)

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(
    not HAVE_FFMPEG,
    reason="ffmpeg not on PATH (absent from the NUC installer; run these on the NUC)",
)

URL = "rtsp://admin:secret@192.168.1.191:554/profile1"


def _jpeg(payload: bytes = b"body") -> bytes:
    return b"\xff\xd8" + payload + b"\xff\xd9"


def _make_segments(d: Path, n: int, start: int = 0) -> list[Path]:
    out = []
    for i in range(start, start + n):
        p = d / f"seg_{i:06d}.ts"
        p.write_bytes(b"x" * 16)
        out.append(p)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Command construction — the audio policy is enforced here
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gcap_01_no_audio_data_or_subtitles_on_any_output(tmp_path):
    cmd = build_capture_command(URL, tmp_path, fps=1, segment_seconds=10, ffmpeg="ffmpeg")

    # Two outputs → each exclusion must appear twice, once per output.
    assert cmd.count("-an") == 2, "audio must be refused on BOTH outputs"
    assert cmd.count("-dn") == 2, "data stream must be refused on BOTH outputs"
    assert cmd.count("-sn") == 2
    assert cmd.count("-map") == 2
    for i, a in enumerate(cmd):
        if a == "-map":
            assert cmd[i + 1] == "0:v:0", "only the first video stream may be admitted"

    # Nothing may re-admit audio.
    assert "-acodec" not in cmd
    assert not any(a.startswith("-c:a") for a in cmd)


def test_tc_gcap_02_single_input_two_outputs(tmp_path):
    """One RTSP session is the constraint; two outputs from one input is how it is met."""
    cmd = build_capture_command(URL, tmp_path, fps=1, segment_seconds=10, ffmpeg="ffmpeg")
    assert cmd.count("-i") == 1, "more than one -i would open a second RTSP session"
    assert cmd[-1] == "pipe:1"
    assert any(str(tmp_path) in a for a in cmd), "segment output missing"


def test_tc_gcap_03_segments_are_mpegts_not_mp4(tmp_path):
    """MP4 killed mid-write is a 0-byte unplayable file. See TC-GCAP-14."""
    cmd = build_capture_command(URL, tmp_path, fps=1, segment_seconds=10, ffmpeg="ffmpeg")
    assert SEGMENT_FORMAT == "mpegts"
    i = cmd.index("-segment_format")
    assert cmd[i + 1] == "mpegts"
    j = cmd.index("-segment_time")
    assert cmd[j + 1] == "10"
    assert "mp4" not in " ".join(cmd).lower()
    seg_arg = [a for a in cmd if a.endswith(".ts")]
    assert seg_arg and seg_arg[0].endswith("seg_%06d.ts")


def test_tc_gcap_04_monotonic_names_not_segment_wrap(tmp_path):
    """-segment_wrap would overwrite a segment an in-progress alarm clip still needs,
    which is exactly what pinning (TC-GCAP-13) exists to prevent."""
    cmd = build_capture_command(URL, tmp_path, fps=1, segment_seconds=10, ffmpeg="ffmpeg")
    assert "-segment_wrap" not in cmd


@pytest.mark.parametrize("fps", [1, 2, 0.5])
def test_tc_gcap_05_frame_output_honours_fps(tmp_path, fps):
    cmd = build_capture_command(URL, tmp_path, fps=fps, segment_seconds=10, ffmpeg="ffmpeg")
    i = cmd.index("-vf")
    assert cmd[i + 1] == f"fps={fps}"
    assert "image2pipe" in cmd
    assert cmd[cmd.index("-vcodec") + 1] == "mjpeg"


def test_tc_gcap_06_concat_command_is_copy_and_audio_free(tmp_path):
    cmd = build_concat_command(
        ["a.ts", "b.ts"], tmp_path / "l.txt", tmp_path / "out.mp4",
        max_seconds=60, ffmpeg="ffmpeg",
    )
    assert "-an" in cmd and "-dn" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "copy", "assembly must not re-encode"
    assert cmd[cmd.index("-t") + 1] == "60", "the 60 s cap must be enforced by ffmpeg"
    assert "+faststart" in cmd
    assert cmd[-1].endswith("out.mp4")

    no_cap = build_concat_command(["a.ts"], tmp_path / "l.txt", tmp_path / "o.mp4",
                                  ffmpeg="ffmpeg")
    assert "-t" not in no_cap


def test_tc_gcap_07_concat_list_escaping(tmp_path):
    lst = tmp_path / "list.txt"
    write_concat_list(
        [tmp_path / "plain.ts", tmp_path / "with space.ts", "/x/it's.ts"], lst,
    )
    body = lst.read_text(encoding="utf-8")
    assert body.count("file '") == 3
    assert "with space.ts" in body
    assert "it'\\''s.ts" in body, "single quotes need the concat demuxer's escaping"


def test_tc_gcap_08_credentials_never_logged(tmp_path):
    assert _redact(URL) == "rtsp://admin:***@192.168.1.191:554/profile1"
    assert "secret" not in _redact(URL)
    # Non-URL args pass through untouched
    assert _redact("-an") == "-an"
    assert _redact("rtsp://192.168.1.191/profile1") == "rtsp://192.168.1.191/profile1"

    cap = CameraCapture(URL, tmp_path, ffmpeg="ffmpeg")
    assert "secret" not in " ".join(_redact(a) for a in cap.command())


# ═══════════════════════════════════════════════════════════════════════════
# MJPEG framing
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gcap_09_framing_splits_clean_stream():
    frames = [_jpeg(b"one"), _jpeg(b"two"), _jpeg(b"three")]
    got = list(iter_jpeg_frames(io.BytesIO(b"".join(frames)), read_chunk=7))
    assert got == frames


def test_tc_gcap_10_framing_resynchronises():
    # Leading garbage before the first SOI, and a trailing incomplete frame.
    stream = b"\x00\x01garbage" + _jpeg(b"a") + _jpeg(b"b") + b"\xff\xd8incomplete"
    got = list(iter_jpeg_frames(io.BytesIO(stream), read_chunk=3))
    assert got == [_jpeg(b"a"), _jpeg(b"b")], "incomplete trailing frame must be dropped"


def test_tc_gcap_11_framing_bounds_buffer_without_end_marker():
    """A desynchronised stream must not grow the buffer without limit, and must not
    raise — the worker staying up matters more than one corrupt frame."""
    stream = b"\xff\xd8" + b"z" * 5000          # SOI then never an EOI
    got = list(iter_jpeg_frames(io.BytesIO(stream), max_frame_bytes=256, read_chunk=64))
    assert got == []


# ═══════════════════════════════════════════════════════════════════════════
# Segment ring
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gcap_12_ring_keeps_newest_n(tmp_path):
    _make_segments(tmp_path, 10)
    deleted = prune_segments(tmp_path, keep=6)
    assert len(deleted) == 4
    remaining = [p.name for p in list_segments(tmp_path)]
    assert remaining == [f"seg_{i:06d}.ts" for i in range(4, 10)]
    assert [p.name for p in deleted] == [f"seg_{i:06d}.ts" for i in range(4)]

    # Idempotent once at the limit
    assert prune_segments(tmp_path, keep=6) == []
    # Under the limit does nothing
    assert prune_segments(tmp_path, keep=99) == []


def test_tc_gcap_13_ring_never_deletes_pinned_segment(tmp_path):
    """An alarm clip being assembled pins the segments it still needs. Deleting one
    would destroy evidence mid-assembly — this is why the module manages the ring
    instead of using ffmpeg's -segment_wrap."""
    _make_segments(tmp_path, 10)
    pinned = {"seg_000000.ts", "seg_000001.ts"}
    deleted = prune_segments(tmp_path, keep=6, pinned=pinned)

    assert {p.name for p in deleted}.isdisjoint(pinned)
    survivors = {p.name for p in list_segments(tmp_path)}
    assert pinned <= survivors, "pinned segments must survive pruning"
    assert len(deleted) == 2       # only 2,3 were deletable


def test_tc_gcap_16_complete_segments_excludes_the_one_being_written(tmp_path):
    """The newest segment is still open in ffmpeg; using it would splice a partial
    file into an alarm clip."""
    _make_segments(tmp_path, 4)
    assert [p.name for p in complete_segments(tmp_path)] == [
        "seg_000000.ts", "seg_000001.ts", "seg_000002.ts",
    ]
    # Degenerate cases
    empty = tmp_path / "empty"
    empty.mkdir()
    assert complete_segments(empty) == []
    one = tmp_path / "one"
    one.mkdir()
    _make_segments(one, 1)
    assert complete_segments(one) == []


# ═══════════════════════════════════════════════════════════════════════════
# TC-GCAP-14/15 — real ffmpeg. Synthetic source, so no camera is needed.
# ═══════════════════════════════════════════════════════════════════════════

def ffmpeg_version() -> str:
    """First line of `ffmpeg -version`.

    Recorded in every failure message because dev and production DIVERGED on exactly this
    behaviour: observed **ffmpeg 8.0.1-3ubuntu2 on marina-iot (2026-09-26)**, where the
    original form of TC-GCAP-14 failed while passing on the dev box. A future divergence
    should be visible rather than confusing.
    """
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True,
                             timeout=30)
        return out.stdout.splitlines()[0] if out.stdout else "unknown"
    except Exception:
        return "unknown"


def decoded_frame_count(path: Path) -> int | None:
    """Frames that actually DECODE, via `ffprobe -count_frames`.

    Deliberately not a header duration and not a packet count: a damaged file can carry a
    plausible-looking header over unreadable payload, which is how the first version of
    TC-GCAP-14 fooled itself into reporting 393 s for a 4 s clip. Decoding is much harder
    to fool. Returns None when the file cannot be read at all.
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
             "-show_entries", "stream=nb_read_frames",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=120,
        )
        if out.returncode != 0:
            return None
        first = out.stdout.strip().splitlines()[0] if out.stdout.strip() else ""
        return int(first) if first.isdigit() else None
    except Exception:
        return None


def _record_then_signal(tmp_path: Path, container: str, suffix: str, sig: str,
                        seconds: float = 6.0):
    """Record `container` in REALTIME, then stop it with SIGTERM or SIGKILL.

    `-re` is essential. Without it lavfi generates frames as fast as the encoder consumes
    them, so a few seconds of wall time yields minutes of video and every duration-based
    assertion becomes meaningless.
    """
    out_path = tmp_path / ("killed_" + container + suffix)
    proc = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-re",                                   # realtime: frames approx wall seconds
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
         "-map", "0:v:0", "-an", "-dn", "-sn",
         "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
         "-f", container, "-y", str(out_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    t0 = time.time()
    time.sleep(seconds)
    if sig == "SIGKILL":
        proc.kill()
    else:
        proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    return out_path, time.time() - t0


@needs_ffmpeg
def test_tc_gcap_14_abrupt_kill_leaves_playable_file(tmp_path):
    """THE regression the field finding demands — corrected after the NUC run.

    The first version asserted the wrong property and was rightly caught: it reported a
    393.48 s duration for what should have been a 4 s clip. Two mistakes, both fixed:

      1. No `-re`, so lavfi ran far faster than realtime. The MP4 really did contain
         ~393 s of video; nothing was corrupt.
      2. It stopped ffmpeg with SIGTERM, which **ffmpeg handles gracefully** by writing a
         valid MP4 `moov` trailer. So the MP4 was fine and the assertion was simply false.

    That corrects the RATIONALE as well as the test. mpegts is NOT needed to survive
    SIGTERM. It is needed to survive **SIGKILL and power loss** — the genuine hazard here,
    because `CameraCapture.stop()` escalates to SIGKILL after a 5 s timeout, systemd
    escalates the same way, and a pontoon loses power. The conclusion (mpegts for the ring)
    stands; the reason is now accurate.

    Switching the ring to MP4 is caught by TC-GCAP-03, which asserts the segment format
    directly. This test exists to prove why that assertion matters.
    """
    ver = ffmpeg_version()
    fps = 25

    # mpegts under SIGKILL: must still decode roughly the length actually recorded.
    ts_path, elapsed = _record_then_signal(tmp_path, "mpegts", ".ts", "SIGKILL")
    expected = elapsed * fps
    assert ts_path.exists() and ts_path.stat().st_size > 0, (
        "mpegts left no usable file after SIGKILL (ffmpeg: " + ver + ")"
    )
    ts_frames = decoded_frame_count(ts_path)
    assert ts_frames is not None and ts_frames > 0, (
        "mpegts killed with SIGKILL did not decode at all - the segment ring would be "
        "producing unplayable evidence. ffmpeg: " + ver
    )
    assert 0.4 * expected <= ts_frames <= 1.6 * expected, (
        f"mpegts decoded {ts_frames} frames but ~{expected:.0f} were recorded "
        f"({elapsed:.1f}s at {fps}fps). A count far outside that band means the file is "
        f"not a faithful recording even though it opened. ffmpeg: {ver}"
    )

    # MP4 under SIGKILL: must NOT come back as a faithful recording.
    mp4_path, mp4_elapsed = _record_then_signal(tmp_path, "mp4", ".mp4", "SIGKILL")
    mp4_expected = mp4_elapsed * fps
    mp4_frames = decoded_frame_count(mp4_path) if mp4_path.exists() else None
    mp4_faithful = (mp4_frames is not None
                    and 0.4 * mp4_expected <= mp4_frames <= 1.6 * mp4_expected)
    assert not mp4_faithful, (
        f"MP4 SURVIVED a SIGKILL as a faithful recording ({mp4_frames} frames vs "
        f"~{mp4_expected:.0f} recorded, ffmpeg: {ver}). If this ffmpeg now writes a "
        "recoverable moov on SIGKILL, the premise behind the mpegts ring has changed. "
        "Revisit the ring format DELIBERATELY - measure it, update "
        "docs/guard_b1_design.md and this docstring - do not just relax this assertion. "
        "mpegts remains safe either way, so there is no urgency."
    )

    # Document the trap: MP4 DOES survive SIGTERM. That is exactly why graceful shutdown
    # cannot be the safety mechanism, and why the ring format has to carry the guarantee.
    term_path, term_elapsed = _record_then_signal(tmp_path, "mp4", ".mp4", "SIGTERM")
    term_frames = decoded_frame_count(term_path) if term_path.exists() else None
    print("\n[TC-GCAP-14] ffmpeg: " + ver)
    print(f"  mpegts + SIGKILL : {ts_frames} frames (~{expected:.0f} recorded) -> SAFE")
    print(f"  mp4    + SIGKILL : {mp4_frames} frames (~{mp4_expected:.0f} recorded) -> unsafe")
    print(f"  mp4    + SIGTERM : {term_frames} frames "
          f"(~{term_elapsed * fps:.0f} recorded) -> survives, which is WHY graceful "
          "shutdown cannot be relied on")


@needs_ffmpeg
def test_tc_gcap_15_real_capture_yields_segments_and_frames(tmp_path):
    """One process, two outputs: segments land on disk while frames arrive on stdout."""
    seg_dir = tmp_path / "segments"
    seg_dir.mkdir()
    # input_args swaps the RTSP flags for a synthetic source — no camera needed, and no
    # hand-editing of the command list, so this exercises the REAL command shape.
    cmd = build_capture_command(
        "testsrc=size=320x240:rate=25", seg_dir,
        fps=2, segment_seconds=1, ffmpeg="ffmpeg", input_args=["-f", "lavfi"],
    )
    assert "-rtsp_transport" not in cmd

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    frames = []
    try:
        deadline = time.time() + 12
        for frame in iter_jpeg_frames(proc.stdout):
            frames.append(frame)
            if len(frames) >= 4 or time.time() > deadline:
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait(timeout=5)

    err = proc.stderr.read(2000).decode("utf-8", "replace") if proc.stderr else ""
    assert len(frames) >= 2, f"expected frames on stdout, got {len(frames)}. stderr: {err}"
    for f in frames:
        assert f.startswith(b"\xff\xd8") and f.endswith(b"\xff\xd9")
    segs = list_segments(seg_dir)
    assert len(segs) >= 1, f"expected segments on disk. stderr: {err}"
    assert all(s.suffix == ".ts" for s in segs)
