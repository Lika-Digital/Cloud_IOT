import { useState } from 'react'

interface DenyDialogProps {
  sessionId: number
  onConfirm: (reason?: string) => Promise<void>
  onCancel: () => void
}

export default function DenyDialog({ onConfirm, onCancel }: DenyDialogProps) {
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(false)

  const handleConfirm = async () => {
    setLoading(true)
    try {
      await onConfirm(reason.trim() || undefined)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-full max-w-md shadow-2xl">
        <h3 className="text-lg font-bold text-white mb-2">Deny Session</h3>
        <p className="text-sm text-gray-400 mb-4">Optionally provide a reason for the customer.</p>
        <textarea
          className="w-full bg-gray-800 border border-gray-700 rounded-lg p-3 text-gray-200 text-sm resize-none focus:outline-none focus:border-red-500 mb-4"
          rows={3}
          placeholder="Reason (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <div className="flex gap-3">
          <button
            className="flex-1 py-2 rounded-lg bg-gray-700 text-gray-300 hover:bg-gray-600 text-sm font-medium transition-colors"
            onClick={onCancel}
            disabled={loading}
          >
            Cancel
          </button>
          <button
            className="flex-1 py-2 rounded-lg bg-red-600 text-white hover:bg-red-700 text-sm font-medium transition-colors disabled:opacity-50"
            onClick={handleConfirm}
            disabled={loading}
          >
            {loading ? 'Denying…' : 'Deny'}
          </button>
        </div>
      </div>
    </div>
  )
}
