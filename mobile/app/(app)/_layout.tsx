import { Tabs } from 'expo-router'
import { Text } from 'react-native'

export default function AppLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarStyle: { backgroundColor: '#1f2937', borderTopColor: '#374151' },
        tabBarActiveTintColor: '#60a5fa',
        tabBarInactiveTintColor: '#6b7280',
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
      {/* Hidden tab screens (navigated to programmatically) */}
      <Tabs.Screen
        name="contracts"
        options={{ href: null }}
      />
      <Tabs.Screen
        name="services"
        options={{ href: null }}
      />
    </Tabs>
  )
}
