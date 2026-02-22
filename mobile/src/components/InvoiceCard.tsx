import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native'
import { useState } from 'react'
import { payInvoice, type Invoice } from '../api/invoices'

interface Props {
  invoice: Invoice
  onPaid: (updated: Invoice) => void
}

export function InvoiceCard({ invoice, onPaid }: Props) {
  const [paying, setPaying] = useState(false)

  const handlePay = async () => {
    setPaying(true)
    try {
      const updated = await payInvoice(invoice.id)
      onPaid(updated)
    } finally {
      setPaying(false)
    }
  }

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>Invoice #{invoice.id}</Text>
        <View style={[styles.badge, invoice.paid ? styles.paidBadge : styles.unpaidBadge]}>
          <Text style={[styles.badgeText, invoice.paid ? styles.paidText : styles.unpaidText]}>
            {invoice.paid ? 'Paid' : 'Unpaid'}
          </Text>
        </View>
      </View>
      <Text style={styles.date}>{new Date(invoice.created_at).toLocaleDateString()}</Text>
      <View style={styles.rows}>
        {invoice.energy_kwh != null && (
          <Row label="Energy" value={`${invoice.energy_kwh.toFixed(4)} kWh`} cost={invoice.energy_cost_eur} />
        )}
        {invoice.water_liters != null && (
          <Row label="Water" value={`${invoice.water_liters.toFixed(2)} L`} cost={invoice.water_cost_eur} />
        )}
      </View>
      <View style={styles.totalRow}>
        <Text style={styles.totalLabel}>Total</Text>
        <Text style={styles.totalValue}>€{invoice.total_eur.toFixed(2)}</Text>
      </View>
      {!invoice.paid && (
        <TouchableOpacity style={styles.payBtn} onPress={handlePay} disabled={paying}>
          {paying ? <ActivityIndicator color="#fff" /> : <Text style={styles.payText}>Pay Now</Text>}
        </TouchableOpacity>
      )}
    </View>
  )
}

function Row({ label, value, cost }: { label: string; value: string; cost: number | null | undefined }) {
  return (
    <View style={rowStyles.row}>
      <Text style={rowStyles.label}>{label}</Text>
      <Text style={rowStyles.value}>{value}</Text>
      {cost != null && <Text style={rowStyles.cost}>€{cost.toFixed(4)}</Text>}
    </View>
  )
}

const rowStyles = StyleSheet.create({
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 4 },
  label: { color: '#9ca3af', fontSize: 14 },
  value: { color: '#d1d5db', fontSize: 14, fontFamily: 'monospace' },
  cost: { color: '#d1d5db', fontSize: 14, fontFamily: 'monospace' },
})

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#1f2937',
    borderRadius: 14,
    padding: 18,
    marginBottom: 12,
    gap: 8,
  },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  title: { color: '#fff', fontWeight: '700', fontSize: 16 },
  badge: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 20 },
  paidBadge: { backgroundColor: '#166534' },
  unpaidBadge: { backgroundColor: '#7c2d12' },
  badgeText: { fontSize: 12, fontWeight: '600' },
  paidText: { color: '#4ade80' },
  unpaidText: { color: '#fca5a5' },
  date: { color: '#6b7280', fontSize: 12 },
  rows: { borderTopWidth: 1, borderTopColor: '#374151', paddingTop: 8 },
  totalRow: {
    flexDirection: 'row', justifyContent: 'space-between',
    borderTopWidth: 1, borderTopColor: '#374151', paddingTop: 8,
  },
  totalLabel: { color: '#9ca3af', fontWeight: '600', fontSize: 15 },
  totalValue: { color: '#4ade80', fontWeight: '700', fontSize: 18, fontFamily: 'monospace' },
  payBtn: {
    backgroundColor: '#2563eb', paddingVertical: 12,
    borderRadius: 10, alignItems: 'center', marginTop: 4,
  },
  payText: { color: '#fff', fontWeight: '700', fontSize: 15 },
})
