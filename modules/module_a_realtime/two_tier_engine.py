"""
Motor de alertas de dos niveles para el Módulo A.

TIER 1 — Preliminar (GOES-19) : nueva detección                     → status "preliminary"
TIER 2 — Confirmada  (VIIRS)  : dentro de 2 km y 3 h de preliminar  → status "confirmed"
Auto-dismiss                   : sin confirmación VIIRS tras 4 h     → status "unconfirmed"
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .alert_manager import _is_duplicate
from .config import ALERTS_OUTPUT_PATH, DEDUP_RADIUS_M, DEDUP_TIME_WINDOW_HOURS
from .event_tracker import event_tracker  # ADDED: event_tracker
from .intentionality_scorer import intentionality_scorer  # ADDED: intentionality_scorer
from .legal_context import legal_enricher  # ADDED: legal_context
from .spread_estimator import spread_estimator  # ADDED: spread_estimator
from .firms_client import fetch_last_24h
from .geo_filter import filter_biobio

log = logging.getLogger(__name__)

_CRS_PROJECTED = "EPSG:32719"

PRELIMINARY_PATH = ALERTS_OUTPUT_PATH / "preliminary"
CONFIRMED_PATH   = ALERTS_OUTPUT_PATH / "confirmed"
UNCONFIRMED_PATH = ALERTS_OUTPUT_PATH / "unconfirmed"

_CONFIRMATION_WINDOW_HOURS = 3
_CONFIRMATION_RADIUS_M     = 2000.0   # 2 km
_DISMISS_AFTER_HOURS       = 4


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_from(path: Path) -> gpd.GeoDataFrame:
    """Carga todos los GeoJSON de un subdirectorio de alertas."""
    path.mkdir(parents=True, exist_ok=True)
    files = list(path.glob("*.geojson"))
    if not files:
        return gpd.GeoDataFrame(
            columns=["geometry", "acq_datetime", "alert_id", "tier_status"],
            crs="EPSG:4326",
        )
    frames = []
    for f in files:
        try:
            frames.append(gpd.read_file(f))
        except Exception as exc:
            log.warning("No se pudo leer %s: %s", f, exc)
    if not frames:
        return gpd.GeoDataFrame(
            columns=["geometry", "acq_datetime", "alert_id", "tier_status"],
            crs="EPSG:4326",
        )
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
    if "acq_datetime" in gdf.columns:
        gdf["acq_datetime"] = pd.to_datetime(gdf["acq_datetime"], utc=True, errors="coerce")
    return gdf


def _write_alert(gdf: gpd.GeoDataFrame, dest_path: Path, filename: str, status: str, extra: dict) -> None:
    dest_path.mkdir(parents=True, exist_ok=True)
    out = gdf.copy()
    out["tier_status"] = status
    for k, v in extra.items():
        out[k] = v
    # Serialize datetimes to string for GeoJSON
    if "acq_datetime" in out.columns:
        out["acq_datetime"] = out["acq_datetime"].astype(str)
    out.to_file(dest_path / filename, driver="GeoJSON")


def _viirs_confirms(prelim_gdf: gpd.GeoDataFrame, viirs_gdf: gpd.GeoDataFrame) -> bool:
    """True si alguna detección VIIRS está dentro de 2 km y 3 h del punto preliminar."""
    if viirs_gdf.empty or "acq_datetime" not in viirs_gdf.columns:
        return False

    cand_time = prelim_gdf["acq_datetime"].iloc[0]
    if pd.isna(cand_time):
        return False

    window = timedelta(hours=_CONFIRMATION_WINDOW_HOURS)
    time_mask = (
        (viirs_gdf["acq_datetime"] >= cand_time - window) &
        (viirs_gdf["acq_datetime"] <= cand_time + window)
    )
    nearby_pool = viirs_gdf[time_mask]
    if nearby_pool.empty:
        return False

    cand_proj  = prelim_gdf.to_crs(_CRS_PROJECTED)
    pool_proj  = nearby_pool.to_crs(_CRS_PROJECTED)
    distances  = pool_proj.geometry.distance(cand_proj.geometry.iloc[0])
    return bool((distances <= _CONFIRMATION_RADIUS_M).any())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_goes_detections(gdf: gpd.GeoDataFrame) -> int:
    """
    Tier 1 — Deduplica detecciones GOES filtradas contra alertas existentes y
    persiste las nuevas como alertas preliminares.

    Retorna el número de nuevas alertas preliminares generadas.
    """
    if gdf is None or gdf.empty:
        log.info("[TIER1] Sin nuevas detecciones GOES en este ciclo.")
        return 0

    existing_prelim    = _load_from(PRELIMINARY_PATH)
    existing_confirmed = _load_from(CONFIRMED_PATH)

    dup_prelim    = _is_duplicate(gdf, existing_prelim,    DEDUP_RADIUS_M, DEDUP_TIME_WINDOW_HOURS)
    dup_confirmed = _is_duplicate(gdf, existing_confirmed, DEDUP_RADIUS_M, DEDUP_TIME_WINDOW_HOURS)
    dup_mask = dup_prelim | dup_confirmed

    new_gdf = gdf[~dup_mask].copy()
    n_new = len(new_gdf)
    n_dup = int(dup_mask.sum())
    log.info("[TIER1] GOES: %d nuevas | %d duplicadas.", n_new, n_dup)

    now = datetime.now(timezone.utc)
    for i, (_, row) in enumerate(new_gdf.iterrows()):
        ts_tag   = now.strftime("%Y%m%d_%H%M%S")
        alert_id = f"prelim_goes_{ts_tag}_{i}"
        row_gdf  = gpd.GeoDataFrame([row], crs="EPSG:4326")
        _write_alert(
            row_gdf,
            PRELIMINARY_PATH,
            f"{alert_id}.geojson",
            "preliminary",
            {"alert_id": alert_id, "created_at": now.isoformat()},
        )
        log.info(
            "[TIER1] Alerta preliminar creada: %s | lat=%.4f lon=%.4f conf=%s",
            alert_id,
            row.get("latitude", float("nan")),
            row.get("longitude", float("nan")),
            row.get("confidence", "?"),
        )
        # ADDED: event_tracker
        event_tracker.ingest({
            "lat": row.get("latitude"), "lon": row.get("longitude"),
            "acq_datetime": row.get("acq_datetime"), "frp": row.get("frp"),
            "source": "GOES_NRT", "tier": "preliminary",
        })

    return n_new


def check_confirmations() -> None:
    """
    Job APScheduler — ejecutar cada 20 minutos.

    Para cada alerta preliminar pendiente:
      · Si VIIRS tiene detección dentro de 2 km y 3 h → CONFIRMADA
      · Si han pasado > 4 h sin confirmación           → DESCARTADA (sin confirmar)
    """
    ts_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    prelim_files = list(PRELIMINARY_PATH.glob("*.geojson"))
    if not prelim_files:
        log.info("[TIER2] Sin alertas preliminares pendientes.")
        print(f"[TIER2]   {ts_str} UTC — 0 alertas confirmadas por VIIRS | 0 descartadas")
        return

    # Obtiene VIIRS reciente (con filtros de confianza >= 70)
    try:
        viirs_raw = fetch_last_24h()
        viirs_gdf = filter_biobio(viirs_raw)
        if "acq_datetime" not in viirs_gdf.columns:
            viirs_gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    except Exception as exc:
        log.error("[TIER2] Error obteniendo datos VIIRS: %s", exc)
        viirs_gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    now = datetime.now(timezone.utc)
    n_confirmed = 0
    n_dismissed = 0

    for prelim_file in prelim_files:
        try:
            p_gdf = gpd.read_file(prelim_file)
        except Exception as exc:
            log.warning("[TIER2] No se pudo leer %s: %s", prelim_file, exc)
            continue

        if p_gdf.empty or "acq_datetime" not in p_gdf.columns:
            continue

        p_gdf["acq_datetime"] = pd.to_datetime(p_gdf["acq_datetime"], utc=True, errors="coerce")
        acq_dt   = p_gdf["acq_datetime"].iloc[0]
        alert_id = p_gdf["alert_id"].iloc[0] if "alert_id" in p_gdf.columns else prelim_file.stem

        if pd.isna(acq_dt):
            continue

        age_hours = (now - acq_dt).total_seconds() / 3600

        if _viirs_confirms(p_gdf, viirs_gdf):
            # ADDED: legal_context
            _pt = p_gdf.geometry.iloc[0]
            _ctx = legal_enricher.enrich(_pt.y, _pt.x)
            # ADDED: spread_estimator
            _frp = float(p_gdf["frp"].iloc[0]) if "frp" in p_gdf.columns else 0.0
            _spread = spread_estimator.estimate(_pt.y, _pt.x, frp_mw=_frp)
            # ADDED: intentionality_scorer
            _event_dict = {
                "event_id": alert_id,
                "start_date": acq_dt,
                "centroid_lat": _pt.y,
                "centroid_lon": _pt.x,
                "detection_count": 1,
                "duration_hours": age_hours,
                "max_frp": _frp,
                "sources": ["GOES_NRT"],
            }
            _intent = intentionality_scorer.score(
                event=_event_dict,
                legal_context=_ctx,
                active_events=event_tracker.get_active_events(),
            )
            _write_alert(
                p_gdf, CONFIRMED_PATH, prelim_file.name,
                "confirmed",
                {"confirmed_at": now.isoformat(), **_ctx, **_spread, **_intent},
            )
            prelim_file.unlink()
            n_confirmed += 1
            log.info(
                "[TIER2] ✓ Alerta %s CONFIRMADA por VIIRS (%.1fh de edad) → %s",
                alert_id, age_hours, CONFIRMED_PATH / prelim_file.name,
            )

        elif age_hours > _DISMISS_AFTER_HOURS:
            _write_alert(
                p_gdf, UNCONFIRMED_PATH, prelim_file.name,
                "unconfirmed",
                {"dismissed_at": now.isoformat()},
            )
            prelim_file.unlink()
            n_dismissed += 1
            log.info(
                "[TIER2] ✗ Alerta %s DESCARTADA sin confirmación (%.1fh > %dh umbral) → %s",
                alert_id, age_hours, _DISMISS_AFTER_HOURS, UNCONFIRMED_PATH / prelim_file.name,
            )

    log.info("[TIER2] Ciclo completado: %d confirmadas | %d descartadas.", n_confirmed, n_dismissed)
    print(f"[TIER2]   {ts_str} UTC — {n_confirmed} alertas confirmadas por VIIRS | {n_dismissed} descartadas")
    # ADDED: event_tracker
    event_tracker.close_stale_events()
    log.info("[EventTracker]\n%s", event_tracker.get_event_summary())
