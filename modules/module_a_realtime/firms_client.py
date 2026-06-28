"""
Cliente NASA FIRMS para detecciones VIIRS en tiempo casi-real.
Docs: https://firms.modaps.eosdis.nasa.gov/api/area/
"""

import io
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

from .config import BBOX, FIRMS_MAP_KEY, FIRMS_SOURCES

log = logging.getLogger(__name__)

_FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

# Formato: lon_min,lat_min,lon_max,lat_max
_BBOX_STR = "{lon_min},{lat_min},{lon_max},{lat_max}".format(**BBOX)

_REQUIRED_COLS = {"latitude", "longitude", "confidence", "acq_date", "acq_time"}


def _fetch_source(source: str, days: int = 1, retries: int = 3, backoff: float = 5.0) -> Optional[pd.DataFrame]:
    """Descarga CSV de una fuente VIIRS para el área configurada."""
    url = f"{_FIRMS_BASE}/{FIRMS_MAP_KEY}/{source}/{_BBOX_STR}/{days}"
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 429:
                wait = backoff * attempt
                log.warning("FIRMS rate limit en %s. Esperando %.0fs antes de reintentar.", source, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            if not resp.text.strip():
                log.info("Sin datos para fuente %s en el área configurada.", source)
                return pd.DataFrame()
            df = pd.read_csv(io.StringIO(resp.text))
            missing = _REQUIRED_COLS - set(df.columns)
            if missing:
                log.warning("Columnas faltantes en respuesta de %s: %s", source, missing)
                return pd.DataFrame()
            log.info("Fuente %s: %d detecciones descargadas.", source, len(df))
            return df
        except requests.exceptions.Timeout:
            log.warning("Timeout en %s (intento %d/%d).", source, attempt, retries)
        except requests.exceptions.ConnectionError as exc:
            log.warning("Error de conexión en %s: %s (intento %d/%d).", source, exc, attempt, retries)
        except requests.exceptions.HTTPError as exc:
            log.error("Error HTTP en %s: %s", source, exc)
            return pd.DataFrame()
        if attempt < retries:
            time.sleep(backoff * attempt)
    log.error("No se pudo obtener datos de %s tras %d intentos.", source, retries)
    return pd.DataFrame()


def _parse_acq_datetime(df: pd.DataFrame) -> pd.DataFrame:
    """Construye columna acq_datetime combinando acq_date + acq_time (HHMM)."""
    df = df.copy()
    time_str = df["acq_time"].astype(str).str.zfill(4)
    df["acq_datetime"] = pd.to_datetime(
        df["acq_date"].astype(str) + " " + time_str.str[:2] + ":" + time_str.str[2:],
        format="%Y-%m-%d %H:%M",
        utc=True,
        errors="coerce",
    )
    return df


def fetch_last_24h() -> gpd.GeoDataFrame:
    """
    Consulta NASA FIRMS para ambas fuentes VIIRS y retorna un GeoDataFrame
    con las detecciones de las últimas 24 horas.
    """
    frames: list[pd.DataFrame] = []
    for source in FIRMS_SOURCES:
        df = _fetch_source(source, days=1)
        if df is not None and not df.empty:
            df["source"] = source
            frames.append(df)

    if not frames:
        log.warning("Sin detecciones activas en las últimas 24h para el área Biobío.")
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    combined = pd.concat(frames, ignore_index=True)
    combined = _parse_acq_datetime(combined)

    # Filtrar a ventana de 24h estricta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    before = len(combined)
    combined = combined[combined["acq_datetime"] >= cutoff]
    log.info("Filtro temporal 24h: %d → %d detecciones.", before, len(combined))

    geometry = [Point(xy) for xy in zip(combined["longitude"], combined["latitude"])]
    gdf = gpd.GeoDataFrame(combined, geometry=geometry, crs="EPSG:4326")
    return gdf
