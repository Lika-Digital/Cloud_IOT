import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authLogin, authVerifyOtp } from '../api/auth'
import { useAuthStore } from '../store/authStore'

type Step = 'credentials' | 'otp'

export default function LoginPage() {
  const navigate = useNavigate()
  const { setAuth } = useAuthStore()

  const [step, setStep] = useState<Step>('credentials')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [otp, setOtp] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleCredentials = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await authLogin(email, password)
      setStep('otp')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Login failed. Check your email and password.')
    } finally {
      setLoading(false)
    }
  }

  const handleOtp = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const data = await authVerifyOtp(email, otp)
      setAuth(data.access_token, data.role, data.email)
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Invalid or expired code.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Header */}
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
                    type="email"
                    required
                    autoFocus
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
                    placeholder="you@example.com"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Password</label>
                  <input
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
                    placeholder="••••••••"
                  />
                </div>

                {error && (
                  <div className="text-sm text-red-400 bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">
                    {error}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={loading}
                  className="btn-primary w-full"
                >
                  {loading ? 'Sending code…' : 'Continue'}
                </button>
              </form>
            </>
          ) : (
            <>
              <h2 className="text-lg font-semibold text-white mb-1">Enter verification code</h2>
              <p className="text-sm text-gray-500 mb-4">
                A 6-digit code was sent to <span className="text-gray-300">{email}</span>.
                Check your email (or the server console in dev mode).
              </p>
              <form onSubmit={handleOtp} className="space-y-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Verification code</label>
                  <input
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    required
                    autoFocus
                    value={otp}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm text-center tracking-[0.5em] text-xl font-mono focus:outline-none focus:border-blue-500"
                    placeholder="000000"
                  />
                </div>

                {error && (
                  <div className="text-sm text-red-400 bg-red-900/20 border border-red-700/30 rounded-lg px-3 py-2">
                    {error}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={loading || otp.length !== 6}
                  className="btn-primary w-full"
                >
                  {loading ? 'Verifying…' : 'Sign In'}
                </button>

                <button
                  type="button"
                  onClick={() => { setStep('credentials'); setOtp(''); setError(null) }}
                  className="w-full text-sm text-gray-500 hover:text-gray-300 transition-colors"
                >
                  ← Back
                </button>
              </form>
            </>
          )}
        </div>

        {/* Default credentials are available in the server console on first startup */}
      </div>
    </div>
  )
}
