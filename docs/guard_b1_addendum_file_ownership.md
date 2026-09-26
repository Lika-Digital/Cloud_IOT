# B1 Addendum — file ownership, the delete/serve race, and one flagged deviation

**Date:** 2026-09-26 · Answers the blocking question on B1 §5, plus a deviation from the
approved build order that I am flagging rather than adapting to silently.

---

## 1. The delete/serve race — what happens, precisely

**Confirmed: the worker is the only writer under `/var/lib/marina-guard/`, and the backend
opens files read-only.** The race is real and will happen. Four things make it safe, and
the first is the one that does most of the work.

### 1.1 An in-flight download always completes — POSIX guarantees it

`unlink()` removes the directory entry, not the inode. While the backend holds an open file
descriptor, the inode and its blocks survive until that fd closes. So a download already
streaming when retention deletes the file **finishes normally, uncorrupted**, and the space
is reclaimed afterwards.

This means **no locking, no in-use markers, no coordination** is needed for the common case.
I considered a lease/refcount scheme and rejected it: it would add cross-process state to
protect against something the kernel already handles correctly.

### 1.2 Deletion order: announce first, then unlink

The worker's retention step is deliberately ordered:

```
1. publish guard/retention  {deleted:[{file_path, reason, bytes}]}
2. fsync-free unlink()
```

Not the other way round. The two failure windows are not symmetric:

| Order | If the worker dies mid-way | Consequence |
|---|---|---|
| **publish → unlink** (chosen) | DB says deleted, file still present | **Orphan file.** Harmless; the startup sweep (§1.4) removes it. |
| unlink → publish | DB says available, file gone | Backend hands out a broken link until the message arrives. Worse. |

So the DB is deliberately **pessimistic**: for a brief window it may report a recording gone
while the bytes are still on disk. That direction of error is safe.

### 1.3 The backend returns 410 Gone, never 404, never 500

`GET /api/guard/events/{id}/video` resolves in this order:

| Situation | Response |
|---|---|
| Event id does not exist | **404 Not Found** — it never existed |
| Row exists, `deleted_at` set | **410 Gone** + `{"reason":"max_days"\|"max_gb","deleted_at":"…Z"}` |
| Row exists, `deleted_at` null, but `open()` raises `ENOENT` | **410 Gone**, *and* the backend sets `deleted_at=now()`, `delete_reason="missing_on_disk"` so the list view self-corrects and the next request is consistent |
| File opens | 200 + stream |

410 rather than 404 is the whole point: the client learns *"this existed and is now gone
under retention"*, which is a different fact from *"no such event"*. The dashboard renders it
as a greyed row with "video expired", not a broken link.

The ENOENT branch is the belt to §1.2's braces — it closes the window between the worker
unlinking and the backend processing `guard/retention`, and it also covers a file removed
out-of-band (someone with a shell, a restore, a disk fault).

### 1.4 Startup reconciliation, both directions

On backend start and then hourly:

- **rows with no file** → set `deleted_at`, `delete_reason="missing_on_disk"`, log once per
  file. Stops the dashboard offering links that cannot work.
- **files with no row** (the §1.2 orphan case, or a crash mid-write) → the *worker* deletes
  them on its own start, since it owns the directory. The backend only reports the count.

Both directions are logged, never silent.

---

## 2. Your two conditions on the frame budget

### 2.1 An ALARM frame is never evicted

Eviction touches **uncertain-band frames only**, oldest first. The order is explicit:

```
over GUARD_MAX_FRAMES_GB?
  1. evict uncertain frames, oldest first          ← the only frames ever deleted
  2. uncertain frames exhausted and still over cap?
       → do NOT touch alarm frames
       → STOP SAVING new uncertain frames
       → raise health flag frames_cap_exhausted
```

The degradation is in *collection*, never in *evidence*. If alarm frames alone exceed the
cap, that is an operator problem — surfaced as a health condition with the numbers — not
something the worker quietly resolves by destroying the thing the cap exists to protect.

Recordings are separate and follow `GUARD_RETENTION_DAYS` / `GUARD_MAX_GB` as specified,
with one addition below.

### 2.2 Eviction is always visible — never silent

Because the point is that you know when training data is being lost:

