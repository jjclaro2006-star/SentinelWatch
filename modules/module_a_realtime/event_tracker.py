"""
Seguimiento incremental de eventos de incendio para el Módulo A.

Agrupa detecciones individuales en eventos persistentes usando clustering
espacio-temporal: mismo incendio si está dentro de 2 km y 72 h del centroide
del evento más cercano.

Estado persistido en data/alerts/module_a/events_state.json para sobrevivir
reinicios del scheduler.
"""

import json
import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .config import ALERTS_OUTPUT_PATH

log = logging.getLogger(__name__)

_STATE_FILE: Path = ALERTS_OUTPUT_PATH / "events_state.json"
_CLUSTER_RADIUS_KM: float = 2.0
_CLUSTER_WINDOW_HOURS: float = 72.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(min(a, 1.0)))


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


_TIER_RANK = {"confirmed": 2, "preliminary": 1, "unconfirmed": 0}


class EventTracker:
    """
    Singleton de seguimiento incremental de eventos de incendio.

    Uso:
        from .event_tracker import event_tracker
        event = event_tracker.ingest(detection_dict)
    """

    def __init__(self) -> None:
        self._active: dict[str, dict] = {}
        self._closed_today: int = 0
        self._closed_today_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._load_state()

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        if not _STATE_FILE.exists():
            return
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            self._active = data.get("active", {})
            for ev in self._active.values():
                for det in ev.get("detections", []):
                    if isinstance(det.get("acq_datetime"), str):
                        det["acq_datetime"] = _parse_dt(det["acq_datetime"])
            self._closed_today = data.get("closed_today", 0)
            stored_date = data.get("closed_today_date", "")
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if stored_date != today:
                self._closed_today = 0
                self._closed_today_date = today
            else:
                self._closed_today_date = stored_date
            log.info("[EventTracker] Estado cargado: %d eventos activos.", len(self._active))
        except Exception as exc:
            log.warning("[EventTracker] No se pudo cargar estado: %s", exc)
            self._active = {}

    def _save_state(self) -> None:
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "active": self._active,
                "closed_today": self._closed_today,
                "closed_today_date": self._closed_today_date,
            }
            _STATE_FILE.write_text(
                json.dumps(payload, default=str, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("[EventTracker] No se pudo guardar estado: %s", exc)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def ingest(self, detection: dict) -> dict:
        """
        Recibe una detección individual y la asigna al evento activo más
        cercano (dentro de 2 km y 72 h) o crea uno nuevo.

        Retorna el dict del evento actualizado/creado.
        """
        lat = float(detection.get("lat") or detection.get("latitude") or 0)
        lon = float(detection.get("lon") or detection.get("longitude") or 0)
        frp = float(detection.get("frp") or 0)
        source = str(detection.get("source") or detection.get("satellite") or "UNKNOWN")
        tier = str(detection.get("tier") or "preliminary")
        acq_dt = _parse_dt(detection.get("acq_datetime")) or datetime.now(timezone.utc)

        now = datetime.now(timezone.utc)
        best_id: str | None = None
        best_dist = float("inf")

        for eid, ev in self._active.items():
            last_seen = _parse_dt(ev.get("last_seen"))
            if last_seen is None:
                continue
            if (now - last_seen).total_seconds() >= _CLUSTER_WINDOW_HOURS * 3600:
                continue
            dist_km = _haversine_km(lat, lon, ev["centroid_lat"], ev["centroid_lon"])
            time_diff_h = abs((acq_dt - last_seen).total_seconds()) / 3600
            if dist_km <= _CLUSTER_RADIUS_KM and time_diff_h <= _CLUSTER_WINDOW_HOURS:
                if dist_km < best_dist:
                    best_dist = dist_km
                    best_id = eid

        det_record = {"lat": lat, "lon": lon, "acq_datetime": acq_dt}

        if best_id:
            ev = self._active[best_id]
            n = ev["detection_count"]
            ev["centroid_lat"] = (ev["centroid_lat"] * n + lat) / (n + 1)
            ev["centroid_lon"] = (ev["centroid_lon"] * n + lon) / (n + 1)
            ev["detection_count"] = n + 1
            ev["last_seen"] = acq_dt.isoformat()
            if frp > ev.get("max_frp", 0):
                ev["max_frp"] = frp
            sources = set(ev.get("sources") or [])
            sources.add(source)
            ev["sources"] = sorted(sources)
            if _TIER_RANK.get(tier, 0) > _TIER_RANK.get(ev.get("tier", "unconfirmed"), 0):
                ev["tier"] = tier
            start = _parse_dt(ev.get("start_date"))
            ev["duration_hours"] = (
                round((acq_dt - start).total_seconds() / 3600, 1) if start else 0.0
            )
            ev.setdefault("detections", []).append(det_record)
            result_id = best_id
        else:
            date_tag = acq_dt.strftime("%Y%m%d")
            uid = uuid.uuid4().hex[:6]
            result_id = f"EVT-{date_tag}-{uid}"
            ev = {
                "event_id": result_id,
                "start_date": acq_dt.isoformat(),
                "last_seen": acq_dt.isoformat(),
                "centroid_lat": lat,
                "centroid_lon": lon,
                "detection_count": 1,
                "max_frp": frp,
                "sources": [source],
                "tier": tier,
                "duration_hours": 0.0,
                "detections": [det_record],
            }
            self._active[result_id] = ev
            log.info(
                "[EventTracker] Nuevo evento: %s | lat=%.4f lon=%.4f frp=%.1f MW",
                result_id, lat, lon, frp,
            )

        self._save_state()
        self.merge_adjacent_events()
        # result_id may have been absorbed into an older event during merge
        ev = self._active.get(result_id) or max(self._active.values(), key=lambda e: e.get("detection_count", 0))
        return dict(ev)

    def get_active_events(self) -> list:
        """Retorna todos los eventos cuyo last_seen fue hace menos de 72 h."""
        now = datetime.now(timezone.utc)
        result = []
        for ev in self._active.values():
            last_seen = _parse_dt(ev.get("last_seen"))
            if last_seen and (now - last_seen).total_seconds() < _CLUSTER_WINDOW_HOURS * 3600:
                result.append(dict(ev))
        return result

    def _events_are_connected(self, a: dict, b: dict) -> bool:
        """True if any detection in A is within 2 km and 72 h of any detection in B."""
        for da in a.get("detections", []):
            for db in b.get("detections", []):
                if _haversine_km(da["lat"], da["lon"], db["lat"], db["lon"]) <= 2.0:
                    dt_a = da["acq_datetime"] if isinstance(da["acq_datetime"], datetime) else _parse_dt(da["acq_datetime"])
                    dt_b = db["acq_datetime"] if isinstance(db["acq_datetime"], datetime) else _parse_dt(db["acq_datetime"])
                    if dt_a and dt_b and abs((dt_a - dt_b).total_seconds()) <= _CLUSTER_WINDOW_HOURS * 3600:
                        return True
        return False

    def merge_adjacent_events(self) -> int:
        """
        Merges pairs of active events that share at least one detection pair
        within 2 km and 72 h of each other (detection-chain merge).
        The younger event (later start_date) is absorbed into the older one.
        Returns the number of merges performed.
        """
        merges = 0

        merged = True
        while merged:
            merged = False
            ids = list(self._active.keys())
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a_id, b_id = ids[i], ids[j]
                    if a_id not in self._active or b_id not in self._active:
                        continue
                    a = self._active[a_id]
                    b = self._active[b_id]

                    if not self._events_are_connected(a, b):
                        continue

                    # Identify older (keeper) and younger (absorbed)
                    a_start = _parse_dt(a.get("start_date")) or datetime.now(timezone.utc)
                    b_start = _parse_dt(b.get("start_date")) or datetime.now(timezone.utc)
                    keeper_id, young_id = (a_id, b_id) if a_start <= b_start else (b_id, a_id)
                    keeper = self._active[keeper_id]
                    young = self._active[young_id]

                    n_k = keeper["detection_count"]
                    n_y = young["detection_count"]
                    n_total = n_k + n_y

                    keeper["centroid_lat"] = (keeper["centroid_lat"] * n_k + young["centroid_lat"] * n_y) / n_total
                    keeper["centroid_lon"] = (keeper["centroid_lon"] * n_k + young["centroid_lon"] * n_y) / n_total
                    keeper["detection_count"] = n_total
                    keeper["max_frp"] = max(keeper.get("max_frp", 0), young.get("max_frp", 0))

                    k_seen = _parse_dt(keeper.get("last_seen"))
                    y_seen = _parse_dt(young.get("last_seen"))
                    if k_seen and y_seen:
                        latest_seen = max(k_seen, y_seen)
                    else:
                        latest_seen = k_seen or y_seen
                    if latest_seen:
                        keeper["last_seen"] = latest_seen.isoformat()

                    sources = set(keeper.get("sources") or []) | set(young.get("sources") or [])
                    keeper["sources"] = sorted(sources)

                    if _TIER_RANK.get(young.get("tier", "unconfirmed"), 0) > _TIER_RANK.get(keeper.get("tier", "unconfirmed"), 0):
                        keeper["tier"] = young["tier"]

                    oldest_start = _parse_dt(keeper.get("start_date"))
                    if oldest_start and latest_seen:
                        keeper["duration_hours"] = round((latest_seen - oldest_start).total_seconds() / 3600, 1)

                    keeper["detections"] = keeper.get("detections", []) + young.get("detections", [])

                    del self._active[young_id]
                    merges += 1
                    merged = True
                    log.info(
                        "[EventTracker] Merge: %s absorbió %s | total %d detecciones",
                        keeper_id, young_id, n_total,
                    )
                    break
                if merged:
                    break

        if merges:
            self._save_state()
        return merges

    def close_stale_events(self) -> list:
        """
        Mueve a estado cerrado los eventos sin actividad en 72 h.
        Retorna la lista de eventos cerrados para logging.
        """
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        if today != self._closed_today_date:
            self._closed_today = 0
            self._closed_today_date = today

        stale_ids = [
            eid for eid, ev in self._active.items()
            if (
                (ls := _parse_dt(ev.get("last_seen"))) is not None
                and (now - ls).total_seconds() >= _CLUSTER_WINDOW_HOURS * 3600
            )
        ]

        closed = []
        for eid in stale_ids:
            ev = self._active.pop(eid)
            closed.append(ev)
            self._closed_today += 1
            log.info(
                "[EventTracker] Evento cerrado: %s | %d detecciones | %.1fh activo",
                ev["event_id"], ev["detection_count"], ev.get("duration_hours", 0),
            )

        if stale_ids:
            self._save_state()

        return closed

    def get_event_summary(self) -> str:
        """
        Retorna una cadena de resumen para logging:
            Eventos activos: X | Confirmados: X | Preliminares: X | Cerrados hoy: X
            Mayor evento: EVT-YYYYMMDD-XXXXXX | XX detecciones | XX.Xh activo | FRP max: XXX MW
        """
        active = self.get_active_events()
        confirmed = sum(1 for e in active if e.get("tier") == "confirmed")
        preliminary = sum(1 for e in active if e.get("tier") == "preliminary")

        line1 = (
            f"Eventos activos: {len(active)} | "
            f"Confirmados: {confirmed} | "
            f"Preliminares: {preliminary} | "
            f"Cerrados hoy: {self._closed_today}"
        )

        if not active:
            return line1

        top = max(active, key=lambda e: e.get("detection_count", 0))
        line2 = (
            f"Mayor evento: {top['event_id']} | "
            f"{top['detection_count']} detecciones | "
            f"{top.get('duration_hours', 0):.1f}h activo | "
            f"FRP max: {top.get('max_frp', 0):.0f} MW"
        )

        return f"{line1}\n{line2}"


# Singleton — importar directamente desde otros módulos:
#   from .event_tracker import event_tracker
event_tracker = EventTracker()
