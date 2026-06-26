# NFC charging (mobile) — testing guide

Lets a phone scan the NFC tag on a pedestal socket and start a real charging
session on the NUC. Uses the backend's existing NFC endpoints **unchanged**.

## Flow

1. **Scan** tab → "Scan tag" → phone reads the tag's hardware UID.
2. App calls `POST /api/nfc/scan` (auth: ERP `X-API-Key`) → pre-registers a
   5-minute charge window and returns the cabinet + socket.
3. **Plug in the cable.** The socket activates only if the pedestal is in
   **Smart Mode ON** (backend gate). The backend broadcasts `session_created`
   with our `nfc_user_id`.
4. The app's existing WebSocket adopts that session and shows it **active** with
   live **power / energy** (and estimated cost, polled from `/api/nfc/session/{id}`).
5. **Stop** in-app (`POST /api/nfc/session/{id}/stop`) or just unplug.

## One-time prerequisites

- **Tags must be provisioned.** An admin maps each physical tag UID → socket via
  the operator UI (`POST /api/nfc/tags`). If a scan returns *"Tag not
  provisioned"*, the app shows the UID it read — register that exact value.
- **ERP API key.** Put the NUC's `ERP_API_KEY` into `mobile/.env` as
  `EXPO_PUBLIC_ERP_API_KEY=...`. `scripts/setup-env.js` preserves it across runs
  (or export `MARINA_ERP_API_KEY` before `npm start`).
- **Smart Mode ON** on the pedestal, or the plug-in won't activate.

## Build (NFC needs native code — Expo Go won't work)

```bash
cd mobile
npm install                      # pulls react-native-nfc-manager
npx expo prebuild                # generates native projects with the NFC plugin
# Android device on the same Wi-Fi as the NUC:
npx expo run:android
# or an EAS dev build:
npx eas build --profile development --platform android
```

iOS additionally needs the *Near Field Communication Tag Reading* capability on
the Apple Developer provisioning profile (the config plugin adds the entitlement;
the capability must be enabled for the app id).

## Notes

- On web / Expo Go the Scan tab loads but reports "NFC isn't available" — the
  native module is guarded so the rest of the app still runs.
- Tag UID is normalised to uppercase hex with no separators before sending. If a
  provisioned value uses a different format, re-provision using the UID shown.
