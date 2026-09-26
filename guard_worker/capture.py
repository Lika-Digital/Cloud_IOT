"""
Guard capture — ONE persistent ffmpeg per camera, TWO outputs, ONE RTSP session.

Build order step 1. Replaces nothing: `backend/app/services/frame_buffer.py` keeps its
own 10 s poll for berth occupancy and is deliberately untouched, because guard runs only
while armed and berth occupancy must not depend on the guard toggle. See
`docs/guard_b1_addendum_file_ownership.md` §3. Field-verified 2026-09-26: the camera
accepts two simultaneous RTSP sessions.

    ffmpeg -i rtsp://…
        ├─ output 1: -c copy → 10 s mpegts segments on disk (the pre-roll ring)
        └─ output 2: -vf fps=N → MJPEG frames on stdout (the detector's input)

Two field findings from the NUC shape this module, and both are enforced rather than
merely intended:

1. **NO AUDIO, EVER.** The camera streams `pcm_alaw`, which MP4 rejects outright
   ("Could not find tag for codec pcm_alaw") — without `-an` the recording produced
   nothing at all. But dropping audio is a *deliberate policy decision*, not a
   workaround: recording conversations on a pontoon is a separate legal question from
   video, and it must not enter the system by accident. Every command this module builds
   carries `-map 0:v:0 -an -dn -sn` — four independent layers — and
   `test_guard_capture.py` asserts it on every command shape, so it cannot be dropped by
   a future edit.

2. **mpegts for the ring, never MP4.** MP4 keeps its index (`moov`) until the file is
   finalised, so an MP4 that is not finalised is unplayable. mpegts carries no such
   global index — every packet stands alone, so a truncated file still decodes up to the
   truncation point.

   The precise hazard, corrected after the NUC run (TC-GCAP-14): **ffmpeg handles SIGTERM
   gracefully and DOES write a valid MP4 trailer**, so MP4 survives a polite stop. What
   it does not survive is **SIGKILL or power loss** — and both are real here:
   `CameraCapture.stop()` escalates to SIGKILL after a 5 s timeout, systemd escalates the
   same way, and a pontoon loses power. Graceful shutdown therefore cannot be the safety
   mechanism; the container format has to carry the guarantee. ffmpeg's segment muxer also
   closes each completed segment cleanly, so only the segment in flight is ever at risk.

Stream confirmed on site: h264 High, 1920x1080, 25 fps, plus a pcm_alaw audio stream and
a data stream — the latter two discarded.

Stdlib only, deliberately: no numpy, no PIL, no openvino. Frames leave here as JPEG
bytes, so this module is importable and testable anywhere, including the staging venv.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

# Container for the segment ring. NOT MP4 — see the module docstring.
SEGMENT_FORMAT = "mpegts"
SEGMENT_SUFFIX = ".ts"
SEGMENT_PATTERN = "seg_%06d" + SEGMENT_SUFFIX
SEGMENT_GLOB = "seg_*" + SEGMENT_SUFFIX

# JPEG markers, for splitting the MJPEG stream coming back on stdout.
_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"

# A 1080p JPEG at -q:v 3 is a few hundred KB. This bound only exists so a desynchronised
# or garbage stream cannot grow the buffer without limit.
_MAX_FRAME_BYTES = 8 * 1024 * 1024
_READ_CHUNK = 64 * 1024


class FfmpegNotAvailable(RuntimeError):
    """ffmpeg is not on PATH. It is absent from the NUC installer, so this is a real
    deployment condition rather than a theoretical one."""


def _require_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise FfmpegNotAvailable(
            "ffmpeg not found on PATH. Install it (`sudo apt install -y ffmpeg`) — it is "
            "missing from nuc_image/ubuntu-install.sh."
        )
    return exe


# ─── command construction ────────────────────────────────────────────────────
#
# One function builds every ffmpeg command in this module so the audio/data exclusion
# cannot be forgotten in one place while being correct in another.

def _video_only_args() -> list[str]:
    """Select video and nothing else.

    Four layers, all intentional: `-map 0:v:0` admits exactly the first video stream;
    `-an`/`-dn`/`-sn` additionally refuse audio, data and subtitles. Any one of these
    would be enough today; together they survive a future ffmpeg changing its defaults,
    and they make the policy obvious to anyone reading a logged command line.
    """
    return ["-map", "0:v:0", "-an", "-dn", "-sn"]


def build_capture_command(
    stream_url: str,
    segment_dir: str | os.PathLike[str],
    *,
    fps: float,
    segment_seconds: int,
    rtsp_transport: str = "tcp",
    jpeg_quality: int = 3,
    loglevel: str = "warning",
    ffmpeg: str | None = None,
    input_args: list[str] | None = None,
) -> list[str]:
    """The single persistent capture command: one input, two outputs.

    Output 1 is `-c:v copy`, so the ring costs no re-encoding. Output 2 decodes and
    downsamples to `fps`, which is the only real CPU cost here and is why GUARD_FPS
    matters. Both outputs come from one input, hence one RTSP session.
    """
    seg_target = str(Path(segment_dir) / SEGMENT_PATTERN)
    return [
        ffmpeg or _require_ffmpeg(),
        "-hide_banner",
        "-loglevel", loglevel,
        # Input flags. `input_args` overrides the RTSP-specific set so a non-RTSP source
        # (e.g. `-f lavfi` in tests) can be used without rewriting the command by hand.
        *(input_args if input_args is not None else [
            "-rtsp_transport", rtsp_transport,
            # A marina camera drops. Without these ffmpeg exits and we lean on the
            # supervisor; with them short blips are absorbed in-process.
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "10",
            "-fflags", "+genpts",
        ]),
        "-i", str(stream_url),

        # ── output 1: the pre-roll ring, stream-copied, abrupt-stop-safe ──
        *_video_only_args(),
        "-c:v", "copy",
        "-f", "segment",
        "-segment_time", str(int(segment_seconds)),
        "-segment_format", SEGMENT_FORMAT,
        "-reset_timestamps", "1",
        # Monotonic names, NOT -segment_wrap: the ring is pruned by this module so a
        # segment an in-progress event still needs can be pinned against deletion.
        # -segment_wrap would silently overwrite it.
        "-strftime", "0",
        seg_target,

        # ── output 2: frames for the detector, on stdout ──
        *_video_only_args(),
        "-vf", f"fps={fps}",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-q:v", str(int(jpeg_quality)),
        "pipe:1",
    ]


def build_concat_command(
    segment_paths: list[str],
    list_file: str | os.PathLike[str],
    out_path: str | os.PathLike[str],
    *,
    max_seconds: int | None = None,
    loglevel: str = "warning",
    ffmpeg: str | None = None,
) -> list[str]:
    """Assemble an alarm clip from complete segments. Stream copy, so ~0 % CPU.

    Callers must write to a `.part` path and `os.replace()` on success — a killed
    assembly then leaves a stray `.part` for the startup sweep rather than a
    truncated file under a real evidence name. `+faststart` also makes the result
    tolerable to a truncating reader.
    """
    cmd = [
        ffmpeg or _require_ffmpeg(),
        "-hide_banner", "-loglevel", loglevel,
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        *_video_only_args(),
        "-c:v", "copy",
        "-movflags", "+faststart",
    ]
    if max_seconds is not None:
        cmd += ["-t", str(int(max_seconds))]
    cmd += ["-y", str(out_path)]
    return cmd


def write_concat_list(segment_paths: list[str], list_file: str | os.PathLike[str]) -> None:
    """Write an ffmpeg concat demuxer list. Paths are single-quoted with embedded quotes
    escaped, which is the format's own escaping rule."""
    with open(list_file, "w", encoding="utf-8", newline="\n") as fh:
        for p in segment_paths:
            safe = str(p).replace("'", "'\\''")
            fh.write(f"file '{safe}'\n")


