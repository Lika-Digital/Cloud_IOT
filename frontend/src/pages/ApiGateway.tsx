import { useEffect, useState, useCallback } from 'react'
import {
  getCatalog,
  getConfig,
  updateConfig,
  rotateKey,
  verifyConfig,
  activateConfig,
  deactivateConfig,
  type Catalog,
  type ExtApiConfig,
  type EndpointEntry,
  type VerifyResult,
} from '../api/externalApi'

// ── Utilities ─────────────────────────────────────────────────────────────────

function groupBy<T>(items: T[], key: keyof T): Record<string, T[]> {
  return items.reduce((acc, item) => {
    const k = String(item[key])
    if (!acc[k]) acc[k] = []
    acc[k].push(item)
    return acc
  }, {} as Record<string, T[]>)
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusBadge({ active, verified }: { active: boolean; verified: boolean }) {
  if (active) return <span className="px-3 py-1 rounded-full text-xs font-bold bg-green-600/20 text-green-400 border border-green-600/30">Active</span>
  if (verified) return <span className="px-3 py-1 rounded-full text-xs font-bold bg-yellow-600/20 text-yellow-400 border border-yellow-600/30">Verified</span>
  return <span className="px-3 py-1 rounded-full text-xs font-bold bg-gray-700 text-gray-400">Inactive</span>
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
      <h2 className="text-base font-semibold text-gray-200 mb-4">{title}</h2>
      {children}
    </div>
  )
}

