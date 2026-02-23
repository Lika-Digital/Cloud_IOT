import { useRef } from 'react'
import { Modal, View, Text, TouchableOpacity, StyleSheet, StatusBar } from 'react-native'
import { useVideoPlayer, VideoView } from 'expo-video'

// In production this would be a live RTSP/HLS stream URL.
// For testing we use the bundled sample video.
const BERTH_VIDEO = require('../../assets/berth_live.mp4')

interface Props {
  visible: boolean
  shipName?: string
  onClose: () => void
}

export function ShipCameraModal({ visible, shipName, onClose }: Props) {
  const player = useVideoPlayer(BERTH_VIDEO, (p) => {
    p.loop = true
    p.play()
  })

  return (
    <Modal
      visible={visible}
      animationType="fade"
      statusBarTranslucent
      onRequestClose={onClose}
    >
      <StatusBar hidden />
      <View style={styles.container}>
        {/* Header bar */}
        <View style={styles.header}>
          <View style={styles.liveBadge}>
            <View style={styles.liveDot} />
            <Text style={styles.liveText}>LIVE</Text>
          </View>
          <Text style={styles.headerTitle}>
            {shipName ? `${shipName} — Berth Camera` : 'Berth Camera'}
          </Text>
          <TouchableOpacity style={styles.closeBtn} onPress={onClose}>
            <Text style={styles.closeBtnText}>✕</Text>
          </TouchableOpacity>
        </View>

        {/* Video */}
        <VideoView
          player={player}
          style={styles.video}
          contentFit="contain"
          nativeControls
        />

        {/* Footer */}
        <View style={styles.footer}>
          <Text style={styles.footerText}>📍 Marina Portorož — Berth Camera</Text>
          <Text style={styles.footerSub}>Pull down to close</Text>
        </View>
      </View>
    </Modal>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingTop: 50,
    paddingHorizontal: 16,
    paddingBottom: 12,
    backgroundColor: '#000',
    gap: 10,
  },
  liveBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: '#dc2626',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
  liveDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: '#fff' },
  liveText: { color: '#fff', fontWeight: '800', fontSize: 11 },
  headerTitle: { flex: 1, color: '#fff', fontWeight: '700', fontSize: 14 },
  closeBtn: {
    width: 32, height: 32, borderRadius: 16,
    backgroundColor: '#374151', alignItems: 'center', justifyContent: 'center',
  },
  closeBtnText: { color: '#fff', fontSize: 14, fontWeight: '700' },

  video: { flex: 1, width: '100%' },

  footer: {
    paddingVertical: 12,
    paddingHorizontal: 16,
    backgroundColor: '#111',
    alignItems: 'center',
    gap: 2,
  },
  footerText: { color: '#9ca3af', fontSize: 12 },
  footerSub: { color: '#4b5563', fontSize: 11 },
})
