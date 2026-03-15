import { useColorScheme } from 'react-native'
import { useThemeStore } from '../store/themeStore'
import { dark, light } from '../theme'

export function useTheme() {
  const { mode } = useThemeStore()
  const systemScheme = useColorScheme()
  const isDark = mode === 'system' ? systemScheme === 'dark' : mode === 'dark'
  return isDark ? dark : light
}
