import React, { useState } from 'react'
import {
  View, Text, TextInput, TouchableOpacity,
  StyleSheet, KeyboardAvoidingView, Platform, ScrollView,
  ActivityIndicator, LayoutAnimation,
} from 'react-native'
import { Link } from 'expo-router'
import { register, getMe } from '../../src/api/auth'
import { useAuthStore } from '../../src/store/authStore'

// ─── Field hint definitions ──────────────────────────────────────────────────
const HELP_ITEMS = [
  { label: 'Email *', hint: 'Required. Must be a valid address, e.g. john@example.com. Used to log in.' },
  { label: 'Password *', hint: 'Required. Minimum 6 characters. Use letters, numbers or symbols.' },
  { label: 'Full Name', hint: 'Optional. Your first and last name as it will appear on invoices.' },
  { label: 'Ship Name', hint: 'Optional. Name of your vessel (e.g. "Blue Wave").' },
  { label: 'VAT Number', hint: 'Optional. Your tax/VAT ID for billing purposes.' },
  { label: 'Ship Registration', hint: 'Optional. Official vessel registration number (e.g. "HR-ST-123").' },
]

// ─── Extract a readable message from any Axios error ─────────────────────────
function extractError(e: any): string {
  if (e?.code === 'ECONNABORTED' || e?.message?.includes('timeout')) {
    return 'Request timed out.\nMake sure:\n• Phone and PC are on the same Wi-Fi\n• Backend is running with --host 0.0.0.0\n• EXPO_PUBLIC_API_URL is set to the PC\'s LAN IP (not localhost)'
  }
  if (!e?.response) {
    return 'Cannot connect to server.\nMake sure:\n• Phone and PC are on the same Wi-Fi\n• Backend is running with --host 0.0.0.0\n• EXPO_PUBLIC_API_URL is set to the PC\'s LAN IP (not localhost)'
  }
  const detail = e.response.data?.detail
  if (Array.isArray(detail) && detail.length > 0) {
    // Pydantic 422 validation error — each item has .msg
    return detail.map((d: any) => d.msg ?? String(d)).join('\n')
  }
  if (typeof detail === 'string') return detail
  return `Server error (${e.response.status}). Please try again.`
}

// ─── Client-side validation ───────────────────────────────────────────────────
function validate(email: string, password: string): string | null {
  const trimEmail = email.trim()
  if (!trimEmail) return 'Email is required.'
  const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  if (!emailRe.test(trimEmail)) return 'Enter a valid email address (e.g. john@example.com).'
  if (!password) return 'Password is required.'
  if (password.length < 6) return 'Password must be at least 6 characters.'
  return null
}

