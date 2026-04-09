"""Static catalog of exposable endpoints and push events for the External API Gateway."""

ENDPOINT_CATALOG = [
    {"id": "pedestals.list",         "path": "/api/pedestals",                       "method": "GET",  "category": "Pedestals",   "allow_bidirectional": False},
    {"id": "pedestals.health",       "path": "/api/pedestals/health",                "method": "GET",  "category": "Health",      "allow_bidirectional": False},
    {"id": "sessions.active",        "path": "/api/sessions/active",                 "method": "GET",  "category": "Sessions",    "allow_bidirectional": False},
    {"id": "sessions.pending",       "path": "/api/sessions/pending",                "method": "GET",  "category": "Sessions",    "allow_bidirectional": False},
    {"id": "controls.allow",         "path": "/api/controls/{id}/allow",             "method": "POST", "category": "Controls",    "allow_bidirectional": True},
    {"id": "controls.deny",          "path": "/api/controls/{id}/deny",              "method": "POST", "category": "Controls",    "allow_bidirectional": True},
    {"id": "controls.stop",          "path": "/api/controls/{id}/stop",              "method": "POST", "category": "Controls",    "allow_bidirectional": True},
    {"id": "analytics.daily",        "path": "/api/analytics/consumption/daily",     "method": "GET",  "category": "Analytics",   "allow_bidirectional": False},
    {"id": "analytics.summary",      "path": "/api/analytics/sessions/summary",      "method": "GET",  "category": "Analytics",   "allow_bidirectional": False},
    {"id": "alarms.active",          "path": "/api/alarms/active",                   "method": "GET",  "category": "Alarms",      "allow_bidirectional": False},
    {"id": "alarms.acknowledge",     "path": "/api/alarms/{id}/acknowledge",         "method": "POST", "category": "Alarms",      "allow_bidirectional": True},
    {"id": "berths.list",            "path": "/api/berths",                          "method": "GET",  "category": "Berths",      "allow_bidirectional": False},
    {"id": "diagnostics.run",        "path": "/api/pedestals/{id}/diagnostics/run",  "method": "POST", "category": "Diagnostics", "allow_bidirectional": True},
    {"id": "camera.detections",      "path": "/api/camera/{id}/detections",          "method": "GET",  "category": "Camera",      "allow_bidirectional": False},
    {"id": "controls.reset",         "path": "/api/controls/pedestal/{id}/reset",    "method": "POST", "category": "Controls",    "allow_bidirectional": True},
    {"id": "controls.led",           "path": "/api/controls/pedestal/{id}/led",      "method": "POST", "category": "Controls",    "allow_bidirectional": True},
]

EVENT_CATALOG = [
    {"id": "power_reading",            "name": "Power Readings",      "category": "Sensors"},
    {"id": "water_reading",            "name": "Water Readings",      "category": "Sensors"},
    {"id": "temperature_reading",      "name": "Temperature",         "category": "Sensors"},
    {"id": "moisture_reading",         "name": "Moisture",            "category": "Sensors"},
    {"id": "heartbeat",                "name": "Heartbeat",           "category": "Health"},
    {"id": "pedestal_health_updated",  "name": "Pedestal Health",     "category": "Health"},
    {"id": "session_created",          "name": "Session Created",     "category": "Sessions"},
    {"id": "session_updated",          "name": "Session Updated",     "category": "Sessions"},
    {"id": "session_completed",        "name": "Session Completed",   "category": "Sessions"},
    {"id": "berth_occupancy_updated",  "name": "Berth Occupancy",     "category": "Berths"},
    {"id": "diagnostics_result",       "name": "Diagnostics Results", "category": "Diagnostics"},
    {"id": "marina_door",              "name": "Cabinet Door",        "category": "Hardware"},
    {"id": "marina_event",             "name": "Cabinet Events",      "category": "Hardware"},
    {"id": "marina_ack",               "name": "Command Acks",        "category": "Hardware"},
    {"id": "pedestal_reset_sent",      "name": "Pedestal Reset",      "category": "Controls"},
]
