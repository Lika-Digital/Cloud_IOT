import { useState } from 'react'
import {
  View, Text, TextInput, TouchableOpacity,
  StyleSheet, KeyboardAvoidingView, Platform, ScrollView, ActivityIndicator,
} from 'react-native'
import { Link } from 'expo-router'
import { login, getMe } from '../../src/api/auth'
import { useAuthStore } from '../../src/store/authStore'

export default function LoginScreen() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { setToken, setProfile } = useAuthStore()

  const handleLogin = async () => {
    setLoading(true)
    setError('')
    try {
      const { access_token } = await login(email.trim(), password)
      setToken(access_token)
      const profile = await getMe()
      setProfile(profile)
    } catch (e: any) {
      if (e?.code === 'ECONNABORTED' || e?.message?.includes('timeout')) {
        setError('Request timed out.\nCheck Wi-Fi and that the backend runs with --host 0.0.0.0')
      } else if (!e?.response) {
        setError('Cannot connect to server.\nCheck Wi-Fi and EXPO_PUBLIC_API_URL in .env')
      } else {
        setError(e?.response?.data?.detail ?? 'Login failed')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <Text style={styles.logo}>⚓</Text>
        <Text style={styles.title}>Marina IoT</Text>
        <Text style={styles.subtitle}>Sign in to your account</Text>

        <View style={styles.form}>
          <TextInput
            style={styles.input}
            placeholder="Email"
            placeholderTextColor="#6b7280"
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            keyboardType="email-address"
          />
          <TextInput
            style={styles.input}
            placeholder="Password"
            placeholderTextColor="#6b7280"
            value={password}
            onChangeText={setPassword}
            secureTextEntry
          />
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <TouchableOpacity style={styles.btn} onPress={handleLogin} disabled={loading}>
            {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnText}>Sign In</Text>}
          </TouchableOpacity>
          <Link href="/(auth)/register" style={styles.link}>
            Don't have an account? Register
          </Link>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  )
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: '#111827' },
  container: { flexGrow: 1, justifyContent: 'center', padding: 24 },
  logo: { fontSize: 64, textAlign: 'center' },
  title: { color: '#fff', fontSize: 28, fontWeight: '800', textAlign: 'center', marginTop: 8 },
  subtitle: { color: '#6b7280', textAlign: 'center', marginBottom: 32 },
  form: { gap: 14 },
  input: {
    backgroundColor: '#1f2937',
    borderWidth: 1,
    borderColor: '#374151',
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 14,
    color: '#fff',
    fontSize: 16,
  },
  error: { color: '#ef4444', textAlign: 'center', fontSize: 14 },
  btn: {
    backgroundColor: '#2563eb',
    paddingVertical: 15,
    borderRadius: 10,
    alignItems: 'center',
  },
  btnText: { color: '#fff', fontWeight: '700', fontSize: 16 },
  link: { color: '#60a5fa', textAlign: 'center', fontSize: 14, paddingVertical: 4 },
})
