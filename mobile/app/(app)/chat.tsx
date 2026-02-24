import { useState, useEffect, useRef, useCallback } from 'react'
import {
  View, Text, TextInput, TouchableOpacity,
  FlatList, StyleSheet, SafeAreaView, KeyboardAvoidingView, Platform,
  ActivityIndicator,
} from 'react-native'
import { getMyMessages, sendMessage, type ChatMessage } from '../../src/api/chat'
import { ChatBubble } from '../../src/components/ChatBubble'
import { useWebSocket } from '../../src/hooks/useWebSocket'
import { useAuthStore } from '../../src/store/authStore'

export default function ChatScreen() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const flatRef = useRef<FlatList>(null)
  const inFlight = useRef(false)
  const { profile } = useAuthStore()

  const handleIncoming = useCallback((msg: any) => {
    if (msg.customer_id === profile?.id) {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now(),
          customer_id: msg.customer_id,
          message: msg.message,
          direction: msg.direction,
          created_at: msg.created_at,
          read_at: null,
        },
      ])
    }
  }, [profile?.id])

  useWebSocket(handleIncoming)

  const loadMessages = () => {
    setLoadError(false)
    setLoading(true)
    getMyMessages().then((msgs) => {
      setMessages(msgs)
      setLoading(false)
    }).catch(() => {
      setLoadError(true)
      setLoading(false)
    })
  }

  useEffect(() => {
    loadMessages()
  }, [])

  useEffect(() => {
    if (messages.length > 0) {
      flatRef.current?.scrollToEnd({ animated: true })
    }
  }, [messages])

  const handleSend = async () => {
    const msg = text.trim()
    if (!msg || inFlight.current) return
    inFlight.current = true
    setSending(true)
    try {
      const sent = await sendMessage(msg)
      setMessages((prev) => [...prev, sent])
      setText('')
    } finally {
      inFlight.current = false
      setSending(false)
    }
  }

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={90}
      >
        <View style={styles.header}>
          <Text style={styles.headerTitle}>Marina Support</Text>
        </View>

        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} color="#60a5fa" />
        ) : loadError ? (
          <TouchableOpacity style={styles.errorContainer} onPress={loadMessages}>
            <Text style={styles.errorText}>Could not load messages — tap to retry</Text>
          </TouchableOpacity>
        ) : (
          <FlatList
            ref={flatRef}
            data={messages}
            keyExtractor={(item) => String(item.id)}
            renderItem={({ item }) => (
              <ChatBubble
                message={item.message}
                direction={item.direction}
                createdAt={item.created_at}
              />
            )}
            contentContainerStyle={styles.list}
            ListEmptyComponent={<Text style={styles.empty}>No messages yet. Say hello!</Text>}
          />
        )}

        <View style={styles.inputRow}>
          <TextInput
            style={styles.input}
            placeholder="Type a message…"
            placeholderTextColor="#6b7280"
            value={text}
            onChangeText={setText}
            multiline
          />
          <TouchableOpacity style={styles.sendBtn} onPress={handleSend} disabled={sending || !text.trim()}>
            {sending ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.sendText}>Send</Text>}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#111827' },
  flex: { flex: 1 },
  header: { padding: 16, borderBottomWidth: 1, borderBottomColor: '#1f2937' },
  headerTitle: { color: '#fff', fontSize: 18, fontWeight: '700', textAlign: 'center' },
  list: { paddingVertical: 12 },
  empty: { color: '#6b7280', textAlign: 'center', marginTop: 40 },
  inputRow: {
    flexDirection: 'row',
    padding: 12,
    gap: 8,
    borderTopWidth: 1,
    borderTopColor: '#1f2937',
    backgroundColor: '#111827',
  },
  input: {
    flex: 1,
    backgroundColor: '#1f2937',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 10,
    color: '#fff',
    fontSize: 15,
    maxHeight: 100,
  },
  sendBtn: {
    backgroundColor: '#2563eb',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 10,
    alignSelf: 'flex-end',
    justifyContent: 'center',
  },
  sendText: { color: '#fff', fontWeight: '700', fontSize: 14 },
})
