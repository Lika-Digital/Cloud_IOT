/**
 * Customer JWT storage — uses OS Keychain / Keystore on native (via
 * expo-secure-store) so a rooted device or backed-up filesystem cannot
 * extract the token. Falls back to AsyncStorage on web because SecureStore
 * is a native-only module.
 *
 * On first launch after the migration from plain AsyncStorage, readToken()
 * transparently promotes any existing token from AsyncStorage to SecureStore
 * and deletes the old copy, so existing customers are not logged out.
 */
import { Platform } from 'react-native'
import AsyncStorage from '@react-native-async-storage/async-storage'
import * as SecureStore from 'expo-secure-store'

const KEY = 'customer_token'


export async function writeToken(value: string): Promise<void> {
  if (Platform.OS === 'web') {
    await AsyncStorage.setItem(KEY, value)
    return
  }
  await SecureStore.setItemAsync(KEY, value)
}


export async function clearToken(): Promise<void> {
  if (Platform.OS === 'web') {
    await AsyncStorage.removeItem(KEY)
    return
  }
  await SecureStore.deleteItemAsync(KEY)
  // Best-effort cleanup of the legacy AsyncStorage entry, if any.
  try { await AsyncStorage.removeItem(KEY) } catch { /* ignore */ }
}


export async function readToken(): Promise<string | null> {
  if (Platform.OS === 'web') {
    return AsyncStorage.getItem(KEY)
  }
  const fromSecure = await SecureStore.getItemAsync(KEY)
  if (fromSecure) return fromSecure

  // One-shot migration: pick up the legacy plaintext token, move it, delete.
  try {
    const legacy = await AsyncStorage.getItem(KEY)
    if (legacy) {
      await SecureStore.setItemAsync(KEY, legacy)
      await AsyncStorage.removeItem(KEY)
      return legacy
    }
  } catch {
    // AsyncStorage read failure is non-fatal — user just signs in again.
  }
  return null
}
