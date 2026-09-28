"""
Guard recording — assemble alarm clips from the segment ring, and retain them.

Build order step 3. The worker OWNS `/var/lib/marina-guard/`: it writes recordings and
annotated frames, and it performs retention deletion. The backend only reads, and is the
only writer of the database. See `docs/guard_b1_addendum_file_ownership.md`.

Four properties this module exists to guarantee:

1. **An alarm clip is assembled from COMPLETE segments only.** The newest segment is still
   open in ffmpeg, so splicing it would put a partial file into evidence.
   `capture.complete_segments()` excludes it.

2. **Segments an in-progress clip needs are PINNED against pruning.** Pre-roll plus a 60 s
   cap can exceed the ring's own span, so without pinning the ring would overwrite the
   pre-roll of an alarm still being assembled. This is why the ring is self-managed rather
   than `-segment_wrap`.

3. **A killed assembly never leaves a truncated file under a real evidence name.** Output
   goes to `<name>.part` and is `os.replace()`d on success — atomic within a filesystem. A
   crash leaves a `.part` for the startup sweep, never a half clip that looks complete.

4. **Retention degrades COLLECTION, never EVIDENCE.** Eviction touches uncertain frames
   only, oldest first. If uncertain frames run out and we are still over the cap, alarm
   frames are *not* touched: the worker stops saving new uncertain frames and raises
   `frames_cap_exhausted`. Labelled recordings resist `max_days` because they are the
   evidence behind a label, and `max_gb` evicts them last.

Stdlib only, like `capture.py`: no numpy, no PIL, no openvino. Frames arrive as bytes.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .capture import (
    SEGMENT_SUFFIX,
    build_concat_command,
    complete_segments,
    write_concat_list,
)

logger = logging.getLogger(__name__)

RECORDING_SUFFIX = ".mp4"
PART_SUFFIX = ".part"
FRAME_SUFFIX = ".jpg"

# Filename is the alarm timestamp, UTC, filesystem-safe: 2026-09-27T14-32-07Z.mp4
# Colons are illegal on some filesystems and awkward everywhere, so they become hyphens.
_TS_FORMAT = "%Y-%m-%dT%H-%M-%SZ"
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})Z$")


def timestamp_name(when: datetime) -> str:
    """Format an alarm time as a filesystem-safe UTC stem.

    Naive datetimes are treated as UTC, matching the storage convention used throughout
    this codebase (`app/time_utils.py`). An aware datetime is converted, so a caller
    passing local time cannot silently mislabel evidence.
    """
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc).replace(tzinfo=None)
    return when.strftime(_TS_FORMAT)


def parse_timestamp_name(stem: str) -> datetime | None:
    """Inverse of `timestamp_name`. None if the stem is not one of ours.

    Used by retention so age comes from the NAME rather than from mtime: a file copied,
    restored from backup or touched by a filesystem operation would otherwise look newer
    than the event it records, and could outlive its retention window.
    """
    m = _TS_RE.match(stem)
    if not m:
        return None
    try:
        return datetime.strptime(stem, _TS_FORMAT)
    except ValueError:
        return None


@dataclass
class RecordingConfig:
    storage_path: Path
    record_seconds: int = 60          # hard cap, per the spec
    segment_seconds: int = 10
    preroll_seconds: int = 6          # ~3 segments; pre-roll comes from the ring, not RAM
    max_days: int = 14
    max_gb: float = 20.0
    max_frames_gb: float = 2.0
    frame_min_interval_s: float = 10.0
    ffmpeg: str | None = None

    def camera_dir(self, camera_id: int) -> Path:
        return Path(self.storage_path) / str(camera_id)

    def frames_dir(self, camera_id: int) -> Path:
        return self.camera_dir(camera_id) / "frames"


@dataclass
class AssembledClip:
    path: Path
    started_at: datetime
    duration_s: float
    file_size: int
    segment_names: list[str]
    truncated: bool = False           # True when the 60 s cap cut it short


@dataclass
class RetentionReport:
    """What retention did, so the backend can persist it and the dashboard can show it.

    Every deletion is reported — never silent — because the operator needs to know when
    training data is being lost.
    """
    deleted_recordings: list[dict] = field(default_factory=list)
    deleted_frames: list[dict] = field(default_factory=list)
    frames_gb_used: float = 0.0
    recordings_gb_used: float = 0.0
    frames_evicting: bool = False
    frames_cap_exhausted: bool = False
    labelled_evicted: int = 0

    @property
    def anything_deleted(self) -> bool:
        return bool(self.deleted_recordings or self.deleted_frames)


# ─── assembly ────────────────────────────────────────────────────────────────

class ClipAssembler:
    """Turns an alarm into a clip, from segments that already exist on disk.

    Pinning is the subtle part. `pinned_segments` is read by the capture ring's pruner, so
    while an assembly is outstanding those files cannot be deleted underneath it. The set is
    cleared in a `finally`, so a failed assembly does not pin the ring forever — that would
    silently stop the ring from reclaiming space.
    """

    def __init__(self, cfg: RecordingConfig, segment_dir: Path | str):
        self.cfg = cfg
        self.segment_dir = Path(segment_dir)
        self._pinned: set[str] = set()

    @property
    def pinned_segments(self) -> frozenset[str]:
        """Basenames the ring must not delete. Passed to `CameraCapture.prune()`."""
        return frozenset(self._pinned)

    def select_segments(self, alarm_at: float, now: float | None = None) -> list[Path]:
        """Complete segments covering pre-roll through the cap around `alarm_at`.

        Selection is by file mtime, which for a rolled segment is when ffmpeg closed it —
        i.e. approximately the END of the period it covers. So a segment is relevant when
        its close time falls in [alarm - preroll - segment_seconds, alarm + cap].
        """
        now = now if now is not None else time.time()
        start = alarm_at - self.cfg.preroll_seconds - self.cfg.segment_seconds
        end = alarm_at + self.cfg.record_seconds

        chosen: list[Path] = []
        for seg in complete_segments(self.segment_dir):
            try:
                closed_at = seg.stat().st_mtime
            except OSError:
                continue
            if start <= closed_at <= end:
                chosen.append(seg)
        return chosen

    def pin(self, segments: list[Path]) -> None:
        self._pinned.update(s.name for s in segments)

    def unpin_all(self) -> None:
        self._pinned.clear()

    def assemble(
        self,
        camera_id: int,
        alarm_at: datetime,
        segments: list[Path],
        *,
        work_dir: Path | None = None,
    ) -> AssembledClip | None:
        """Concatenate `segments` into one capped clip. Returns None on failure.

        Never raises for an ffmpeg failure: losing a clip must not take the worker down,
        because the alarm itself and its annotated frame are already recorded. The event row
        simply carries `video_skipped`.
        """
        if not segments:
            logger.warning("Guard: no complete segments to assemble for alarm at %s",
                           alarm_at)
            return None

        out_dir = self.cfg.camera_dir(camera_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = timestamp_name(alarm_at)
        final = out_dir / f"{stem}{RECORDING_SUFFIX}"
        part = out_dir / f"{stem}{RECORDING_SUFFIX}{PART_SUFFIX}"
        list_file = (work_dir or out_dir) / f".{stem}.concat.txt"

        self.pin(segments)
        try:
            write_concat_list([str(s) for s in segments], list_file)
            cmd = build_concat_command(
                [str(s) for s in segments], list_file, part,
                max_seconds=self.cfg.record_seconds, ffmpeg=self.cfg.ffmpeg,
            )
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=self.cfg.record_seconds + 120)
            if proc.returncode != 0 or not part.exists() or part.stat().st_size == 0:
                logger.warning(
                    "Guard: clip assembly failed for %s (rc=%s): %s",
                    stem, proc.returncode, (proc.stderr or "")[-500:],
                )
                part.unlink(missing_ok=True)
                return None

            size = part.stat().st_size
            # Atomic within the filesystem: either the full clip appears under its real
            # name, or nothing does. A crash mid-assembly leaves only the .part.
            os.replace(part, final)

            duration = _probe_duration(final, self.cfg.ffmpeg)
            if duration is None:
                # Fall back to the nominal span rather than reporting nothing; the file is
                # present and playable, only its measured length is unknown.
                duration = float(min(
                    len(segments) * self.cfg.segment_seconds, self.cfg.record_seconds,
                ))
            logger.info("Guard: assembled %s (%d bytes, %.1fs, %d segment(s))",
                        final.name, size, duration, len(segments))
            return AssembledClip(
                path=final,
                started_at=alarm_at,
                duration_s=duration,
                file_size=size,
                segment_names=[s.name for s in segments],
                truncated=duration >= self.cfg.record_seconds - 0.5,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Guard: clip assembly timed out for %s", stem)
            part.unlink(missing_ok=True)
            return None
        except Exception as exc:
            logger.warning("Guard: clip assembly error for %s: %s", stem, exc)
            part.unlink(missing_ok=True)
            return None
        finally:
            # Always release, or a failed assembly would pin the ring permanently and stop
            # it reclaiming space.
            self.unpin_all()
            try:
                Path(list_file).unlink(missing_ok=True)
            except OSError:
                pass


def _probe_duration(path: Path, ffmpeg: str | None = None) -> float | None:
    from .capture import resolve_ffprobe

    ffprobe = resolve_ffprobe(ffmpeg)
    if ffprobe is None:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        val = out.stdout.strip()
        return float(val) if val and val.replace(".", "", 1).isdigit() else None
    except Exception:
        return None


def sweep_orphan_parts(cfg: RecordingConfig, camera_id: int) -> list[Path]:
    """Delete leftover `.part` files at worker start.

    These are assemblies interrupted by a kill. They are never valid evidence, and leaving
    them would slowly consume the storage budget for files nothing references.
    """
    out_dir = cfg.camera_dir(camera_id)
    if not out_dir.is_dir():
        return []
    removed = []
    for part in out_dir.glob(f"*{RECORDING_SUFFIX}{PART_SUFFIX}"):
        try:
            part.unlink()
            removed.append(part)
            logger.info("Guard: removed orphaned partial clip %s", part.name)
        except OSError as exc:
            logger.warning("Guard: could not remove %s: %s", part, exc)
    return removed


# ─── retention ───────────────────────────────────────────────────────────────

def _dir_bytes(path: Path, suffix: str) -> int:
    if not path.is_dir():
        return 0
    total = 0
    for p in path.glob(f"*{suffix}"):
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def apply_retention(
    cfg: RecordingConfig,
    camera_id: int,
    *,
    labelled: set[str] | frozenset[str] = frozenset(),
    alarm_frames: set[str] | frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> RetentionReport:
    """Enforce max_days and max_gb on recordings, and max_frames_gb on frames.

    Args:
        labelled: recording filenames whose event carries a correct/false-alarm label.
            These resist `max_days` — they are the evidence behind a label, the most
            valuable video on the box. `max_gb` can still evict them because disk safety
            has to win, but they go LAST and are counted separately so the loss is visible.
        alarm_frames: frame filenames from the alarm band. **Never evicted.** Only
            uncertain frames are; if those run out while still over cap, the worker stops
            SAVING new uncertain frames instead. Degradation lands on collection, never on
            evidence.

    The caller (the worker) publishes this report so the backend can persist it and the
    dashboard can show it. Nothing here is silent.
    """
    now = now or datetime.utcnow()
    report = RetentionReport()
    rec_dir = cfg.camera_dir(camera_id)
    frames_dir = cfg.frames_dir(camera_id)

    # ── recordings: max_days, labelled exempt ──
    recordings = sorted(rec_dir.glob(f"*{RECORDING_SUFFIX}")) if rec_dir.is_dir() else []
    cutoff_days = cfg.max_days
    survivors: list[Path] = []
    for rec in recordings:
        age_days = None
        stamped = parse_timestamp_name(rec.stem)
        if stamped is not None:
            age_days = (now - stamped).total_seconds() / 86400.0
        if age_days is not None and age_days > cutoff_days:
            if rec.name in labelled:
                # Labelled recordings outlive max_days: a label without its evidence is
                # much less useful, and these are the Phase 2 ground truth.
                survivors.append(rec)
                continue
            _delete(rec, "max_days", report.deleted_recordings)
            continue
        survivors.append(rec)

    # ── recordings: max_gb, unlabelled first, then labelled oldest-first ──
    budget = int(cfg.max_gb * 1024 ** 3)
    total = sum(_size(p) for p in survivors)
    if total > budget:
        unlabelled = [p for p in survivors if p.name not in labelled]
        labelled_list = [p for p in survivors if p.name in labelled]
        # Oldest first within each group, by NAME not mtime — see parse_timestamp_name.
        order = sorted(unlabelled, key=lambda p: p.stem) + \
            sorted(labelled_list, key=lambda p: p.stem)
        for rec in order:
            if total <= budget:
                break
            size = _size(rec)
            was_labelled = rec.name in labelled
            if _delete(rec, "max_gb", report.deleted_recordings, labelled=was_labelled):
                total -= size
                if was_labelled:
                    report.labelled_evicted += 1

    report.recordings_gb_used = _dir_bytes(rec_dir, RECORDING_SUFFIX) / 1024 ** 3

    # ── frames: uncertain only, oldest first; alarm frames are untouchable ──
    frame_budget = int(cfg.max_frames_gb * 1024 ** 3)
    frame_total = _dir_bytes(frames_dir, FRAME_SUFFIX)
    if frame_total > frame_budget and frames_dir.is_dir():
        report.frames_evicting = True
        uncertain = sorted(
            (p for p in frames_dir.glob(f"*{FRAME_SUFFIX}") if p.name not in alarm_frames),
            key=lambda p: p.stem,
        )
        for frame in uncertain:
            if frame_total <= frame_budget:
                break
            size = _size(frame)
            if _delete(frame, "max_frames_gb", report.deleted_frames):
                frame_total -= size
        if frame_total > frame_budget:
            # Out of uncertain frames and still over budget. Alarm frames are NOT deleted:
            # stop collecting instead. This is the point of the whole scheme.
            report.frames_cap_exhausted = True
            logger.warning(
                "Guard: frame cap exhausted for camera %s — %d bytes of ALARM frames "
                "exceed the %.1f GB budget on their own. Alarm frames are NOT deleted; "
                "new uncertain frames will not be saved until space is available.",
                camera_id, frame_total, cfg.max_frames_gb,
            )

    report.frames_gb_used = _dir_bytes(frames_dir, FRAME_SUFFIX) / 1024 ** 3
    return report


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _delete(path: Path, reason: str, into: list[dict], *, labelled: bool = False) -> bool:
    """Delete one file and record it. Every deletion is logged — never silent."""
    size = _size(path)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("Guard retention: could not delete %s: %s", path, exc)
        return False
    into.append({
        "file_path": str(path), "file_name": path.name,
        "reason": reason, "bytes": size, "labelled": labelled,
    })
    logger.info("Guard retention: deleted %s (%s, %d bytes%s)",
                path.name, reason, size, ", LABELLED" if labelled else "")
    return True


# ─── frame saving ────────────────────────────────────────────────────────────

class FrameWriter:
    """Writes annotated frames for uncertain and alarm detections, under a rate limit.

    Logging every detection is cheap (~12 k rows/day worst case, a couple of MB). Saving a
    frame for each is not: ~50 KB x 12 k is ~600 MB/day. So frames are rate-limited to one
    per `frame_min_interval_s`, EXCEPT that an alarm frame is always written — an alarm is
    the thing the whole system exists to record, and it is far rarer than the rate limit.
    """

    def __init__(self, cfg: RecordingConfig, camera_id: int):
        self.cfg = cfg
        self.camera_id = camera_id
        self._last_uncertain_at: float = 0.0
        self.alarm_frame_names: set[str] = set()

    def should_save(self, band: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        if band == "alarm":
            return True                     # never rate-limited, never evicted
        if band != "uncertain":
            return False                    # `none` writes nothing at all
        return (now - self._last_uncertain_at) >= self.cfg.frame_min_interval_s

    def save(self, jpeg: bytes, band: str, when: datetime,
             now: float | None = None) -> Path | None:
        """Write the frame. Returns the path, or None if the rate limit declined it."""
        if not self.should_save(band, now):
            return None
        frames_dir = self.cfg.frames_dir(self.camera_id)
        frames_dir.mkdir(parents=True, exist_ok=True)
        # Band is in the name so retention can tell evidence from collection without a DB
        # lookup — the worker must be able to decide this on its own.
        name = f"{timestamp_name(when)}_{band}{FRAME_SUFFIX}"
        path = frames_dir / name
        try:
            path.write_bytes(jpeg)
        except OSError as exc:
            logger.warning("Guard: could not write frame %s: %s", name, exc)
            return None
        if band == "alarm":
            self.alarm_frame_names.add(name)
        else:
            self._last_uncertain_at = now if now is not None else time.time()
        return path
