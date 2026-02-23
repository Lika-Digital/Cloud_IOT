import { useRef } from 'react'
import { Modal, View, Text, TouchableOpacity, StyleSheet } from 'react-native'
import SignatureCanvas from 'react-native-signature-canvas'

interface Props {
  visible: boolean
  onConfirm: (base64: string) => void
  onCancel: () => void
}

export function SignaturePad({ visible, onConfirm, onCancel }: Props) {
  const sigRef = useRef<SignatureCanvas>(null)

  const handleOK = (signature: string) => {
    onConfirm(signature)
  }

  const handleClear = () => {
    sigRef.current?.clearSignature()
  }

  const handleConfirm = () => {
    sigRef.current?.readSignature()
  }

  return (
    <Modal visible={visible} animationType="slide" transparent>
      <View style={styles.overlay}>
        <View style={styles.container}>
          <Text style={styles.title}>Sign with your finger</Text>
          <View style={styles.canvasWrapper}>
            <SignatureCanvas
              ref={sigRef}
              onOK={handleOK}
              onEmpty={() => {}}
              descriptionText=""
              clearText=""
              confirmText=""
              webStyle={`
                .m-signature-pad { box-shadow: none; border: none; }
                .m-signature-pad--body { border: none; }
                .m-signature-pad--footer { display: none; }
                body, html { margin: 0; padding: 0; }
              `}
              backgroundColor="white"
              penColor="#1a3c5e"
            />
          </View>
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
  buttons: {
    flexDirection: 'row',
    gap: 10,
  },
  clearBtn: {
    flex: 1,
    paddingVertical: 12,
    backgroundColor: '#374151',
    borderRadius: 10,
    alignItems: 'center',
  },
  clearBtnText: { color: '#d1d5db', fontWeight: '600' },
  cancelBtn: {
    flex: 1,
    paddingVertical: 12,
    backgroundColor: '#374151',
    borderRadius: 10,
    alignItems: 'center',
  },
  cancelBtnText: { color: '#d1d5db', fontWeight: '600' },
  confirmBtn: {
    flex: 1,
    paddingVertical: 12,
    backgroundColor: '#2563eb',
    borderRadius: 10,
    alignItems: 'center',
  },
  confirmBtnText: { color: '#fff', fontWeight: '700' },
})
