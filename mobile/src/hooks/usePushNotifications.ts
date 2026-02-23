import { useEffect, useRef } from 'react'
import * as Device from 'expo-device'
import * as Notifications from 'expo-notifications'
import Constants from 'expo-constants'
import { Platform } from 'react-native'
import { registerPushToken } from '../api/profile'

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
})

export function usePushNotifications() {
  const notificationListener = useRef<Notifications.EventSubscription | null>(null)

  useEffect(() => {
    registerForPushNotifications()

    notificationListener.current = Notifications.addNotificationReceivedListener((notification) => {
      // Notification received in foreground — handler above shows it automatically
      console.log('Notification received:', notification.request.content.title)
    })

    return () => {
      notificationListener.current?.remove()
    }
  }, [])
}

async function registerForPushNotifications() {
  if (!Device.isDevice) {
    // Push notifications require a physical device
    return
  }

  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('default', {
      name: 'default',
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: '#3b82f6',
    })
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync()
  let finalStatus = existingStatus

  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync()
    finalStatus = status
  }

  if (finalStatus !== 'granted') {
    return
  }

  const projectId = Constants.expoConfig?.extra?.eas?.projectId
  if (!projectId) {
    console.warn('Push notifications: no EAS projectId configured — skipping token registration')
    return
  }

  try {
    const tokenData = await Notifications.getExpoPushTokenAsync({ projectId })
    const token = tokenData.data
    await registerPushToken(token)
  } catch (e) {
    console.warn('Failed to register push token:', e)
  }
}
