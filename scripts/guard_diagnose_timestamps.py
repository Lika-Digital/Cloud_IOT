#!/usr/bin/env python3
"""
guard_diagnose_timestamps.py — find what actually silences the segment-muxer notice.

    [segment @ 0x...] Timestamps are unset in a packet for stream 0. This is deprecated
    and will stop working in the future.

Read-only and self-contained: writes only under a temp directory, touches no production
config, and needs nothing but ffmpeg and stdlib Python. Run it on the NUC against the real
camera, because that is the only place this reproduces — a file or lavfi source does not.

    python3 scripts/guard_diagnose_timestamps.py \\
        --url 'rtsp://admin:PASS@192.168.1.191:554/profile1'

It runs each variant for --seconds (default 12) and reports, per variant: whether the
deprecation appeared, how many segments were produced, whether one decodes, and any other
stderr. The point is to replace guessing with a table.

Why a matrix rather than another single change: the notice comes from `[segment @ ...]`,
the MUXER, so an input option may not reach it at all under `-c:v copy`. The variants
separate the possible causes — the segment muxer itself, `-reset_timestamps`,
`-avoid_negative_ts`, stream-copy bypassing the stamping, or the camera simply sending
packets without PTS.
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile

DEPRECATION_MARKER = "deprecat"
TIMESTAMP_MARKER = "timestamps are unset"


def redact(url: str) -> str:
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    host = rest.split("/")[0]
    if "@" in host and ":" in host.split("@")[0]:
        user = host.split(":", 1)[0]
        return f"{scheme}://{user}:***@{rest.split('@', 1)[1]}"
    return url


# Each variant returns the argv AFTER the ffmpeg binary. `seg` is the output pattern.
# Ordered so the earliest ones isolate the coarsest question (is it the segment muxer at
# all?) before the later ones tune options.
def variants(url: str, seg_dir: str, single: str, seconds: int) -> list[tuple[str, str, list[str]]]:
    seg = os.path.join(seg_dir, "seg_%06d.ts")
    # -t before -i bounds how much INPUT is read, so every variant self-limits and the
    # caller needs no argv surgery.
    base_in = ["-rtsp_transport", "tcp", "-t", str(seconds)]
    vid_only = ["-map", "0:v:0", "-an", "-dn", "-sn"]
    seg_out = [
        "-f", "segment", "-segment_time", "4",
        "-segment_format", "mpegts", "-reset_timestamps", "1",
        "-avoid_negative_ts", "make_zero", seg,
    ]

    return [
        (
            "A_current_production",
            "exactly what capture.py builds today (wallclock + genpts + copy + segment)",
            [*base_in, "-use_wallclock_as_timestamps", "1", "-fflags", "+genpts",
             "-i", url, *vid_only, "-c:v", "copy", *seg_out],
        ),
        (
            "B_no_segment_muxer",
            "plain -f mpegts to ONE file: is the segment muxer the source of the notice?",
            [*base_in, "-use_wallclock_as_timestamps", "1", "-fflags", "+genpts",
             "-i", url, *vid_only, "-c:v", "copy", "-f", "mpegts", "-y", single],
        ),
        (
            "C_no_wallclock",
            "drop -use_wallclock_as_timestamps: is it helping at all, or irrelevant?",
            [*base_in, "-fflags", "+genpts", "-i", url, *vid_only, "-c:v", "copy", *seg_out],
        ),
        (
            "D_no_genpts",
            "drop -fflags +genpts, keep wallclock",
            [*base_in, "-use_wallclock_as_timestamps", "1",
             "-i", url, *vid_only, "-c:v", "copy", *seg_out],
        ),
        (
            "E_bare_input",
            "no timestamp options at all — the pre-fix baseline",
            [*base_in, "-i", url, *vid_only, "-c:v", "copy", *seg_out],
        ),
        (
            "F_no_reset_timestamps",
            "PRIME SUSPECT: -reset_timestamps makes the segment muxer rewrite timestamps",
            [*base_in, "-use_wallclock_as_timestamps", "1", "-fflags", "+genpts",
             "-i", url, *vid_only, "-c:v", "copy",
             "-f", "segment", "-segment_time", "4", "-segment_format", "mpegts",
             "-avoid_negative_ts", "make_zero", seg],
        ),
        (
            "G_no_avoid_negative_ts",
            "keep reset_timestamps, drop -avoid_negative_ts",
            [*base_in, "-use_wallclock_as_timestamps", "1", "-fflags", "+genpts",
             "-i", url, *vid_only, "-c:v", "copy",
             "-f", "segment", "-segment_time", "4", "-segment_format", "mpegts",
             "-reset_timestamps", "1", seg],
        ),
        (
            "H_neither_seg_option",
            "segment muxer with no timestamp rewriting options at all",
            [*base_in, "-use_wallclock_as_timestamps", "1", "-fflags", "+genpts",
             "-i", url, *vid_only, "-c:v", "copy",
             "-f", "segment", "-segment_time", "4", "-segment_format", "mpegts", seg],
        ),
        (
            "I_copyts",
            "-copyts: pass input timestamps through untouched",
            [*base_in, "-use_wallclock_as_timestamps", "1", "-copyts",
             "-i", url, *vid_only, "-c:v", "copy", *seg_out],
        ),
        (
            "J_stream_segment",
            "-f stream_segment (ssegment): the muxer intended for non-seekable formats",
            [*base_in, "-use_wallclock_as_timestamps", "1", "-fflags", "+genpts",
             "-i", url, *vid_only, "-c:v", "copy",
             "-f", "stream_segment", "-segment_time", "4",
             "-segment_format", "mpegts", seg],
        ),
        (
            "K_fps_mode_passthrough",
            "-fps_mode passthrough, in case frame-rate handling drops timestamps",
            [*base_in, "-use_wallclock_as_timestamps", "1", "-fflags", "+genpts",
             "-i", url, *vid_only, "-c:v", "copy", "-fps_mode", "passthrough", *seg_out],
        ),
        (
            "L_reencode",
            "RE-ENCODE instead of copy: proves whether -c:v copy bypasses the stamping. "
            "NOTE: expensive in production — see the cost note in the report.",
            [*base_in, "-use_wallclock_as_timestamps", "1", "-fflags", "+genpts",
             "-i", url, *vid_only, "-c:v", "libx264", "-preset", "ultrafast", "-g", "50",
             *seg_out],
        ),
    ]


def describe_input(ffmpeg: str, url: str, seconds: int) -> str:
    """What the demuxer says about the input, including all three streams.

    The camera sends video + pcm_alaw audio + a `Data: none` stream. `-map 0:v:0` selects
    video only, but the DEMUXER still parses all three, so the report is worth reading in
    full before blaming the muxer.
    """
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-rtsp_transport", "tcp",
         "-i", url, "-t", "1", "-f", "null", "-"],
        capture_output=True, text=True, timeout=seconds + 40,
    )
    return proc.stderr.strip()


def run_variant(ffmpeg: str, name: str, argv: list[str], seconds: int,
                seg_dir: str) -> dict:
    """Run one variant and report what it produced.

    `seg_dir` MUST be the same directory the variant's output pattern points at — an
    earlier version of this globbed a per-variant subdirectory while the variants wrote to
    the root, so every row reported 0 segments and the whole table would have been
    misleading. It is emptied before each run so counts belong to this variant alone.
    """
    os.makedirs(seg_dir, exist_ok=True)
    for stale in glob.glob(os.path.join(seg_dir, "*.ts")):
        try:
            os.unlink(stale)
        except OSError:
            pass
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin", *argv]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 30)
        rc, err = proc.returncode, proc.stderr
    except subprocess.TimeoutExpired as exc:
        rc = 124
        err = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(
            exc.stderr, bytes) else (exc.stderr or "")

    files = sorted(glob.glob(os.path.join(seg_dir, "*.ts")))
    # The no-segment-muxer variant writes ONE file outside seg_dir; count it too so its row
    # is not reported as having produced nothing.
    single_out = [a for a in argv if a.endswith("single.ts")]
    if not files and single_out and os.path.exists(single_out[0]):
        files = [single_out[0]]
    nonempty = [f for f in files if os.path.getsize(f) > 0]
    decoded = None
    if nonempty:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
             "-show_entries", "stream=nb_read_frames",
             "-of", "default=noprint_wrappers=1:nokey=1", nonempty[0]],
            capture_output=True, text=True, timeout=120,
        )
        val = probe.stdout.strip().splitlines()
        decoded = int(val[0]) if val and val[0].strip().isdigit() else None

    lower = err.lower()
    return {
        "name": name,
        "rc": rc,
        "deprecation": TIMESTAMP_MARKER in lower or DEPRECATION_MARKER in lower,
        "timestamp_notice": TIMESTAMP_MARKER in lower,
        "files": len(files),
        "nonempty": len(nonempty),
        "decoded_frames": decoded,
        "stderr": err.strip(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="RTSP URL of the real camera")
    ap.add_argument("--seconds", type=int, default=12, help="run length per variant")
    ap.add_argument("--only", help="comma-separated variant prefixes, e.g. A,F,J")
    args = ap.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        print("[FAIL] ffmpeg/ffprobe not on PATH", file=sys.stderr)
        return 1

    ver = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True,
                         timeout=30).stdout.splitlines()[0]
    print("=" * 78)
    print("Guard timestamp diagnosis")
    print("=" * 78)
    print(f"ffmpeg : {ver}")
    print(f"camera : {redact(args.url)}")
    print(f"per-variant run: {args.seconds}s\n")

    workdir = tempfile.mkdtemp(prefix="guard_ts_diag_")
    seg_dir = os.path.join(workdir, "segments")
    os.makedirs(seg_dir, exist_ok=True)
    single = os.path.join(workdir, "single.ts")
    try:
        print("-" * 78)
        print("INPUT AS THE DEMUXER SEES IT (all streams, before any mapping)")
        print("-" * 78)
        print(describe_input(ffmpeg, args.url, args.seconds))
        print()

        rows = []
        wanted = [p.strip().upper() for p in args.only.split(",")] if args.only else None
        for name, why, argv in variants(args.url, seg_dir, single, args.seconds):
            if wanted and name.split("_")[0] not in wanted:
                continue
            print("-" * 78)
            print(f"{name}\n  {why}")
            row = run_variant(ffmpeg, name, argv, args.seconds, seg_dir)
            rows.append(row)
            verdict = "NOTICE PRESENT" if row["timestamp_notice"] else "clean"
            print(f"  rc={row['rc']} files={row['files']} nonempty={row['nonempty']} "
                  f"decoded={row['decoded_frames']} -> {verdict}")
            if row["stderr"]:
                for line in row["stderr"].splitlines()[:6]:
                    print(f"    {line}")
            print()

        print("=" * 78)
        print("SUMMARY")
        print("=" * 78)
        print(f"{'variant':26s} {'rc':>4s} {'segs':>5s} {'frames':>7s}  timestamp notice")
        for r in rows:
            print(f"{r['name']:26s} {r['rc']:>4d} {r['nonempty']:>5d} "
                  f"{str(r['decoded_frames']):>7s}  "
                  f"{'YES' if r['timestamp_notice'] else 'no'}")

        clean = [r for r in rows
                 if not r["timestamp_notice"] and r["nonempty"] >= 1 and r["decoded_frames"]]
        print()
        if clean:
            print("Variants that are BOTH clean and produced decodable segments:")
            for r in clean:
                print(f"  - {r['name']}")
            print("\nPick from these. Prefer one that keeps -c:v copy: re-encoding 1080p25")
            print("continuously would cost far more than the 273 ms/frame of CPU the")
            print("detector was budgeted at, and would break the <15 %-of-4-cores target.")
        else:
            print("NO variant was both clean and usable.")
            print("That makes this a decision rather than a fix — see the options in the")
            print("report: accept + pin ffmpeg + rely on a runtime segment-health check, or")
            print("pay the re-encode cost. Do not relax the test either way.")
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
