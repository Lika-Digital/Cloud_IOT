import { useState } from 'react'
import {
  View, Text, StyleSheet, SafeAreaView, ScrollView,
  TextInput, TouchableOpacity, Alert, Switch,
} from 'react-native'
import { useRouter } from 'expo-router'
import { useAuthStore } from '../../src/store/authStore'
import { updateProfile } from '../../src/api/profile'
import * as Notifications from 'expo-notifications'

export default function ProfileScreen() {
  const { profile, logout, setProfile } = useAuthStore()
  const router = useRouter()

  const [name, setName] = useState(profile?.name ?? '')
  const [shipName, setShipName] = useState(profile?.ship_name ?? '')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const [notificationsEnabled, setNotificationsEnabled] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      const updated = await updateProfile({ name, ship_name: shipName })
      setProfile(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      Alert.alert('Error', 'Failed to update profile. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const handleToggleNotifications = async (value: boolean) => {
    if (value) {
      const { status } = await Notifications.requestPermissionsAsync()
      setNotificationsEnabled(status === 'granted')
    } else {
      setNotificationsEnabled(false)
    }
  }

  const handleLogout = () => {
    Alert.alert('Sign Out', 'Are you sure you want to sign out?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Sign Out',
        style: 'destructive',
        onPress: () => {
          logout()
          router.replace('/(auth)/login')
        },
      },
    ])
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.pageTitle}>Profile</Text>

        {/* Account info section */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Account Information</Text>
          <View style={styles.infoRow}>
            <Text style={styles.label}>Email</Text>
            <Text style={styles.value}>{profile?.email ?? '—'}</Text>
          </View>
          <View style={styles.inputGroup}>
            <Text style={styles.label}>Name</Text>
            <TextInput
              style={styles.input}
              value={name}
              onChangeText={setName}
              placeholder="Your name"
              placeholderTextColor="#6b7280"
            />
          </View>
          <View style={styles.inputGroup}>
            <Text style={styles.label}>Ship / Vessel Name</Text>
            <TextInput
              style={styles.input}
              value={shipName}
              onChangeText={setShipName}
              placeholder="Vessel name"
              placeholderTextColor="#6b7280"
            />
          </View>
          <TouchableOpacity
            style={[styles.saveBtn, saving && styles.saveBtnDisabled]}
            onPress={handleSave}
            disabled={saving}
          >
            <Text style={styles.saveBtnText}>
              {saved ? 'Saved!' : saving ? 'Saving…' : 'Save Changes'}
            </Text>
          </TouchableOpacity>
        </View>

        {/* Notifications section */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Notifications</Text>
          <View style={styles.toggleRow}>
            <Text style={styles.toggleLabel}>Session updates</Text>
            <Switch
              value={notificationsEnabled}
              onValueChange={handleToggleNotifications}
              trackColor={{ false: '#374151', true: '#2563eb' }}
              thumbColor="#fff"
            />
          </View>
          <Text style={styles.hint}>Receive push notifications when your session is approved or denied.</Text>
        </View>

        {/* Logout */}
        <TouchableOpacity style={styles.logoutBtn} onPress={handleLogout}>
          <Text style={styles.logoutText}>Sign Out</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#111827' },
  container: { padding: 20, gap: 20, paddingBottom: 40 },
  pageTitle: { color: '#fff', fontSize: 24, fontWeight: '800', marginBottom: 4 },
  section: {
    backgroundColor: '#1f2937',
    borderRadius: 16,
    padding: 16,
    gap: 12,
  },
  sectionTitle: { color: '#f9fafb', fontSize: 16, fontWeight: '700' },
  infoRow: { gap: 2 },
  inputGroup: { gap: 4 },
  label: { color: '#9ca3af', fontSize: 12 },
  value: { color: '#e5e7eb', fontSize: 15 },
  input: {
    backgroundColor: '#374151',
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    color: '#f9fafb',
    fontSize: 15,
  },
  saveBtn: {
    backgroundColor: '#2563eb',
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
    marginTop: 4,
  },
  saveBtnDisabled: { opacity: 0.5 },
  saveBtnText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  toggleLabel: { color: '#e5e7eb', fontSize: 15 },
  hint: { color: '#6b7280', fontSize: 12 },
  logoutBtn: {
    backgroundColor: '#7f1d1d',
    borderRadius: 14,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 8,
  },
  logoutText: { color: '#fca5a5', fontWeight: '700', fontSize: 16 },
})
