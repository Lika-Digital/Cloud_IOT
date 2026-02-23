import { useEffect, useRef } from 'react'
import Constants from 'expo-constants'

// expo-notifications remote push was removed from Expo Go in SDK 53.
// Only load the module in real device builds (development build or standalone).
const IS_EXPO_GO = Constants.appOwnership === 'expo'

export function usePushNotifications() {
  const notificationListener = useRef<any>(null)

  useEffect(() => {
    if (IS_EXPO_GO) return  // push not supported in Expo Go SDK 53+

    async function setup() {
      const Notifications = await import('expo-notifications')
      const Device      = await import('expo-device')
      const { Platform } = await import('react-native')

      Notifications.setNotificationHandler({
        handleNotification: async () => ({
          shouldShowAlert: true,
          shouldPlaySound: true,
          shouldSetBadge: false,
          shouldShowBanner: true,
          shouldShowList: true,
        }),
      })

      notificationListener.current = Notifications.addNotificationReceivedListener(
        (notification: any) => {
          console.log('Notification received:', notification.request.content.title)
        },
      )

      if (!Device.isDevice) return

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
      if (finalStatus !== 'granted') return

      const projectId = Constants.expoConfig?.extra?.eas?.projectId
      if (!projectId) {
        console.warn('Push notifications: no EAS projectId configured — skipping token registration')
        return
      }

      try {
        const { registerPushToken } = await import('../api/profile')
        const tokenData = await Notifications.getExpoPushTokenAsync({ projectId })
        await registerPushToken(tokenData.data)
      } catch (e) {
        console.warn('Failed to register push token:', e)
      }
    }

    setup()

    return () => {
      notificationListener.current?.remove()
    }
  }, [])
}
