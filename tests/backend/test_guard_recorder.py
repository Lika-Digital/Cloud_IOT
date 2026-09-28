"""
Guard recording assembly + retention (step 3, v3.42)
===================================================

The worker owns `/var/lib/marina-guard/`; the backend only reads. These tests pin the four
properties the module exists to guarantee:

  * an alarm clip is assembled from COMPLETE segments only (the newest is still being
    written by ffmpeg)
  * segments an in-progress clip needs are PINNED against the ring's pruner
  * a killed assembly never leaves a truncated file under a real evidence name
  * retention degrades COLLECTION, never EVIDENCE

  TC-GREC-01  filename is the alarm timestamp, UTC, filesystem-safe
  TC-GREC-02  naive is treated as UTC; aware is converted (no mislabelled evidence)
  TC-GREC-03  name round-trips, and junk is rejected
  TC-GREC-04  segment selection spans pre-roll through the cap
  TC-GREC-05  selection NEVER includes the in-progress segment
  TC-GREC-06  segments are pinned during assembly and released afterwards
  TC-GREC-07  a FAILED assembly still releases the pin (or the ring never reclaims)
  TC-GREC-08  assembly writes .part then renames — no truncated evidence name
  TC-GREC-09  a failed assembly leaves no .part behind
  TC-GREC-10  no segments -> None, and the worker keeps running
  TC-GREC-11  orphaned .part files are swept at startup
  TC-GREC-12  retention: max_days deletes old recordings
  TC-GREC-13  retention: LABELLED recordings resist max_days
  TC-GREC-14  retention: max_gb evicts unlabelled first, labelled last and counted
  TC-GREC-15  retention: age comes from the NAME, not mtime
  TC-GREC-16  frames: uncertain evicted oldest-first, ALARM frames never
  TC-GREC-17  frames: cap exhausted -> stop collecting, do not delete alarm frames
  TC-GREC-18  every deletion is reported, never silent
  TC-GREC-19  frame writer rate-limits uncertain but NEVER an alarm frame
  TC-GREC-20  [ffmpeg] a real clip assembles from real segments and plays
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from guard_worker.recorder import (
    FRAME_SUFFIX,
    PART_SUFFIX,
    RECORDING_SUFFIX,
    ClipAssembler,
    FrameWriter,
    RecordingConfig,
    apply_retention,
    parse_timestamp_name,
    sweep_orphan_parts,
    timestamp_name,
)
from guard_worker.capture import resolve_ffmpeg, resolve_ffprobe

HAVE_FFMPEG = resolve_ffmpeg() is not None
# The binary every test uses, whether it only builds a command string or actually runs
# one. No test asserts on argv[0], so using the resolved path throughout costs nothing
# and stops the executing tests from failing on a box where ffmpeg is not on PATH.
FFMPEG = resolve_ffmpeg() or "ffmpeg"
FFPROBE = resolve_ffprobe(FFMPEG) or "ffprobe"
needs_ffmpeg = pytest.mark.skipif(
    not HAVE_FFMPEG, reason="no ffmpeg (set GUARD_FFMPEG or put it on PATH)")

CAM = 1
ALARM_AT = datetime(2026, 9, 27, 14, 32, 7)


def _cfg(tmp_path: Path, **kw) -> RecordingConfig:
    defaults = dict(storage_path=tmp_path / "recordings", segment_seconds=2,
                    preroll_seconds=4, record_seconds=60, ffmpeg=FFMPEG)
    defaults.update(kw)
    return RecordingConfig(**defaults)


def _segments(seg_dir: Path, mtimes: list[float], size: int = 64) -> list[Path]:
    """Create segments with explicit mtimes (their ffmpeg close times)."""
    seg_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for i, mt in enumerate(mtimes):
        p = seg_dir / f"seg_{i:06d}.ts"
        p.write_bytes(b"x" * size)
        os.utime(p, (mt, mt))
        made.append(p)
    return made


def _recording(cfg: RecordingConfig, when: datetime, size: int = 1024) -> Path:
    d = cfg.camera_dir(CAM)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{timestamp_name(when)}{RECORDING_SUFFIX}"
    p.write_bytes(b"v" * size)
    return p


def _frame(cfg: RecordingConfig, when: datetime, band: str, size: int = 512) -> Path:
    d = cfg.frames_dir(CAM)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{timestamp_name(when)}_{band}{FRAME_SUFFIX}"
    p.write_bytes(b"f" * size)
    return p


# ═══════════════════════════════════════════════════════════════════════════
# Naming
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_grec_01_filename_is_the_alarm_timestamp():
    assert timestamp_name(ALARM_AT) == "2026-09-27T14-32-07Z"
    # No colons: illegal on some filesystems, awkward everywhere.
    assert ":" not in timestamp_name(ALARM_AT)


def test_tc_grec_02_naive_is_utc_and_aware_is_converted():
    """A caller passing local time must not silently mislabel evidence."""
    assert timestamp_name(ALARM_AT) == "2026-09-27T14-32-07Z"
    aware = datetime(2026, 9, 27, 16, 32, 7, tzinfo=timezone(timedelta(hours=2)))
    assert timestamp_name(aware) == "2026-09-27T14-32-07Z", "CEST must convert to UTC"


def test_tc_grec_03_name_roundtrips_and_rejects_junk():
    assert parse_timestamp_name(timestamp_name(ALARM_AT)) == ALARM_AT
    for junk in ("", "not-a-stamp", "2026-09-27", "2026-09-27T14:32:07Z",
                 "2026-13-45T99-99-99Z"):
        assert parse_timestamp_name(junk) is None, junk


# ═══════════════════════════════════════════════════════════════════════════
# Segment selection + pinning
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_grec_04_selection_spans_preroll_through_cap(tmp_path):
    cfg = _cfg(tmp_path, segment_seconds=2, preroll_seconds=4, record_seconds=10)
    seg_dir = tmp_path / "segments"
    alarm = 1_000.0
    # Closes at: way before / just before (pre-roll) / at / after / way after, + in-progress
    _segments(seg_dir, [900.0, 997.0, 1_000.0, 1_005.0, 1_200.0, 1_201.0])

    chosen = ClipAssembler(cfg, seg_dir).select_segments(alarm)
    names = [p.name for p in chosen]
    # window = [1000 - 4 - 2, 1000 + 10] = [994, 1010]
    assert names == ["seg_000001.ts", "seg_000002.ts", "seg_000003.ts"]
    assert "seg_000000.ts" not in names, "900 is before the pre-roll window"
    assert "seg_000004.ts" not in names, "1200 is past the cap"


def test_tc_grec_05_selection_never_includes_the_in_progress_segment(tmp_path):
    """The newest file is still open in ffmpeg; splicing it would put a partial file into
    evidence."""
    cfg = _cfg(tmp_path)
    seg_dir = tmp_path / "segments"
    _segments(seg_dir, [1_000.0, 1_001.0, 1_002.0])
    chosen = ClipAssembler(cfg, seg_dir).select_segments(1_002.0)
    assert "seg_000002.ts" not in [p.name for p in chosen], (
        "the newest segment is in progress and must be excluded"
    )
    assert len(chosen) == 2


def test_tc_grec_06_segments_are_pinned_then_released(tmp_path):
    """Pre-roll plus a 60 s cap can exceed the ring's own span, so without pinning the
    pruner would delete the pre-roll of an alarm still being assembled."""
    cfg = _cfg(tmp_path)
    seg_dir = tmp_path / "segments"
    segs = _segments(seg_dir, [1_000.0, 1_001.0, 1_002.0])
    asm = ClipAssembler(cfg, seg_dir)

    assert asm.pinned_segments == frozenset()
    asm.pin(segs[:2])
    assert asm.pinned_segments == frozenset({"seg_000000.ts", "seg_000001.ts"})

    # And the ring's pruner honours it (verified directly against the real pruner).
    from guard_worker.capture import prune_segments
    deleted = prune_segments(seg_dir, keep=0, pinned=asm.pinned_segments)
    assert {p.name for p in deleted} == {"seg_000002.ts"}, "pinned files must survive"

    asm.unpin_all()
    assert asm.pinned_segments == frozenset()


def test_tc_grec_07_failed_assembly_still_releases_the_pin(tmp_path):
    """A pin that leaks would stop the ring reclaiming space forever — a slow disk-fill
    caused by an error path, which is the worst kind."""
    cfg = _cfg(tmp_path, ffmpeg="/nonexistent/ffmpeg")
    seg_dir = tmp_path / "segments"
    segs = _segments(seg_dir, [1_000.0, 1_001.0])
    asm = ClipAssembler(cfg, seg_dir)

    result = asm.assemble(CAM, ALARM_AT, segs)
    assert result is None, "a missing ffmpeg must fail the assembly"
    assert asm.pinned_segments == frozenset(), "the pin MUST be released on failure"


def test_tc_grec_08_and_09_no_truncated_evidence_name(tmp_path):
    """Output goes to .part and is renamed on success, so a crash never leaves a half clip
    under a name that looks complete. A failure leaves no .part either."""
    cfg = _cfg(tmp_path, ffmpeg="/nonexistent/ffmpeg")
    seg_dir = tmp_path / "segments"
    segs = _segments(seg_dir, [1_000.0, 1_001.0])

    assert ClipAssembler(cfg, seg_dir).assemble(CAM, ALARM_AT, segs) is None
    out_dir = cfg.camera_dir(CAM)
    if out_dir.exists():
        assert list(out_dir.glob(f"*{RECORDING_SUFFIX}")) == [], "no evidence-named file"
        assert list(out_dir.glob(f"*{PART_SUFFIX}")) == [], "no .part left behind"
        assert list(out_dir.glob("*.concat.txt")) == [], "concat list cleaned up"


def test_tc_grec_10_no_segments_returns_none(tmp_path):
    cfg = _cfg(tmp_path)
    seg_dir = tmp_path / "segments"
    seg_dir.mkdir()
    assert ClipAssembler(cfg, seg_dir).assemble(CAM, ALARM_AT, []) is None


def test_tc_grec_11_orphan_parts_swept_at_startup(tmp_path):
    """A .part is an assembly interrupted by a kill: never valid evidence, and leaving it
    would consume the storage budget for a file nothing references."""
    cfg = _cfg(tmp_path)
    d = cfg.camera_dir(CAM)
    d.mkdir(parents=True)
    orphan = d / f"2026-09-27T10-00-00Z{RECORDING_SUFFIX}{PART_SUFFIX}"
    orphan.write_bytes(b"partial")
    keeper = _recording(cfg, datetime(2026, 9, 27, 11, 0, 0))

    removed = sweep_orphan_parts(cfg, CAM)
    assert [p.name for p in removed] == [orphan.name]
    assert not orphan.exists()
    assert keeper.exists(), "real recordings must not be touched"


# ═══════════════════════════════════════════════════════════════════════════
# Retention
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_grec_12_max_days_deletes_old_recordings(tmp_path):
    cfg = _cfg(tmp_path, max_days=7, max_gb=100.0)
    now = datetime(2026, 9, 27, 12, 0, 0)
    old = _recording(cfg, now - timedelta(days=10))
    fresh = _recording(cfg, now - timedelta(days=2))

    report = apply_retention(cfg, CAM, now=now)
    assert not old.exists()
    assert fresh.exists()
    assert [d["file_name"] for d in report.deleted_recordings] == [old.name]
    assert report.deleted_recordings[0]["reason"] == "max_days"


def test_tc_grec_13_labelled_recordings_resist_max_days(tmp_path):
    """A label without its evidence is much less useful, and these are the Phase 2 ground
    truth — so max_days skips them."""
    cfg = _cfg(tmp_path, max_days=7, max_gb=100.0)
    now = datetime(2026, 9, 27, 12, 0, 0)
    labelled = _recording(cfg, now - timedelta(days=30))
    unlabelled = _recording(cfg, now - timedelta(days=30, hours=1))

    report = apply_retention(cfg, CAM, labelled={labelled.name}, now=now)
    assert labelled.exists(), "a labelled recording must outlive max_days"
    assert not unlabelled.exists()
    assert report.labelled_evicted == 0


def test_tc_grec_14_max_gb_evicts_unlabelled_first_labelled_last(tmp_path):
    """Disk safety wins over data collection, but labelled files go last and are counted so
    the loss is visible."""
    cfg = _cfg(tmp_path, max_days=3650, max_gb=3_072 / 1024 ** 3)   # 3 KB budget
    now = datetime(2026, 9, 27, 12, 0, 0)
    a = _recording(cfg, now - timedelta(hours=5), size=1024)   # oldest unlabelled
    b = _recording(cfg, now - timedelta(hours=4), size=1024)
    lab = _recording(cfg, now - timedelta(hours=6), size=1024)  # oldest overall, labelled
    d = _recording(cfg, now - timedelta(hours=1), size=1024)

    report = apply_retention(cfg, CAM, labelled={lab.name}, now=now)

    # Budget 3 KB, 4 KB present -> exactly one eviction, and it must be the oldest
    # UNLABELLED, not the older labelled one.
    assert len(report.deleted_recordings) == 1
    assert report.deleted_recordings[0]["file_name"] == a.name
    assert report.deleted_recordings[0]["reason"] == "max_gb"
    assert lab.exists(), "labelled must survive while any unlabelled remains"
    assert b.exists() and d.exists()
    assert report.labelled_evicted == 0


def test_tc_grec_14b_labelled_evicted_only_as_last_resort_and_counted(tmp_path):
    cfg = _cfg(tmp_path, max_days=3650, max_gb=1_024 / 1024 ** 3)   # 1 KB budget
    now = datetime(2026, 9, 27, 12, 0, 0)
    lab_old = _recording(cfg, now - timedelta(hours=9), size=1024)
    lab_new = _recording(cfg, now - timedelta(hours=1), size=1024)

    report = apply_retention(cfg, CAM,
                             labelled={lab_old.name, lab_new.name}, now=now)
    assert report.labelled_evicted == 1, "the loss of labelled data must be counted"
    assert not lab_old.exists(), "oldest labelled goes first when only labelled remain"
    assert lab_new.exists()
    assert report.deleted_recordings[0]["labelled"] is True


def test_tc_grec_15_age_comes_from_the_name_not_mtime(tmp_path):
    """A file restored from backup or touched by a filesystem operation would look newer
    than the event it records, and could outlive its retention window."""
    cfg = _cfg(tmp_path, max_days=7, max_gb=100.0)
    now = datetime(2026, 9, 27, 12, 0, 0)
    old = _recording(cfg, now - timedelta(days=30))
    os.utime(old, (time.time(), time.time()))       # mtime says "just now"

    apply_retention(cfg, CAM, now=now)
    assert not old.exists(), "age must come from the timestamp in the NAME"


def test_tc_grec_16_frames_uncertain_evicted_alarm_never(tmp_path):
    cfg = _cfg(tmp_path, max_frames_gb=1_024 / 1024 ** 3)   # 1 KB budget
    now = datetime(2026, 9, 27, 12, 0, 0)
    u_old = _frame(cfg, now - timedelta(minutes=30), "uncertain", size=512)
    u_new = _frame(cfg, now - timedelta(minutes=5), "uncertain", size=512)
    alarm = _frame(cfg, now - timedelta(minutes=40), "alarm", size=512)

    report = apply_retention(cfg, CAM, alarm_frames={alarm.name}, now=now)

    assert alarm.exists(), "an ALARM frame must NEVER be evicted"
    assert not u_old.exists(), "oldest uncertain goes first"
    assert u_new.exists()
    assert report.frames_evicting is True
    assert report.frames_cap_exhausted is False
    assert [d["file_name"] for d in report.deleted_frames] == [u_old.name]


def test_tc_grec_17_cap_exhausted_stops_collecting_not_deleting(tmp_path):
    """The whole point: when only alarm frames remain and we are still over cap, the worker
    stops SAVING new uncertain frames rather than destroying evidence."""
    cfg = _cfg(tmp_path, max_frames_gb=512 / 1024 ** 3)     # 512 B budget
    now = datetime(2026, 9, 27, 12, 0, 0)
    a1 = _frame(cfg, now - timedelta(minutes=40), "alarm", size=512)
    a2 = _frame(cfg, now - timedelta(minutes=20), "alarm", size=512)

    report = apply_retention(cfg, CAM, alarm_frames={a1.name, a2.name}, now=now)

    assert a1.exists() and a2.exists(), "alarm frames survive even over budget"
    assert report.frames_cap_exhausted is True
    assert report.deleted_frames == [], "nothing was deleted, because only alarms remained"


def test_tc_grec_18_every_deletion_is_reported(tmp_path):
    """Never silent — the operator has to know when training data is being lost."""
    cfg = _cfg(tmp_path, max_days=1, max_gb=100.0)
    now = datetime(2026, 9, 27, 12, 0, 0)
    for h in (100, 200, 300):
        _recording(cfg, now - timedelta(hours=h), size=256)

    report = apply_retention(cfg, CAM, now=now)
    assert len(report.deleted_recordings) == 3
    for entry in report.deleted_recordings:
        assert set(entry) == {"file_path", "file_name", "reason", "bytes", "labelled"}
        assert entry["bytes"] == 256
        assert entry["reason"] == "max_days"
    assert report.anything_deleted is True
    assert apply_retention(cfg, CAM, now=now).anything_deleted is False


def test_tc_grec_19_frame_writer_rate_limits_uncertain_not_alarm(tmp_path):
    """Saving every uncertain frame would be ~600 MB/day. An alarm frame is never
    rate-limited: it is the thing the system exists to record, and far rarer."""
    cfg = _cfg(tmp_path, frame_min_interval_s=10.0)
    w = FrameWriter(cfg, CAM)
    when = datetime(2026, 9, 27, 12, 0, 0)

    assert w.should_save("none") is False, "`none` writes nothing at all"

    assert w.save(b"j1", "uncertain", when, now=1_000.0) is not None
    assert w.save(b"j2", "uncertain", when + timedelta(seconds=2), now=1_002.0) is None, \
        "inside the interval, declined"
    assert w.save(b"j3", "uncertain", when + timedelta(seconds=15), now=1_015.0) is not None

    # Alarm frames ignore the limit entirely, back to back.
    p1 = w.save(b"a1", "alarm", when + timedelta(seconds=16), now=1_016.0)
    p2 = w.save(b"a2", "alarm", when + timedelta(seconds=17), now=1_017.0)
    assert p1 is not None and p2 is not None
    assert w.alarm_frame_names == {p1.name, p2.name}, (
        "alarm frame names must be tracked so retention can protect them"
    )
    assert "_alarm" in p1.name and p1.suffix == FRAME_SUFFIX


# ═══════════════════════════════════════════════════════════════════════════
# TC-GREC-20 — real ffmpeg end to end
# ═══════════════════════════════════════════════════════════════════════════

@needs_ffmpeg
def test_tc_grec_20_real_clip_assembles_and_plays(tmp_path):
    """Build real mpegts segments, assemble them, and confirm the clip decodes.

    Covers the whole step-3 path with the production concat command: stream copy, audio
    refused, 60 s cap, .part then rename.
    """
    seg_dir = tmp_path / "segments"
    seg_dir.mkdir()
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25", "-t", "9",
         "-map", "0:v:0", "-an", "-dn", "-sn",
         "-c:v", "libx264", "-preset", "ultrafast", "-g", "25",
         "-f", "segment", "-segment_time", "3", "-segment_format", "mpegts",
         str(seg_dir / "seg_%06d.ts")],
        check=True, capture_output=True, timeout=180,
    )
    segs = sorted(seg_dir.glob("*.ts"))
    assert len(segs) >= 3, f"expected several segments, got {len(segs)}"

    cfg = _cfg(tmp_path, segment_seconds=3, record_seconds=60, ffmpeg=FFMPEG)
    asm = ClipAssembler(cfg, seg_dir)
    # Assemble all but the last (treated as in progress), mirroring production.
    clip = asm.assemble(CAM, ALARM_AT, segs[:-1])

    assert clip is not None, "assembly failed"
    assert clip.path.name == f"2026-09-27T14-32-07Z{RECORDING_SUFFIX}"
    assert clip.path.exists() and clip.file_size > 0
    assert not clip.path.with_suffix(f"{RECORDING_SUFFIX}{PART_SUFFIX}").exists()
    assert asm.pinned_segments == frozenset(), "pin released after success"

    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames,codec_type",
         "-of", "default=noprint_wrappers=1", str(clip.path)],
        capture_output=True, text=True, timeout=120,
    )
    print(f"\n[TC-GREC-20] clip={clip.path.name} size={clip.file_size} "
          f"duration={clip.duration_s:.1f}s\n{probe.stdout.strip()}")
    assert "nb_read_frames=" in probe.stdout
    frames = int(probe.stdout.split("nb_read_frames=")[1].split()[0])
    assert frames > 25, f"clip decoded only {frames} frames"

    # No audio may reach a clip either — the policy applies to assembly, not just capture.
    kinds = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "default=noprint_wrappers=1:nokey=1", str(clip.path)],
        capture_output=True, text=True, timeout=60,
    ).stdout
    assert "audio" not in kinds, f"audio reached an assembled clip: {kinds!r}"
