"""Static catalog of exposable endpoints and push events for the External API Gateway."""

ENDPOINT_CATALOG = [
    {"id": "pedestals.list",         "path": "/api/pedestals",                       "method": "GET",  "category": "Pedestals",   "allow_bidirectional": False},
    {"id": "pedestals.health",       "path": "/api/pedestals/health",                "method": "GET",  "category": "Health",      "allow_bidirectional": False},
    {"id": "sessions.active",        "path": "/api/sessions/active",                 "method": "GET",  "category": "Sessions",    "allow_bidirectional": False},
    {"id": "sessions.pending",       "path": "/api/sessions/pending",                "method": "GET",  "category": "Sessions",    "allow_bidirectional": False},
    {"id": "controls.allow",         "path": "/api/controls/{id}/allow",             "method": "POST", "category": "Controls",    "allow_bidirectional": True},
    {"id": "controls.deny",          "path": "/api/controls/{id}/deny",              "method": "POST", "category": "Controls",    "allow_bidirectional": True},
    {"id": "controls.stop",          "path": "/api/controls/{id}/stop",              "method": "POST", "category": "Controls",    "allow_bidirectional": True},
    {"id": "controls.socket_approve","path": "/api/controls/sockets/{pedestal_id}/{socket_id}/approve", "method": "POST", "category": "Controls", "allow_bidirectional": True},
    {"id": "controls.socket_reject", "path": "/api/controls/sockets/{pedestal_id}/{socket_id}/reject",  "method": "POST", "category": "Controls", "allow_bidirectional": True},
    {"id": "controls.socket_cmd",    "path": "/api/controls/pedestal/{pedestal_id}/socket/{socket_name}/cmd", "method": "POST", "category": "Controls", "allow_bidirectional": True},
    {"id": "controls.water_cmd",     "path": "/api/controls/pedestal/{pedestal_id}/water/{valve_name}/cmd",   "method": "POST", "category": "Controls", "allow_bidirectional": True},
    {"id": "analytics.daily",        "path": "/api/analytics/consumption/daily",     "method": "GET",  "category": "Analytics",   "allow_bidirectional": False},
    {"id": "analytics.summary",      "path": "/api/analytics/sessions/summary",      "method": "GET",  "category": "Analytics",   "allow_bidirectional": False},
    {"id": "alarms.active",          "path": "/api/alarms/active",                   "method": "GET",  "category": "Alarms",      "allow_bidirectional": False},
    {"id": "alarms.acknowledge",     "path": "/api/alarms/{id}/acknowledge",         "method": "POST", "category": "Alarms",      "allow_bidirectional": True},
    {"id": "berths.list",            "path": "/api/berths",                          "method": "GET",  "category": "Berths",      "allow_bidirectional": False},
    {"id": "diagnostics.run",        "path": "/api/pedestals/{id}/diagnostics/run",  "method": "POST", "category": "Diagnostics", "allow_bidirectional": True},
    {"id": "camera.snapshot",        "path": "/api/camera/{pedestal_id}/snapshot",   "method": "GET",  "category": "Camera",      "allow_bidirectional": False},
    {"id": "camera.stream",          "path": "/api/camera/{pedestal_id}/stream",     "method": "GET",  "category": "Camera",      "allow_bidirectional": False},
    # Per-socket auto-activation (v3.5)
    {"id": "sockets.config_list",    "path": "/api/pedestals/{pedestal_id}/sockets/config",                     "method": "GET",   "category": "Controls", "allow_bidirectional": False},
    {"id": "sockets.config_patch",   "path": "/api/pedestals/{pedestal_id}/sockets/{socket_id}/config",          "method": "PATCH", "category": "Controls", "allow_bidirectional": True},
    {"id": "sockets.auto_log",       "path": "/api/pedestals/{pedestal_id}/sockets/{socket_id}/auto-activate-log","method": "GET",   "category": "Controls", "allow_bidirectional": False},
    # Mobile QR-claim + monitoring (v3.6)
    {"id": "mobile.qr_claim",        "path": "/api/mobile/qr/claim",                                            "method": "POST",  "category": "Mobile", "allow_bidirectional": True},
    {"id": "mobile.session_live",    "path": "/api/mobile/sessions/{session_id}/live",                          "method": "GET",   "category": "Mobile", "allow_bidirectional": False},
    {"id": "mobile.socket_qr",       "path": "/api/mobile/socket/{pedestal_id}/{socket_id}/qr",                 "method": "GET",   "category": "Mobile", "allow_bidirectional": False},
    # Auto-discovery + printable QR bundles (v3.7)
    {"id": "qr.pedestal_all",        "path": "/api/pedestals/{cabinet_id}/qr/all",                              "method": "GET",   "category": "QR",     "allow_bidirectional": False},
    {"id": "qr.pedestal_regenerate", "path": "/api/pedestals/{cabinet_id}/qr/regenerate",                       "method": "POST",  "category": "QR",     "allow_bidirectional": True},
    {"id": "controls.reset",         "path": "/api/controls/pedestal/{id}/reset",    "method": "POST", "category": "Controls",    "allow_bidirectional": True},
    {"id": "controls.led",           "path": "/api/controls/pedestal/{id}/led",      "method": "POST", "category": "Controls",    "allow_bidirectional": True},
    # Direct ext-pedestal endpoints (not proxied — served by ext_pedestal_endpoints router)
    {"id": "berths.occupancy_ext",   "path": "/api/ext/pedestals/{id}/berths/occupancy", "method": "GET",  "category": "Berths",    "allow_bidirectional": False},
    {"id": "camera.frame_ext",       "path": "/api/ext/pedestals/{id}/camera/frame",     "method": "GET",  "category": "Camera",    "allow_bidirectional": False},
    {"id": "camera.stream_ext",      "path": "/api/ext/pedestals/{id}/camera/stream",    "method": "GET",  "category": "Camera",    "allow_bidirectional": False},
    # v3.8 — Breaker Management API (direct ext routes, not gateway-proxied).
    # Category groups them in the API Gateway UI per D14.
    {"id": "breakers.pedestal_list_ext",    "path": "/api/ext/pedestals/{pedestal_id}/breakers",                            "method": "GET",  "category": "Breaker Management", "allow_bidirectional": False},
    {"id": "breakers.socket_get_ext",       "path": "/api/ext/pedestals/{pedestal_id}/sockets/{socket_id}/breaker",         "method": "GET",  "category": "Breaker Management", "allow_bidirectional": False},
    {"id": "breakers.socket_reset_ext",     "path": "/api/ext/pedestals/{pedestal_id}/sockets/{socket_id}/breaker/reset",   "method": "POST", "category": "Breaker Management", "allow_bidirectional": True},
    {"id": "breakers.pedestal_history_ext", "path": "/api/ext/pedestals/{pedestal_id}/breaker/history",                     "method": "GET",  "category": "Breaker Management", "allow_bidirectional": False},
    {"id": "breakers.marina_alarms_ext",    "path": "/api/ext/marinas/{marina_id}/breaker/alarms",                          "method": "GET",  "category": "Breaker Management", "allow_bidirectional": False},
]

