import { useState } from 'react'
import {
  Modal, View, Text, TextInput, TouchableOpacity,
  StyleSheet, ActivityIndicator, KeyboardAvoidingView, Platform,
} from 'react-native'
import { submitReview } from '../api/reviews'

interface Props {
  visible: boolean
  sessionId?: number
  serviceOrderId?: number
  title?: string
  onClose: () => void
  onSubmitted: () => void
}

export function ReviewModal({ visible, sessionId, serviceOrderId, title, onClose, onSubmitted }: Props) {
  const [stars, setStars] = useState(0)
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const reset = () => { setStars(0); setComment(''); setError('') }

  const handleClose = () => { reset(); onClose() }

  const handleSubmit = async () => {
    if (stars === 0) { setError('Please select a star rating.'); return }
    setSubmitting(true)
    setError('')
    try {
      await submitReview({
        stars,
        comment: comment.trim() || undefined,
        session_id: sessionId,
        service_order_id: serviceOrderId,
      })
      reset()
      onSubmitted()
    } catch {
      setError('Failed to submit review. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={handleClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.overlay}
      >
        <View style={styles.sheet}>
          <Text style={styles.heading}>Rate Your Experience</Text>
          {title ? <Text style={styles.subtitle}>{title}</Text> : null}

          {/* Stars */}
          <View style={styles.starsRow}>
            {[1, 2, 3, 4, 5].map((n) => (
              <TouchableOpacity key={n} onPress={() => setStars(n)} activeOpacity={0.7}>
                <Text style={[styles.star, n <= stars && styles.starFilled]}>★</Text>
              </TouchableOpacity>
            ))}
          </View>
          <Text style={styles.starLabel}>
            {stars === 0 ? 'Tap to rate' : ['', 'Poor', 'Fair', 'Good', 'Great', 'Excellent!'][stars]}
          </Text>

          {/* Comment */}
          <TextInput
            style={styles.input}
            placeholder="Leave a comment (optional)"
            placeholderTextColor="#6b7280"
            value={comment}
            onChangeText={setComment}
            multiline
            numberOfLines={3}
            maxLength={500}
          />

          {error ? <Text style={styles.error}>{error}</Text> : null}

          <View style={styles.buttons}>
            <TouchableOpacity style={styles.cancelBtn} onPress={handleClose} disabled={submitting}>
              <Text style={styles.cancelText}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.submitBtn, submitting && styles.btnDisabled]}
              onPress={handleSubmit}
              disabled={submitting}
            >
              {submitting
                ? <ActivityIndicator color="#fff" size="small" />
                : <Text style={styles.submitText}>Submit Review</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  )
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.6)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: '#1f2937',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: 24,
    paddingBottom: 40,
    gap: 14,
  },
  heading: { color: '#f9fafb', fontSize: 20, fontWeight: '800', textAlign: 'center' },
  subtitle: { color: '#9ca3af', fontSize: 13, textAlign: 'center', marginTop: -6 },

  starsRow: { flexDirection: 'row', justifyContent: 'center', gap: 8, marginTop: 4 },
  star: { fontSize: 42, color: '#374151' },
  starFilled: { color: '#fbbf24' },
  starLabel: { color: '#9ca3af', fontSize: 13, textAlign: 'center', marginTop: -6 },

  input: {
    backgroundColor: '#111827',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#374151',
    color: '#f9fafb',
    padding: 12,
    fontSize: 14,
    textAlignVertical: 'top',
    minHeight: 80,
  },
  error: { color: '#f87171', fontSize: 13, textAlign: 'center' },

  buttons: { flexDirection: 'row', gap: 10, marginTop: 4 },
  cancelBtn: {
    flex: 1, paddingVertical: 14, borderRadius: 12,
    backgroundColor: '#374151', alignItems: 'center',
  },
  cancelText: { color: '#d1d5db', fontWeight: '700', fontSize: 15 },
  submitBtn: {
    flex: 2, paddingVertical: 14, borderRadius: 12,
    backgroundColor: '#2563eb', alignItems: 'center',
  },
  btnDisabled: { opacity: 0.5 },
  submitText: { color: '#fff', fontWeight: '700', fontSize: 15 },
})
