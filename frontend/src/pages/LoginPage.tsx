import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  authLogin, authFirstPassword, authTotpLogin, authTotpEnroll, authTotpEnrollVerify,
  type TokenResponse, type TotpSetupResponse,
} from '../api/auth'
import { useAuthStore } from '../store/authStore'

// v3.33 — TOTP is the only second factor (email OTP removed). The first login is
// a short wizard: credentials -> [set new password if forced] -> [enrol an
// authenticator if none yet, else enter the code] -> signed in.
type Step = 'credentials' | 'password' | 'enroll' | 'totp'

function errDetail(err: unknown, fallback: string): string {
  return (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? fallback
}

export default function LoginPage() {
  const navigate = useNavigate()
  const { setAuth } = useAuthStore()

  const [step, setStep] = useState<Step>('credentials')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [partialToken, setPartialToken] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [enroll, setEnroll] = useState<TotpSetupResponse | null>(null)
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const finish = (data: TokenResponse) => {
    setAuth(data.access_token, data.role, data.email)
    navigate('/dashboard', { replace: true })
  }

  // Begin TOTP: a user with an authenticator enters a code; a first-time user
  // fetches a QR to enrol one.
  const beginTotp = async (totpEnabled: boolean, token: string) => {
    if (totpEnabled) {
      setStep('totp'); setCode(''); return
    }
    setLoading(true)
    try {
      const qr = await authTotpEnroll(token)
      setEnroll(qr); setStep('enroll'); setCode('')
    } catch (err: unknown) {
      setError(errDetail(err, 'Could not start authenticator setup.'))
    } finally {
      setLoading(false)
    }
  }

  const handleCredentials = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null); setLoading(true)
    try {
      const data = await authLogin(email, password)
      setPartialToken(data.partial_token)
      if (data.must_change_password) {
        setNewPassword(''); setConfirmPassword(''); setStep('password')
      } else {
        await beginTotp(data.totp_enabled, data.partial_token)
      }
    } catch (err: unknown) {
      setError(errDetail(err, 'Login failed. Check your email and password.'))
    } finally {
      setLoading(false)
    }
  }

  const handleNewPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    if (newPassword.length < 8) { setError('Password must be at least 8 characters.'); return }
    if (newPassword !== confirmPassword) { setError('Passwords do not match.'); return }
    setError(null); setLoading(true)
    try {
      const r = await authFirstPassword(partialToken, newPassword)
      await beginTotp(r.totp_enabled, partialToken)   // continue to the second factor
    } catch (err: unknown) {
      setError(errDetail(err, 'Could not set the new password.'))
    } finally {
      setLoading(false)
    }
  }

  const submitTotpCode = async (codeVal: string) => {
    if (loading) return
    setError(null); setLoading(true)
    try {
      const data = step === 'enroll'
        ? await authTotpEnrollVerify(partialToken, codeVal)
        : await authTotpLogin(partialToken, codeVal)
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
    if (v.length === 6) void submitTotpCode(v)   // auto-submit on 6 digits
  }

  const backToStart = () => {
    setStep('credentials'); setCode(''); setError(null)
    setPartialToken(''); setEnroll(null); setNewPassword(''); setConfirmPassword('')
  }

  const inputCls =
    'w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-sm focus:outline-none focus:border-blue-500'

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="text-4xl mb-3">⚡</div>
          <h1 className="text-2xl font-bold text-gray-100">IoT Dashboard</h1>
          <p className="text-gray-500 text-sm mt-1">Smart Pedestal Management</p>
        </div>

        <div className="card">
          {/* ── Step 1: credentials ── */}
          {step === 'credentials' && (
            <>
              <h2 className="text-lg font-semibold text-gray-100 mb-4">Sign In</h2>
              <form onSubmit={handleCredentials} className="space-y-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Email</label>
                  <input
                    type="email" required autoFocus value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={inputCls} placeholder="you@example.com"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Password</label>
                  <input
                    type="password" required value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className={inputCls} placeholder="••••••••"
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
          )}

          {/* ── Step 2 (optional): forced password change ── */}
          {step === 'password' && (
            <>
              <h2 className="text-lg font-semibold text-gray-100 mb-1">Choose a new password</h2>
              <p className="text-sm text-gray-500 mb-4">
                This account uses a temporary password. Set your own to continue.
              </p>
              <form onSubmit={handleNewPassword} className="space-y-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">New password</label>
                  <input
                    type="password" required autoFocus minLength={8} value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className={inputCls} placeholder="At least 8 characters"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Confirm password</label>
                  <input
                    type="password" required minLength={8} value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className={inputCls} placeholder="Repeat new password"
                  />
                </div>
                {error && (
                  <div className="text-sm text-red-400 bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">{error}</div>
                )}
                <button type="submit" disabled={loading} className="btn-primary w-full">
                  {loading ? 'Saving…' : 'Set password & continue'}
                </button>
                <button type="button" onClick={backToStart}
                  className="w-full text-sm text-gray-500 hover:text-gray-300 transition-colors">← Back</button>
              </form>
            </>
          )}

          {/* ── Step 3a: TOTP enrolment (first login, no authenticator yet) ── */}
          {step === 'enroll' && (
            <>
              <h2 className="text-lg font-semibold text-gray-100 mb-1">Set up your authenticator</h2>
              <p className="text-sm text-gray-500 mb-4">
                Scan this QR code with Google Authenticator, 1Password, or any TOTP app,
                then enter the 6-digit code to finish signing in.
              </p>
              {enroll && (
                <div className="flex flex-col items-center mb-4">
                  <img src={`data:image/png;base64,${enroll.qr_code}`} alt="Authenticator QR code"
                    className="w-44 h-44 rounded-lg bg-white p-2" />
                  <p className="text-xs text-gray-500 mt-2">Can’t scan? Enter this key manually:</p>
                  <code className="text-xs text-gray-300 bg-gray-800 rounded px-2 py-1 mt-1 break-all">{enroll.secret}</code>
                </div>
              )}
              <form onSubmit={(e) => { e.preventDefault(); if (code.length === 6) void submitTotpCode(code) }} className="space-y-4">
                <input
                  type="text" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required autoFocus
                  value={code} onChange={(e) => onCodeChange(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-center tracking-[0.5em] text-xl font-mono focus:outline-none focus:border-blue-500"
                  placeholder="000000"
                />
                {error && (
                  <div className="text-sm text-red-400 bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">{error}</div>
                )}
                <button type="submit" disabled={loading || code.length !== 6} className="btn-primary w-full">
                  {loading ? 'Verifying…' : 'Confirm & Sign In'}
                </button>
                <button type="button" onClick={backToStart}
                  className="w-full text-sm text-gray-500 hover:text-gray-300 transition-colors">← Back</button>
                <p className="text-center text-xs text-gray-600">This sign-in session expires in 5 minutes.</p>
              </form>
            </>
          )}

          {/* ── Step 3b: TOTP code (existing authenticator) ── */}
          {step === 'totp' && (
            <>
              <h2 className="text-lg font-semibold text-gray-100 mb-1">Two-factor authentication</h2>
              <p className="text-sm text-gray-500 mb-4">
                Enter the 6-digit code from your authenticator app.
              </p>
              <form onSubmit={(e) => { e.preventDefault(); if (code.length === 6) void submitTotpCode(code) }} className="space-y-4">
                <input
                  type="text" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required autoFocus
                  value={code} onChange={(e) => onCodeChange(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-center tracking-[0.5em] text-xl font-mono focus:outline-none focus:border-blue-500"
                  placeholder="000000"
                />
                {error && (
                  <div className="text-sm text-red-400 bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">{error}</div>
                )}
                <button type="submit" disabled={loading || code.length !== 6} className="btn-primary w-full">
                  {loading ? 'Verifying…' : 'Sign In'}
                </button>
                <button type="button" onClick={backToStart}
                  className="w-full text-sm text-gray-500 hover:text-gray-300 transition-colors">← Back</button>
                <p className="text-center text-xs text-gray-600">
                  Lost your authenticator? Ask an administrator to reset your 2FA.
                </p>
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