EVENT_CATALOG = [
    {"id": "power_reading",            "name": "Power Readings",      "category": "Sensors"},
    {"id": "water_reading",            "name": "Water Readings",      "category": "Sensors"},
    {"id": "temperature_reading",      "name": "Temperature",         "category": "Sensors"},
    {"id": "moisture_reading",         "name": "Moisture",            "category": "Sensors"},
    {"id": "heartbeat",                "name": "Heartbeat",           "category": "Health"},
    {"id": "pedestal_health_updated",  "name": "Pedestal Health",     "category": "Health"},
    {"id": "hardware_alarm",           "name": "Hardware Alarm",      "category": "Health"},
    {"id": "session_created",          "name": "Session Created",     "category": "Sessions"},
    {"id": "session_updated",          "name": "Session Updated",     "category": "Sessions"},
    {"id": "session_completed",        "name": "Session Completed",   "category": "Sessions"},
    {"id": "socket_pending",           "name": "Socket Pending",      "category": "Sessions"},
    {"id": "socket_rejected",          "name": "Socket Rejected",     "category": "Sessions"},
    {"id": "socket_state_changed",     "name": "Socket State Changed","category": "Sessions"},
    {"id": "socket_auto_activate_skipped", "name": "Auto-Activate Skipped", "category": "Sessions"},
    {"id": "session_telemetry",        "name": "Session Telemetry (mobile)", "category": "Sessions"},
    {"id": "session_ended",            "name": "Session Ended (mobile)", "category": "Sessions"},
    {"id": "pedestal_registered",      "name": "Pedestal Registered", "category": "Discovery"},
    {"id": "user_plugged_in",          "name": "User Plugged In",     "category": "Sessions"},
    {"id": "invoice_created",          "name": "Invoice Created",     "category": "Billing"},
    {"id": "berth_occupancy_updated",  "name": "Berth Occupancy",     "category": "Berths"},
    {"id": "diagnostics_result",       "name": "Diagnostics Results", "category": "Diagnostics"},
    {"id": "marina_door",              "name": "Cabinet Door",        "category": "Hardware"},
    {"id": "marina_event",             "name": "Cabinet Events",      "category": "Hardware"},
    {"id": "marina_ack",               "name": "Command Acks",        "category": "Hardware"},
    {"id": "opta_socket_status",       "name": "Opta Socket Status",  "category": "Hardware"},
    {"id": "opta_water_status",        "name": "Opta Water Status",   "category": "Hardware"},
    {"id": "opta_status",              "name": "Opta Status",         "category": "Hardware"},
    {"id": "pedestal_reset_sent",      "name": "Pedestal Reset",      "category": "Controls"},
    # v3.8 — breaker state + alarm events. Both flow through the existing
    # ws_manager broadcast hook to webhook_service, so setting either in
    # ExternalApiConfig.allowed_events pushes them to the ERP webhook.
    # Note: a state transition to `resetting` is itself a breaker_state_changed
    # broadcast — no separate reset_sent event is needed.
    {"id": "breaker_state_changed",    "name": "Breaker State Changed", "category": "Breaker Management"},
    {"id": "breaker_alarm",            "name": "Breaker Alarm",         "category": "Breaker Management"},
]
