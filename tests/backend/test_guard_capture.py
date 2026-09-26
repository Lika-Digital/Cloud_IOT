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
  TC-GCAP-14  [ffmpeg] the RING retains usable history across SIGKILL ← the regression
  TC-GCAP-18  [ffmpeg] why mpegts and not mp4 segments (the in-flight segment)
  TC-GCAP-19  [ffmpeg, opt-in GUARD_TEST_RTSP_URL] the same, against the REAL camera
  TC-GCAP-20  no HTTP-only input options on an RTSP command (ffmpeg 8 refuses to start)
  TC-GCAP-21  -nostdin is always present, and precedes -i
  TC-GCAP-22  supervisor restarts with backoff and REPORTS why
  TC-GCAP-23  supervisor does not retry a missing ffmpeg binary
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

    Reported in every failure message because dev and production have now diverged TWICE
    on this test. Observed on marina-iot: **ffmpeg 8.0.1-3ubuntu2 (2026-09-26)**.
    """
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True,
                             timeout=30)
        return out.stdout.splitlines()[0] if out.stdout else "unknown"
    except Exception:
        return "unknown"


def decoded_frame_count(path: Path) -> int | None:
    """Frames that actually DECODE, via `ffprobe -count_frames`.

    Not a header duration and not a packet count: a damaged file can carry a plausible
    header over unreadable payload, which is how an earlier version of these tests fooled
    itself into reporting 393 s for a 4 s clip. None when the file cannot be read at all.
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


def _make_h264_source(tmp_path: Path, seconds: int = 40) -> Path:
    """Pre-encode an H.264 file to stand in for the camera.

    This matters: the production segment output is `-c:v copy`, which requires ALREADY
    ENCODED input. Feeding raw lavfi video into it cannot work — mpegts carries no
    rawvideo — and an earlier version of TC-GCAP-15 did exactly that, then passed anyway
    because it only asserted that a segment FILE existed. A 0-byte file satisfied it.
    Stream-copying pre-encoded video is also what really happens with RTSP.
    """
    src = tmp_path / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=25",
         "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast",
         "-g", "25", "-an", "-y", str(src)],
        check=True, capture_output=True, timeout=300,
    )
    assert src.exists() and src.stat().st_size > 0, "could not build the test source"
    return src


def _run_ring_until_killed(tmp_path: Path, source: Path, *, segment_seconds: int,
                           record_seconds: float, sig: str):
    """Drive the REAL capture command against `source` in realtime, then signal it.

    Uses `build_capture_command` itself, so this exercises the production command shape:
    one input, `-c:v copy` into the segment muxer, MJPEG frames on stdout.
    """
    seg_dir = tmp_path / "segments"
    seg_dir.mkdir(exist_ok=True)
    cmd = build_capture_command(
        str(source), seg_dir,
        fps=1, segment_seconds=segment_seconds, ffmpeg="ffmpeg",
        # -re throttles the file read to realtime, standing in for a live 25 fps source.
        input_args=["-re"],
    )
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    sizes = []
    t0 = time.time()
    try:
        while time.time() - t0 < record_seconds:
            time.sleep(1.0)
            sizes.append(sum(p.stat().st_size for p in list_segments(seg_dir)))
        if sig == "SIGKILL":
            proc.kill()
        else:
            proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    err = proc.stderr.read(3000).decode("utf-8", "replace") if proc.stderr else ""
    return seg_dir, sizes, err


