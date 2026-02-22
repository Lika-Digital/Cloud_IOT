import { View, Text, StyleSheet } from 'react-native'

interface Props {
  message: string
  direction: 'from_customer' | 'from_operator'
  createdAt: string
}

export function ChatBubble({ message, direction, createdAt }: Props) {
  const isMine = direction === 'from_customer'
  return (
    <View style={[styles.row, isMine ? styles.rowRight : styles.rowLeft]}>
      <View style={[styles.bubble, isMine ? styles.bubbleMine : styles.bubbleOther]}>
        <Text style={styles.text}>{message}</Text>
        <Text style={styles.time}>{new Date(createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</Text>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  row: { marginVertical: 4, paddingHorizontal: 12 },
  rowLeft: { alignItems: 'flex-start' },
  rowRight: { alignItems: 'flex-end' },
  bubble: { maxWidth: '75%', padding: 12, borderRadius: 16 },
  bubbleMine: { backgroundColor: '#2563eb', borderBottomRightRadius: 4 },
  bubbleOther: { backgroundColor: '#374151', borderBottomLeftRadius: 4 },
  text: { color: '#fff', fontSize: 15 },
  time: { color: 'rgba(255,255,255,0.6)', fontSize: 11, marginTop: 4, textAlign: 'right' },
})
