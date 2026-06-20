# Two-Factor Authentication — Setup & Recovery Guide

Cloud_IOT operator login uses **mandatory two-factor authentication (2FA)**. After
your email + password you must complete a second factor.

As of **v3.33 the authenticator app (TOTP) is the only second factor** — email/log
OTP has been removed. TOTP is a 6-digit code from an app on your phone, works fully
offline (no internet, no SMTP), and is set up the **first time you log in**.

---

## 1. Compatible authenticator apps

- **Aegis Authenticator** (Android, open-source, **recommended**) — https://getaegis.app
- **Google Authenticator** (Android / iOS) — App Store / Google Play
- **Microsoft Authenticator** (Android / iOS) — App Store / Google Play
- **1Password / Bitwarden** and any other RFC-6238 TOTP app

No account or internet is required on the phone.

---

## 2. First login (new account)

When an admin creates your account they set a **temporary password** and you have
no authenticator yet. Your first login is a short wizard:

1. Enter your **email + temporary password** → **Continue**.
2. **Choose a new password** (required on first login) and confirm it.
3. **Set up your authenticator:** a QR code and a manual-entry key appear in the
   browser. In your authenticator app choose **Add / Scan QR code** and scan it.
   (Can't scan? Choose "Enter a setup key" and type the key shown; issuer "Marina IoT".)
4. The app now shows a 6-digit code that changes every ~30 s. Type the current code
   and submit — you're signed in, and TOTP is now enabled for your account.

From every later login, after email + password you simply enter the current
authenticator code.

---

## 3. Normal login (authenticator already enrolled)

1. Enter your **email + password** → **Continue**.
2. Enter the **6-digit code** from your authenticator app. (It auto-submits once you
   type the sixth digit.)

The code lasts ~30 s; one window of clock drift (±30 s) is tolerated.

---

## 4. Lost authenticator — admin reset (recovery)

Because the authenticator is the only second factor, a lost or wiped phone is
recovered by an **admin**, not self-service:

1. An admin opens **Settings → Operator Accounts**.
2. On the affected user's row, click **Reset 2FA** and confirm.
3. That user's TOTP is cleared. On their **next login** they re-enrol a new
   authenticator (the QR wizard from section 2, step 3). Their password is unchanged.

### Last-resort recovery (no other admin available)

If **every** admin is locked out, clear the 2FA state directly on the NUC database:

```bash
# On the NUC — clear TOTP + any lockout for one operator so they re-enrol on next login
sudo /opt/cloud-iot/backend/.venv/bin/python - <<'PY'
import sqlite3
db = sqlite3.connect('/opt/cloud-iot/backend/data/users.db')
db.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL, "
           "totp_failed_attempts=0, totp_locked_until=NULL "
           "WHERE email=?", ("you@example.com",))
db.commit(); print("reset:", db.total_changes); db.close()
PY
```

The account then re-enrols a fresh authenticator at the next login.

---

## 5. Admin TOTP management (Settings)

Admins can also manage their own authenticator from **Settings → Two-Factor
Authentication**:

- **Setup Authenticator** — generate a new secret + QR and verify it. Re-running this
  generates a **new** secret and invalidates the previous QR; only the most recently
  verified secret works.
- **Disable Two-Factor Authentication** — requires your **current password** and a
  **current authenticator code**. Note: 2FA is mandatory, so disabling only clears the
  current secret — you will be asked to enrol again on your next login.

---

## 6. Troubleshooting

- **"Invalid code" on a fresh setup or login** — almost always **phone clock drift**.
  Set the phone time to **automatic / network time**, then try the next code.
- **"Too many failed attempts — locked for 15 minutes"** — after **5** failed
  second-factor attempts the account locks for **15 minutes**. Wait it out, or an admin
  can **Reset 2FA** (which also clears the lockout), or use the recovery snippet above.
- **Lost the phone and no other admin** — use the last-resort DB snippet in section 4.
- **No second-factor screen appears** — 2FA is mandatory; if you reach the dashboard
  straight after the password, report it (that would be a bug).