@needs_ffmpeg
def test_tc_gcap_14_ring_retains_history_across_sigkill(tmp_path):
    """THE regression, now testing the property we actually depend on.

    Corrected twice after NUC runs, and the history is the point:

      * v1 had no `-re`, so lavfi ran far faster than realtime (393 s of video in 4 s) and
        stopped with SIGTERM, which ffmpeg handles gracefully by writing a valid MP4
        trailer. The assertion was simply false.
      * v2 added `-re` and SIGKILL, and then FAILED on the NUC with a 0-byte file. That was
        a test artefact, not a format property: a tiny 320x240 synthetic stream produces so
        few bytes that a single ffmpeg output can still hold everything in its AVIO buffer
        after several seconds, so SIGKILL loses it. Without `-re` the same stream overflowed
        the buffer constantly, which is why v1 appeared to pass.

    What we depend on is NOT "one mpegts file survives SIGKILL in the abstract". It is
    **the segment ring retains usable history when the worker is killed** — a property of
    the ring, so it is tested through the real segment muxer via `build_capture_command`.

    The segment muxer closes each file as it rolls, and closing flushes. So COMPLETED
    segments are on disk regardless of how the process dies. The in-progress segment may
    be lost, which is expected and already handled by `complete_segments()` excluding the
    newest file.
    """
    ver = ffmpeg_version()
    src = _make_h264_source(tmp_path, seconds=40)

    # segment_time=2 and ~9 s of recording gives ~4 completed segments to inspect.
    seg_dir, sizes, err = _run_ring_until_killed(
        tmp_path, src, segment_seconds=2, record_seconds=9.0, sig="SIGKILL",
    )

    all_segs = list_segments(seg_dir)
    complete = complete_segments(seg_dir)
    print(f"\n[TC-GCAP-14] ffmpeg: {ver}")
    print(f"  bytes on disk over time : {sizes}")
    print(f"  segments total/complete : {len(all_segs)}/{len(complete)}")

    assert all_segs, f"the ring produced no segments at all. stderr: {err}"
    assert len(complete) >= 1, (
        f"no COMPLETED segment survived SIGKILL ({len(all_segs)} file(s) total). The ring "
        f"retains no usable history, so the pre-roll design does not hold. "
        f"ffmpeg: {ver}. stderr: {err}"
    )

    # Every completed segment must decode a plausible amount of video.
    expected_per_segment = 2 * 25
    for seg in complete:
        size = seg.stat().st_size
        assert size > 0, f"completed segment {seg.name} is 0 bytes. ffmpeg: {ver}"
        frames = decoded_frame_count(seg)
        assert frames is not None and frames > 0, (
            f"completed segment {seg.name} ({size} bytes) does not decode — the ring is "
            f"storing unplayable evidence. ffmpeg: {ver}"
        )
        assert frames >= 0.4 * expected_per_segment, (
            f"completed segment {seg.name} decoded only {frames} frames, expected roughly "
            f"{expected_per_segment}. ffmpeg: {ver}"
        )

    # Growth over time confirms bytes really are reaching disk continuously, which is the
    # behaviour the v2 failure was actually about.
    assert sizes[-1] > 0, f"nothing ever reached disk. ffmpeg: {ver}. stderr: {err}"

    # Informational, deliberately NOT asserted: mpegts often leaves the in-flight segment
    # partially decodable, which MP4 never would. That is mpegts' remaining advantage once
    # the segment muxer is in play (see TC-GCAP-18), but it depends on buffer timing and is
    # too flaky to gate a build on.
    if all_segs:
        newest = all_segs[-1]
        print(f"  in-flight segment       : {newest.name}, {newest.stat().st_size} bytes, "
              f"{decoded_frame_count(newest)} frames (salvage is a bonus, not required)")


@needs_ffmpeg
def test_tc_gcap_18_why_mpegts_and_not_mp4_segments(tmp_path):
    """Records the honest, narrower reason for mpegts — my original claim was too broad.

    With the segment muxer, COMPLETED segments are finalised on roll in either format, so
    "MP4 loses everything" is wrong once segmenting is involved. What MP4 loses is the
    **in-flight** segment: with no `moov` it is unplayable, whereas a truncated mpegts
    decodes up to the cut.

    That in-flight file holds the most RECENT 0-10 s — exactly the seconds closest to an
    alarm, and the most valuable for pre-roll. So mpegts is still right, and it costs
    nothing. This test documents that difference rather than asserting a flaky salvage.
    """
    ver = ffmpeg_version()
    src = _make_h264_source(tmp_path, seconds=20)
    results = {}

    for fmt, suffix in (("mpegts", ".ts"), ("mp4", ".mp4")):
        out = tmp_path / f"single_{fmt}{suffix}"
        proc = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-re", "-i", str(src),
             "-map", "0:v:0", "-an", "-dn", "-sn", "-c:v", "copy",
             "-f", fmt, "-y", str(out)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        time.sleep(6)
        proc.kill()                      # abrupt, no chance to write a trailer
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.wait(timeout=5)
        results[fmt] = (
            out.stat().st_size if out.exists() else 0,
            decoded_frame_count(out) if out.exists() else None,
        )

    print(f"\n[TC-GCAP-18] ffmpeg: {ver}")
    for fmt, (size, frames) in results.items():
        print(f"  single {fmt:6s} + SIGKILL: {size} bytes, {frames} frames")

    mp4_size, mp4_frames = results["mp4"]
    ts_size, ts_frames = results["mpegts"]

    # The claim we rely on: an unfinalised MP4 is not usable video. If a future ffmpeg
    # makes it usable, the in-flight advantage disappears and the choice should be
    # revisited deliberately — but mpegts stays safe either way, so this is informational
    # unless MP4 clearly wins.
    assert not (mp4_frames and ts_frames and mp4_frames > ts_frames * 1.5), (
        f"MP4 now retains MORE decodable video than mpegts under SIGKILL "
        f"(mp4={mp4_frames}, mpegts={ts_frames}, ffmpeg: {ver}). The premise behind the "
        "ring format has inverted — revisit docs/guard_b1_design.md and capture.py "
        "deliberately rather than relaxing this."
    )


