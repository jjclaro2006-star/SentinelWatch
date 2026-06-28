"""
Deduplicación y persistencia de alertas de incendio del Módulo A.
"""

import json
import logging
from datetime import timedelta
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from .config import ALERTS_OUTPUT_PATH, DEDUP_RADIUS_M, DEDUP_TIME_WINDOW_HOURS

log = logging.getLogger(__name__)

# CRS proyectado para cálculo de distancias en metros (UTM zona 19S, Biobío)
_CRS_PROJECTED = "EPSG:32719"


def _load_existing_alerts() -> gpd.GeoDataFrame:
    """Carga todas las alertas ya persistidas en el directorio de salida."""
    geojsons = list(ALERTS_OUTPUT_PATH.glob("*.geojson"))
    if not geojsons:
        return gpd.GeoDataFrame(columns=["geometry", "acq_datetime"], crs="EPSG:4326")

    frames = []
    for f in geojsons:
        try:
            frames.append(gpd.read_file(f))
        except Exception as exc:
            log.warning("No se pudo leer el archivo de alertas %s: %s", f, exc)

    if not frames:
        return gpd.GeoDataFrame(columns=["geometry", "acq_datetime"], crs="EPSG:4326")

    existing = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
    if "acq_datetime" in existing.columns:
        existing["acq_datetime"] = pd.to_datetime(existing["acq_datetime"], utc=True, errors="coerce")
    return existing


def _is_duplicate(
    candidate: gpd.GeoDataFrame,
    existing: gpd.GeoDataFrame,
    radius_m: float,
    hours: int,
) -> pd.Series:
    """
    Para cada fila en 'candidate', retorna True si existe una alerta en
    'existing' dentro del radio espacial Y la ventana temporal.
    """
    if existing.empty or "acq_datetime" not in existing.columns:
        return pd.Series(False, index=candidate.index)

    cand_proj = candidate.to_crs(_CRS_PROJECTED)
    exist_proj = existing.to_crs(_CRS_PROJECTED)

    is_dup = []
    for _, row in cand_proj.iterrows():
        time_window = timedelta(hours=hours)
        cand_time = row.get("acq_datetime")
        if pd.isna(cand_time):
            is_dup.append(False)
            continue

        time_mask = (
            (existing["acq_datetime"] >= cand_time - time_window) &
            (existing["acq_datetime"] <= cand_time + time_window)
        ) if "acq_datetime" in existing.columns else pd.Series(True, index=existing.index)

        nearby = exist_proj[time_mask.values]
        if nearby.empty:
            is_dup.append(False)
            continue

        distances = nearby.geometry.distance(row.geometry)
        is_dup.append(bool((distances <= radius_m).any()))

    return pd.Series(is_dup, index=candidate.index)


def process_and_save(gdf: gpd.GeoDataFrame, batch_id: str) -> dict:
    """
    Deduplica las detecciones contra alertas existentes y persiste las nuevas.
    Retorna un resumen con conteos de nuevas y duplicadas.
    """
    ALERTS_OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

    if gdf.empty:
        log.info("Sin detecciones para procesar en este ciclo.")
        return {"nuevas": 0, "duplicadas": 0, "total_entrada": 0}

    existing = _load_existing_alerts()
    dup_mask = _is_duplicate(gdf, existing, DEDUP_RADIUS_M, DEDUP_TIME_WINDOW_HOURS)

    new_alerts = gdf[~dup_mask].copy()
    n_dup = int(dup_mask.sum())
    n_new = len(new_alerts)

    log.info("Alertas procesadas: %d nuevas | %d duplicadas (de %d totales).", n_new, n_dup, len(gdf))

    if n_new > 0:
        out_file = ALERTS_OUTPUT_PATH / f"alerts_biobio_{batch_id}.geojson"
        new_alerts["acq_datetime"] = new_alerts["acq_datetime"].astype(str)
        new_alerts.to_file(out_file, driver="GeoJSON")
        log.info("Alertas nuevas guardadas en: %s", out_file)

    return {"nuevas": n_new, "duplicadas": n_dup, "total_entrada": len(gdf)}