# ─── segment ring ────────────────────────────────────────────────────────────

def list_segments(segment_dir: str | os.PathLike[str]) -> list[Path]:
    """Segments oldest-first. Names are zero-padded and monotonic, so lexical order is
    chronological — no stat() call per file."""
    return sorted(Path(segment_dir).glob(SEGMENT_GLOB))


def complete_segments(segment_dir: str | os.PathLike[str]) -> list[Path]:
    """Segments safe to read: all but the newest, which ffmpeg is still writing.

    Using the newest file would put a partially written segment into an alarm clip.
    """
    segs = list_segments(segment_dir)
    return segs[:-1] if segs else []


def prune_segments(
    segment_dir: str | os.PathLike[str],
    keep: int,
    *,
    pinned: frozenset[str] | set[str] = frozenset(),
) -> list[Path]:
    """Keep the newest `keep` segments; delete older ones unless pinned.

    `pinned` holds basenames an in-progress event still needs. Pinning is why this
    module manages the ring instead of using ffmpeg's `-segment_wrap`, which would
    overwrite a segment that an alarm clip had not yet consumed.

    Returns the paths actually deleted.
    """
    segs = list_segments(segment_dir)
    if len(segs) <= keep:
        return []

    deleted: list[Path] = []
    for seg in segs[: len(segs) - keep]:
        if seg.name in pinned:
            logger.debug("Segment %s is pinned by an active event — not deleting", seg.name)
            continue
        try:
            seg.unlink()
            deleted.append(seg)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not delete segment %s: %s", seg, exc)
    return deleted


# ─── MJPEG framing ───────────────────────────────────────────────────────────