@needs_ffmpeg
def test_tc_gcap_15_real_capture_yields_segments_and_frames(tmp_path):
    """One process, two outputs: segments land on disk while frames arrive on stdout."""
    seg_dir = tmp_path / "segments"
    seg_dir.mkdir()
    # A PRE-ENCODED source, because the segment output is `-c:v copy` and cannot
    # accept raw lavfi video. The earlier version fed raw video in and passed only
    # because it asserted a segment file existed — a 0-byte file satisfied it.
    src = _make_h264_source(tmp_path, seconds=20)
    cmd = build_capture_command(
        str(src), seg_dir,
        fps=2, segment_seconds=1, ffmpeg="ffmpeg", input_args=["-re"],
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
    # Presence is not enough — a 0-byte segment is what the old version accepted.
    complete = complete_segments(seg_dir)
    assert complete, f"no completed segment to verify. stderr: {err}"
    for seg in complete:
        assert seg.stat().st_size > 0, f"{seg.name} is 0 bytes. stderr: {err}"
        assert decoded_frame_count(seg), (
            f"{seg.name} does not decode — -c:v copy likely rejected the input. "
            f"stderr: {err}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# TC-GCAP-19 — the same ring property against the REAL camera.
#
# Opt-in, because it needs credentials and the marina LAN:
#
#   GUARD_TEST_RTSP_URL='rtsp://admin:PASS@192.168.1.191:554/profile1' \
#     python -m pytest tests/backend/test_guard_capture.py -q -s --noconftest
#
# This is the test that matters most. The synthetic tests prove the command shape and
# the ring logic, but the timing behaviour of a live 25 fps RTSP source is what
# production actually depends on — and it is precisely where a low-bitrate synthetic
# stream misled us (the 0-byte v2 failure was ffmpeg buffering a tiny stream, not a
# format property). A real 1080p25 feed writes continuously, so completed segments
# should land on disk every GUARD_SEGMENT_SECONDS regardless of how the worker dies.
# ═══════════════════════════════════════════════════════════════════════════

RTSP_URL_ENV = os.environ.get("GUARD_TEST_RTSP_URL", "").strip()
needs_camera = pytest.mark.skipif(
    not RTSP_URL_ENV,
    reason="set GUARD_TEST_RTSP_URL to run the real-camera ring test (NUC only)",
)


@needs_ffmpeg
@needs_camera
def test_tc_gcap_19_real_camera_ring_survives_sigkill(tmp_path):
    """Production shape, production source, production kill path."""
    ver = ffmpeg_version()
    seg_dir = tmp_path / "segments"
    seg_dir.mkdir()

    # The real command, unmodified: RTSP flags, -c:v copy, segment muxer, MJPEG frames.
    cap = CameraCapture(
        RTSP_URL_ENV, seg_dir,
        fps=1, segment_seconds=5, segment_ring=6, ffmpeg="ffmpeg",
    )
    cap.start()

    # Did the process even START? Claiming "output 2 is not working" while ffmpeg had
    # already exited on an invalid option cost real debugging time, so diagnose first and
    # assert second. drain_stderr() existed all along and the test simply never used it.
    time.sleep(3)
    alive = cap.is_running
    early_exit_rc = None if alive else (cap._proc.returncode if cap._proc else None)
    if not alive:
        why = cap.drain_stderr()
        print(f"\n[TC-GCAP-19] ffmpeg EXITED EARLY rc={early_exit_rc}")
        print(f"  command: {' '.join(_redact(a) for a in cap.command())}")
        print(f"  stderr : {why.strip()}")
        cap.stop()
        pytest.fail(
            f"ffmpeg exited within 3s (rc={early_exit_rc}) — the process never ran, so "
            f"any claim about frames or segments would be misleading.\nstderr: "
            f"{why.strip()}\ncommand: {' '.join(_redact(a) for a in cap.command())}"
        )

    sizes = []
    frames_seen = 0
    try:
        t0 = time.time()
        # Read a few frames so output 2 is exercised too, then let segments accumulate.
        for _frame in cap.frames():
            frames_seen += 1
            if frames_seen >= 3 or time.time() - t0 > 20:
                break
        while time.time() - t0 < 22:
            time.sleep(2)
            sizes.append(sum(p.stat().st_size for p in list_segments(seg_dir)))
            if not cap.is_running:
                break
    finally:
        still_running = cap.is_running
        stderr_tail = "" if still_running else cap.drain_stderr()
        # SIGKILL directly — the watchdog's escalation path, and the worst realistic case.
        if cap._proc is not None and cap._proc.poll() is None:
            cap._proc.kill()
            cap._proc.wait(timeout=10)
    if not still_running:
        print(f"\n[TC-GCAP-19] ffmpeg exited during the run: {stderr_tail.strip()[-600:]}")

    all_segs = list_segments(seg_dir)
    complete = complete_segments(seg_dir)
    print(f"\n[TC-GCAP-19] ffmpeg: {ver}")
    print(f"  camera            : {_redact(RTSP_URL_ENV)}")
    print(f"  frames from stdout: {frames_seen}")
    print(f"  bytes over time   : {sizes}")
    print(f"  segments total/cmp: {len(all_segs)}/{len(complete)}")

    assert frames_seen >= 2, (
        f"no MJPEG frames arrived from the camera — output 2 is not working. ffmpeg: {ver}"
    )
    assert all_segs, f"the ring produced no segments from the camera. ffmpeg: {ver}"
    assert len(complete) >= 2, (
        f"expected at least 2 completed 5 s segments in ~22 s, got {len(complete)}. "
        f"The ring is not retaining history from the live source. ffmpeg: {ver}"
    )
    for seg in complete:
        size = seg.stat().st_size
        frames = decoded_frame_count(seg)
        print(f"    {seg.name}: {size} bytes, {frames} frames")
        assert size > 0, f"completed segment {seg.name} is 0 bytes. ffmpeg: {ver}"
        assert frames is not None and frames > 0, (
            f"completed segment {seg.name} does not decode — the ring would be storing "
            f"unplayable evidence from the real camera. ffmpeg: {ver}"
        )
        # 5 s at 25 fps ~= 125 frames; allow wide tolerance for keyframe alignment.
        assert frames >= 25, (
            f"completed segment {seg.name} decoded only {frames} frames for a 5 s "
            f"segment. ffmpeg: {ver}"
        )

    # No audio may reach disk — the policy, verified on the real stream that HAS audio.
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "default=noprint_wrappers=1:nokey=1", str(complete[0])],
        capture_output=True, text=True, timeout=60,
    )
    kinds = [ln.strip() for ln in probe.stdout.splitlines() if ln.strip()]
    print(f"  streams in segment: {kinds}")
    assert "audio" not in kinds, (
        f"AUDIO REACHED DISK from the real camera ({kinds}). The camera streams pcm_alaw "
        "and guard must never record it — this is a policy requirement, not a codec "
        "workaround. Check -map 0:v:0 -an -dn -sn on the segment output."
    )

