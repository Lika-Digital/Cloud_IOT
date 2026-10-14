"""Generates Broker_Firmware_Contract.docx with three sections:
1. Kako trenutno rade osnovne funkcije ormara (voda + struja).
2. MQTT broker ↔ firmware ugovor (sve topice po fazama).
3. Sto fali na firmware/PLC strani za pun rad sistema.
"""
from pathlib import Path
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT = Path(__file__).resolve().parent.parent / "Broker_Firmware_Contract.docx"


def h1(doc, text):
    p = doc.add_heading(text, level=1)
    return p


def h2(doc, text):
    return doc.add_heading(text, level=2)


def h3(doc, text):
    return doc.add_heading(text, level=3)


def para(doc, text, bold=False):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(11)
    return p


def bullet(doc, text):
    p = doc.add_paragraph(text, style="List Bullet")
    for r in p.runs:
        r.font.size = Pt(11)
    return p


def code_block(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "Consolas"
    run.font.size = Pt(9)
    p.paragraph_format.left_indent = Cm(0.5)
    return p


def add_table(doc, headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = h
        for r in hdr[i].paragraphs[0].runs:
            r.bold = True
            r.font.size = Pt(10)
    for r_idx, row in enumerate(rows, start=1):
        for c_idx, val in enumerate(row):
            table.rows[r_idx].cells[c_idx].text = val
            for r in table.rows[r_idx].cells[c_idx].paragraphs[0].runs:
                r.font.size = Pt(10)
    return table


def build():
    doc = Document()

    # Document title
    title = doc.add_heading("Cloud_IOT — Broker ↔ Firmware Contract", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("Stanje brokera: v3.12   |   Stanje firmware-a: Lika v2.0 (sketch + PLC)")
    r.italic = True
    r.font.size = Pt(10)

    # ─────────────────────────────────────────────────────────────────────
    # SECTION 1
    # ─────────────────────────────────────────────────────────────────────
    h1(doc, "1. Trenutno ponasanje ormara — osnovne funkcije")

    para(doc,
         "Ovaj dio opisuje sto se dogada kad se ormar prvi put upali, kako se "
         "ponasa voda, kako struja, i kakvu ulogu ima auto-activate konfiguracija. "
         "Sve sto je ovdje opisano je trenutno implementirano u brokeru.")

    h2(doc, "1.1  Inicijalizacija ormara")
    bullet(doc,
           "Cabinet se spaja na MQTT broker i pocinje publishati retained "
           "'opta/status' heartbeat svakih ~60 s (s cabinetId, seq, uptime, door).")
    bullet(doc,
           "Broker auto-registrira nepoznati pedestal u bazi cim primi prvi "
           "heartbeat (v3.7 auto-discovery). Ime ormara se prvi put 'uljepsa' "
           "(MAR_KRK_ORM_01 → MAR KRK ORM 01); operatorske preimenovanja se "
           "kasnije ne prepisuju.")
    bullet(doc,
           "Cim stignu prve 'opta/sockets/Q*/status' poruke, broker auto-create "
           "SocketConfig red s 'auto_activate=False' (default OFF za struju) i "
           "generira QR PNG label na disku.")
    bullet(doc,
           "Cim stignu prve 'opta/water/V*/status' poruke, broker auto-create "
           "ValveConfig red s 'auto_activate=True' (default ON za vodu).")
    bullet(doc,
           "Broker posalje 'opta/cmd/time' za RTC sync na seq:0 i ponavlja "
           "svakih 60 minuta.")
    bullet(doc,
           "Broker zatim okine 'opta/cmd/diagnostic' za provjeru senzora.")

    h2(doc, "1.2  Voda — opt-out, default OTVORENA")
    para(doc,
         "Voda je dostupna korisniku praktick neposredno nakon paljenja ormara. "
         "Hardver ventila je 'normally-closed', pa cinjenica da je auto-activate "
         "default uključen znaci da broker AKTIVNO mora poslati activate komandu "
         "— nista ne curi samo od sebe ako MQTT padne.",
         bold=False)

    para(doc, "Sekvenca:", bold=True)
    bullet(doc, "Cabinet prijavi 'opta/water/V{n}/status' → broker kreira ValveConfig (auto_activate=True).")
    bullet(doc, "Broker dobije odgovor na diagnostic ('opta/diagnostic') koji sadrzi 'water_v1' i 'water_v2' status.")
    bullet(doc, "Za svaki ventil ciji senzor javi 'ok', broker publishira:")
    code_block(doc,
               "topic:   opta/cmd/water/V{n}\n"
               "payload: {\"msgId\":\"...\",\"cabinetId\":\"...\",\"action\":\"activate\"}")
    bullet(doc, "Firmware odgovori s 'OutletActivated' eventom → broker kreira UNATTRIBUTED sesiju (customer_id=NULL).")
    bullet(doc, "Dashboard pokazuje amber UNATTRIBUTED znacku — voda tece, mjeri se, ali nije ni kome naplacena.")
    bullet(doc, "30 s nakon publisha radi 'zero-flow watchdog' — ako je lpm=0, broker generira upozorenje (vjerojatno hose nije spojen). Ventil ostaje otvoren.")

    para(doc, "Guardovi koji mogu sprijeciti auto-open:", bold=True)
    bullet(doc, "Operater je rucno isključio auto_activate na tom ventilu.")
    bullet(doc, "Vec postoji aktivna water sesija na tom ventilu.")
    bullet(doc, "Operater je rucno stopirao ventil u zadnjih 10 minuta (cooldown sprjecava replay).")
    bullet(doc, "Pedestal nema konfiguriran cabinet_id (MQTT publish nije moguc).")

    h2(doc, "1.3  Struja — opt-in, default NIJE AKTIVNA")
    para(doc,
         "Struja se NE aktivira automatski po defaultu. To je svjesno dizajn "
         "rjesenje — automatski energizirati utičnicu bez operatorske odluke je "
         "rizik (kratki spoj, kriva potrosnja, sigurnost korisnika).")

    para(doc, "Default sekvenca (auto_activate=False):", bold=True)
    bullet(doc, "Korisnik utakne kabel u utičnicu.")
    bullet(doc, "Firmware emitira 'UserPluggedIn' event na 'opta/events'.")
    bullet(doc, "Broker prebaci socket u stanje 'pending' (žuta boja u dashboardu, tooltip 'Plug inserted — awaiting activation').")
    bullet(doc, "Stop — broker NE salje activate sam od sebe.")
    bullet(doc, "Operater u Control Centeru klikne Activate → broker publishira 'opta/cmd/socket/Q{n}' s {\"action\":\"activate\"} → struja tece.")

    para(doc, "Opcijska sekvenca (operater rucno upalio auto_activate na tom socketu):", bold=True)
    bullet(doc, "Korisnik utakne → UserPluggedIn → socket 'pending'.")
    bullet(doc, "Broker pokrene 5 precondition checkova:")
    code_block(doc,
               "1. vrata zatvorena (unknown ≡ open)\n"
               "2. nema aktivnog alarma na pedestalu\n"
               "3. heartbeat unutar 300 s\n"
               "4. socket nije vec aktivan\n"
               "5. nije bilo diagnostica u zadnjih 60 s")
    bullet(doc, "Ako sve prode → 2 s firmware stabilisation delay.")
    bullet(doc, "Re-check (operater mozda u meduvremenu kliknuo, plug izvucen) → publish activate.")
    bullet(doc, "Svaki ishod (success/skipped + razlog) zapisuje se u 'auto_activation_log' tablicu i broadcasta na dashboard.")

    h2(doc, "1.4  Blokada i prekid sesije")
    bullet(doc, "Operator stop: dashboard → 'opta/cmd/socket/Q{n}' s {\"action\":\"stop\"} → sesija 'end_reason=operator_stop'.")
    bullet(doc, "Customer stop: mobilna aplikacija MORA fizicki izvuci kabel — softverski stop sa strane mobitela vraca HTTP 403 (v3.6).")
    bullet(doc, "UserPluggedOut event: backend prvo publishira stop, pa zatvara sesiju cisto.")
    bullet(doc, "Auto-stop overload (v3.12): ako live meter pokaze 90% od rated_amps, broker sam publishira stop i postavlja latch koji blokira ponovnu aktivaciju dok admin ne kliknne Acknowledge.")
    bullet(doc, "Breaker trip (v3.8): BreakerTripped event automatski zatvara aktivnu sesiju s 'end_reason=breaker_trip'.")
    bullet(doc, "Deny pending sesije: mobilni claim flow moze biti odbijen s razlogom preko 'POST /api/customer/sessions/{id}/deny'.")

    h2(doc, "1.5  Auto-activate konfiguracija — sazetak")
    add_table(doc,
              ["Resurs", "Default flag", "Trigger za auto-fire", "Tko mijenja"],
              [
                  ["Voda V1/V2", "auto_activate = TRUE", "Odgovor na opta/diagnostic (per-valve OK)",
                   "Operator preko PATCH /api/pedestals/{pid}/valves/{vid}/config"],
                  ["Struja Q1..Q4", "auto_activate = FALSE", "UserPluggedIn (samo ako je flag rucno upaljen)",
                   "Operator preko PATCH /api/pedestals/{pid}/sockets/{sid}/config"],
              ])

    # ─────────────────────────────────────────────────────────────────────
    # SECTION 2
    # ─────────────────────────────────────────────────────────────────────
    doc.add_page_break()
    h1(doc, "2. MQTT broker ↔ firmware ugovor")

    para(doc,
         "Ovaj dio opisuje sto broker salje, sto subscribea, i kada — kroz "
         "cetiri faze zivotnog ciklusa: inicijalizacija, aktivacija sesije, "
         "zatvaranje sesije, alarmi. Sve cabinetId vrijednosti dolaze iz "
         "opta/status heartbeata; broker ih cache-ira (~60 s) i koristi za "
         "atribuciju svih ostalih poruka.")

    h2(doc, "2.1  Kompletna mapa topicova")
    para(doc, "Device → Backend (broker subscribea):", bold=True)
    add_table(doc,
              ["Topic", "Retain", "Sadrzaj"],
              [
                  ["opta/status", "YES", "Heartbeat — cabinetId, seq, uptime_ms, door"],
                  ["opta/door/status", "YES", "Vrata open/closed (cabinetId, ts)"],
                  ["opta/sockets/Q{1-4}/status", "NO", "Per-socket state, hw_status, session info"],
                  ["opta/sockets/Q{1-4}/power", "NO", "watts, kwh_total (legacy, sad embedan u events)"],
                  ["opta/water/V{1-2}/status", "NO", "Per-valve state, hw_status, total_l, session_l"],
                  ["opta/events", "NO", "Strukturirani JSON: UserPluggedIn/Out, OutletActivated, SessionEnded, AlarmRaised, BreakerTripped, DoorOpen/Closed, TelemetryUpdate"],
                  ["opta/acks", "NO", "Command acknowledgements (cmd_topic, status, msgId, ts)"],
                  ["opta/diagnostic", "NO", "Odgovor na cmd/diagnostic — power[], water[], time, door"],
                  ["opta/breakers/Q{n}/status", "YES*", "v3.8 breaker state + RCD metadata (FIRMWARE NE PUBLISHIRA)"],
                  ["opta/config/hardware", "YES*", "v3.11 phases, ratedAmps, modbusAddress po socketu (FIRMWARE NE PUBLISHIRA)"],
                  ["opta/meters/{socketId}/telemetry", "NO", "v3.11 live amps/V/PF/freq svakih 5 s (FIRMWARE NE PUBLISHIRA)"],
              ])

    para(doc, "Backend → Device (broker publishira):", bold=True)
    add_table(doc,
              ["Topic", "Payload", "Kada se publishira"],
              [
                  ["opta/cmd/socket/Q{1-4}", "{msgId, cabinetId, action: activate|stop}",
                   "Operator klik Activate/Stop u Control Centeru; auto-stop na 90%"],
                  ["opta/cmd/water/V{1-2}", "{msgId, cabinetId, action: activate|stop}",
                   "Post-diagnostic auto-open; operator stop"],
                  ["opta/cmd/led", "{cabinetId, color, state}", "Operator iz UI-ja ili LED scheduler tick"],
                  ["opta/cmd/reset", "{cabinetId, cmd: reset}", "Operator double-click confirm; prekida sve sesije"],
                  ["opta/cmd/time", "{msgId, action: sync, epoch, iso}",
                   "Auto: na seq:0 (Opta restart) + svakih 60 min"],
                  ["opta/cmd/diagnostic", "{cabinetId, request: all}",
                   "Operator klik Run Diagnostics; takoder okida valve auto-open flow"],
                  ["opta/cmd/breaker/Q{n}", "{msgId, cabinetId, action: reset}",
                   "v3.8 (FIRMWARE NE SUBSCRIBEA jos)"],
              ])

    h2(doc, "2.2  Faza A — Inicijalizacija ormara")
    para(doc,
         "Sve od trenutka kad Opta dobije IP i otvori MQTT konekciju do "
         "trenutka kad je ormar 'spreman za korisnika'.")

    bullet(doc, "T+0 ms: Firmware spaja se na broker, publishira retained 'opta/status' (cabinetId, seq=0, uptime_ms, door).")
    bullet(doc, "T+~50 ms: Broker prima heartbeat, auto-registrira pedestal ako je nepoznat. Resetira cache cabinetId-a.")
    bullet(doc, "T+~50 ms: Broker detektira seq:0 → automatski publishira 'opta/cmd/time' za sync RTC-a.")
    bullet(doc, "T+~100 ms: Firmware publishira retained 'opta/door/status' i (trebao bi) retained 'opta/breakers/Q{n}/status' i 'opta/config/hardware' — zadnja dva ne stizu jos.")
    bullet(doc, "T+~200 ms: Firmware publishira inicijalne 'opta/sockets/Q*/status' i 'opta/water/V*/status'.")
    bullet(doc, "T+~200 ms: Broker za svaki neviden socket/valve auto-create SocketConfig/ValveConfig red s odgovarajucim defaultom (False/True).")
    bullet(doc, "T+~500 ms: Broker publishira 'opta/cmd/diagnostic'.")
    bullet(doc, "T+~1-5 s: Firmware odgovori s 'opta/diagnostic' koji ukljucuje water_v1, water_v2, power[Q1..Q4] status.")
    bullet(doc, "T+~5 s: Broker iterira kroz per_valve_ok rezultate i okida '_maybe_auto_open_valve' za svaki valid ventil → publish 'opta/cmd/water/V{n}' activate.")
    bullet(doc, "T+~7 s: Firmware odgovori s 'OutletActivated' eventom za svaki otvoreni ventil → broker kreira unattributed water sesiju.")
    bullet(doc, "Od ovog trenutka voda je dostupna korisniku, struja ceka 'UserPluggedIn'.")

    h2(doc, "2.3  Faza B — Aktivacija sesije")

    para(doc, "B.1  Aktivacija struje (default, bez auto_activate):", bold=True)
    code_block(doc,
               "user           firmware                     broker                       UI\n"
               "  │              │                            │                          │\n"
               "  ├─ plug in ──▶ │                            │                          │\n"
               "  │              ├──── UserPluggedIn ────────▶│                          │\n"
               "  │              │       (opta/events)        ├── socket_state_changed ─▶│ (yellow, pending)\n"
               "  │              │                            │                          │\n"
               "  │              │                            │◀────── click Activate ───┤\n"
               "  │              │◀── opta/cmd/socket/Q{n} ───┤   {action:activate}      │\n"
               "  │              │       (activate)           │                          │\n"
               "  │              ├──── opta/acks (ok) ───────▶│                          │\n"
               "  │              ├──── OutletActivated ──────▶│── socket_state_changed ─▶│ (green, active)\n"
               "  │              │       (opta/events)        ├── create session row     │\n"
               "  │              ├──── TelemetryUpdate ──────▶│  (svakih 15 s)           │\n"
               "  │              │   (kw, kwh, duration)      │                          │")

    para(doc, "B.2  Aktivacija vode (post-diagnostic auto-open, default):", bold=True)
    bullet(doc, "Broker primio 'opta/diagnostic' s water_v1/water_v2='ok'.")
    bullet(doc, "Broker iterira po ventilima koji su prosli guarde (auto_activate, no-active-session, 10-min cooldown, cabinet_id).")
    bullet(doc, "Broker publish 'opta/cmd/water/V{n}' s msgId=epoch_ms i action='activate'.")
    bullet(doc, "Firmware otvori relej, generira ormarSessionId (OBE-S-XXXX), publish 'OutletActivated' s mmSessionId='' (prazno).")
    bullet(doc, "Broker primi event, kreira sesiju s customer_id=NULL, type='water', valve_id=1 ili 2.")
    bullet(doc, "Broker postavi 30 s watchdog — ako lpm=0 nakon toga, generira valve_flow_warning.")
    bullet(doc, "Firmware salje TelemetryUpdate (waterLitersTotal, flowLpm) svakih 15 s.")

    h2(doc, "2.4  Faza C — Zatvaranje sesije")
    add_table(doc,
              ["Trigger", "Mehanizam", "end_reason"],
              [
                  ["Operator Stop (dashboard)", "Broker publish opta/cmd/socket/Q{n} action=stop → firmware → SessionEnded event", "operator_stop"],
                  ["User unplug", "Firmware emit UserPluggedOut event → broker publish stop → close session", "user_unplugged"],
                  ["Customer pull-cable", "Isto kao gore — mobitel NE moze softverski stopirati", "user_unplugged"],
                  ["Breaker trip (v3.8)", "BreakerTripped event → automatski close + session ends", "breaker_trip"],
                  ["Overload auto-stop (v3.12)", "Meter telemetry >= 90% rated_amps → broker auto-publish stop + alarm latch", "auto_stop_overload"],
                  ["Pedestal reset", "Broker publish opta/cmd/reset → firmware zatvara sve sesije", "device_reset"],
                  ["MQTT disconnect", "Broker detektira nestanak heartbeata > 5 min, zatvara sve aktivne sesije", "disconnect"],
              ])
    para(doc,
         "Bez obzira na trigger, sesija se zatvara idempotentno (invoices.session_id "
         "ima UNIQUE constraint, create_invoice_for_session se ne moze duplo "
         "izvrsiti). Energija/voda totali uzimaju max(readings) jer firmware "
         "salje session-cumulative metrike, ne lifetime.")

    h2(doc, "2.5  Faza D — Alarmi i upozorenja")
    add_table(doc,
              ["Izvor", "Topic / Event", "Sto broker radi"],
              [
                  ["Firmware AlarmRaised", "opta/events eventType=AlarmRaised",
                   "Spremi u alarms tablicu, broadcast hardware_alarm, browser notification adminima"],
                  ["BreakerTripped (v3.8)", "opta/events eventType=BreakerTripped",
                   "Append u breaker_events, close active session, broadcast breaker_alarm, fire webhook"],
                  ["Temperature > 50°C", "pedestal/{id}/sensors/temperature (legacy)",
                   "Hardware alarm, persistent, admin notification"],
                  ["Moisture > 90%", "pedestal/{id}/sensors/moisture (legacy)",
                   "Hardware alarm, persistent"],
                  ["Door open", "opta/door/status door=open",
                   "Broadcast door_state_changed, ako je auto_activate na bilo kojem socketu → blokira ga"],
                  ["Zero-flow nakon valve auto-open", "Watchdog (interno, ne MQTT)",
                   "valve_flow_warning broadcast + admin notification, ventil ostaje otvoren"],
                  ["Meter 60% load (v3.11)", "opta/meters/+/telemetry",
                   "INSERT u meter_load_alarms (warning), broadcast meter_load_warning"],
                  ["Meter 80% load (v3.11)", "opta/meters/+/telemetry",
                   "Auto-resolve warning → critical, broadcast meter_load_critical, browser notification"],
                  ["Meter 90% load (v3.12)", "opta/meters/+/telemetry",
                   "AUTO-STOP — publish stop, latch=True, alarm_type=auto_stop, blokira reactivate dok admin ne acknowledge"],
              ])

    # ─────────────────────────────────────────────────────────────────────
    # SECTION 3
    # ─────────────────────────────────────────────────────────────────────
    doc.add_page_break()
    h1(doc, "3. Sto fali na firmware/PLC strani")

    para(doc,
         "Broker je trenutno na v3.12 i podržava funkcije koje firmware Lika v2.0 "
         "(sketch + PLC) jos ne implementira. Sve sto je ispod identificirano je "
         "kroz citanje izvornog koda 'LLSketch.ino' (1433 linije) i PLC simbolne "
         "tablice 'Build/Lika - v2.0.sym.xml'. Dok ovo ne stigne, odgovarajuce "
         "broker funkcije su 'dormant' — UI pokazuje 'Awaiting hardware configuration' "
         "ili alarmi se naprosto nikad ne pojavljuju.")

    h2(doc, "3.1  CRITICAL — v3.11 / v3.12 load monitoring i overload zastita")
    para(doc,
         "Bez ovih topica, 90% auto-stop overload zastita FIZICKI NE MOZE OKINUTI. "
         "U kodu broker explicitly preskace auto-stop granu kad je rated_amps=NULL "
         "i upisuje warning log. To znaci da je kljucna sigurnosna znacajka "
         "trenutno neaktivna na proizvodnji.",
         bold=False)

    h3(doc, "3.1.1  opta/config/hardware — NE PUBLISHIRA SE")
    para(doc, "Sto firmware mora dodati:", bold=True)
    bullet(doc, "Publish na prvi MQTT connect i u odgovoru na svaki diagnostic request.")
    bullet(doc, "Preporuceno retain=true (kao opta/status i opta/door/status).")
    bullet(doc, "Required keys po socketu: socketId (Q1..Q4), phases (1 ili 3), ratedAmps (per-fazni rating u A).")
    bullet(doc, "Optional ali korisno: meterType, modbusAddress.")
    bullet(doc, "Per-valve: valveId (V1/V2), ratedLitersPerMin.")
    para(doc, "Primjer payloada:", bold=True)
    code_block(doc,
               "{\n"
               "  \"cabinetId\": \"MAR_KRK_ORM_01\",\n"
               "  \"firmwareVersion\": \"2.1.0\",\n"
               "  \"sockets\": [\n"
               "    {\"socketId\":\"Q1\",\"meterType\":\"ABB D11 15-M 40\",\"phases\":1,\"ratedAmps\":16,\"modbusAddress\":1},\n"
               "    {\"socketId\":\"Q2\",\"meterType\":\"ABB D11 15-M 40\",\"phases\":1,\"ratedAmps\":32,\"modbusAddress\":2},\n"
               "    {\"socketId\":\"Q3\",\"meterType\":\"ABB D11 15-M 40\",\"phases\":1,\"ratedAmps\":32,\"modbusAddress\":3},\n"
               "    {\"socketId\":\"Q4\",\"meterType\":\"ABB D13 15-M 65\",\"phases\":3,\"ratedAmps\":65,\"modbusAddress\":4}\n"
               "  ],\n"
               "  \"valves\": [\n"
               "    {\"valveId\":\"V1\",\"ratedLitersPerMin\":20},\n"
               "    {\"valveId\":\"V2\",\"ratedLitersPerMin\":20}\n"
               "  ]\n"
               "}")

    h3(doc, "3.1.2  opta/meters/{socketId}/telemetry — NE PUBLISHIRA SE")
    para(doc, "Sto firmware mora dodati:", bold=True)
    bullet(doc, "Publish svakih 5 s dok je cabinet ziv, bez obzira ima li aktivne sesije.")
    bullet(doc, "Cadence ostaje 5 s i kad nema sesije — broker mora vidjeti idle currentAmps≈0 da bi znao da je sve OK.")
    bullet(doc, "Payload shape SIGNALIZIRA fazu: 'currentAmps' (1Φ) ili 'currentAmpsTotal' (3Φ). Broker NE GLEDA topic name niti socketId — gleda payload.")

    para(doc, "1Φ primjer:", bold=True)
    code_block(doc,
               "{\n"
               "  \"cabinetId\":\"MAR_KRK_ORM_01\",\"socketId\":\"Q1\",\n"
               "  \"currentAmps\":14.7,\"voltageV\":231.2,\n"
               "  \"powerKw\":3.39,\"powerFactor\":0.98,\n"
               "  \"energyKwh\":1234.56,\"frequency\":50.0,\"ts\":12345678\n"
               "}")

    para(doc, "3Φ primjer:", bold=True)
    code_block(doc,
               "{\n"
               "  \"cabinetId\":\"MAR_KRK_ORM_01\",\"socketId\":\"Q4\",\n"
               "  \"currentAmpsL1\":12.1,\"currentAmpsL2\":11.8,\"currentAmpsL3\":12.3,\n"
               "  \"currentAmpsTotal\":36.2,\n"
               "  \"voltageL1\":231.0,\"voltageL2\":230.8,\"voltageL3\":231.5,\n"
               "  \"powerKwTotal\":8.37,\"powerFactor\":0.97,\n"
               "  \"energyKwh\":567.89,\"frequency\":50.0,\"ts\":12345678\n"
               "}")

    h3(doc, "3.1.3  PLC posao za 3.1.1 i 3.1.2")
    para(doc,
         "Trenutna PLC simbolna tablica (Build/Lika - v2.0.sym.xml) ima samo "
         "Q1..Q4_kW i Q1..Q4_kWh (vjerojatno pulse-based brojaci kroz "
         "'PulsesperkWh'). 'ModbusTCP.conf' u root projekta je prazan fajl. "
         "Modbus RTU/TCP runtime infrastruktura postoji (MbStatus, sysMbMRtu_*), "
         "ali nijedan ABB D11/D13 brojac nije mapiran.")
    para(doc, "Sto se mora dodati u PLC projekt:", bold=True)
    bullet(doc, "Modbus RTU map za ABB D11 (1Φ) brojace na adresama 1, 2, 3 — registri za current, voltage, powerKw, powerFactor, energyKwh, frequency.")
    bullet(doc, "Modbus RTU map za ABB D13 (3Φ) brojac na adresi 4 — registri za L1/L2/L3 amps, L1/L2/L3 voltage, total amps, total power, PF, energy, frequency.")
    bullet(doc, "Izloziti sve to kao PLCOut.QX_amps, PLCOut.QX_voltage, PLCOut.QX_pf, PLCOut.QX_freq (+ L1/L2/L3 varijante za 3Φ Q4).")
    bullet(doc, "ModbusTCP.conf treba popuniti tako da Modbus stack zaista konfigurira RS-485 master.")

    h2(doc, "3.2  CRITICAL — v3.8 breaker monitoring i remote reset")

    h3(doc, "3.2.1  opta/breakers/Q{n}/status — NE PUBLISHIRA SE")
    para(doc, "Sto firmware mora dodati:", bold=True)
    bullet(doc, "Publish kad god se promijeni stanje breakera (trip/close/reset).")
    bullet(doc, "MORA biti retained (retain=true) — broker ocekuje da nakon restarta vidi zadnje stanje. Bez retaina, dashboard pokazuje 'unknown' do sljedeceg state changea.")
    bullet(doc, "States: 'closed' | 'tripped' | 'open' | 'resetting'.")
    bullet(doc, "Metadata polja: type, rating, poles, rcd (yes/no), rcdSensitivity. Broker primjenjuje 'no-overwrite-with-null' pravilo, pa metadatu treba poslati barem jednom.")
    para(doc, "Primjer publish-a u PubSubClient:", bold=True)
    code_block(doc, "mqtt.publish(TOP_BREAKER_STATE_i, buf, true /* retained */);")

    h3(doc, "3.2.2  opta/cmd/breaker/Q{n} — NE SUBSCRIBEA SE")
    para(doc, "Sto firmware mora dodati:", bold=True)
    bullet(doc, "Subscribe na 'opta/cmd/breaker/Q{1-4}'.")
    bullet(doc, "Payload: {msgId, cabinetId, action:'reset'}.")
    bullet(doc, "Handler: aktivirati hardverski reset puls breakera, vratiti ACK na 'opta/acks'.")
    bullet(doc, "Dok reset traje, publish 'opta/breakers/Q{n}/status' s state='resetting', pa nakon ~1 s s 'closed' ili ponovo 'tripped' ako se nije moglo.")

    h3(doc, "3.2.3  BreakerTripped event")
    para(doc, "Sto firmware mora dodati:", bold=True)
    bullet(doc, "Kad PLC detektira da je breaker okinuo, emit 'BreakerTripped' event na 'opta/events':")
    code_block(doc,
               "{\n"
               "  \"eventId\":\"...\",\"eventType\":\"BreakerTripped\",\n"
               "  \"occurredAt\":\"...\",\n"
               "  \"device\":{\"cabinetId\":\"...\",\"outletId\":\"Q2\"},\n"
               "  \"breaker\":{\"cause\":\"overcurrent|short_circuit|rcd|manual\",\"prevState\":\"closed\"}\n"
               "}")

    h3(doc, "3.2.4  PLC posao za 3.2")
    bullet(doc, "Dodati digitalne ulaze za breaker pomocni kontakt po socketu (Q1..Q4) — minimum 'tripped' (yes/no).")
    bullet(doc, "Opcionalno: drugi DI za RCD trip cause distinkciju.")
    bullet(doc, "Digitalni izlaz po socketu za breaker reset puls (relej koji pulse-a mehanizam za remote reset).")
    bullet(doc, "Izloziti kao PLCOut.QX_BreakerTripped, PLCIn.QX_BreakerReset.")

    h2(doc, "3.3  MINOR — v3.10 LED 'white' boja")
    bullet(doc, "Backend trenutno sipa samo {green, blue, red, yellow}.")
    bullet(doc, "Product spec trazi 'white', ali handleLedCmd u sketchu nije potvrden da ga prima.")
    bullet(doc, "Treba: verificirati u 'LLSketch.ino' color-string switch da li 'white' radi, pa odjaviti broker tim da prosiri _LED_COLORS.")

    h2(doc, "3.4  Sazetak prioriteta")
    add_table(doc,
              ["Prioritet", "Sto fali", "Posljedica dok ne stigne"],
              [
                  ["P0 — CRITICAL",
                   "opta/meters/+/telemetry + PLC Modbus meteri",
                   "90% auto-stop overload zastita NE RADI; load monitoring dormant"],
                  ["P0 — CRITICAL",
                   "opta/config/hardware + PLC ratedAmps po socketu",
                   "rated_amps=NULL → auto-stop grana se preskace s warning logom"],
                  ["P1 — HIGH",
                   "opta/breakers/Q{n}/status (retained) + PLC breaker DI",
                   "Nema vidljivosti trip state-a, BreakerTripped event ne stize, auto-close sesije ne radi"],
                  ["P1 — HIGH",
                   "opta/cmd/breaker/Q{n} subscribe + PLC reset DO",
                   "Remote breaker reset (operator + ERP) potpuno odsutan"],
                  ["P2 — LOW",
                   "LED 'white' validacija u handleLedCmd",
                   "Operator ne moze izabrati bijelu boju u LED scheduleru"],
              ])

    h2(doc, "3.5  Sto JE usklađeno (potvrda)")
    bullet(doc, "v3.4/v3.5 plug state machine — sketch publishira UserPluggedIn / UserPluggedOut event na opta/events.")
    bullet(doc, "v3.9 water auto-open — handleWaterCmd + startWaterSession emitiraju OutletActivated bezuvjetno cak i kad activate stigne bez sessionContext.")
    bullet(doc, "v34 fix — opta/cmd/time topic je u sketchu (prije je bilo opta/isotime, sto nikad nije match-alo backend).")
    bullet(doc, "Idempotency: 16-entry msgId cirkularni cache u firmware-u kako broker dokumentira.")
    bullet(doc, "Retained publishi: opta/status (L552) i opta/door/status (L616) — kao sto contract trazi.")

    para(doc, "")
    p = doc.add_paragraph()
    r = p.add_run("Izvori za sve sto je u dokumentu:")
    r.bold = True
    r.font.size = Pt(10)
    bullet(doc, "Cloud_IOT/README.md — changelog v3.4–v3.12 (linije 33–471).")
    bullet(doc, "Cloud_IOT/docs/firmware_requirements.md — non-code firmware ↔ backend ugovor.")
    bullet(doc, "Cloud_IOT/backend/app/services/mqtt_handlers.py — broker handleri (1500+ linija).")
    bullet(doc, "Cloud_IOT/backend/app/models/{socket_config.py, valve_config.py} — auto_activate defaulti.")
    bullet(doc, "Opta V2/Lika - v2.0/LLSketch/LLSketch.ino — sketch (1433 linije).")
    bullet(doc, "Opta V2/Lika - v2.0/Build/Lika - v2.0.sym.xml — PLC simbolna tablica.")

    doc.save(OUT)
    print(f"OK -> {OUT}")


if __name__ == "__main__":
    build()