// ─── Component ────────────────────────────────────────────────────────────────
export default function RegisterScreen() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [shipName, setShipName] = useState('')
  const [vatNumber, setVatNumber] = useState('')
  const [shipReg, setShipReg] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [helpOpen, setHelpOpen] = useState(false)
  const { setToken, setProfile } = useAuthStore()

  const toggleHelp = () => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut)
    setHelpOpen((v) => !v)
  }

  const handleRegister = async () => {
    setError('')
    const validationError = validate(email, password)
    if (validationError) {
      setError(validationError)
      return
    }
    setLoading(true)
    try {
      const { access_token } = await register({
        email: email.trim(),
        password,
        name: name.trim() || undefined,
        ship_name: shipName.trim() || undefined,
        vat_number: vatNumber.trim() || undefined,
        ship_registration: shipReg.trim() || undefined,
      })
      setToken(access_token)
      const profile = await getMe()
      setProfile(profile)
    } catch (e: any) {
      setError(extractError(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>Create Account</Text>
        <Text style={styles.subtitle}>Register to use marina services</Text>

        {/* ── Help panel ─────────────────────────────────────────────────── */}
        <TouchableOpacity style={styles.helpToggle} onPress={toggleHelp} activeOpacity={0.7}>
          <Text style={styles.helpToggleText}>
            {helpOpen ? '▲  Hide field guide' : '▼  Registration help & field guide'}
          </Text>
        </TouchableOpacity>

        {helpOpen && (
          <View style={styles.helpPanel}>
            <Text style={styles.helpTitle}>Field Guide</Text>
            {HELP_ITEMS.map((item) => (
              <View key={item.label} style={styles.helpRow}>
                <Text style={styles.helpLabel}>{item.label}</Text>
                <Text style={styles.helpHint}>{item.hint}</Text>
              </View>
            ))}
            <View style={styles.helpDivider} />
            <Text style={styles.helpNote}>
              Fields marked * are required. All other fields are optional and can be updated later.
            </Text>
          </View>
        )}

        {/* ── Form ───────────────────────────────────────────────────────── */}
        <View style={styles.form}>
          <LabeledInput
            label="Email *"
            placeholder="john@example.com"
            value={email}
            onChangeText={setEmail}
            keyboardType="email-address"
            maxLength={120}
          />
          <LabeledInput
            label="Password *"
            placeholder="Min. 6 characters"
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            maxLength={128}
          />
          <LabeledInput
            label="Full Name"
            placeholder="John Smith  (optional)"
            value={name}
            onChangeText={setName}
            autoCapitalize="words"
            maxLength={120}
          />
          <LabeledInput
            label="Ship Name"
            placeholder="Blue Wave  (optional)"
            value={shipName}
            onChangeText={setShipName}
            autoCapitalize="words"
            maxLength={120}
          />
          <LabeledInput
            label="VAT Number"
            placeholder="e.g. HR12345678  (optional)"
            value={vatNumber}
            onChangeText={setVatNumber}
            maxLength={40}
          />
          <LabeledInput
            label="Ship Registration"
            placeholder="e.g. HR-ST-123  (optional)"
            value={shipReg}
            onChangeText={setShipReg}
            maxLength={60}
          />

          {error ? <Text style={styles.error}>{error}</Text> : null}

          <TouchableOpacity style={styles.btn} onPress={handleRegister} disabled={loading}>
            {loading
              ? <ActivityIndicator color="#fff" />
              : <Text style={styles.btnText}>Create Account</Text>}
          </TouchableOpacity>

          <Link href="/(auth)/login" style={styles.link}>
            Already have an account? Sign in
          </Link>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  )
}

// ─── Labeled input component ──────────────────────────────────────────────────
interface LabeledInputProps extends React.ComponentProps<typeof TextInput> {
  label: string
}
function LabeledInput({ label, ...props }: LabeledInputProps) {
  return (
    <View>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        autoCapitalize="none"
        {...props}
        style={[styles.input, props.style]}
        placeholderTextColor="#4b5563"
      />
    </View>
  )
}

// ─── Styles ───────────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: '#111827' },
  container: { flexGrow: 1, padding: 24, paddingTop: 60, paddingBottom: 40 },

  title: { color: '#fff', fontSize: 26, fontWeight: '800', textAlign: 'center' },
  subtitle: { color: '#6b7280', textAlign: 'center', marginBottom: 16 },

  // help toggle
  helpToggle: {
    alignSelf: 'center',
    marginBottom: 12,
    paddingVertical: 6,
    paddingHorizontal: 14,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#374151',
  },
  helpToggleText: { color: '#60a5fa', fontSize: 13, fontWeight: '600' },

  // help panel
  helpPanel: {
    backgroundColor: '#1e2d47',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#2563eb55',
  },
  helpTitle: { color: '#93c5fd', fontWeight: '700', fontSize: 14, marginBottom: 10 },
  helpRow: { marginBottom: 8 },
  helpLabel: { color: '#f9fafb', fontWeight: '600', fontSize: 13 },
  helpHint: { color: '#9ca3af', fontSize: 12, marginTop: 2, lineHeight: 17 },
  helpDivider: { height: 1, backgroundColor: '#374151', marginVertical: 10 },
  helpNote: { color: '#6b7280', fontSize: 12, lineHeight: 17 },

  // form
  form: { gap: 10 },
  fieldLabel: { color: '#d1d5db', fontSize: 12, fontWeight: '600', marginBottom: 4, marginLeft: 2 },
  input: {
    backgroundColor: '#1f2937',
    borderWidth: 1,
    borderColor: '#374151',
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 13,
    color: '#fff',
    fontSize: 15,
  },

  error: {
    color: '#ef4444',
    fontSize: 13,
    lineHeight: 19,
    textAlign: 'center',
    backgroundColor: '#1f1515',
    borderRadius: 8,
    padding: 10,
  },
  btn: {
    backgroundColor: '#2563eb',
    paddingVertical: 15,
    borderRadius: 10,
    alignItems: 'center',
    marginTop: 4,
  },
  btnText: { color: '#fff', fontWeight: '700', fontSize: 16 },
  link: { color: '#60a5fa', textAlign: 'center', fontSize: 14, paddingVertical: 4 },
})
