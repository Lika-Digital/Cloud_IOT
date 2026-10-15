import { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { getMarinaCore, type MarinaPedestal } from '../../api/marina'
import { TONE } from '../../components/marina/Status'

/**
 * /marina/setup — where the admin nav's "Setup" lands (block 4, nav, 2026-10-15).
 *
 * The wizard is per pedestal (/marina/setup/:pid) and until now nothing linked to it: it was
 * reachable only by typing the address. One pedestal (cabinet 1 today) goes straight to its
 * wizard; several are listed. Admin only, in the route, like the wizard itself.
 */
export default function SetupIndex() {
  const [pedestals, setPedestals] = useState<MarinaPedestal[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    getMarinaCore().then((c) => setPedestals(c.pedestals)).catch(() => setFailed(true))
  }, [])

  if (pedestals && pedestals.length === 1) {
    return <Navigate to={`/marina/setup/${pedestals[0].pedestal_id}`} replace />
  }
  return (
    <div className="p-3 sm:p-4 max-w-2xl" data-testid="setup-index">
      <h1 className="text-lg font-semibold text-gray-100 mb-3">Set up a pedestal</h1>
      {failed && <p className={`text-sm ${TONE.noticeText}`}>The pedestals could not be loaded.</p>}
      {!failed && !pedestals && <p className="text-sm text-gray-400" role="status">Loading…</p>}
      {pedestals && pedestals.length === 0 && (
        <p className="text-sm text-gray-400">No pedestals are set up yet.</p>
      )}
      {pedestals && pedestals.length > 1 && (
        <ul className="flex flex-col gap-2">
          {pedestals.map((p) => (
            <li key={p.pedestal_id}>
              <Link to={`/marina/setup/${p.pedestal_id}`}
                className="text-sm text-blue-300 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400">
                {p.dock ? `Dock ${p.dock}` : 'Pedestal'}{' '}
                <span className="font-mono text-gray-400">{p.cabinet_id ?? `#${p.pedestal_id}`}</span> ›
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
