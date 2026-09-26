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
  TC-GCAP-14  [ffmpeg] killed mid-recording leaves a PLAYABLE file  ← the regression
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

def _probe_duration(path: Path) -> float | None:
    """Seconds of decodable video, via ffprobe. None if unreadable."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-count_packets", "-show_entries", "stream=nb_read_packets,codec_name",
             "-of", "default=noprint_wrappers=1", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            return None
        packets = None
        for line in out.stdout.splitlines():
            if line.startswith("nb_read_packets="):
                packets = int(line.split("=")[1])
        return None if not packets else packets / 25.0
    except Exception:
        return None


@needs_ffmpeg
def test_tc_gcap_14_killed_mid_recording_leaves_playable_file(tmp_path):
    """THE regression the field finding demands.

    The watchdog is designed to stop the worker abruptly (SUSPENDED_CPU), so a
    mid-recording kill must never leave unplayable evidence. mpegts survives; MP4 does
    not — and this test proves both halves, so nobody can 'simplify' the ring back to
    MP4 without a red test.
    """
    src = ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=25"]

    # ── mpegts: killed mid-write, must still decode ──
    ts_path = tmp_path / "killed.ts"
    proc = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", *src,
         "-map", "0:v:0", "-an", "-dn", "-sn", "-c:v", "libx264", "-preset", "ultrafast",
         "-f", "mpegts", "-y", str(ts_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    time.sleep(4)
    proc.terminate()                      # exactly what the watchdog will do
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait(timeout=5)

    assert ts_path.exists(), "mpegts file missing entirely"
    size = ts_path.stat().st_size
    assert size > 0, "mpegts left a 0-byte file — the ring format is not abrupt-stop safe"
    dur = _probe_duration(ts_path)
    assert dur is not None and dur > 0.5, (
        f"mpegts killed mid-write did not decode (size={size}, duration={dur}) — "
        "the segment ring would be producing unplayable evidence"
    )

    # ── mp4: the same treatment, to document WHY we do not use it ──
    mp4_path = tmp_path / "killed.mp4"
    proc2 = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", *src,
         "-map", "0:v:0", "-an", "-dn", "-sn", "-c:v", "libx264", "-preset", "ultrafast",
         "-f", "mp4", "-y", str(mp4_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    time.sleep(4)
    proc2.terminate()
    try:
        proc2.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc2.kill(); proc2.wait(timeout=5)

    mp4_dur = _probe_duration(mp4_path) if mp4_path.exists() else None
    assert mp4_dur is None or mp4_dur == 0, (
        f"MP4 unexpectedly survived a mid-write kill (duration={mp4_dur}). If ffmpeg "
        "now writes a recoverable moov, revisit the ring-format choice deliberately "
        "rather than leaving this comment stale."
    )


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
