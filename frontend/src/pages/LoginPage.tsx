import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  authLogin, authTotpLogin, authOtpRequest, authOtpLogin,
  type TokenResponse,
} from '../api/auth'
import { useAuthStore } from '../store/authStore'

type Step = 'credentials' | 'second'
type Mode = 'totp' | 'otp'

function errDetail(err: unknown, fallback: string): string {
  return (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? fallback
}

export default function LoginPage() {
  const navigate = useNavigate()
  const { setAuth } = useAuthStore()

  const [step, setStep] = useState<Step>('credentials')
  const [mode, setMode] = useState<Mode>('totp')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [partialToken, setPartialToken] = useState('')
  const [method, setMethod] = useState<'log' | 'email' | null>(null)
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleCredentials = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null); setLoading(true)
    try {
      const data = await authLogin(email, password)
      setPartialToken(data.partial_token)
      setMethod(data.method)
      setMode(data.totp_required ? 'totp' : 'otp')   // no-TOTP user already got an OTP
      setCode('')
      setStep('second')
    } catch (err: unknown) {
      setError(errDetail(err, 'Login failed. Check your email and password.'))
    } finally {
      setLoading(false)
    }
  }

  const finish = (data: TokenResponse) => {
    setAuth(data.access_token, data.role, data.email)
    navigate('/dashboard', { replace: true })
  }

  const submitSecondFactor = async (codeVal: string) => {
    if (loading) return
    setError(null); setLoading(true)
    try {
      const data = mode === 'totp'
        ? await authTotpLogin(partialToken, codeVal)
        : await authOtpLogin(partialToken, codeVal)
      finish(data)
    } catch (err: unknown) {
      setError(errDetail(err, 'Invalid or expired code.'))
      setCode('')
    } finally {
      setLoading(false)
    }
  }

  const onCodeChange = (raw: string) => {
    const v = raw.replace(/\D/g, '').slice(0, 6)
    setCode(v)
    if (v.length === 6) void submitSecondFactor(v)   // auto-submit on 6 digits
  }

  const handleUseBackup = async () => {
    setError(null); setLoading(true)
    try {
      const r = await authOtpRequest(partialToken)
      setMethod(r.method)
      setMode('otp')
      setCode('')
    } catch (err: unknown) {
      setError(errDetail(err, 'Could not send a backup code.'))
    } finally {
      setLoading(false)
    }
  }

  const backToStart = () => {
    setStep('credentials'); setCode(''); setError(null); setPartialToken(''); setMethod(null)
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="text-4xl mb-3">⚡</div>
          <h1 className="text-2xl font-bold text-white">IoT Dashboard</h1>
          <p className="text-gray-500 text-sm mt-1">Smart Pedestal Management</p>
        </div>

        <div className="card">
          {step === 'credentials' ? (
            <>
              <h2 className="text-lg font-semibold text-white mb-4">Sign In</h2>
              <form onSubmit={handleCredentials} className="space-y-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Email</label>
                  <input
                    type="email" required autoFocus value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
                    placeholder="you@example.com"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Password</label>
                  <input
                    type="password" required value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
                    placeholder="••••••••"
                  />
                </div>
                {error && (
                  <div className="text-sm text-red-400 bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">{error}</div>
                )}
                <button type="submit" disabled={loading} className="btn-primary w-full">
                  {loading ? 'Checking…' : 'Continue'}
                </button>
              </form>
            </>
          ) : (
            <>
              <h2 className="text-lg font-semibold text-white mb-1">
                {mode === 'totp' ? 'Two-factor authentication' : 'Enter backup code'}
              </h2>

              {mode === 'totp' ? (
                <p className="text-sm text-gray-500 mb-4">
                  Enter the 6-digit code from your authenticator app.
                </p>
              ) : (
                <p className="text-sm text-gray-500 mb-4">
                  {method === 'email'
                    ? <>A backup code was sent to your email address (<span className="text-gray-300">{email}</span>).</>
                    : <>A backup code was written to the backend log. Ask your administrator or check:
                        <code className="block mt-1 text-xs text-gray-400 bg-gray-800 rounded px-2 py-1">sudo journalctl -u cloud-iot-backend -f</code></>}
                </p>
              )}

              <form onSubmit={(e) => { e.preventDefault(); if (code.length === 6) void submitSecondFactor(code) }} className="space-y-4">
                <input
                  type="text" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required autoFocus
                  value={code}
                  onChange={(e) => onCodeChange(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-center tracking-[0.5em] text-xl font-mono focus:outline-none focus:border-blue-500"
                  placeholder="000000"
                />

                {error && (
                  <div className="text-sm text-red-400 bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">{error}</div>
                )}

                <button type="submit" disabled={loading || code.length !== 6} className="btn-primary w-full">
                  {loading ? 'Verifying…' : 'Sign In'}
                </button>

                {mode === 'totp' && (
                  <button type="button" onClick={handleUseBackup} disabled={loading}
                    className="w-full text-sm text-blue-400 hover:text-blue-300 transition-colors">
                    Use backup code instead
                  </button>
                )}

                <button type="button" onClick={backToStart}
                  className="w-full text-sm text-gray-500 hover:text-gray-300 transition-colors">
                  ← Back
                </button>
                <p className="text-center text-xs text-gray-600">This sign-in session expires in 5 minutes.</p>
              </form>
            </>
          )}
        </div>

        <div className="mt-4 text-center">
          <Link to="/register" className="text-sm text-gray-500 hover:text-gray-300 transition-colors">
            No account? Request access
          </Link>
        </div>
      </div>
    </div>
  )
}
