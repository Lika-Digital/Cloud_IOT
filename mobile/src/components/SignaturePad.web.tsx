/**
 * Web-only signature pad using HTML5 Canvas.
 * Metro loads this file instead of SignaturePad.tsx on web.
 * react-native-signature-canvas uses WebView internally and cannot run in a browser.
 */
import { useRef, useEffect, useCallback } from 'react'
import { Modal, View, Text, TouchableOpacity, StyleSheet } from 'react-native'

interface Props {
  visible: boolean
  onConfirm: (base64: string) => void
  onCancel: () => void
}

export function SignaturePad({ visible, onConfirm, onCancel }: Props) {
  const wrapperRef = useRef<any>(null)
  const canvasRef  = useRef<HTMLCanvasElement | null>(null)
  const isDrawing  = useRef(false)

  /** Create and attach canvas the first time the modal becomes visible. */
  const setup = useCallback(() => {
    const wrapper = wrapperRef.current
    if (!wrapper) return

    // If canvas already exists just clear it
    if (canvasRef.current) {
      const ctx = canvasRef.current.getContext('2d')!
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, canvasRef.current.width, canvasRef.current.height)
      return
    }

    const canvas = document.createElement('canvas')
    canvas.width  = 340
    canvas.height = 220
    Object.assign(canvas.style, {
      display: 'block',
      touchAction: 'none',
      cursor: 'crosshair',
      width: '100%',
      height: '100%',
      borderRadius: '8px',
    })
    canvasRef.current = canvas

    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)

    const getPos = (e: MouseEvent | TouchEvent) => {
      const rect  = canvas.getBoundingClientRect()
      const scaleX = canvas.width  / rect.width
      const scaleY = canvas.height / rect.height
      const src = (e as TouchEvent).touches?.[0] ?? (e as MouseEvent)
      return { x: (src.clientX - rect.left) * scaleX, y: (src.clientY - rect.top) * scaleY }
    }

    canvas.addEventListener('mousedown', (e) => {
      isDrawing.current = true
      const { x, y } = getPos(e)
      ctx.beginPath(); ctx.moveTo(x, y)
    })
    canvas.addEventListener('mousemove', (e) => {
      if (!isDrawing.current) return
      ctx.strokeStyle = '#1a3c5e'; ctx.lineWidth = 2; ctx.lineCap = 'round'
      const { x, y } = getPos(e); ctx.lineTo(x, y); ctx.stroke()
    })
    canvas.addEventListener('mouseup',    () => { isDrawing.current = false })
    canvas.addEventListener('mouseleave', () => { isDrawing.current = false })

    canvas.addEventListener('touchstart', (e) => {
      e.preventDefault(); isDrawing.current = true
      const { x, y } = getPos(e); ctx.beginPath(); ctx.moveTo(x, y)
    }, { passive: false })
    canvas.addEventListener('touchmove', (e) => {
      e.preventDefault(); if (!isDrawing.current) return
      ctx.strokeStyle = '#1a3c5e'; ctx.lineWidth = 2; ctx.lineCap = 'round'
      const { x, y } = getPos(e); ctx.lineTo(x, y); ctx.stroke()
    }, { passive: false })
    canvas.addEventListener('touchend', () => { isDrawing.current = false })

    wrapper.appendChild(canvas)
  }, [])

  useEffect(() => {
    if (visible) {
      // Small delay lets the Modal finish animating before we touch the DOM
      const id = setTimeout(setup, 80)
      return () => clearTimeout(id)
    }
  }, [visible, setup])

  const handleClear = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
  }

  const handleConfirm = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    onConfirm(canvas.toDataURL('image/png'))
  }

  return (
    <Modal visible={visible} animationType="slide" transparent>
      <View style={styles.overlay}>
        <View style={styles.container}>
          <Text style={styles.title}>Sign with your mouse / finger</Text>
          {/* wrapperRef is a RN View → in React Native Web it renders as a div */}
          <View style={styles.canvasWrapper} ref={wrapperRef} />
          <View style={styles.buttons}>
            <TouchableOpacity style={styles.clearBtn} onPress={handleClear}>
              <Text style={styles.clearBtnText}>Clear</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.cancelBtn} onPress={onCancel}>
              <Text style={styles.cancelBtnText}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.confirmBtn} onPress={handleConfirm}>
              <Text style={styles.confirmBtnText}>Confirm</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  )
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'flex-end',
  },
  container: {
    backgroundColor: '#1f2937',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    padding: 20,
    paddingBottom: 40,
  },
  title: {
    color: '#f9fafb',
    fontSize: 18,
    fontWeight: '700',
    marginBottom: 16,
    textAlign: 'center',
  },
  canvasWrapper: {
    height: 250,
    borderRadius: 12,
    overflow: 'hidden',
    backgroundColor: '#fff',
    marginBottom: 16,
  },
  buttons: { flexDirection: 'row', gap: 10 },
  clearBtn: {
    flex: 1, paddingVertical: 12, backgroundColor: '#374151',
    borderRadius: 10, alignItems: 'center',
  },
  clearBtnText: { color: '#d1d5db', fontWeight: '600' },
  cancelBtn: {
    flex: 1, paddingVertical: 12, backgroundColor: '#374151',
    borderRadius: 10, alignItems: 'center',
  },
  cancelBtnText: { color: '#d1d5db', fontWeight: '600' },
  confirmBtn: {
    flex: 1, paddingVertical: 12, backgroundColor: '#2563eb',
    borderRadius: 10, alignItems: 'center',
  },
  confirmBtnText: { color: '#fff', fontWeight: '700' },
})
