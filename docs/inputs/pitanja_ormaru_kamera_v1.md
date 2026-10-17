# Pitanja ERP-a ormaru — ugovor `camera.live_*` (R35)

| | |
|---|---|
| Od | ERP (`Lika-Digital/ERP-IOT`, `docs/erp_spec.md` v30, §7.2 R35, §14.8) |
| Za | chat ormara (`Cloud_IOT`) |
| Datum | 2026-10-17 |
| Status | pitanja; uz svako je prijedlog ERP-a. Ništa se ne gradi dok ormar ne odgovori |

**Kontekst.**
- ERP ormar zove isključivo kao `api_client` preko `/api/ext/*`. Mobilna aplikacija i preglednik
  nikad ne vide adresu ormara ni kamere.
- ERP povlači svaki segment jednom, drži ga samo u memoriji i dijeli svim gledateljima.
- Dok postoji gledatelj, ERP šalje keepalive svakih 10 s, a kad ode zadnji, šalje `live_stop`.
- Ormar sam gasi stream nakon 30 s bez keepalivea, a u svakom slučaju nakon 10 min.
- Prijenos je HLS s kašnjenjem 8–12 s.
- Danas na `Cloud_IOT` `main` ništa od ovoga ne postoji, a katalog odbija sve kamerne rute
  (`PHASE1_NO_IMAGES_TO_ERP = True`).

---

### 1. Putanje, metode, tijela i razina dopuštenja

*Kontekst:* ERP mora znati točne rute i hoće li ih Gateway tretirati kao `monitor` ili
`bidirectional`.

*ERP predlaže:*
- `POST /api/ext/pedestals/{id}/camera/live/start`, `…/keepalive`, `…/stop` i
  `GET …/camera/live/status`, s praznim tijelom.
- Sve četiri rute na razini `monitor`, jer gledanje ne upravlja ničim.
- Smart Mode ON se ne traži.

### 2. Što `live_start` vraća i je li idempotentan

*Kontekst:* ERP prepisuje listu na svoje putanje, pa mu treba relativna putanja. Dva gledatelja
mogu kliknuti istodobno.

*ERP predlaže:*
- Odgovor `{"state":"starting|live","playlist":"camera/live/index.m3u8","expires_in_s":600}` s
  **relativnom** putanjom.
- Ponovni `start` na kameri koja već radi vraća 200 s istim streamom. Ne restartira ga i ne
  produljuje granicu od 10 min.

### 3. Stabilni ključevi stanja u `live_status`

*Kontekst:* ERP svako stanje pretvara u rečenicu korisniku, pa mu trebaju ključevi koji se ne
mijenjaju.

*ERP predlaže:*
- Ključevi `starting`, `live`, `stopped_idle` (30 s bez keepalivea), `stopped_limit` (10 min),
  `stopped` (izričit stop), `camera_unreachable` i `not_enabled`.
- Uz to `started_at` i `remaining_s`.
- Novi ključ smije se dodati, a postojeći se ne preimenuje.

### 4. Ponovno pokretanje nakon granice i broj istodobnih kamera

*Kontekst:* osoblje nakon 10 min klikne ponovno.

*ERP predlaže:*
- Novi `start` odmah nakon `stopped_limit` je dopušten.
- Po ormaru radi najviše jedna kamera, jer je i kamera jedna (vidi pitanje 6).
- Ako ormar ipak treba stanku, neka to bude `429` s `Retry-After`.

### 5. Parametri streama

*Kontekst:* o tome ovise međuspremnik i kvota prometa na ERP-u (40 GB po marini mjesečno,
procjena oko 58 MB za 10 min).

*ERP predlaže:*
- H.264 bez zvuka, 1280×720, otprilike 0,8 Mbit/s.
- Segment 2 s s keyframeom na početku svakog segmenta, lista od 6 segmenata.
- Segmenti MPEG-TS ili fMP4; ERP prima oba, samo neka bude jedno i stalno.
- Ormar ne transkodira ništa osim onoga što kamera već daje.

### 6. Jedna kamera po ormaru

*Kontekst:* odluka vlasnika je bez izreza po vezu. Pravo kupca da gleda veže se uz ugovor za vez
koji ormar služi.

*ERP predlaže:* potvrdite da ormar ima točno jednu kameru i da njena slika pokazuje sve vezove
tog ormara. Ako neki ormar ima više kamera ili nijednu, neka to vidi `live_status`
(`not_enabled`).

### 7. Maske privatnosti (R37)

*Kontekst:* kupci smiju gledati tek kad su maske postavljene i kad marina napravi DPIA.

*ERP predlaže:*
- Maske se nanose na ormaru, **prije** nego segment izađe s ormara.
- `live_status` javlja `privacy_mask: true|false`.
- Kupcu ERP stream ne daje dok je vrijednost `false`. Osoblju ga daje.

### 8. Oblik grešaka

*Kontekst:* ERP već razlikuje 409, 429 i 503 na drugim ext rutama, uvijek po ključu, nikad po
tekstu.

*ERP predlaže:*
- Isti oblik kao na ostalim ext rutama, uz stabilan ključ: `409 camera_busy` ili `not_enabled`,
  `429` s `Retry-After`, `503 camera_unreachable`.
- Lista i segmenti traže isti token. Kad stream ne radi, vraćaju `404`, nikad praznu listu
  s 200.
