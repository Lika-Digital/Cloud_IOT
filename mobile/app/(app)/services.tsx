import { useState } from 'react'
import {
  View, Text, StyleSheet, SafeAreaView, ScrollView,
  TouchableOpacity, TextInput, Alert, ActivityIndicator,
} from 'react-native'
import { submitServiceOrder } from '../../src/api/serviceOrders'

const SERVICES = [
  { type: 'crane', label: 'Crane', icon: '🏗️', description: 'Crane lifting service for your vessel' },
  { type: 'engine_check', label: 'Engine Check', icon: '⚙️', description: 'Professional engine inspection' },
  { type: 'hull_clean', label: 'Hull Clean', icon: '🚢', description: 'Hull cleaning and anti-fouling' },
  { type: 'diver', label: 'Diver', icon: '🤿', description: 'Underwater inspection and services' },
  { type: 'battery_check', label: 'Battery Check', icon: '🔋', description: 'Battery test and maintenance' },
  { type: 'electrical_check', label: 'Electrical', icon: '⚡', description: 'Onboard electrical inspection' },
]

export default function ServicesScreen() {
  const [selectedType, setSelectedType] = useState<string | null>(null)
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!selectedType) return
    setSubmitting(true)
    try {
      await submitServiceOrder(selectedType, notes.trim() || undefined)
      Alert.alert(
        'Request Submitted!',
        'Marina staff will contact you shortly.',
        [{ text: 'OK', onPress: () => { setSelectedType(null); setNotes('') } }]
      )
    } catch {
      Alert.alert('Error', 'Failed to submit request. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.pageTitle}>Marina Services</Text>
        <Text style={styles.subtitle}>Select a service to request assistance from marina staff</Text>

        {/* Service grid */}
        <View style={styles.grid}>
          {SERVICES.map((service) => (
            <TouchableOpacity
              key={service.type}
              style={[
                styles.serviceCard,
                selectedType === service.type && styles.serviceCardSelected,
              ]}
              onPress={() => setSelectedType(selectedType === service.type ? null : service.type)}
            >
              <Text style={styles.serviceIcon}>{service.icon}</Text>
              <Text style={styles.serviceLabel}>{service.label}</Text>
              <Text style={styles.serviceDesc}>{service.description}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* Order form */}
        {selectedType && (
          <View style={styles.form}>
            <Text style={styles.formTitle}>
              {SERVICES.find((s) => s.type === selectedType)?.icon}{' '}
              {SERVICES.find((s) => s.type === selectedType)?.label}
            </Text>
            <Text style={styles.formLabel}>Additional notes (optional)</Text>
            <TextInput
              style={styles.notesInput}
              value={notes}
              onChangeText={setNotes}
              placeholder="Describe any specific requirements..."
              placeholderTextColor="#6b7280"
              multiline
              numberOfLines={4}
              textAlignVertical="top"
            />
            <TouchableOpacity
              style={[styles.submitBtn, submitting && styles.submitBtnDisabled]}
              onPress={handleSubmit}
              disabled={submitting}
            >
              {submitting ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.submitBtnText}>Submit Request</Text>
              )}
            </TouchableOpacity>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#111827' },
  container: { padding: 20, gap: 20, paddingBottom: 40 },
  pageTitle: { color: '#fff', fontSize: 24, fontWeight: '800' },
  subtitle: { color: '#6b7280', fontSize: 14 },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
  },
  serviceCard: {
    width: '47%',
    backgroundColor: '#1f2937',
    borderRadius: 16,
    padding: 16,
    gap: 6,
    borderWidth: 2,
    borderColor: 'transparent',
  },
  serviceCardSelected: {
    borderColor: '#2563eb',
    backgroundColor: '#1e3a5f',
  },
  serviceIcon: { fontSize: 28 },
  serviceLabel: { color: '#f9fafb', fontSize: 14, fontWeight: '700' },
  serviceDesc: { color: '#9ca3af', fontSize: 11, lineHeight: 15 },
  form: {
    backgroundColor: '#1f2937',
    borderRadius: 16,
    padding: 16,
    gap: 12,
    borderWidth: 2,
    borderColor: '#2563eb',
  },
  formTitle: { color: '#fff', fontSize: 18, fontWeight: '700' },
  formLabel: { color: '#9ca3af', fontSize: 12 },
  notesInput: {
    backgroundColor: '#374151',
    borderRadius: 10,
    padding: 12,
    color: '#f9fafb',
    fontSize: 14,
    minHeight: 100,
  },
  submitBtn: {
    backgroundColor: '#2563eb',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  submitBtnDisabled: { opacity: 0.5 },
  submitBtnText: { color: '#fff', fontWeight: '700', fontSize: 16 },
})