def iter_jpeg_frames(
    stream,
    *,
    max_frame_bytes: int = _MAX_FRAME_BYTES,
    read_chunk: int = _READ_CHUNK,
) -> Iterator[bytes]:
    """Split an MJPEG byte stream into individual JPEGs.

    Scanning for SOI/EOI is safe for JPEG: inside entropy-coded data every 0xFF is
    byte-stuffed as 0xFF 0x00, so a bare 0xFFD9 only ever appears as a real end marker.

    Stops when the stream closes. Never raises on malformed input — a desynchronised
    stream drops bytes and resynchronises at the next SOI, because the alternative
    (raising) would take the worker down over a corrupt frame.
    """
    buf = bytearray()
    while True:
        chunk = stream.read(read_chunk)
        if not chunk:
            break
        buf += chunk

        while True:
            soi = buf.find(_SOI)
            if soi < 0:
                # No start marker yet. Keep only a trailing byte in case a 0xFF at the
                # boundary begins the next SOI.
                if len(buf) > 1:
                    del buf[: len(buf) - 1]
                break
            if soi > 0:
                del buf[:soi]          # discard pre-SOI garbage
            eoi = buf.find(_EOI, 2)
            if eoi < 0:
                if len(buf) > max_frame_bytes:
                    logger.warning(
                        "MJPEG frame exceeded %d bytes without an end marker — "
                        "resynchronising", max_frame_bytes,
                    )
                    del buf[:2]        # drop this SOI and look for the next
                    continue
                break                  # incomplete frame, need more bytes
            yield bytes(buf[: eoi + 2])
            del buf[: eoi + 2]


# ─── the process ─────────────────────────────────────────────────────────────

class CameraCapture:
    """Owns the persistent ffmpeg for one camera.

    Lifecycle is explicit: `start()` on arm, `stop()` on disarm or watchdog suspend.
    Nothing here runs while the guard is disarmed — no process, no decoding, no RTSP
    session, which is what makes "guard OFF costs nothing" verifiable with `ps`.
    """

    def __init__(
        self,
        stream_url: str,
        segment_dir: str | os.PathLike[str],
        *,
        fps: float = 1.0,
        segment_seconds: int = 10,
        segment_ring: int = 6,
        rtsp_transport: str = "tcp",
        jpeg_quality: int = 3,
        ffmpeg: str | None = None,
    ):
        self.stream_url = stream_url
        self.segment_dir = Path(segment_dir)
        self.fps = fps
        self.segment_seconds = segment_seconds
        self.segment_ring = segment_ring
        self.rtsp_transport = rtsp_transport
        self.jpeg_quality = jpeg_quality
        # An absolute path from config is preferable to relying on PATH: the unit runs
        # with ProtectSystem=strict, and a service should not depend on the caller's
        # environment for the binary it executes.
        self.ffmpeg = ffmpeg
        self._proc: subprocess.Popen | None = None
        self.started_at: float | None = None

    # ── lifecycle ──

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    def command(self) -> list[str]:
        return build_capture_command(
            self.stream_url, self.segment_dir,
            fps=self.fps, segment_seconds=self.segment_seconds,
            rtsp_transport=self.rtsp_transport, jpeg_quality=self.jpeg_quality,
            ffmpeg=self.ffmpeg,
        )

    def start(self) -> None:
        if self.is_running:
            return
        self.segment_dir.mkdir(parents=True, exist_ok=True)
        cmd = self.command()
        # Log the command with credentials stripped — this goes to journald.
        logger.info("Starting capture: %s", " ".join(_redact(a) for a in cmd))
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.started_at = time.time()

    def stop(self, timeout: float = 5.0) -> int | None:
        """Terminate gracefully, then kill.

        SIGTERM first: ffmpeg handles it gracefully and closes the current segment
        cleanly. The SIGKILL escalation below is why the ring is mpegts rather than MP4 —
        an unfinalised MP4 is unplayable, whereas a truncated mpegts still decodes up to
        the cut. So the common path is clean and the abrupt path is still safe.
        """
        if self._proc is None:
            return None
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning("ffmpeg did not exit in %.1fs — killing pid %s",
                               timeout, self._proc.pid)
                self._proc.kill()
                try:
                    self._proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    logger.error("ffmpeg pid %s would not die", self._proc.pid)
        rc = self._proc.returncode
        for pipe in (self._proc.stdout, self._proc.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except OSError:
                pass
        self._proc = None
        self.started_at = None
        return rc

    # ── frames ──

    def frames(self) -> Iterator[bytes]:
        """Yield JPEG frames as they arrive. Ends when ffmpeg exits."""
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("capture not started")
        yield from iter_jpeg_frames(self._proc.stdout)

    # ── ring ──

    def prune(self, pinned: frozenset[str] | set[str] = frozenset()) -> list[Path]:
        return prune_segments(self.segment_dir, self.segment_ring, pinned=pinned)

    def complete_segments(self) -> list[Path]:
        return complete_segments(self.segment_dir)

    def drain_stderr(self, limit: int = 4000) -> str:
        """Non-blocking-ish read of whatever ffmpeg complained about, for logging on
        unexpected exit. Only safe to call after the process has exited."""
        if self._proc is None or self._proc.stderr is None:
            return ""
        try:
            return self._proc.stderr.read(limit).decode("utf-8", "replace")
        except Exception:
            return ""


def _redact(arg: str) -> str:
    """Hide RTSP credentials in anything that reaches a log."""
    if "://" not in arg:
        return arg
    scheme, rest = arg.split("://", 1)
    host_part = rest.split("/")[0]
    if "@" in host_part and ":" in host_part.split("@")[0]:
        user = host_part.split(":", 1)[0]
        return f"{scheme}://{user}:***@{rest.split('@', 1)[1]}"
    return arg
