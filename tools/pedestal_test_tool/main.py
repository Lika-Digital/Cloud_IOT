#!/usr/bin/env python3
"""
Pedestal Test Tool  v1.1
─────────────────────────────────────────────────────────────────────────────
Simulates two networked devices for Cloud IoT NUC testing:

  1. Arduino OPTA  — MQTT client that publishes sensor/status data and
                     receives control commands from the NUC backend.
  2. IP Temp Sensor — sends SNMP v2c Traps via UDP to the NUC SNMP trap
                     receiver (does NOT use MQTT — raw UDP on port 1620).

Run:   python main.py
Deps:  pip install paho-mqtt          (only external dependency)
─────────────────────────────────────────────────────────────────────────────
"""
import json
import queue
import socket
import struct
import time
import tkinter as tk
from tkinter import ttk, scrolledtext
from datetime import datetime

try:
    import paho.mqtt.client as mqtt
except ImportError:
    import subprocess, sys
    print("paho-mqtt not found — installing …")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paho-mqtt"])
    import paho.mqtt.client as mqtt


# ── Minimal SNMP v2c Trap builder (raw UDP, no pysnmp needed) ─────────────────

def _ber_len(n: int) -> bytes:
    if n <= 127:
        return bytes([n])
    elif n <= 255:
        return bytes([0x81, n])
    else:
        return bytes([0x82, n >> 8, n & 0xFF])


def _tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _ber_len(len(content)) + content


def _encode_int(v: int) -> bytes:
    if v == 0:
        return b'\x00'
    parts = []
    while v > 0:
        parts.insert(0, v & 0xFF)
        v >>= 8
    if parts[0] & 0x80:
        parts.insert(0, 0x00)
    return bytes(parts)


