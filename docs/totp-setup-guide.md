# Two-Factor Authentication — Setup & Recovery Guide

Cloud_IOT operator login uses **mandatory two-factor authentication (2FA)**. After
your email + password you must complete a second factor. Two methods are
available:

- **TOTP** — a 6-digit code from an authenticator app on your phone (primary, fully offline).
- **OTP fallback** — a one-time code written to the backend log (and emailed if SMTP is configured). Always available, even if TOTP is not set up.

> TOTP setup is **admin-only**. Monitor accounts always use the OTP fallback.

---

## 1. Two-factor options at a glance

| | TOTP (authenticator app) | OTP fallback |
|---|---|---|
| Where the code comes from | Your phone app | Backend log / email |
| Internet needed | **No** (works fully offline) | No (log) / yes for email only |
| Who can enable | Admin | Always on for everyone |
| Code lifetime | ~30 s rolling | 10 minutes, single use |

At the second-factor screen you can always click **"Use backup code instead"** to
switch from TOTP to the OTP fallback (lost phone, dead battery, clock drift).

---

## 2. Compatible authenticator apps

- **Aegis Authenticator** (Android, open-source, **recommended**) — https://getaegis.app
- **Google Authenticator** (Android / iOS) — App Store / Google Play
- **Microsoft Authenticator** (Android / iOS) — App Store / Google Play

Any RFC-6238 TOTP app works. No account or internet is required on the phone.

---

## 3. Set up TOTP (admin)

1. Sign in and open **Settings** → **Two-Factor Authentication**.
2. Click **Setup Authenticator**. A QR code and a manual-entry key appear.
3. In your authenticator app choose **Add / Scan QR code** and scan it.
   (Can't scan? Choose "Enter a setup key" and type the manual key shown; issuer "Marina IoT".)
4. The app now shows a 6-digit code that changes every ~30 s.
5. Type the current code into **Verify and Enable** and submit.
6. A green **"Two-factor authentication enabled"** confirmation appears. Done.

> Re-running **Setup Authenticator** generates a **new** secret and invalidates the
> previous QR code — only the most recently verified secret works.

From the next login, after email + password you'll be asked for the authenticator code.

---

## 4. Using the OTP fallback (lost phone, dead battery, clock drift)

At the second-factor screen click **"Use backup code instead"** (TOTP users) — or,
if you have no TOTP set up, a code is sent automatically after your password. Then:

### Read the code from the backend log
SSH into the NUC and run:
```bash
sudo journalctl -u cloud-iot-backend -f
```
Submit your email + password in the browser, watch the log for a line like
`OTP for you@example.com: 123456`, and enter that code. (Ctrl+C to stop the tail.)

The OTP **expires after 10 minutes** and is **single-use**.

### Email delivery (optional)
If SMTP is configured, the OTP is emailed instead of (only) logged, and the screen
says "sent to your email address."

---

## 5. Configure SMTP for email OTP (optional)

Set these in `/opt/cloud-iot/backend/.env` (or via **Settings → Email / SMTP**):
```
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_TLS=true
SMTP_USER=you@example.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=noreply@yourmarina.com
```
Then `sudo cloud-iot restart`. With SMTP set, OTP codes are emailed; without it, they
are written to the backend log (above).

---

## 6. Recovery — both TOTP and OTP inaccessible

If an admin loses their authenticator **and** cannot reach the backend log/email,
another admin (or direct DB access on the NUC) can clear the locked/2FA state:

```bash
# On the NUC — clear TOTP + any lockout for one operator, forcing OTP-log fallback
sudo /opt/cloud-iot/backend/.venv/bin/python - <<'PY'
import sqlite3
db = sqlite3.connect('/opt/cloud-iot/backend/data/users.db')
db.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL, "
           "totp_failed_attempts=0, totp_locked_until=NULL "
           "WHERE email=?", ("you@example.com",))
db.commit(); print("reset:", db.total_changes); db.close()
PY
```
The account then logs in with the OTP-log fallback, and the admin can re-enroll TOTP.

---

## 7. Disable TOTP

**Settings → Two-Factor Authentication → Disable Two-Factor Authentication.** You must
provide your **current password** and a **current authenticator code**. This clears the
secret; the OTP fallback remains available as the second factor.

---

## 8. Troubleshooting

- **"Invalid code" on a fresh TOTP setup or login** — almost always **phone clock drift**.
  Set the phone time to **automatic / network time**, then try the next code.
- **OTP says expired** — codes last **10 minutes** and are single-use. Request a new one
  ("Use backup code instead") and read the latest line from the log.
- **"Too many failed attempts — locked for 15 minutes"** — after **5** failed second-factor
  attempts the account locks for **15 minutes** (applies to both TOTP and OTP). Wait it out,
  or an admin can clear `totp_locked_until` via the recovery snippet above.
- **No second-factor screen appears** — 2FA is mandatory; if you reach the dashboard straight
  after the password, report it (that would be a bug).
