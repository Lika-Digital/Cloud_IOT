import { useCallback } from 'react'
import { Tabs } from 'expo-router'
import { Text } from 'react-native'
import { useTheme } from '../../src/hooks/useTheme'
import { useWebSocket } from '../../src/hooks/useWebSocket'
import { useSessionStore, type IncomingChatMessage } from '../../src/store/sessionStore'

export default function AppLayout() {
  const t = useTheme()
  const { setLatestChatMsg } = useSessionStore()

  // Route incoming chat messages to the store so the Chat screen can pick them up.
  const handleChatMsg = useCallback((msg: IncomingChatMessage) => {
    setLatestChatMsg(msg)
  }, [setLatestChatMsg])

  // Single persistent WS connection for the entire app session.
  // Lives here (layout) so it stays connected regardless of active tab.
  useWebSocket(handleChatMsg)

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarStyle: {
          backgroundColor: t.tabBar,
          borderTopColor: t.tabBorder,
          borderTopWidth: 1,
        },
        tabBarActiveTintColor: t.accentLight,
        tabBarInactiveTintColor: t.textMuted,
      }}
    >
      <Tabs.Screen
        name="index"
        options={{ title: 'Home', tabBarIcon: () => <Text style={{ fontSize: 20 }}>🏠</Text> }}
      />
      <Tabs.Screen
        name="history"
        options={{ title: 'History', tabBarIcon: () => <Text style={{ fontSize: 20 }}>📋</Text> }}
      />
      <Tabs.Screen
        name="chat"
        options={{ title: 'Chat', tabBarIcon: () => <Text style={{ fontSize: 20 }}>💬</Text> }}
      />
      <Tabs.Screen
        name="profile"
        options={{ title: 'Profile', tabBarIcon: () => <Text style={{ fontSize: 20 }}>👤</Text> }}
      />
      <Tabs.Screen name="contracts" options={{ href: null }} />
      <Tabs.Screen name="services" options={{ href: null }} />
    </Tabs>
  )
}