- **`/api/guard/status`** gains a `retention` block:
  ```json
  "retention": {
    "frames_gb_used": 1.7, "frames_gb_cap": 2.0, "frames_evicting": true,
    "frames_cap_exhausted": false,
    "recordings_gb_used": 12.4, "recordings_gb_cap": 20.0,
    "last_eviction_at": "2026-09-26T14:02:11Z",
    "evicted_24h": {"frames": 812, "recordings": 3, "labelled_recordings": 0}
  }
  ```
- **WebSocket** `guard_retention_state_changed` fires on transition into and out of
  eviction — not per file, which would be noise.
- **Dashboard banner** while `frames_evicting` is true: *"Frame storage full — oldest
  uncertain frames are being deleted. Alarm frames are protected."* A stronger red banner
  for `frames_cap_exhausted`: *"No longer saving uncertain frames."*
- Every deletion writes an audit line (file, reason, bytes) via the existing `error_logs`.

### 2.3 One addition I am proposing: labelled recordings resist `max_days`

Once you have marked an event correct or false-alarm, its recording is the evidence behind
a label — the most valuable video on the box. So:

- `max_days` **skips** recordings whose event carries a label.
- `max_gb` can still evict them, because disk safety has to win over data collection, but
  they go **last** (unlabelled first, then labelled oldest-first) and each such eviction
  increments `evicted_24h.labelled_recordings` and raises the dashboard banner.

Not in the original spec. Flagging it as a proposal; say no and `max_days` treats all
recordings alike.

### 2.4 Detection retention is configurable, as asked

`GUARD_DETECTION_RETENTION_DAYS`, default 30, independent of recording retention, runtime-
changeable via `PATCH /api/guard/{cam}/config`. Raising it once the Phase 2 pipeline exists
needs no redeploy. Sizing at the worst case measured so far: ~12 k rows/day ≈ 2.4 MB/day, so
30 d ≈ 72 MB and 180 d ≈ 430 MB in `pedestal.db`. Safe to extend.

---

## 3. FLAGGED DEVIATION — "replaces the per-poll spawn"

The approved build order says the persistent ffmpeg *replaces* the per-poll ffmpeg spawn.
**I am not going to do that, and I want to say so plainly rather than quietly not doing it.**

The per-poll spawn is `frame_buffer.py`, which feeds **berth occupancy** every 10 s. Guard's
persistent ffmpeg runs **only while armed**. If guard's stream replaced it, then:

- while guard is **disarmed** (the default, and the state for the next week) berth occupancy
  would have no frame source at all, or
- berth occupancy's frame source would start and stop with the guard toggle, making a
  working feature depend on an unproven one.

Either outcome violates the hard constraint that guard must never degrade berth occupancy —
and acceptance criterion 5 ("berth occupancy keeps running unchanged through arm, alarm,
suspend and re-arm") cannot be met by a design where arming changes its frame source.

**So: `frame_buffer.py` is left completely untouched, and guard opens its own stream.** The
"one RTSP connection" constraint is honoured *within guard* — one persistent process with
two outputs via `tee`, not two — but the box will hold **two** RTSP sessions to the camera
while guard is armed: guard's persistent one, plus berth occupancy's 10-second poll.

**What this needs verifying on the NUC before step 1 is accepted** (cheap, read-only, and it
does not require guard to exist):

```bash
# Session 1: hold a stream open
timeout 60 ffmpeg -rtsp_transport tcp -i "rtsp://admin:PASS@192.168.1.191:554/profile1" \
  -c copy -f mp4 /tmp/concurrent_a.mp4 &
sleep 5
# Session 2: the berth-occupancy pattern, while session 1 is live
timeout 20 ffmpeg -rtsp_transport tcp -i "rtsp://admin:PASS@192.168.1.191:554/profile1" \
  -vframes 1 /tmp/concurrent_b.jpg
ls -l /tmp/concurrent_a.mp4 /tmp/concurrent_b.jpg
```

Both files non-empty → the camera serves two concurrent sessions and the design stands.
If the second fails, the honest options are: point guard at `profile2` (sub-stream, at the
cost of the resolution that gives us the 25–30 m range), or have guard publish frames that
berth occupancy consumes — which reintroduces the coupling above and I would want to discuss
before choosing.

**I will build step 1 assuming two sessions work, because that is the design that protects
berth occupancy, and treat the check above as a step-1 acceptance item.**

---

## 4. Merge gate, restated

`main` receives nothing until the acceptance criteria are **measured on the NUC and the
numbers are in your hands**. Not measured-then-merged in one motion — numbers first, merge
after your word.
