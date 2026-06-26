import { useEffect, useRef, useState } from 'react'
import { Platform } from 'react-native'

// Thin wrapper over react-native-nfc-manager that reads a tag's hardware UID.
// The native module is unavailable on web and in Expo Go, so everything is
// lazy-required and guarded — the screen degrades to "NFC not available" there
// instead of crashing the bundle. NFC works only in a custom dev/EAS build.

type NfcModule = {
  default: any
  NfcTech: any
}

let mod: NfcModule | null = null
let started = false

function loadNfc(): NfcModule | null {
  if (Platform.OS === 'web') return null
  if (mod) return mod
  try {
    // Indirect specifier so TS/Metro don't statically resolve the native module
    // (keeps web/Expo-Go bundles working before `npm install` adds the package).
    const name = 'react-native-nfc-manager'
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const req: (m: string) => unknown = require
    mod = req(name) as NfcModule
  } catch {
    mod = null
  }
  return mod
}

/** Normalise the lib's tag id to uppercase hex without separators. */
function normaliseUid(raw: unknown): string {
  if (typeof raw === 'string') return raw.replace(/[^0-9a-fA-F]/g, '').toUpperCase()
  if (Array.isArray(raw)) {
    return raw.map((b: number) => (b & 0xff).toString(16).padStart(2, '0')).join('').toUpperCase()
  }
  return ''
}

export function useNfc() {
  const [supported, setSupported] = useState<boolean | null>(null)
  const [scanning, setScanning] = useState(false)
  const cancelledRef = useRef(false)

  useEffect(() => {
    let active = true
    const m = loadNfc()
    if (!m) {
      setSupported(false)
      return
    }
    ;(async () => {
      try {
        const ok = await m.default.isSupported()
        if (!started && ok) {
          await m.default.start()
          started = true
        }
        if (active) setSupported(ok)
      } catch {
        if (active) setSupported(false)
      }
    })()
    return () => {
      active = false
    }
  }, [])

  /** Read a tag and return its UID (uppercase hex). Throws on failure/cancel. */
  async function readTagUid(): Promise<string> {
    const m = loadNfc()
    if (!m) throw new Error('NFC is not available on this device/build.')
    cancelledRef.current = false
    setScanning(true)
    try {
      // Ndef tech works for the NTAG/MIFARE tags these pedestals use and exposes
      // the UID via getTag().id on both iOS and Android.
      await m.default.requestTechnology(m.NfcTech.Ndef)
      const tag = await m.default.getTag()
      const uid = normaliseUid(tag?.id)
      if (!uid) throw new Error('Could not read a UID from this tag.')
      return uid
    } finally {
      try {
        await m.default.cancelTechnologyRequest()
      } catch {
        /* ignore */
      }
      setScanning(false)
    }
  }

  function cancel() {
    cancelledRef.current = true
    const m = loadNfc()
    try {
      m?.default.cancelTechnologyRequest()
    } catch {
      /* ignore */
    }
    setScanning(false)
  }

  return { supported, scanning, readTagUid, cancel }
}
