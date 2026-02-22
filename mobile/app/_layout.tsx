import { useEffect } from 'react'
import { Stack, useRouter, useSegments } from 'expo-router'
import { GestureHandlerRootView } from 'react-native-gesture-handler'
import { useAuthStore } from '../src/store/authStore'

export default function RootLayout() {
  const { token, loaded, loadFromStorage } = useAuthStore()
  const router = useRouter()
  const segments = useSegments()

  useEffect(() => {
    loadFromStorage()
  }, [])

  useEffect(() => {
    if (!loaded) return  // wait until AsyncStorage is read
    const inAuth = segments[0] === '(auth)'
    if (!token && !inAuth) {
      router.replace('/(auth)/login')
    } else if (token && inAuth) {
      router.replace('/(app)')
    }
  }, [token, loaded, segments])

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="(auth)" />
        <Stack.Screen name="(app)" />
      </Stack>
    </GestureHandlerRootView>
  )
}
