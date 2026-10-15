/** L2 building blocks: a titled section and a label/value row. Split out of BerthDetail.tsx (§9). */

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4 border border-gray-700 rounded bg-gray-900/40 p-3">
      <h2 className="text-[11px] uppercase tracking-wide text-gray-500 mb-2">{title}</h2>
      {children}
    </section>
  )
}

export function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 py-0.5 flex-wrap">
      <dt className="text-gray-400 w-20 shrink-0">{label}</dt>
      <dd className="text-gray-200 min-w-0">{children}</dd>
    </div>
  )
}
