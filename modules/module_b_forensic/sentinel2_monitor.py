"""
Module B — Sentinel-2 availability monitor.

Runs every 6 hours via APScheduler. For each confirmed fire alert that has
no forensic analysis yet, checks whether a cloud-free Sentinel-2 post-fire
image is available in GEE. If so, triggers forensic_analyzer.analyze().
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ee

from auth import authenticate_and_initialize

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIRMED_DIR = PROJECT_ROOT / "data" / "alerts" / "module_a" / "confirmed"
EVENTS_STATE = PROJECT_ROOT / "data" / "alerts" / "module_a" / "events_state.json"

_GEE_READY = False


def _ensure_gee() -> None:
    global _GEE_READY
    if not _GEE_READY:
        authenticate_and_initialize()
        _GEE_READY = True


def check_availability(
    lat: float,
    lon: float,
    date_str: str,
    min_days_after: int = 5,
    max_days_after: int = 60,
) -> dict:
    """Query GEE for the best Sentinel-2 post-fire image.

    Returns a dict with keys: available, post_date, cloud_cover, days_after_fire.
    """
    _ensure_gee()

    fire_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    search_start = (fire_date + timedelta(days=min_days_after)).isoformat()
    search_end = (fire_date + timedelta(days=max_days_after)).isoformat()

    point = ee.Geometry.Point([lon, lat])
    roi = point.buffer(5000)  # 5 km buffer

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(roi)
        .filterDate(search_start, search_end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 30))
        .sort("CLOUDY_PIXEL_PERCENTAGE")
    )

    size = collection.size().getInfo()
    if size == 0:
        return {"available": False, "post_date": None, "cloud_cover": None, "days_after_fire": None}

    best = collection.first()
    props = best.toDictionary(["system:time_start", "CLOUDY_PIXEL_PERCENTAGE"]).getInfo()

    ts_ms = props["system:time_start"]
    image_date = date.fromtimestamp(ts_ms / 1000)
    cloud_cover = float(props["CLOUDY_PIXEL_PERCENTAGE"])
    days_after = (image_date - fire_date).days

    return {
        "available": True,
        "post_date": image_date.isoformat(),
        "cloud_cover": cloud_cover,
        "days_after_fire": days_after,
    }


def get_pending_alerts() -> list[dict]:
    """Return confirmed alerts that have no forensic analysis and are > 5 days old."""
    pending = []
    cutoff = date.today() - timedelta(days=5)

    # First try the confirmed/ subdirectory (GeoJSON files written by module_a)
    if CONFIRMED_DIR.exists():
        import geopandas as gpd

        for geojson_path in CONFIRMED_DIR.glob("*.geojson"):
            try:
                gdf = gpd.read_file(geojson_path)
            except Exception as exc:
                log.warning("No se pudo leer %s: %s", geojson_path, exc)
                continue

            for _, row in gdf.iterrows():
                props = row.to_dict()
                if "forensic_score" in props:
                    continue
                fire_date_raw = props.get("fire_date") or props.get("acq_datetime") or props.get("start_date")
                if not fire_date_raw:
                    continue
                try:
                    fire_date = datetime.fromisoformat(str(fire_date_raw)).date()
                except ValueError:
                    continue
                if fire_date > cutoff:
                    continue
                alert_id = props.get("alert_id") or geojson_path.stem
                event_id = props.get("event_id", alert_id)
                geom = row.geometry
                pending.append({
                    "alert_id": alert_id,
                    "lat": geom.centroid.y,
                    "lon": geom.centroid.x,
                    "fire_date": fire_date.isoformat(),
                    "event_id": event_id,
                    "source_path": str(geojson_path),
                })
        return pending

    # Fallback: read events_state.json
    if not EVENTS_STATE.exists():
        log.warning("No se encontró events_state.json ni directorio confirmed/")
        return []

    with open(EVENTS_STATE, encoding="utf-8") as f:
        state = json.load(f)

    for event_id, evt in state.get("active", {}).items():
        if evt.get("tier") != "confirmed":
            continue
        start_raw = evt.get("start_date", "")
        try:
            fire_date = datetime.fromisoformat(start_raw).date()
        except ValueError:
            continue
        if fire_date > cutoff:
            continue
        pending.append({
            "alert_id": event_id,
            "lat": evt["centroid_lat"],
            "lon": evt["centroid_lon"],
            "fire_date": fire_date.isoformat(),
            "event_id": event_id,
            "source_path": None,
        })

    return pending


def monitor_loop() -> None:
    """Main loop: check Sentinel-2 availability and trigger forensic analysis."""
    from modules.module_b_forensic.forensic_analyzer import forensic_analyzer

    log.info("[MONITOR] Iniciando ciclo de monitoreo Sentinel-2...")
    alerts = get_pending_alerts()
    log.info("[MONITOR] %d alertas confirmadas pendientes de análisis forense.", len(alerts))

    for alert in alerts:
        event_id = alert["event_id"]
        try:
            avail = check_availability(
                lat=alert["lat"],
                lon=alert["lon"],
                date_str=alert["fire_date"],
            )
        except Exception as exc:
            log.error("[MONITOR] %s — error consultando disponibilidad: %s", event_id, exc)
            continue

        if not avail["available"]:
            log.info("[MONITOR] %s — imagen aún no disponible.", event_id)
            continue

        if avail["cloud_cover"] >= 30.0:
            log.info(
                "[MONITOR] %s — imagen disponible pero nubosidad %.1f%% > 30%%. Descartando.",
                event_id, avail["cloud_cover"],
            )
            continue

        log.info(
            "[MONITOR] %s — imagen disponible %dd después — disparando análisis forense",
            event_id, avail["days_after_fire"],
        )

        try:
            forensic_analyzer.analyze(
                lat=alert["lat"],
                lon=alert["lon"],
                fire_date=alert["fire_date"],
                alert_id=alert["alert_id"],
            )
        except Exception as exc:
            log.error("[MONITOR] %s — error en análisis forense: %s", event_id, exc, exc_info=True)


# Module-level singleton used by scheduler.py and tests
sentinel2_monitor = type("_Monitor", (), {
    "monitor_loop": staticmethod(monitor_loop),
    "get_pending_alerts": staticmethod(get_pending_alerts),
    "check_availability": staticmethod(check_availability),
})()
