import { useState, useEffect } from 'react'
import { getCustomers, type CustomerRow } from '../api/billing'
import { useStore } from '../store'
import ChatPanel from '../components/chat/ChatPanel'

export default function Users() {
  const [customers, setCustomers] = useState<CustomerRow[]>([])
  const [chatCustomer, setChatCustomer] = useState<CustomerRow | null>(null)
  const { unreadChatCount, setUnreadChatCount } = useStore()

  useEffect(() => {
    getCustomers().then(setCustomers)
  }, [])

  const handleOpenChat = (customer: CustomerRow) => {
    setChatCustomer(customer)
  }

  const handleCloseChat = () => {
    setChatCustomer(null)
    setUnreadChatCount(0)
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Customers</h1>
        <p className="text-gray-400 text-sm mt-1">Registered marina customers and their activity</p>
      </div>

      {customers.length === 0 ? (
        <div className="card text-center py-12 text-gray-500">
          <p className="text-4xl mb-3">👥</p>
          <p>No customers registered yet.</p>
        </div>
      ) : (
        <div className="card">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700 text-gray-400 text-left">
                  <th className="py-2 pr-4">Name / Email</th>
                  <th className="py-2 pr-4">Ship</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Registered</th>
                  <th className="py-2">Chat</th>
                </tr>
              </thead>
              <tbody>
                {customers.map((c) => (
                  <tr key={c.id} className="border-b border-gray-800 hover:bg-gray-800/50">
                    <td className="py-3 pr-4">
                      <div className="text-gray-200 font-medium">{c.name ?? '—'}</div>
                      <div className="text-xs text-gray-500">{c.email}</div>
                    </td>
                    <td className="py-3 pr-4 text-gray-300">{c.ship_name ?? '—'}</td>
                    <td className="py-3 pr-4">
                      {c.active_session_id ? (
                        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                          c.active_session_type === 'electricity'
                            ? 'bg-blue-900/40 text-blue-300 border border-blue-700/40'
                            : 'bg-cyan-900/40 text-cyan-300 border border-cyan-700/40'
                        }`}>
                          {c.active_session_type === 'electricity' ? '⚡ Active' : '💧 Active'}
                        </span>
                      ) : (
                        <span className="text-gray-600 text-xs">Idle</span>
                      )}
                    </td>
                    <td className="py-3 pr-4 text-gray-500 text-xs">
                      {new Date(c.created_at).toLocaleDateString()}
                    </td>
                    <td className="py-3">
                      <button
                        className="px-3 py-1.5 bg-gray-700 text-gray-300 hover:bg-gray-600 rounded-lg text-xs font-medium transition-colors"
                        onClick={() => handleOpenChat(c)}
                      >
                        Chat
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {chatCustomer && (
        <ChatPanel
          customerId={chatCustomer.id}
          customerName={chatCustomer.name}
          customerEmail={chatCustomer.email}
          onClose={handleCloseChat}
        />
      )}
    </div>
  )
}
