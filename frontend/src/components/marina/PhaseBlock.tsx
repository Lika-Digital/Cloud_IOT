/**
 * Per-phase current of a three-phase socket — berth detail only (§5.3), never on an L1 row.
 *
 * ABSENT, not empty, when there is nothing per-phase to show: `phases` is null for a
 * single-phase socket, with no session running, or when the telemetry is not current (§4.7).
 *
 * Labelled "Phase 1 / 2 / 3" in words, never L1/L2/L3 — "L1" is the dashboard level in this
 * spec and a phase on the hardware, and that collision is exactly what ends up on a screen.
 * A phase the cabinet did not send is "—", never 0: 0 A is a measurement.
 */
export function PhaseBlock({ phases }: { phases: (number | null)[] | null }) {
  if (!phases) return null
  return (
    <dl className="mt-2 ml-24 flex gap-4 flex-wrap text-sm" data-testid="phase-block">
      {phases.map((a, i) => (
        <div key={i} className="flex gap-1.5 items-baseline">
          <dt className="text-gray-400">Phase {i + 1}</dt>
          <dd className="text-gray-100 tabular-nums">
            {a === null ? <span className="text-gray-500">—</span> : `${a} A`}
          </dd>
        </div>
      ))}
    </dl>
  )
}
