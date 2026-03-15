#!/usr/bin/env bash
# ============================================================================
# Cloud IoT NUC v2.0 — MQTT Broker Watchdog
#
# Pings the local MQTT broker every 15 seconds.
# If the broker does not respond for 60 seconds → triggers a hard reboot
# via the Linux hardware watchdog (/dev/watchdog).
#
# Design:
#   - While MQTT is healthy: keeps writing to /dev/watchdog to prevent reboot
#   - When MQTT fails: stops writing → kernel watchdog fires after 60s
#   - Uses mosquitto_pub/sub (included in mosquitto-clients package)
# ============================================================================

MQTT_HOST="localhost"
MQTT_PORT="1883"
CHECK_INTERVAL=15          # seconds between health checks
WATCHDOG_TIMEOUT=60        # seconds — must match /etc/watchdog.conf watchdog-timeout
WATCHDOG_DEVICE="/dev/watchdog"
LOG_TAG="cloud-iot-watchdog"

FAIL_SINCE=0               # epoch timestamp of first failure (0 = healthy)
WATCHDOG_FD=""

logger() { /usr/bin/logger -t "$LOG_TAG" "$*"; }

# Open watchdog device (keep it open — closing it without writing 'V' causes reboot)
open_watchdog() {
  if [ -c "$WATCHDOG_DEVICE" ]; then
    exec {WATCHDOG_FD}<>"$WATCHDOG_DEVICE" 2>/dev/null || {
      logger "WARNING: Cannot open ${WATCHDOG_DEVICE} — watchdog disabled"
      WATCHDOG_FD=""
    }
    logger "Watchdog device opened: ${WATCHDOG_DEVICE}"
  else
    logger "WARNING: ${WATCHDOG_DEVICE} not found — hardware watchdog not active"
    WATCHDOG_FD=""
  fi
}

# Write a keepalive byte to the watchdog (resets the countdown)
pet_watchdog() {
  if [ -n "$WATCHDOG_FD" ]; then
    echo -n "1" >&"$WATCHDOG_FD" 2>/dev/null || true
  fi
}

# Gracefully close the watchdog (write 'V' to tell kernel we're shutting down cleanly)
close_watchdog() {
  if [ -n "$WATCHDOG_FD" ]; then
    echo -n "V" >&"$WATCHDOG_FD" 2>/dev/null || true
    exec {WATCHDOG_FD}>&- 2>/dev/null || true
    WATCHDOG_FD=""
  fi
}

# Check if MQTT broker is alive by publishing a test message
check_mqtt() {
  timeout 5 mosquitto_pub \
    -h "$MQTT_HOST" \
    -p "$MQTT_PORT" \
    -t "system/watchdog/ping" \
    -m "$(date +%s)" \
    -q 0 \
    2>/dev/null
}

# Cleanup on exit — close watchdog gracefully so kernel doesn't reboot
trap 'logger "Watchdog stopping — closing device gracefully"; close_watchdog; exit 0' \
  TERM INT EXIT

# ── Main loop ────────────────────────────────────────────────────────────────
logger "MQTT watchdog starting (host=${MQTT_HOST}:${MQTT_PORT}, interval=${CHECK_INTERVAL}s, timeout=${WATCHDOG_TIMEOUT}s)"

open_watchdog

while true; do
  if check_mqtt; then
    # MQTT healthy
    if [ "$FAIL_SINCE" -ne 0 ]; then
      logger "MQTT broker recovered — resuming watchdog keepalive"
      FAIL_SINCE=0
    fi
    pet_watchdog

  else
    # MQTT unhealthy
    NOW=$(date +%s)
    if [ "$FAIL_SINCE" -eq 0 ]; then
      FAIL_SINCE="$NOW"
      logger "WARNING: MQTT broker not responding — starting ${WATCHDOG_TIMEOUT}s countdown"
    fi

    ELAPSED=$(( NOW - FAIL_SINCE ))
    logger "MQTT unreachable for ${ELAPSED}s (timeout=${WATCHDOG_TIMEOUT}s)"

    if [ "$ELAPSED" -ge "$WATCHDOG_TIMEOUT" ]; then
      # Stop petting the watchdog → kernel will reboot after watchdog-timeout
      logger "CRITICAL: MQTT broker unresponsive for ${ELAPSED}s — stopping watchdog keepalive — hard reboot imminent"

      # Try to restart the Docker service first as a last resort
      systemctl restart cloud-iot-compose 2>/dev/null || true
      sleep 10
      if check_mqtt; then
        logger "MQTT recovered after restart — watchdog keepalive resumed"
        FAIL_SINCE=0
        pet_watchdog
      else
        logger "MQTT still down — letting watchdog expire"
        # Do NOT pet the watchdog — let it count down to reboot
        # Sleep until watchdog fires
        sleep $(( WATCHDOG_TIMEOUT + 10 ))
      fi
    else
      # Still within grace period — keep petting the watchdog
      # (We don't want a single blip to cause a reboot)
      pet_watchdog
    fi
  fi

  sleep "$CHECK_INTERVAL"
done