# ═══════════════════════════════════════════════════════════════════════════
# TC-GCAP-20/21 — static guards for the class of bug synthetic tests cannot see
#
# -reconnect / -reconnect_streamed / -reconnect_delay_max are HTTP/TCP protocol options.
# On a lavfi or file input they are harmless, so every synthetic test passed. On an RTSP
# input ffmpeg 8.0.1 REFUSES TO START ("Option reconnect not found"), so the real command
# produced 0 frames, 0 segments and 0 bytes. Only TC-GCAP-19 against the real camera
# exposed it.
#
# A static assertion cannot replace TC-GCAP-19, but it does stop this specific regression
# from returning silently, and it names the reason at the point of failure.
# ═══════════════════════════════════════════════════════════════════════════

# Input options that only exist for HTTP/TCP protocols and are invalid for RTSP.
HTTP_ONLY_INPUT_OPTIONS = (
    "-reconnect",
    "-reconnect_streamed",
    "-reconnect_at_eof",
    "-reconnect_on_network_error",
    "-reconnect_delay_max",
    "-multiple_requests",
    "-http_persistent",
)


def test_tc_gcap_20_no_http_only_options_on_rtsp_input(tmp_path):
    cmd = build_capture_command(URL, tmp_path, fps=1, segment_seconds=10, ffmpeg="ffmpeg")
    for opt in HTTP_ONLY_INPUT_OPTIONS:
        assert opt not in cmd, (
            f"{opt} is an HTTP/TCP protocol option and is INVALID for an RTSP input. "
            "ffmpeg 8.0.1 refuses to start with it ('Option reconnect not found'), so the "
            "capture process never runs at all — no frames, no segments, no bytes. It "
            "looks harmless in synthetic tests because lavfi and file inputs accept it. "
            "RTSP reconnection belongs in CaptureSupervisor, not in the input flags."
        )


