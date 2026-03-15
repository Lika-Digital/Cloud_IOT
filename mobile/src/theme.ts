export interface AppTheme {
  isDark: boolean
  bg: string
  bgSecondary: string
  card: string
  cardAlt: string
  border: string
  textPrimary: string
  textSecondary: string
  textMuted: string
  accent: string
  accentLight: string
  accentBg: string
  tabBar: string
  tabBorder: string
  inputBg: string
  danger: string
  success: string
  warning: string
  marinaCard: string
  marinaBorder: string
}

export const dark: AppTheme = {
  isDark: true,
  bg: '#0f172a',
  bgSecondary: '#111827',
  card: '#1e293b',
  cardAlt: '#162032',
  border: '#334155',
  textPrimary: '#f1f5f9',
  textSecondary: '#cbd5e1',
  textMuted: '#64748b',
  accent: '#2563eb',
  accentLight: '#60a5fa',
  accentBg: '#1e3a5f',
  tabBar: '#1e293b',
  tabBorder: '#334155',
  inputBg: '#334155',
  danger: '#ef4444',
  success: '#22c55e',
  warning: '#f59e0b',
  marinaCard: '#1e3a5f',
  marinaBorder: '#2563eb40',
}

export const light: AppTheme = {
  isDark: false,
  bg: '#f0f4f8',
  bgSecondary: '#f8fafc',
  card: '#ffffff',
  cardAlt: '#f1f5f9',
  border: '#e2e8f0',
  textPrimary: '#0f172a',
  textSecondary: '#334155',
  textMuted: '#94a3b8',
  accent: '#2563eb',
  accentLight: '#3b82f6',
  accentBg: '#dbeafe',
  tabBar: '#ffffff',
  tabBorder: '#e2e8f0',
  inputBg: '#f1f5f9',
  danger: '#dc2626',
  success: '#16a34a',
  warning: '#d97706',
  marinaCard: '#1e40af',
  marinaBorder: '#3b82f640',
}