function Btn({
  onClick,
  loading,
  disabled,
  variant = 'primary',
  children,
}: {
  onClick: () => void
  loading?: boolean
  disabled?: boolean
  variant?: 'primary' | 'danger' | 'ghost'
  children: React.ReactNode
}) {
  const base = 'px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50'
  const variants = {
    primary: 'bg-blue-600 hover:bg-blue-700 text-white',
    danger:  'bg-red-600/20 hover:bg-red-600/30 text-red-400 border border-red-600/30',
    ghost:   'bg-gray-800 hover:bg-gray-700 text-gray-300',
  }
  return (
    <button className={`${base} ${variants[variant]}`} onClick={onClick} disabled={disabled || loading}>
      {loading ? 'Working…' : children}
    </button>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ApiGateway() {
  const [catalog, setCatalog]               = useState<Catalog | null>(null)
  const [config, setConfig]                 = useState<ExtApiConfig | null>(null)
  const [loading, setLoading]               = useState(true)
  const [error, setError]                   = useState<string | null>(null)

  // Card 1 — Key
  const [showKey, setShowKey]               = useState(false)
  const [rotatingKey, setRotatingKey]       = useState(false)
  const [copiedKey, setCopiedKey]           = useState(false)

  // Card 2 — Endpoints (local state until saved)
  const [localEndpoints, setLocalEndpoints] = useState<EndpointEntry[]>([])
  const [endpointsDirty, setEndpointsDirty] = useState(false)
  const [savingEps, setSavingEps]           = useState(false)

  // Card 3 — Webhook
  const [webhookEnabled, setWebhookEnabled] = useState(false)
  const [webhookUrl, setWebhookUrl]         = useState('')
  const [localEvents, setLocalEvents]       = useState<string[]>([])
  const [webhookDirty, setWebhookDirty]     = useState(false)
  const [savingWebhook, setSavingWebhook]   = useState(false)

  // Card 4 — Verify & Activate
  const [verifying, setVerifying]           = useState(false)
  const [verifyResults, setVerifyResults]   = useState<VerifyResult[] | null>(null)
  const [verifyOk, setVerifyOk]             = useState(false)
  const [activating, setActivating]         = useState(false)

  // ── Load ──────────────────────────────────────────────────────────────────

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [cat, cfg] = await Promise.all([getCatalog(), getConfig()])
      setCatalog(cat)
      setConfig(cfg)
      setLocalEndpoints(cfg.allowed_endpoints ?? [])
      setWebhookEnabled(!!cfg.webhook_url)
      setWebhookUrl(cfg.webhook_url ?? '')
      setLocalEvents(cfg.allowed_events ?? [])
      if (cfg.verification_results) {
        setVerifyResults(cfg.verification_results)
        setVerifyOk(cfg.verified)
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load config')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // ── Endpoint helpers ──────────────────────────────────────────────────────

  function isEndpointEnabled(id: string) {
    return localEndpoints.some((e) => e.id === id)
  }

  function getEndpointMode(id: string): 'monitor' | 'bidirectional' {
    return localEndpoints.find((e) => e.id === id)?.mode ?? 'monitor'
  }

  function toggleEndpoint(id: string, allowBidirectional: boolean) {
    setEndpointsDirty(true)
    setLocalEndpoints((prev) => {
      if (prev.some((e) => e.id === id)) return prev.filter((e) => e.id !== id)
      return [...prev, { id, mode: allowBidirectional ? 'monitor' : 'monitor' }]
    })
  }

  function setEndpointMode(id: string, mode: 'monitor' | 'bidirectional') {
    setEndpointsDirty(true)
    setLocalEndpoints((prev) => prev.map((e) => (e.id === id ? { ...e, mode } : e)))
  }

  // ── Event helpers ─────────────────────────────────────────────────────────

  function toggleEvent(id: string) {
    setWebhookDirty(true)
    setLocalEvents((prev) =>
      prev.includes(id) ? prev.filter((e) => e !== id) : [...prev, id]
    )
  }

  // ── Actions ───────────────────────────────────────────────────────────────

  async function handleRotateKey() {
    setRotatingKey(true)
    try {
      const res = await rotateKey()
      setConfig((prev) => prev ? { ...prev, api_key: res.api_key, active: false, verified: false } : prev)
      setVerifyResults(null)
      setVerifyOk(false)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Failed to rotate key')
    } finally {
      setRotatingKey(false)
    }
  }

  async function handleSaveEndpoints() {
    setSavingEps(true)
    try {
      const updated = await updateConfig({
        allowed_endpoints: localEndpoints,
        webhook_url:       webhookEnabled ? webhookUrl || null : null,
        allowed_events:    localEvents,
      })
      setConfig(updated)
      setEndpointsDirty(false)
      setVerifyResults(null)
      setVerifyOk(false)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Failed to save endpoints')
    } finally {
      setSavingEps(false)
    }
  }

  async function handleSaveWebhook() {
    setSavingWebhook(true)
    try {
      const updated = await updateConfig({
        allowed_endpoints: localEndpoints,
        webhook_url:       webhookEnabled ? webhookUrl || null : null,
        allowed_events:    localEvents,
      })
      setConfig(updated)
      setWebhookDirty(false)
      setVerifyResults(null)
      setVerifyOk(false)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Failed to save webhook')
    } finally {
      setSavingWebhook(false)
    }
  }

  async function handleVerify() {
    setVerifying(true)
    setVerifyResults(null)
    try {
      const res = await verifyConfig()
      setVerifyResults(res.results)
      setVerifyOk(res.verified)
      setConfig((prev) => prev ? { ...prev, verified: res.verified } : prev)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Verification failed')
    } finally {
      setVerifying(false)
    }
  }

  async function handleActivate() {
    setActivating(true)
    try {
      await activateConfig()
      setConfig((prev) => prev ? { ...prev, active: true } : prev)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Activation failed')
    } finally {
      setActivating(false)
    }
  }

  async function handleDeactivate() {
    setActivating(true)
    try {
      await deactivateConfig()
      setConfig((prev) => prev ? { ...prev, active: false } : prev)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Deactivation failed')
    } finally {
      setActivating(false)
    }
  }

  function handleCopyKey() {
    const key = config?.api_key
    if (!key) return
    navigator.clipboard.writeText(key).then(() => {
      setCopiedKey(true)
      setTimeout(() => setCopiedKey(false), 2000)
    })
  }

  // ── Render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        Loading API Gateway config…
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <p className="text-red-400">{error}</p>
        <Btn onClick={load} variant="ghost">Retry</Btn>
      </div>
    )
  }

  const hasKey   = !!config?.api_key
  const isActive = !!config?.active
  const isVerified = !!config?.verified
  const baseUrl  = `${window.location.origin}/api/ext/`

  const endpointsByCategory = catalog ? groupBy(catalog.endpoints, 'category') : {}
  const eventsByCategory    = catalog ? groupBy(catalog.events, 'category') : {}

  return (
    <div className="space-y-6">
      {/* Header + status bar */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">API Gateway</h1>
          <p className="text-sm text-gray-400 mt-1">
            Expose a controlled subset of endpoints to 3rd-party systems (BMS, SCADA, etc.)
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge active={isActive} verified={isVerified} />
          <span className="text-xs text-gray-500 font-mono bg-gray-800 px-3 py-1 rounded-lg border border-gray-700">
            {baseUrl}
          </span>
        </div>
      </div>

      {/* Card 1 — API Key (optional legacy) */}
      <Card title="API Key (Optional)">
        <div className="space-y-4">
          <div className="flex items-start gap-2 p-3 bg-blue-600/10 border border-blue-600/20 rounded-lg">
            <svg className="w-4 h-4 text-blue-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p className="text-xs text-blue-300">
              This system uses <strong>JWT service accounts</strong> (api_client role) as the primary auth mechanism for ERP integration.
              A static API key is optional and only needed for legacy or 3rd-party webhook integrations.
            </p>
          </div>

          {hasKey ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <input
                  type={showKey ? 'text' : 'password'}
                  value={config?.api_key ?? ''}
                  readOnly
                  className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs font-mono text-gray-300 focus:outline-none"
                />
                <button
                  onClick={() => setShowKey((v) => !v)}
                  className="px-3 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs text-gray-400 transition-colors"
                >
                  {showKey ? 'Hide' : 'Show'}
                </button>
                <button
                  onClick={handleCopyKey}
                  className="px-3 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs text-gray-400 transition-colors"
                >
                  {copiedKey ? 'Copied!' : 'Copy'}
                </button>
              </div>
              <p className="text-xs text-gray-500">
                Bearer token — include as <code className="text-gray-300 bg-gray-800 px-1 rounded">Authorization: Bearer {'<key>'}</code> in requests.
              </p>
            </div>
          ) : (
            <p className="text-sm text-gray-500">No API key generated yet. Click below to create one.</p>
          )}

          <Btn onClick={handleRotateKey} loading={rotatingKey} variant={hasKey ? 'ghost' : 'primary'}>
            {hasKey ? 'Rotate Key' : 'Generate Key'}
          </Btn>
          {hasKey && (
            <p className="text-xs text-yellow-500/70">
              Rotating the key invalidates all existing 3rd-party integrations.
            </p>
          )}
        </div>
      </Card>

      {/* Card 2 — Endpoint Access */}
      <Card title="Endpoint Access">
        <div className="space-y-4">
          {Object.entries(endpointsByCategory).map(([category, eps]) => (
            <div key={category}>
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">{category}</h3>
              <div className="space-y-2">
                {eps.map((ep) => {
                  const enabled = isEndpointEnabled(ep.id)
                  const mode    = getEndpointMode(ep.id)
                  return (
                    <div key={ep.id} className="flex items-center gap-3 py-2 border-b border-gray-800 last:border-0">
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={() => toggleEndpoint(ep.id, ep.allow_bidirectional)}
                        className="w-4 h-4 rounded accent-blue-500"
                      />
                      <div className="flex-1 min-w-0">
                        <span className="text-sm text-gray-300">{ep.id}</span>
                        <span className="ml-2 text-xs text-gray-600 font-mono">{ep.method} {ep.path}</span>
                      </div>
                      {enabled && ep.allow_bidirectional && (
                        <select
                          value={mode}
                          onChange={(e) => setEndpointMode(ep.id, e.target.value as 'monitor' | 'bidirectional')}
                          className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-xs text-gray-300 focus:outline-none focus:border-blue-500"
                        >
                          <option value="monitor">Monitor (GET only)</option>
                          <option value="bidirectional">Bidirectional</option>
                        </select>
                      )}
                      {enabled && !ep.allow_bidirectional && (
                        <span className="text-xs text-gray-600 px-2 py-1 bg-gray-800 rounded-lg">Monitor</span>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          ))}

          <div className="flex items-center gap-3 pt-2">
            <Btn
              onClick={handleSaveEndpoints}
              loading={savingEps}
              disabled={!endpointsDirty}
            >
              Save Endpoints
            </Btn>
            {endpointsDirty && (
              <span className="text-xs text-yellow-400">Unsaved changes</span>
            )}
          </div>
        </div>
      </Card>

      {/* Card 3 — Webhook Push */}
      <Card title="Webhook Push">
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={webhookEnabled}
                onChange={(e) => {
                  setWebhookEnabled(e.target.checked)
                  setWebhookDirty(true)
                }}
                className="sr-only peer"
              />
              <div className="w-10 h-5 bg-gray-700 peer-checked:bg-blue-600 rounded-full transition-colors after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-transform peer-checked:after:translate-x-5" />
            </label>
            <span className="text-sm text-gray-300">Enable webhook push</span>
          </div>

          {webhookEnabled && (
            <div className="space-y-4 pl-2">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Webhook URL</label>
                <input
                  type="url"
                  value={webhookUrl}
                  onChange={(e) => { setWebhookUrl(e.target.value); setWebhookDirty(true) }}
                  placeholder="https://your-server.com/webhook"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 focus:outline-none focus:border-blue-500"
                />
                <p className="text-xs text-gray-600 mt-1">
                  We will POST to this URL with <code className="text-gray-400">X-API-Key</code> header for selected events.
                </p>
              </div>

              <div>
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Events</h3>
                {Object.entries(eventsByCategory).map(([category, events]) => (
                  <div key={category} className="mb-3">
                    <p className="text-xs text-gray-600 mb-1">{category}</p>
                    <div className="space-y-1">
                      {events.map((ev) => (
                        <label key={ev.id} className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={localEvents.includes(ev.id)}
                            onChange={() => toggleEvent(ev.id)}
                            className="w-4 h-4 rounded accent-blue-500"
                          />
                          <span className="text-sm text-gray-300">{ev.name}</span>
                          <span className="text-xs text-gray-600">{ev.id}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center gap-3">
            <Btn
              onClick={handleSaveWebhook}
              loading={savingWebhook}
              disabled={!webhookDirty}
            >
              Save Webhook
            </Btn>
            {webhookDirty && (
              <span className="text-xs text-yellow-400">Unsaved changes</span>
            )}
          </div>
        </div>
      </Card>

      {/* Card 4 — Verification & Activation */}
      <Card title="Verification & Activation">
        <div className="space-y-4">
          <p className="text-sm text-gray-400">
            Run a live connectivity check on all enabled GET endpoints before activating the gateway.
          </p>
          <div className="flex items-start gap-2 p-3 bg-blue-600/10 border border-blue-600/20 rounded-lg">
            <svg className="w-4 h-4 text-blue-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p className="text-xs text-blue-300">
              If you are using <strong>JWT service accounts</strong> (ERP integration) or <strong>webhook push</strong>,
              verification and activation are not required — the gateway is accessible via Bearer token authentication.
            </p>
          </div>

          <Btn onClick={handleVerify} loading={verifying}>
            Run Verification
          </Btn>

          {verifyResults && (
            <div className="mt-3">
              <table className="w-full text-sm border border-gray-800 rounded-lg overflow-hidden">
                <thead>
                  <tr className="bg-gray-800">
                    <th className="text-left px-3 py-2 text-xs text-gray-400 font-medium">Endpoint</th>
                    <th className="text-left px-3 py-2 text-xs text-gray-400 font-medium">Path</th>
                    <th className="text-left px-3 py-2 text-xs text-gray-400 font-medium">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {verifyResults.map((r, i) => (
                    <tr key={i} className="border-t border-gray-800">
                      <td className="px-3 py-2 text-gray-300 font-mono text-xs">{r.endpoint_id}</td>
                      <td className="px-3 py-2 text-gray-500 font-mono text-xs">{r.path}</td>
                      <td className="px-3 py-2">
                        {r.ok === true && (
                          <span className="text-green-400 text-xs font-medium">Pass</span>
                        )}
                        {r.ok === false && (
                          <span className="text-red-400 text-xs font-medium">{r.note}</span>
                        )}
                        {r.ok === null && (
                          <span className="text-gray-500 text-xs">{r.note}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className={`mt-2 text-sm font-medium ${verifyOk ? 'text-green-400' : 'text-red-400'}`}>
                {verifyOk ? 'All testable endpoints passed.' : 'Some endpoints failed — fix before activating.'}
              </div>
            </div>
          )}

          <div className="flex items-center gap-3 pt-2 border-t border-gray-800">
            {!isActive ? (
              <Btn onClick={handleActivate} loading={activating}>
                Activate API
              </Btn>
            ) : (
              <Btn onClick={handleDeactivate} loading={activating} variant="danger">
                Deactivate
              </Btn>
            )}
          </div>
        </div>
      </Card>
    </div>
  )
}