def test_tc_gcap_21_nostdin_is_always_present(tmp_path):
    """Without -nostdin ffmpeg reads the terminal: it wedged an interactive shell during
    field testing, and under systemd it risks blocking on an stdin that never delivers."""
    capture = build_capture_command(URL, tmp_path, fps=1, segment_seconds=10,
                                    ffmpeg="ffmpeg")
    concat = build_concat_command(["a.ts"], tmp_path / "l.txt", tmp_path / "o.mp4",
                                  ffmpeg="ffmpeg")
    for name, cmd in (("capture", capture), ("concat", concat)):
        assert "-nostdin" in cmd, f"{name} command is missing -nostdin"
        # Must be a global option, i.e. ahead of the input.
        if "-i" in cmd:
            assert cmd.index("-nostdin") < cmd.index("-i"), (
                f"{name}: -nostdin must precede -i to take effect as a global option"
            )


def test_tc_gcap_22_supervisor_restarts_with_backoff_and_reports():
    """The replacement for the flags that never worked: supervise and restart.

    Uses a fake capture so no ffmpeg is needed — what matters is the restart/backoff/report
    behaviour, not the subprocess.
    """
    from guard_worker.capture import CaptureSupervisor

    events: list[tuple[str, dict]] = []
    attempts = {"n": 0}

    class _FakeCapture:
        def __init__(self, frames_to_yield):
            self._frames = frames_to_yield
            self.pid = 4242
            self.stopped = False

        def start(self):
            pass

        def frames(self):
            for f in self._frames:
                yield f

        def stop(self):
            self.stopped = True

        def drain_stderr(self):
            return "camera went away"

    def make():
        attempts["n"] += 1
        # First run yields one frame then "dies"; second yields two; then nothing.
        if attempts["n"] == 1:
            return _FakeCapture([b"f1"])
        if attempts["n"] == 2:
            return _FakeCapture([b"f2", b"f3"])
        return _FakeCapture([])

    sup = CaptureSupervisor(
        make, min_backoff=0.01, max_backoff=0.02, stable_after=999,
        on_event=lambda e, f: events.append((e, f)),
    )

    got = []
    for frame in sup.frames():
        got.append(frame)
        if len(got) >= 3:
            sup.stop()

    assert got == [b"f1", b"f2", b"f3"], "frames must flow across restarts"
    assert sup.restart_count >= 1, "an exited capture must be counted as a restart"
    kinds = [e for e, _ in events]
    assert "capture_started" in kinds
    assert "capture_exited" in kinds, "restarts must be reported, not hidden"
    exited = next(f for e, f in events if e == "capture_exited")
    assert "camera went away" in exited["stderr"], (
        "ffmpeg's own complaint must reach the event so the worker can report WHY"
    )
    assert sup.last_error and "camera" in sup.last_error


def test_tc_gcap_23_supervisor_does_not_retry_a_missing_binary():
    """A missing ffmpeg is a deployment fault, not a transient one — retrying it forever
    would bury the real problem in a restart loop."""
    from guard_worker.capture import CaptureSupervisor, FfmpegNotAvailable

    def make():
        raise FfmpegNotAvailable("ffmpeg not found on PATH")

    sup = CaptureSupervisor(make, min_backoff=0.01)
    with pytest.raises(FfmpegNotAvailable):
        next(iter(sup.frames()))