def _encode_oid(oid_str: str) -> bytes:
    parts = list(map(int, oid_str.strip().split('.')))
    data = bytes([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        if p == 0:
            data += b'\x00'
        else:
            enc: list[int] = []
            while p:
                enc.insert(0, p & 0x7F)
                p >>= 7
            for i, b in enumerate(enc):
                data += bytes([b | (0x80 if i < len(enc) - 1 else 0)])
    return data


def build_snmp_v2c_trap(community: str, temp_oid: str, temperature: float) -> bytes:
    """
    Build a minimal SNMPv2c Trap PDU containing a single temperature OID/value.
    The value is encoded as OctetString ASCII (e.g. "23.5") — most NUC parsers
    accept this; Papouch TME sensors use the same encoding.
    """
    # Well-known OIDs
    SYSUPTIME_OID  = "1.3.6.1.2.1.1.3.0"
    SNMPTRAPOID    = "1.3.6.1.6.3.1.1.4.1.0"
    COLDSTART_OID  = "1.3.6.1.6.3.1.1.5.1"

    def varbind(oid_str: str, val_tag: int, val_bytes: bytes) -> bytes:
        return _tlv(0x30, _tlv(0x06, _encode_oid(oid_str)) + _tlv(val_tag, val_bytes))

    vb1 = varbind(SYSUPTIME_OID,  0x43, _encode_int(0))           # sysUpTime = 0
    vb2 = varbind(SNMPTRAPOID,    0x06, _encode_oid(COLDSTART_OID))  # snmpTrapOID
    vb3 = varbind(temp_oid,       0x04, str(round(temperature, 1)).encode('ascii'))

    var_bind_list = _tlv(0x30, vb1 + vb2 + vb3)
    pdu = _tlv(0xA7,
               _tlv(0x02, _encode_int(1)) +   # request-id
               _tlv(0x02, _encode_int(0)) +   # error-status
               _tlv(0x02, _encode_int(0)) +   # error-index
               var_bind_list)

    message = _tlv(0x30,
                   _tlv(0x02, _encode_int(1)) +           # version = 1 (v2c)
                   _tlv(0x04, community.encode('ascii')) + # community
                   pdu)
    return message

# ─── Colour palette (dark theme) ─────────────────────────────────────────────
BG        = "#1e1e2e"
PANEL_BG  = "#313244"
ENTRY_BG  = "#45475a"
BTN_BG    = "#585b70"
FG        = "#cdd6f4"
GREEN     = "#a6e3a1"
RED       = "#f38ba8"
BLUE      = "#89b4fa"
YELLOW    = "#f9e2af"
PURPLE    = "#cba6f7"
DIM       = "#6c7086"

POLL_MS   = 100   # UI queue poll interval


# ═════════════════════════════════════════════════════════════════════════════
#  Thread-safe MQTT wrapper
# ═════════════════════════════════════════════════════════════════════════════

class MQTTDevice:
    """
    Thin MQTT client wrapper.
    All paho callbacks run on paho's thread; they push events into a queue
    that the tkinter main thread drains with `after()`.
    """

    def __init__(self, name: str, event_queue: queue.Queue):
        self.name   = name
        self._q     = event_queue
        self._cli   = None
        self._connected = False
        self._topics: list[str] = []

    # ── public API ────────────────────────────────────────────────────────────

    def connect(self, host: str, port: int, topics: list[str],
                client_id: str | None = None):
        self.disconnect()
        self._topics = list(topics)
        cid = client_id or f"ptt-{self.name}-{int(time.time())}"
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
        c.on_connect    = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_message    = self._on_message
        self._cli = c
        try:
            c.connect(host, int(port), keepalive=60)
            c.loop_start()
            self._log(f"Connecting to {host}:{port}  (client_id={cid})")
        except Exception as exc:
            self._log(f"[ERROR] {exc}", err=True)

    def disconnect(self):
        if self._cli:
            try:
                self._cli.loop_stop()
                self._cli.disconnect()
            except Exception:
                pass
            self._cli = None
        if self._connected:
            self._connected = False
            self._q.put(("status", self.name, False))

    def publish(self, topic: str, payload: str):
        if self._connected and self._cli:
            self._cli.publish(topic, payload, qos=1)
            self._log(f"→ PUB  [{topic}]\n          {payload}")
        else:
            self._log(f"[SKIP] not connected — {topic}", err=True)

    def subscribe_extra(self, topic: str):
        if self._connected and self._cli:
            self._cli.subscribe(topic, qos=1)
            self._log(f"  + sub [{topic}]")

    @property
    def connected(self) -> bool:
        return self._connected

    # ── paho callbacks (paho thread) ─────────────────────────────────────────

    def _on_connect(self, cli, ud, flags, rc, props):
        ok = (rc == 0)
        self._connected = ok
        self._q.put(("status", self.name, ok))
        if ok:
            self._log("[CONN] Connected ✓")
            for t in self._topics:
                cli.subscribe(t, qos=1)
                self._log(f"  ← sub [{t}]")
        else:
            self._log(f"[CONN] Refused rc={rc}", err=True)

    def _on_disconnect(self, cli, ud, flags, rc, props):
        self._connected = False
        self._q.put(("status", self.name, False))
        self._log(f"[DISC] Disconnected rc={rc}", err=(rc != 0))

    def _on_message(self, cli, ud, msg):
        try:
            payload = msg.payload.decode()
        except Exception:
            payload = repr(msg.payload)
        self._q.put(("msg", self.name, msg.topic, payload))

    def _log(self, text: str, err: bool = False):
        ts = datetime.now().strftime("%H:%M:%S")
        self._q.put(("log", self.name, f"[{ts}] {self.name:<12} {text}", err))


# ═════════════════════════════════════════════════════════════════════════════
#  Main application window
# ═════════════════════════════════════════════════════════════════════════════

class PedestalTestTool(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Pedestal Test Tool  v1.0  —  Cloud IoT NUC Simulator")
        self.geometry("1340x860")
        self.minsize(1100, 700)
        self.configure(bg=BG)

        self._q       = queue.Queue()
        self._arduino = MQTTDevice("Arduino", self._q)
        # Temp sensor uses raw UDP SNMP — no MQTT connection

        self._hb_job   = None   # heartbeat scheduler
        self._temp_job = None   # temperature auto-send scheduler

        self._build_styles()
        self._build_ui()
        self._poll_queue()

    # ═════════════════════════════════════════════════════════════════════════
    #  UI construction
    # ═════════════════════════════════════════════════════════════════════════

    def _build_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TNotebook",      background=BG,       borderwidth=0)
        s.configure("TNotebook.Tab",  background=BTN_BG,   foreground=FG,
                    font=("Consolas", 9), padding=(12, 5))
        s.map("TNotebook.Tab",
              background=[("selected", PANEL_BG)],
              foreground=[("selected", PURPLE)])
        s.configure("TCombobox",
                    fieldbackground=ENTRY_BG, background=ENTRY_BG,
                    foreground=FG, selectbackground=ENTRY_BG,
                    selectforeground=FG)
        s.map("TCombobox", fieldbackground=[("readonly", ENTRY_BG)])

    def _build_ui(self):
        # ── Title bar ──
        bar = tk.Frame(self, bg=BG, pady=8)
        bar.pack(fill=tk.X, padx=12)
        tk.Label(bar, text="⚡  Pedestal Test Tool", bg=BG, fg=FG,
                 font=("Consolas", 15, "bold")).pack(side=tk.LEFT)
        tk.Label(bar, text="  Cloud IoT NUC Simulator", bg=BG, fg=DIM,
                 font=("Consolas", 10)).pack(side=tk.LEFT)

        # ── Main paned area ──
        pane = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg=BG,
                              sashwidth=6, sashrelief=tk.FLAT)
        pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left  = tk.Frame(pane, bg=BG)
        right = tk.Frame(pane, bg=BG)
        pane.add(left,  minsize=660)
        pane.add(right, minsize=380)

        self._build_arduino_section(left)
        self._build_tempsensor_section(right)

        # ── Log area ──
        log_outer = tk.LabelFrame(self, text="  Event Log  ",
                                  bg=BG, fg=DIM, font=("Consolas", 9))
        log_outer.pack(fill=tk.BOTH, padx=8, pady=(0, 8))

        self._log_box = scrolledtext.ScrolledText(
            log_outer, height=8, bg="#11111b", fg=GREEN,
            font=("Consolas", 9), insertbackground=FG,
            wrap=tk.WORD, state=tk.DISABLED,
        )
        self._log_box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._log_box.tag_config("rx",  foreground=BLUE)
        self._log_box.tag_config("err", foreground=RED)

        tk.Button(log_outer, text="Clear", bg=BTN_BG, fg=FG,
                  font=("Consolas", 8), relief=tk.FLAT, padx=8,
                  command=lambda: (
                      self._log_box.config(state=tk.NORMAL),
                      self._log_box.delete("1.0", tk.END),
                      self._log_box.config(state=tk.DISABLED),
                  )).pack(anchor=tk.E, padx=6, pady=(0, 4))

    # ─────────────────────────────────────────────────────────────────────────
    #  Arduino OPTA section  (tabbed notebook)
    # ─────────────────────────────────────────────────────────────────────────

    def _build_arduino_section(self, parent):
        nb = ttk.Notebook(parent)
        nb.pack(fill=tk.BOTH, expand=True)

        tabs = [
            (" Connection ", self._tab_arduino_conn),
            (" Sockets ",    self._tab_sockets),
            (" Sensors / Water ", self._tab_sensors),
            (" Diagnostics ", self._tab_diagnostics),
            (" Custom Topics ", self._tab_custom),
        ]
        for title, builder in tabs:
            frame = tk.Frame(nb, bg=PANEL_BG)
            nb.add(frame, text=title)
            builder(frame)

    def _tab_arduino_conn(self, parent):
        pad = dict(padx=12, pady=6)

        # Status indicator
        row = tk.Frame(parent, bg=PANEL_BG)
        row.pack(fill=tk.X, **pad)
        tk.Label(row, text="Arduino OPTA", bg=PANEL_BG, fg=FG,
                 font=("Consolas", 13, "bold")).pack(side=tk.LEFT)
        self._a_dot = tk.Label(row, text=" ●", bg=PANEL_BG, fg=RED,
                                font=("Consolas", 15))
        self._a_dot.pack(side=tk.LEFT, padx=6)
        self._a_status = tk.Label(row, text="Disconnected", bg=PANEL_BG,
                                   fg=RED, font=("Consolas", 9))
        self._a_status.pack(side=tk.LEFT)

        _sep(parent)

        # Config grid
        cfg = tk.Frame(parent, bg=PANEL_BG)
        cfg.pack(fill=tk.X, **pad)

        self._a_host   = _cfg_row(cfg, "Broker Host:",    "192.168.1.100", 0)
        self._a_port   = _cfg_row(cfg, "Broker Port:",    "1883",          1)
        self._a_pid    = _cfg_row(cfg, "Pedestal ID:",    "1",             2)
        self._a_hb_ms  = _cfg_row(cfg, "Heartbeat (ms):", "5000",         3)

        _sep(parent)

        # Connect / Disconnect
        btn_row = tk.Frame(parent, bg=PANEL_BG)
        btn_row.pack(fill=tk.X, **pad)
        tk.Button(btn_row, text="▶  Connect", bg=GREEN, fg="#1e1e2e",
                  font=("Consolas", 10, "bold"), relief=tk.FLAT,
                  padx=18, pady=7, command=self._arduino_connect
                  ).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(btn_row, text="■  Disconnect", bg=BTN_BG, fg=FG,
                  font=("Consolas", 10), relief=tk.FLAT,
                  padx=18, pady=7, command=self._arduino_disconnect
                  ).pack(side=tk.LEFT)

        _sep(parent)

        # Heartbeat info + manual send
        hb_row = tk.Frame(parent, bg=PANEL_BG)
        hb_row.pack(fill=tk.X, **pad)
        tk.Label(hb_row, text="Last heartbeat:", bg=PANEL_BG, fg=DIM,
                 font=("Consolas", 9)).pack(side=tk.LEFT)
        self._hb_lbl = tk.Label(hb_row, text="—", bg=PANEL_BG, fg=PURPLE,
                                  font=("Consolas", 9))
        self._hb_lbl.pack(side=tk.LEFT, padx=8)
        tk.Button(hb_row, text="Send Now", bg=BTN_BG, fg=FG,
                  font=("Consolas", 8), relief=tk.FLAT, padx=8,
                  command=self._send_heartbeat
                  ).pack(side=tk.RIGHT)

        # Register
        reg_row = tk.Frame(parent, bg=PANEL_BG)
        reg_row.pack(fill=tk.X, **pad)
        tk.Label(reg_row, text="Device registration:", bg=PANEL_BG, fg=DIM,
                 font=("Consolas", 9)).pack(side=tk.LEFT)
        tk.Button(reg_row, text="Send /register", bg=BTN_BG, fg=FG,
                  font=("Consolas", 9), relief=tk.FLAT, padx=10,
                  command=self._send_register
                  ).pack(side=tk.RIGHT)

        _sep(parent)

        # Received NUC commands
        tk.Label(parent, text="Received NUC → Arduino commands:",
                 bg=PANEL_BG, fg=DIM, font=("Consolas", 9)
                 ).pack(anchor=tk.W, padx=12)
        self._cmd_box = scrolledtext.ScrolledText(
            parent, height=7, bg="#11111b", fg=BLUE,
            font=("Consolas", 9), state=tk.DISABLED, wrap=tk.WORD,
        )
        self._cmd_box.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

    def _tab_sockets(self, parent):
        tk.Label(parent, text="Socket Relays  (Arduino OPTA outputs)",
                 bg=PANEL_BG, fg=FG, font=("Consolas", 11, "bold")
                 ).pack(anchor=tk.W, padx=12, pady=(10, 4))
        tk.Label(parent,
                 text="Send 'connected' when plug inserted, 'disconnected' when removed.",
                 bg=PANEL_BG, fg=DIM, font=("Consolas", 8)
                 ).pack(anchor=tk.W, padx=12, pady=(0, 6))

        self._sock_vars: dict[int, tuple[tk.StringVar, tk.StringVar]] = {}

        for s in range(1, 5):
            box = tk.LabelFrame(parent, text=f"  Socket {s}  ",
                                bg=PANEL_BG, fg=PURPLE,
                                font=("Consolas", 9), relief=tk.GROOVE)
            box.pack(fill=tk.X, padx=12, pady=5)

            r1 = tk.Frame(box, bg=PANEL_BG)
            r1.pack(fill=tk.X, padx=8, pady=5)
            tk.Label(r1, text="Status:", bg=PANEL_BG, fg=FG,
                     font=("Consolas", 9), width=8).pack(side=tk.LEFT)
            tk.Button(r1, text="⬤  Connected", bg=GREEN, fg="#1e1e2e",
                      font=("Consolas", 9), relief=tk.FLAT, padx=12,
                      command=lambda sid=s: self._socket_status(sid, "connected")
                      ).pack(side=tk.LEFT, padx=4)
            tk.Button(r1, text="○  Disconnected", bg=RED, fg="#1e1e2e",
                      font=("Consolas", 9), relief=tk.FLAT, padx=12,
                      command=lambda sid=s: self._socket_status(sid, "disconnected")
                      ).pack(side=tk.LEFT, padx=4)

            r2 = tk.Frame(box, bg=PANEL_BG)
            r2.pack(fill=tk.X, padx=8, pady=(0, 7))
            tk.Label(r2, text="Watts:", bg=PANEL_BG, fg=FG,
                     font=("Consolas", 9)).pack(side=tk.LEFT)
            w_var = tk.StringVar(value="230.0")
            tk.Entry(r2, textvariable=w_var, bg=ENTRY_BG, fg=FG,
                     font=("Consolas", 9), width=9, relief=tk.FLAT,
                     insertbackground=FG).pack(side=tk.LEFT, padx=4)
            tk.Label(r2, text="kWh:", bg=PANEL_BG, fg=FG,
                     font=("Consolas", 9)).pack(side=tk.LEFT, padx=(10, 0))
            k_var = tk.StringVar(value="0.000")
            tk.Entry(r2, textvariable=k_var, bg=ENTRY_BG, fg=FG,
                     font=("Consolas", 9), width=9, relief=tk.FLAT,
                     insertbackground=FG).pack(side=tk.LEFT, padx=4)
            tk.Button(r2, text="Send Power", bg=BTN_BG, fg=FG,
                      font=("Consolas", 9), relief=tk.FLAT, padx=10,
                      command=lambda sid=s, wv=w_var, kv=k_var:
                          self._send_power(sid, wv, kv)
                      ).pack(side=tk.LEFT, padx=(12, 0))

            self._sock_vars[s] = (w_var, k_var)

    def _tab_sensors(self, parent):
        pad = dict(padx=12, pady=8)

        # ── Moisture ──
        mbox = tk.LabelFrame(parent, text="  Moisture Sensor  ",
                             bg=PANEL_BG, fg=PURPLE,
                             font=("Consolas", 9), relief=tk.GROOVE)
        mbox.pack(fill=tk.X, **pad)
        mr = tk.Frame(mbox, bg=PANEL_BG)
        mr.pack(fill=tk.X, padx=10, pady=8)
        tk.Label(mr, text="Moisture %:", bg=PANEL_BG, fg=FG,
                 font=("Consolas", 9)).pack(side=tk.LEFT)
        self._moist_var = tk.StringVar(value="45.0")
        tk.Entry(mr, textvariable=self._moist_var, bg=ENTRY_BG, fg=FG,
                 font=("Consolas", 10), width=8, relief=tk.FLAT,
                 insertbackground=FG).pack(side=tk.LEFT, padx=8)
        self._moist_alarm = tk.Label(mr, text="", bg=PANEL_BG, fg=RED,
                                      font=("Consolas", 9, "bold"))
        self._moist_alarm.pack(side=tk.LEFT)
        tk.Label(mr, text="⚠ NUC alarm > 90%", bg=PANEL_BG, fg=DIM,
                 font=("Consolas", 8)).pack(side=tk.LEFT, padx=8)
        tk.Button(mr, text="Send", bg=BTN_BG, fg=FG, font=("Consolas", 9),
                  relief=tk.FLAT, padx=12,
                  command=self._send_moisture
                  ).pack(side=tk.RIGHT, padx=6)

        # ── Water flow ──
        wbox = tk.LabelFrame(parent, text="  Water Flow Meter  ",
                             bg=PANEL_BG, fg=PURPLE,
                             font=("Consolas", 9), relief=tk.GROOVE)
        wbox.pack(fill=tk.X, **pad)
        wr = tk.Frame(wbox, bg=PANEL_BG)
        wr.pack(fill=tk.X, padx=10, pady=8)
        tk.Label(wr, text="Flow L/min:", bg=PANEL_BG, fg=FG,
                 font=("Consolas", 9)).pack(side=tk.LEFT)
        self._water_lpm = tk.StringVar(value="12.5")
        tk.Entry(wr, textvariable=self._water_lpm, bg=ENTRY_BG, fg=FG,
                 font=("Consolas", 9), width=8, relief=tk.FLAT,
                 insertbackground=FG).pack(side=tk.LEFT, padx=6)
        tk.Label(wr, text="Total L:", bg=PANEL_BG, fg=FG,
                 font=("Consolas", 9)).pack(side=tk.LEFT, padx=(10, 0))
        self._water_total = tk.StringVar(value="0.0")
        tk.Entry(wr, textvariable=self._water_total, bg=ENTRY_BG, fg=FG,
                 font=("Consolas", 9), width=8, relief=tk.FLAT,
                 insertbackground=FG).pack(side=tk.LEFT, padx=6)
        tk.Button(wr, text="Send", bg=BTN_BG, fg=FG, font=("Consolas", 9),
                  relief=tk.FLAT, padx=12,
                  command=self._send_water
                  ).pack(side=tk.RIGHT, padx=6)

    def _tab_diagnostics(self, parent):
        tk.Label(parent,
                 text="Diagnostics  —  NUC sends request, Arduino replies with sensor status",
                 bg=PANEL_BG, fg=FG, font=("Consolas", 9, "bold")
                 ).pack(anchor=tk.W, padx=12, pady=(10, 2))
        tk.Label(parent,
                 text="Set each sensor to ok / fail, then click Send Response.",
                 bg=PANEL_BG, fg=DIM, font=("Consolas", 8)
                 ).pack(anchor=tk.W, padx=12, pady=(0, 6))

        _sep(parent)

        self._diag_vars: dict[str, tk.StringVar] = {}
        sensors = ["socket_1", "socket_2", "socket_3", "socket_4",
                   "water", "temperature", "moisture", "camera"]

        grid = tk.Frame(parent, bg=PANEL_BG)
        grid.pack(fill=tk.X, padx=12, pady=8)
        for i, name in enumerate(sensors):
            r, c = divmod(i, 2)
            cell = tk.Frame(grid, bg=PANEL_BG)
            cell.grid(row=r, column=c, padx=14, pady=4, sticky=tk.W)
            var = tk.StringVar(value="ok")
            self._diag_vars[name] = var
            tk.Label(cell, text=f"{name}:", bg=PANEL_BG, fg=FG,
                     font=("Consolas", 9), width=14, anchor=tk.W
                     ).pack(side=tk.LEFT)
            cb = ttk.Combobox(cell, textvariable=var,
                              values=["ok", "fail", "missing"],
                              width=9, state="readonly")
            cb.pack(side=tk.LEFT)

        _sep(parent)

        br = tk.Frame(parent, bg=PANEL_BG)
        br.pack(fill=tk.X, padx=12, pady=6)
        tk.Button(br, text="Send Diagnostics Response", bg=BLUE, fg="#1e1e2e",
                  font=("Consolas", 10, "bold"), relief=tk.FLAT,
                  padx=16, pady=7, command=self._send_diagnostics
                  ).pack(side=tk.LEFT)
        tk.Button(br, text="All OK", bg=GREEN, fg="#1e1e2e",
                  font=("Consolas", 9), relief=tk.FLAT, padx=10,
                  command=lambda: [v.set("ok") for v in self._diag_vars.values()]
                  ).pack(side=tk.LEFT, padx=8)
        tk.Button(br, text="All FAIL", bg=RED, fg="#1e1e2e",
                  font=("Consolas", 9), relief=tk.FLAT, padx=10,
                  command=lambda: [v.set("fail") for v in self._diag_vars.values()]
                  ).pack(side=tk.LEFT)

        _sep(parent)
        tk.Label(parent, text="Last diagnostics request received:",
                 bg=PANEL_BG, fg=DIM, font=("Consolas", 9)
                 ).pack(anchor=tk.W, padx=12)
        self._diag_req_lbl = tk.Label(parent, text="(none)", bg=PANEL_BG,
                                       fg=YELLOW, font=("Consolas", 9))
        self._diag_req_lbl.pack(anchor=tk.W, padx=12, pady=(2, 8))

    def _tab_custom(self, parent):
        tk.Label(parent, text="Custom Publish / Subscribe",
                 bg=PANEL_BG, fg=FG, font=("Consolas", 11, "bold")
                 ).pack(anchor=tk.W, padx=12, pady=(10, 2))
        tk.Label(parent, text="Publish to or subscribe any topic on the Arduino MQTT connection.",
                 bg=PANEL_BG, fg=DIM, font=("Consolas", 8)
                 ).pack(anchor=tk.W, padx=12, pady=(0, 6))

        _sep(parent)

        # Publish row
        pr = tk.Frame(parent, bg=PANEL_BG)
        pr.pack(fill=tk.X, padx=12, pady=6)
        tk.Label(pr, text="Topic:", bg=PANEL_BG, fg=FG,
                 font=("Consolas", 9)).pack(side=tk.LEFT)
        self._cust_topic = tk.StringVar()
        tk.Entry(pr, textvariable=self._cust_topic, bg=ENTRY_BG, fg=FG,
                 font=("Consolas", 9), width=30, relief=tk.FLAT,
                 insertbackground=FG).pack(side=tk.LEFT, padx=6)
        tk.Label(pr, text="Payload:", bg=PANEL_BG, fg=FG,
                 font=("Consolas", 9)).pack(side=tk.LEFT, padx=(10, 0))
        self._cust_payload = tk.StringVar()
        tk.Entry(pr, textvariable=self._cust_payload, bg=ENTRY_BG, fg=FG,
                 font=("Consolas", 9), width=22, relief=tk.FLAT,
                 insertbackground=FG).pack(side=tk.LEFT, padx=6)
        tk.Button(pr, text="Publish", bg=BLUE, fg="#1e1e2e",
                  font=("Consolas", 9), relief=tk.FLAT, padx=10,
                  command=self._custom_publish
                  ).pack(side=tk.LEFT, padx=4)

        _sep(parent)

        # Subscribe row
        sr = tk.Frame(parent, bg=PANEL_BG)
        sr.pack(fill=tk.X, padx=12, pady=6)
        tk.Label(sr, text="Subscribe:", bg=PANEL_BG, fg=FG,
                 font=("Consolas", 9)).pack(side=tk.LEFT)
        self._cust_sub = tk.StringVar()
        tk.Entry(sr, textvariable=self._cust_sub, bg=ENTRY_BG, fg=FG,
                 font=("Consolas", 9), width=36, relief=tk.FLAT,
                 insertbackground=FG).pack(side=tk.LEFT, padx=6)
        tk.Button(sr, text="Subscribe", bg=BTN_BG, fg=FG,
                  font=("Consolas", 9), relief=tk.FLAT, padx=10,
                  command=self._custom_subscribe
                  ).pack(side=tk.LEFT, padx=4)

        _sep(parent)
        tk.Label(parent, text="Active custom subscriptions:",
                 bg=PANEL_BG, fg=DIM, font=("Consolas", 9)
                 ).pack(anchor=tk.W, padx=12)
        self._sub_listbox = tk.Listbox(parent, bg="#11111b", fg=PURPLE,
                                        font=("Consolas", 9), height=6,
                                        selectmode=tk.SINGLE)
        self._sub_listbox.pack(fill=tk.X, padx=12, pady=4)
        tk.Button(parent, text="Remove selected subscription", bg=BTN_BG, fg=FG,
                  font=("Consolas", 8), relief=tk.FLAT, padx=8,
                  command=self._remove_custom_sub
                  ).pack(anchor=tk.W, padx=12, pady=(0, 8))

    # ─────────────────────────────────────────────────────────────────────────
    #  IP Temperature Sensor section
    # ─────────────────────────────────────────────────────────────────────────

    def _build_tempsensor_section(self, parent):
        tk.Label(parent, text="🌡  IP Temperature Sensor  (SNMP)",
                 bg=BG, fg=FG, font=("Consolas", 13, "bold")
                 ).pack(anchor=tk.W, padx=10, pady=(8, 2))
        tk.Label(parent, text="Sends SNMP v2c Traps via UDP — separate device, no MQTT",
                 bg=BG, fg=DIM, font=("Consolas", 8)
                 ).pack(anchor=tk.W, padx=10, pady=(0, 6))

        frame = tk.Frame(parent, bg=PANEL_BG, relief=tk.GROOVE, bd=1)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        pad = dict(padx=12, pady=6)

        # Status (ready/sending indicator — no persistent connection for UDP)
        sr = tk.Frame(frame, bg=PANEL_BG)
        sr.pack(fill=tk.X, **pad)
        self._ts_dot = tk.Label(sr, text=" ●", bg=PANEL_BG, fg=DIM,
                                 font=("Consolas", 15))
        self._ts_dot.pack(side=tk.LEFT)
        self._ts_status = tk.Label(sr, text="Ready (UDP — no persistent connection)",
                                    bg=PANEL_BG, fg=DIM, font=("Consolas", 9))
        self._ts_status.pack(side=tk.LEFT, padx=6)

        _sep(frame)

        # SNMP Config
        cfg = tk.Frame(frame, bg=PANEL_BG)
        cfg.pack(fill=tk.X, **pad)
        self._ts_host     = _cfg_row(cfg, "NUC / Target Host:", "localhost",      0)
        self._ts_snmp_port = _cfg_row(cfg, "SNMP Trap Port:",   "1620",           1)
        self._ts_pid      = _cfg_row(cfg, "Pedestal ID:",       "1",              2)
        self._ts_community = _cfg_row(cfg, "Community:",        "public",         3)
        self._ts_oid      = _cfg_row(cfg, "Temperature OID:",
                                     "1.3.6.1.4.1.18248.20.1.2.1.1.2.1",         4)
        self._ts_interval = _cfg_row(cfg, "Auto-send (ms):",    "10000",          5)

        _sep(frame)

        # Temperature value
        tk.Label(frame, text="Temperature Value",
                 bg=PANEL_BG, fg=FG, font=("Consolas", 10, "bold")
                 ).pack(anchor=tk.W, **pad)

        tv_row = tk.Frame(frame, bg=PANEL_BG)
        tv_row.pack(fill=tk.X, padx=12, pady=4)
        tk.Label(tv_row, text="°C:", bg=PANEL_BG, fg=FG,
                 font=("Consolas", 9)).pack(side=tk.LEFT)
        self._temp_val = tk.StringVar(value="25.0")
        self._temp_entry = tk.Entry(tv_row, textvariable=self._temp_val,
                                    bg=ENTRY_BG, fg=FG,
                                    font=("Consolas", 14, "bold"),
                                    width=8, relief=tk.FLAT,
                                    insertbackground=FG)
        self._temp_entry.pack(side=tk.LEFT, padx=8)
        self._temp_alarm_lbl = tk.Label(tv_row, text="", bg=PANEL_BG, fg=RED,
                                         font=("Consolas", 9, "bold"))
        self._temp_alarm_lbl.pack(side=tk.LEFT)
        tk.Label(tv_row, text="⚠ NUC alarm > 50°C", bg=PANEL_BG, fg=DIM,
                 font=("Consolas", 8)).pack(side=tk.LEFT, padx=8)

        # Slider  −20 … 80 °C
        self._temp_slider = tk.Scale(
            frame, from_=-20, to=80, resolution=0.5, orient=tk.HORIZONTAL,
            bg=PANEL_BG, fg=FG, troughcolor=ENTRY_BG, highlightthickness=0,
            font=("Consolas", 8), label="",
            command=self._slider_moved,
        )
        self._temp_slider.set(25.0)
        self._temp_slider.pack(fill=tk.X, padx=12, pady=4)
        self._temp_val.trace_add("write", self._entry_changed)

        _sep(frame)

        # Auto-send toggle + manual send
        ar = tk.Frame(frame, bg=PANEL_BG)
        ar.pack(fill=tk.X, padx=12, pady=4)
        self._ts_auto_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ar, text="Auto-send (periodic)", variable=self._ts_auto_var,
                       bg=PANEL_BG, fg=FG, selectcolor=ENTRY_BG,
                       activebackground=PANEL_BG, activeforeground=FG,
                       font=("Consolas", 9),
                       command=self._ts_auto_toggle
                       ).pack(side=tk.LEFT)
        tk.Button(ar, text="Send Now", bg=BLUE, fg="#1e1e2e",
                  font=("Consolas", 9, "bold"), relief=tk.FLAT, padx=12,
                  command=self._send_temperature
                  ).pack(side=tk.RIGHT)

        _sep(frame)
        tk.Label(frame, text="Last sent:", bg=PANEL_BG, fg=DIM,
                 font=("Consolas", 9)).pack(anchor=tk.W, padx=12)
        self._ts_last_lbl = tk.Label(frame, text="—", bg=PANEL_BG, fg=PURPLE,
                                      font=("Consolas", 9))
        self._ts_last_lbl.pack(anchor=tk.W, padx=12, pady=(2, 10))

    # ═════════════════════════════════════════════════════════════════════════
    #  Arduino OPTA actions
    # ═════════════════════════════════════════════════════════════════════════

    def _arduino_connect(self):
        pid = self._a_pid.get().strip()
        self._arduino.connect(
            host=self._a_host.get().strip(),
            port=int(self._a_port.get()),
            topics=[
                f"pedestal/{pid}/socket/+/control",
                f"pedestal/{pid}/water/control",
                f"pedestal/{pid}/diagnostics/request",
            ],
            client_id=f"ptt-arduino-p{pid}",
        )

    def _arduino_disconnect(self):
        self._stop_heartbeat()
        self._arduino.disconnect()

    def _send_heartbeat(self):
        pid = self._a_pid.get()
        self._arduino.publish(
            f"pedestal/{pid}/heartbeat",
            json.dumps({"online": True, "timestamp": datetime.utcnow().isoformat()}),
        )
        self._hb_lbl.config(text=datetime.now().strftime("%H:%M:%S"))

    def _start_heartbeat(self):
        self._send_heartbeat()
        try:
            ms = max(500, int(self._a_hb_ms.get()))
        except ValueError:
            ms = 5000
        self._hb_job = self.after(ms, self._start_heartbeat)

    def _stop_heartbeat(self):
        if self._hb_job:
            self.after_cancel(self._hb_job)
            self._hb_job = None

    def _send_register(self):
        pid = self._a_pid.get()
        self._arduino.publish(
            f"pedestal/{pid}/register",
            json.dumps({
                "sensor_name": "Arduino OPTA Multi-Sensor",
                "sensor_type": "multi",
                "mqtt_topic":  f"pedestal/{pid}/socket/1/power",
                "unit":        "W",
            }),
        )

    def _socket_status(self, socket_id: int, status: str):
        pid = self._a_pid.get()
        self._arduino.publish(f"pedestal/{pid}/socket/{socket_id}/status", status)

    def _send_power(self, socket_id: int, w_var: tk.StringVar, k_var: tk.StringVar):
        pid = self._a_pid.get()
        try:
            watts = float(w_var.get())
            kwh   = float(k_var.get())
        except ValueError:
            return
        self._arduino.publish(
            f"pedestal/{pid}/socket/{socket_id}/power",
            json.dumps({"watts": watts, "kwh_total": kwh}),
        )

    def _send_water(self):
        pid = self._a_pid.get()
        try:
            lpm   = float(self._water_lpm.get())
            total = float(self._water_total.get())
        except ValueError:
            return
        self._arduino.publish(
            f"pedestal/{pid}/water/flow",
            json.dumps({"lpm": lpm, "total_liters": total}),
        )

    def _send_moisture(self):
        pid = self._a_pid.get()
        try:
            val = float(self._moist_var.get())
        except ValueError:
            return
        self._moist_alarm.config(text="⚠ ALARM!" if val > 90 else "")
        self._arduino.publish(
            f"pedestal/{pid}/sensors/moisture",
            json.dumps({"value": val}),
        )

    def _send_diagnostics(self):
        pid = self._a_pid.get()
        results = {k: v.get() for k, v in self._diag_vars.items()}
        self._arduino.publish(
            f"pedestal/{pid}/diagnostics/response",
            json.dumps(results),
        )

    def _custom_publish(self):
        topic   = self._cust_topic.get().strip()
        payload = self._cust_payload.get().strip()
        if topic:
            self._arduino.publish(topic, payload)

    def _custom_subscribe(self):
        topic = self._cust_sub.get().strip()
        if not topic:
            return
        self._arduino.subscribe_extra(topic)
        self._sub_listbox.insert(tk.END, topic)
        self._cust_sub.set("")

    def _remove_custom_sub(self):
        sel = self._sub_listbox.curselection()
        if sel:
            self._sub_listbox.delete(sel[0])

    # ═════════════════════════════════════════════════════════════════════════
    #  Temperature Sensor actions
    # ═════════════════════════════════════════════════════════════════════════

    def _ts_connect(self):
        # SNMP uses UDP — no persistent connection. Just validate config.
        try:
            int(self._ts_snmp_port.get())
            int(self._ts_pid.get())
            self._ts_dot.config(fg=GREEN)
            self._ts_status.config(fg=GREEN, text="Config OK — ready to send traps")
            self._append_log(f"[{datetime.now().strftime('%H:%M:%S')}] TempSensor    SNMP ready → "
                             f"{self._ts_host.get()}:{self._ts_snmp_port.get()}", err=False)
        except ValueError:
            self._ts_dot.config(fg=RED)
            self._ts_status.config(fg=RED, text="Invalid port or pedestal ID")

    def _ts_disconnect(self):
        self._stop_temp_auto()
        self._ts_dot.config(fg=DIM)
        self._ts_status.config(fg=DIM, text="Ready (UDP — no persistent connection)")

    def _send_temperature(self):
        try:
            val       = float(self._temp_val.get())
            host      = self._ts_host.get().strip()
            port      = int(self._ts_snmp_port.get())
            community = self._ts_community.get().strip()
            oid       = self._ts_oid.get().strip()
        except ValueError:
            return

        self._temp_alarm_lbl.config(text="⚠ ALARM!" if val > 50 else "")
        try:
            pdu = build_snmp_v2c_trap(community, oid, val)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(pdu, (host, port))
            sock.close()
            ts = datetime.now().strftime('%H:%M:%S')
            self._ts_last_lbl.config(text=f"{val:.1f}°C  at  {ts}")
            self._ts_dot.config(fg=GREEN)
            self._ts_status.config(fg=GREEN, text=f"Sent {val:.1f}°C at {ts}")
            self._append_log(
                f"[{ts}] TempSensor    → SNMP Trap UDP {host}:{port}  OID={oid.split('.')[-1]}…  val={val:.1f}°C",
                err=False,
            )
        except Exception as exc:
            self._ts_dot.config(fg=RED)
            self._ts_status.config(fg=RED, text=f"Send error: {exc}")
            self._append_log(
                f"[{datetime.now().strftime('%H:%M:%S')}] TempSensor    [ERROR] {exc}", err=True
            )

    def _ts_auto_toggle(self):
        if self._ts_auto_var.get():
            self._start_temp_auto()
        else:
            self._stop_temp_auto()

    def _start_temp_auto(self):
        self._send_temperature()
        try:
            ms = max(500, int(self._ts_interval.get()))
        except ValueError:
            ms = 10000
        self._temp_job = self.after(ms, self._start_temp_auto)

    def _stop_temp_auto(self):
        if self._temp_job:
            self.after_cancel(self._temp_job)
            self._temp_job = None
        self._ts_auto_var.set(False)

    def _slider_moved(self, val):
        self._temp_val.set(str(float(val)))

    def _entry_changed(self, *_):
        try:
            val = float(self._temp_val.get())
            self._temp_slider.set(val)
        except (ValueError, tk.TclError):
            pass

    # ═════════════════════════════════════════════════════════════════════════
    #  Event queue polling  (runs on tkinter main thread)
    # ═════════════════════════════════════════════════════════════════════════

    def _poll_queue(self):
        try:
            while True:
                event = self._q.get_nowait()
                kind  = event[0]
                name  = event[1]

                if kind == "log":
                    self._append_log(event[2], err=event[3])

                elif kind == "status":
                    ok = event[2]
                    if name == "Arduino":
                        self._set_conn_status(
                            self._a_dot, self._a_status, ok
                        )
                        if ok:
                            self._start_heartbeat()
                        else:
                            self._stop_heartbeat()

                elif kind == "msg" and name == "Arduino":
                    topic, payload = event[2], event[3]
                    self._handle_nuc_command(topic, payload)

        except queue.Empty:
            pass

        self.after(POLL_MS, self._poll_queue)

    def _handle_nuc_command(self, topic: str, payload: str):
        ts   = datetime.now().strftime("%H:%M:%S")
        text = f"[{ts}]  ← {topic}\n           {payload}\n"
        self._cmd_box.config(state=tk.NORMAL)
        self._cmd_box.insert(tk.END, text)
        self._cmd_box.see(tk.END)
        self._cmd_box.config(state=tk.DISABLED)
        if "diagnostics/request" in topic:
            self._diag_req_lbl.config(
                text=f"Received at {ts}  — payload: {payload}"
            )

    # ═════════════════════════════════════════════════════════════════════════
    #  Helpers
    # ═════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _set_conn_status(dot: tk.Label, lbl: tk.Label, ok: bool):
        color = GREEN if ok else RED
        text  = "Connected" if ok else "Disconnected"
        dot.config(fg=color)
        lbl.config(fg=color, text=text)

    def _append_log(self, text: str, err: bool = False):
        tag = "rx" if ("← " in text) else ("err" if err else "")
        self._log_box.config(state=tk.NORMAL)
        self._log_box.insert(tk.END, text + "\n", tag)
        self._log_box.see(tk.END)
        self._log_box.config(state=tk.DISABLED)

    def on_close(self):
        self._stop_heartbeat()
        self._stop_temp_auto()
        self._arduino.disconnect()
        self.destroy()


# ─── Module-level helpers ─────────────────────────────────────────────────────

def _sep(parent):
    tk.Frame(parent, bg=ENTRY_BG, height=1).pack(fill=tk.X, padx=8, pady=4)


def _cfg_row(grid: tk.Frame, label: str, default: str, row: int) -> tk.StringVar:
    tk.Label(grid, text=label, bg=PANEL_BG, fg=FG,
             font=("Consolas", 9), width=20, anchor=tk.W
             ).grid(row=row, column=0, sticky=tk.W, pady=3)
    var = tk.StringVar(value=default)
    tk.Entry(grid, textvariable=var, bg=ENTRY_BG, fg=FG,
             font=("Consolas", 9), width=24, relief=tk.FLAT,
             insertbackground=FG
             ).grid(row=row, column=1, sticky=tk.W, padx=8, pady=3)
    return var


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = PedestalTestTool()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
