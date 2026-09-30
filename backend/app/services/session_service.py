import logging
import traceback
from datetime import datetime
from sqlalchemy.orm import Session as DBSession
from ..models.session import Session
from ..models.sensor_reading import SensorReading

logger = logging.getLogger(__name__)


def _log(category: str, source: str, msg: str, exc: Exception | None = None):
    """Fire-and-forget to error_log_service without crashing the caller."""
    try:
        from .error_log_service import log_error
        details = traceback.format_exc() if exc else None
        log_error(category, source, msg, details=details)
    except Exception:
        pass


def _log_start(kind: str, session, value) -> None:
    """Record the opening register reading, so a disputed charge can be traced from the log
    alone even if the row is later touched."""
    import logging
    logging.getLogger(__name__).info(
        "[Meter] session %s (%s) opening %s register = %s",
        session.id, session.type, kind, "UNREADABLE" if value is None else f"{value:.3f}",
    )


class SessionService:
    def create_pending(
        self,
        db: DBSession,
        pedestal_id: int,
        socket_id: int | None,
        session_type: str,
        customer_id: int | None = None,
    ) -> Session:
        """Create a pending session. If a partial unique index has already
        accepted another thread's insert for the same (pedestal, socket, type)
        with status in (pending, active), return that row instead of raising —
        MQTT firmware retries must not create duplicates.
        """
        from sqlalchemy.exc import IntegrityError
        session = Session(
            pedestal_id=pedestal_id,
            socket_id=socket_id,
            type=session_type,
            status="pending",
            started_at=datetime.utcnow(),
            customer_id=customer_id,
        )
        try:
            db.add(session)
            db.commit()
            db.refresh(session)
        except IntegrityError:
            db.rollback()
            existing = self.get_active_for_socket(db, pedestal_id, socket_id, session_type=session_type)
            if existing:
                logger.info(
                    f"create_pending: active session {existing.id} already exists for "
                    f"pedestal={pedestal_id} socket={socket_id} type={session_type}; returning it"
                )
                return existing
            _log("system", "session_service",
                 f"IntegrityError on create_pending (pedestal={pedestal_id}, socket={socket_id}) "
                 f"but no active row found — race without winner?")
            raise
        except Exception as e:
            db.rollback()
            _log("system", "session_service", f"Failed to create pending session (pedestal={pedestal_id}): {e}", e)
            raise
        logger.info(f"Created pending session {session.id} for pedestal {pedestal_id} socket {socket_id}")
        return session

    def _capture_start_register(self, db: DBSession, session: Session) -> None:
        """Record what the outlet's cumulative register reads as this session begins (v3.43).

        The session's reported consumption is `end - start` of the meter's own register, so the
        start reading has to be taken at the moment consumption starts counting — activation, not
        creation, because a pending session draws nothing.

        A register we cannot read is left NULL, which makes the final figure UNKNOWN rather than
        zero. That is the honest outcome: zero would tell ERP the customer used nothing.
        """
        from ..models.socket_config import SocketConfig
        from ..models.valve_config import ValveConfig

        if session.socket_id is None:
            return
        try:
            if session.type == "electricity":
                sc = db.query(SocketConfig).filter(
                    SocketConfig.pedestal_id == session.pedestal_id,
                    SocketConfig.socket_id == session.socket_id,
                ).first()
                session.meter_energy_start_kwh = getattr(sc, "meter_energy_kwh", None)
                _log_start("energy", session, session.meter_energy_start_kwh)
            elif session.type == "water":
                vc = db.query(ValveConfig).filter(
                    ValveConfig.pedestal_id == session.pedestal_id,
                    ValveConfig.valve_id == session.socket_id,
                ).first()
                session.meter_water_start_l = getattr(vc, "meter_total_l", None)
                _log_start("water", session, session.meter_water_start_l)
        except Exception as e:
            # Never block activation on bookkeeping: a customer must be able to charge even if
            # we cannot read the register. The NULL start makes the consequence explicit.
            _log("system", "session_service",
                 f"Could not capture start register for session {session.id}: {e}", e)

    def activate(self, db: DBSession, session: Session) -> Session:
        try:
            session.status = "active"
            self._capture_start_register(db, session)
            db.commit()
            db.refresh(session)
        except Exception as e:
            db.rollback()
            _log("system", "session_service", f"Failed to activate session {session.id}: {e}", e)
            raise
        return session

    def deny(self, db: DBSession, session: Session, reason: str | None = None) -> Session:
        try:
            session.status = "denied"
            session.ended_at = datetime.utcnow()
            if reason:
                session.deny_reason = reason
            db.commit()
            db.refresh(session)
        except Exception as e:
            db.rollback()
            _log("system", "session_service", f"Failed to deny session {session.id}: {e}", e)
            raise
        return session

    def complete(
        self,
        db: DBSession,
        session: Session,
        end_reason: str | None = None,
    ) -> Session:
        """Finalise a session.

        `end_reason` is stored machine-readable on `sessions.end_reason` when set
        (e.g. "breaker_trip"). Legacy call sites can omit it; the column stays NULL
        for the natural unplug / operator-stop paths.
        """
        session.status = "completed"
        session.ended_at = datetime.utcnow()
        if end_reason:
            session.end_reason = end_reason

        # Calculate totals from sensor readings
        readings = (
            db.query(SensorReading)
            .filter(SensorReading.session_id == session.id)
            .all()
        )
        # v3.14 — clamp out-of-range readings before max() so a single corrupt
        # telemetry packet (e.g. a garbage 9999 kWh spike) cannot be billed.
        # Uses the same sanity bounds as the startup backfill for consistency.
        from ..database import _MAX_SANE_KWH_PER_SESSION, _MAX_SANE_LITERS_PER_SESSION

        # v3.43 — WE FORWARD THE METER'S FIGURE, WE DO NOT DERIVE ONE.
        #
        # Until now `energy_kwh` was max(reading-based, power x time integral). The integral was
        # the only figure available when it was written (firmware reported energyKwh as 0), but
        # firmware 3.1.0 reports the register live and `powerKw` turns out not to be trustworthy
        # — a capture shows Q2 claiming 0.181 kW for six minutes while its register never moved.
        #
        # So the reported figure is now `register_end - register_start`, and the old integral is
        # kept alongside for comparison only. See services/meter_register.py.
        self._finalise_from_register(db, session, readings)

        # v3.35 — flush the final energy interval before closing so an unplug/stop
        # is billed immediately (energy now finalized above). Best-effort: never
        # let interval bookkeeping block a session from completing.
        if session.type == "electricity":
            try:
                from .energy_interval_service import flush_session_interval
                flush_session_interval(db, session, now=session.ended_at, final=True)
            except Exception as e:
                _log("system", "session_service",
                     f"interval flush on complete failed for session {session.id}: {e}", e)

        try:
            db.commit()
            db.refresh(session)
        except Exception as e:
            db.rollback()
            _log("system", "session_service", f"Failed to complete session {session.id}: {e}", e)
            raise
        return session


    def _finalise_from_register(self, db: DBSession, session: Session, readings) -> None:
        """Set the session's reported consumption from the meter register delta."""
        from ..database import _MAX_SANE_KWH_PER_SESSION, _MAX_SANE_LITERS_PER_SESSION
        from ..models.socket_config import SocketConfig
        from ..models.valve_config import ValveConfig
        from . import meter_register as mr

        if session.type == "electricity":
            # The integral that used to be the reported value is preserved for comparison. It is
            # read off `energy_kwh` because that is where the meter tick accumulated it.
            session.energy_kwh_integrated = session.energy_kwh
            if session.socket_id is not None:
                sc = db.query(SocketConfig).filter(
                    SocketConfig.pedestal_id == session.pedestal_id,
                    SocketConfig.socket_id == session.socket_id,
                ).first()
                session.meter_energy_end_kwh = getattr(sc, "meter_energy_kwh", None)

            result = mr.session_delta(mr.KIND_ENERGY, session.meter_energy_start_kwh,
                                      session.meter_energy_end_kwh)
            if result.is_reportable:
                session.energy_kwh = result.value
                session.consumption_source = mr.SOURCE_REGISTER
            else:
                session.energy_kwh, session.consumption_source = self._legacy_or_unknown(
                    session, result)
            self._report_register_outcome(session, mr.KIND_ENERGY, result,
                                          session.energy_kwh_integrated)

        elif session.type == "water":
            # Water's comparison figure is the firmware's own per-session counter (`session_l`),
            # which arrives as the `total_liters` readings.
            liter_readings = [r.value for r in readings
                             if r.type == "total_liters"
                             and r.value < _MAX_SANE_LITERS_PER_SESSION]
            session.water_liters_firmware = max(liter_readings) if liter_readings else None

            if session.socket_id is not None:
                vc = db.query(ValveConfig).filter(
                    ValveConfig.pedestal_id == session.pedestal_id,
                    ValveConfig.valve_id == session.socket_id,
                ).first()
                session.meter_water_end_l = getattr(vc, "meter_total_l", None)

            result = mr.session_delta(mr.KIND_WATER, session.meter_water_start_l,
                                      session.meter_water_end_l)
            if result.is_reportable:
                session.water_liters = result.value
                session.consumption_source = mr.SOURCE_REGISTER
            else:
                # Water has no integral to fall back to — the firmware's own session counter is
                # a comparison figure, not a substitute for the register — so it is UNKNOWN.
                session.water_liters = None
                session.consumption_source = mr.SOURCE_UNKNOWN
            self._report_register_outcome(session, mr.KIND_WATER, result,
                                          session.water_liters_firmware)

    def _legacy_or_unknown(self, session: Session, result) -> tuple[float | None, str]:
        """No usable register delta — decide between the legacy integral and honest unknown.

        The ONLY case that may fall back is a session that was already running when v3.43
        deployed: it has no start reading because nothing captured one, so its register delta is
        genuinely unknowable, while the old integral for the whole session does exist. Reporting
        that (labelled) beats an unbillable session, and stamping the start register at deploy
        time would be worse — it would silently discard the pre-deploy portion while looking
        correct.

        `assert_legacy_allowed` refuses the label for anything started after the cutoff, so this
        population drains to zero and no new session can join it.
        """
        from . import meter_register as mr

        integral = session.energy_kwh_integrated
        if integral is not None and result.status == "unknown":
            try:
                mr.assert_legacy_allowed(session)
            except mr.LegacySourceNotPermitted as exc:
                # A post-cutoff session with no register is UNKNOWN. Fix the register path
                # rather than relabelling the figure as an estimate.
                mr.raise_meter_alarm(
                    "meter_register_unreadable",
                    f"Session {session.id} on pedestal {session.pedestal_id} has no usable "
                    f"meter register and cannot fall back to an estimate: {exc}",
                    session.pedestal_id, severity="critical",
                )
                return None, mr.SOURCE_UNKNOWN

            mr.raise_meter_alarm(
                "meter_session_spanned_deploy",
                f"Session {session.id} on pedestal {session.pedestal_id} was already running "
                f"when the meter-register change was deployed, so it has no opening meter "
                f"reading. Its figure of {integral:.3f} kWh is an ESTIMATE calculated from "
                f"power over time, NOT a meter reading. Treat it as approximate if it is "
                f"queried. New sessions are measured from the meter.",
                session.pedestal_id,
            )
            return integral, mr.SOURCE_INTEGRATED_LEGACY

        return None, mr.SOURCE_UNKNOWN

    def _report_register_outcome(self, session: Session, kind: str, result, comparison) -> None:
        """Alarm on a refused delta, and on a persistent disagreement with the comparison.

        Both matter permanently. A refused delta means we are reporting nothing for a session
        somebody was billed for, and a disagreement means one of two sources is wrong — the kind
        of thing the old sanity clamp used to correct in silence, which is how it went unnoticed
        at 53x.
        """
        from . import meter_register as mr

        if result.status == "rejected":
            mr.raise_meter_alarm(
                "meter_register_rejected",
                f"Session {session.id} on pedestal {session.pedestal_id}: {result.reason}. "
                f"No consumption figure is being reported for it.",
                session.pedestal_id, severity="critical",
            )
            return
        if result.status == "unknown":
            mr.raise_meter_alarm(
                "meter_register_unreadable",
                f"Session {session.id} on pedestal {session.pedestal_id}: {result.reason}.",
                session.pedestal_id, severity="warning",
            )
            return

        diverged, message = mr.divergence(kind, result.value, comparison)
        if diverged:
            mr.raise_meter_alarm(
                "meter_divergence",
                f"Session {session.id} on pedestal {session.pedestal_id}: {message}",
                session.pedestal_id, severity="warning",
            )


    def get_active_for_socket(
        self,
        db: DBSession,
        pedestal_id: int,
        socket_id: int | None,
        session_type: str | None = None,
    ) -> Session | None:
        """Find the active session for (pedestal, socket).

        `session_type` filter is used by MQTT handlers so a water session on V1
        does not accidentally collide with an electricity session carrying the
        same numeric socket_id from a legacy row.
        """
        q = (
            db.query(Session)
            .filter(
                Session.pedestal_id == pedestal_id,
                Session.socket_id == socket_id,
                Session.status.in_(["pending", "active"]),
            )
        )
        if session_type is not None:
            q = q.filter(Session.type == session_type)
        return q.first()

    def add_reading(
        self,
        db: DBSession,
        session_id: int | None,
        pedestal_id: int,
        socket_id: int | None,
        reading_type: str,
        value: float,
        unit: str,
    ) -> SensorReading | None:
        # v3.13 — disk-space guard. When the disk is nearly full, refuse to
        # buffer new telemetry instead of crashing on ENOSPC or losing data
        # silently. A throttled hardware alarm tells the operator to free space
        # or use the clear-cache action; the session itself keeps running.
        from .disk_guard import has_free_space, note_storage_full
        if not has_free_space():
            note_storage_full(lambda m: _log("hw", "session_service", m))
            return None

        reading = SensorReading(
            session_id=session_id,
            pedestal_id=pedestal_id,
            socket_id=socket_id,
            type=reading_type,
            value=value,
            unit=unit,
        )
        try:
            db.add(reading)
            db.commit()
            db.refresh(reading)
        except Exception as e:
            db.rollback()
            _log("system", "session_service", f"Failed to persist sensor reading ({reading_type}): {e}", e)
            raise
        return reading


session_service = SessionService()
