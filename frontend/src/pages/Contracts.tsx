import { useState, useEffect } from 'react'
import { useAuthStore } from '../store/authStore'
import {
  getTemplates, createTemplate, updateTemplate, getAdminContracts,
  type ContractTemplate, type CustomerContract,
} from '../api/contracts'

export default function Contracts() {
  const [templates, setTemplates] = useState<ContractTemplate[]>([])
  const [contracts, setContracts] = useState<CustomerContract[]>([])
  const [showForm, setShowForm] = useState(false)
  const [saving, setSaving] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [pdfError, setPdfError] = useState<string | null>(null)

  // New template form state
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [validityDays, setValidityDays] = useState('365')
  const [notifyOnRegister, setNotifyOnRegister] = useState(true)

  useEffect(() => {
    Promise.all([
      getTemplates().then(setTemplates),
      getAdminContracts().then(setContracts),
    ]).catch(() => setLoadError('Failed to load contracts data. Check your connection and refresh.'))
  }, [])

  const handleCreateTemplate = async () => {
    if (!title.trim() || !body.trim()) return
    setSaving(true)
    setSaveError(null)
    try {
      const tpl = await createTemplate({
        title,
        body,
        validity_days: parseInt(validityDays, 10) || 365,
        notify_on_register: notifyOnRegister,
      })
      setTemplates((prev) => [...prev, tpl])
      setTitle('')
      setBody('')
      setValidityDays('365')
      setNotifyOnRegister(true)
      setShowForm(false)
    } catch {
      setSaveError('Failed to create template. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (tpl: ContractTemplate) => {
    try {
      const updated = await updateTemplate(tpl.id, { active: !tpl.active })
      setTemplates((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
    } catch {
      setSaveError('Failed to update template status. Please try again.')
    }
  }

  const handleDownloadPdf = (contractId: number) => {
    const token = useAuthStore.getState().token
    const url = `/api/admin/contracts/${contractId}/pdf`
    setPdfError(null)
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.blob()
      })
      .then((blob) => {
        const objUrl = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = objUrl
        a.download = `contract_${contractId}.pdf`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(objUrl)
      })
      .catch(() => setPdfError('Failed to download PDF. Please try again.'))
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Contracts</h1>
        <p className="text-gray-400 text-sm mt-1">Manage marina service agreement templates and customer signatures</p>
      </div>

      {loadError && (
        <div className="px-4 py-3 rounded-lg bg-red-900/30 border border-red-700/40 text-red-400 text-sm">
          {loadError}
        </div>
      )}
      {saveError && (
        <div className="px-4 py-3 rounded-lg bg-red-900/30 border border-red-700/40 text-red-400 text-sm">
          {saveError}
        </div>
      )}
      {pdfError && (
        <div className="px-4 py-3 rounded-lg bg-red-900/30 border border-red-700/40 text-red-400 text-sm">
          {pdfError}
        </div>
      )}

      {/* Templates section */}
      <div className="card space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-gray-200">Contract Templates</h2>
          <button
            className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors"
            onClick={() => setShowForm((v) => !v)}
          >
            {showForm ? 'Cancel' : '+ New Template'}
          </button>
        </div>

        {showForm && (
          <div className="border border-gray-700 rounded-lg p-4 space-y-3 bg-gray-800/30">
            <div>
              <label className="text-xs text-gray-400 block mb-1">Title</label>
              <input
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 text-sm focus:outline-none focus:border-blue-500"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Contract title"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 block mb-1">Body</label>
              <textarea
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 text-sm focus:outline-none focus:border-blue-500 font-mono"
                rows={10}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Contract body text..."
              />
            </div>
            <div className="flex gap-4">
              <div className="flex-1">
                <label className="text-xs text-gray-400 block mb-1">Validity (days)</label>
                <input
                  type="number"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 text-sm focus:outline-none focus:border-blue-500"
                  value={validityDays}
                  onChange={(e) => setValidityDays(e.target.value)}
                />
              </div>
              <div className="flex items-end gap-2 pb-1">
                <label className="text-xs text-gray-400">Notify on register</label>
                <input
                  type="checkbox"
                  checked={notifyOnRegister}
                  onChange={(e) => setNotifyOnRegister(e.target.checked)}
                  className="w-4 h-4"
                />
              </div>
            </div>
            <button
              className="px-4 py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 transition-colors disabled:opacity-50"
              onClick={handleCreateTemplate}
              disabled={saving || !title.trim() || !body.trim()}
            >
              {saving ? 'Creating…' : 'Create Template'}
            </button>
          </div>
        )}

        {templates.length === 0 ? (
          <p className="text-gray-500 text-sm">No templates yet.</p>
        ) : (
          <div className="space-y-2">
            {templates.map((tpl) => (
              <div
                key={tpl.id}
                className="flex items-center justify-between border border-gray-700 rounded-lg px-4 py-3"
              >
                <div>
                  <div className="text-gray-200 font-medium text-sm">{tpl.title}</div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    Valid {tpl.validity_days} days
                    {tpl.notify_on_register ? ' · Notify on register' : ''}
                    {' · '}
                    Created {new Date(tpl.created_at).toLocaleDateString()}
                  </div>
                </div>
                <button
                  className={`px-3 py-1 text-xs rounded-full font-medium transition-colors ${
                    tpl.active
                      ? 'bg-green-900/50 text-green-400 hover:bg-red-900/50 hover:text-red-400'
                      : 'bg-red-900/50 text-red-400 hover:bg-green-900/50 hover:text-green-400'
                  }`}
                  onClick={() => toggleActive(tpl)}
                >
                  {tpl.active ? 'Active' : 'Inactive'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Signed contracts section */}
      <div className="card">
        <h2 className="font-semibold text-gray-200 mb-4">Signed Contracts</h2>
        {contracts.length === 0 ? (
          <p className="text-gray-500 text-sm">No signed contracts yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700 text-gray-400 text-left">
                  <th className="py-2 pr-4">Customer</th>
                  <th className="py-2 pr-4">Contract</th>
                  <th className="py-2 pr-4">Signed</th>
                  <th className="py-2 pr-4">Valid Until</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2">PDF</th>
                </tr>
              </thead>
              <tbody>
                {contracts.map((c) => (
                  <tr key={c.id} className="border-b border-gray-800 hover:bg-gray-800/50">
                    <td className="py-2 pr-4">
                      <div className="text-gray-200">{c.customer_name ?? '—'}</div>
                      <div className="text-xs text-gray-500">{c.customer_email ?? ''}</div>
                    </td>
                    <td className="py-2 pr-4 text-gray-300">{c.template_title ?? `Template #${c.template_id}`}</td>
                    <td className="py-2 pr-4 text-gray-300 font-mono text-xs">
                      {new Date(c.signed_at).toLocaleDateString()}
                    </td>
                    <td className="py-2 pr-4 text-gray-300 font-mono text-xs">
                      {c.valid_until ? new Date(c.valid_until).toLocaleDateString() : '—'}
                    </td>
                    <td className="py-2 pr-4">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        c.status === 'active'
                          ? 'bg-green-900/50 text-green-400'
                          : 'bg-gray-700 text-gray-400'
                      }`}>
                        {c.status}
                      </span>
                    </td>
                    <td className="py-2">
                      <button
                        className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                        onClick={() => handleDownloadPdf(c.id)}
                      >
                        Download
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
