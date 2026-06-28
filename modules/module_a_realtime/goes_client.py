"""
Cliente FIRMS GOES-19 (GOES_NRT) para detecciones en tiempo casi-real.
Polling cada 20 min; umbral de confianza 50 (menor que VIIRS por ruido geoestacionario).
"""

import io
import logging
import time
from datetime import datetime, timedelta, timezone

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

from .config import BBOX, FIRMS_MAP_KEY

log = logging.getLogger(__name__)

_FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
_GOES_SOURCE = "GOES_NRT"
_GOES_SATELLITE = "G19FRP"
_GOES_MIN_CONFIDENCE = 50
_BBOX_STR = "{lon_min},{lat_min},{lon_max},{lat_max}".format(**BBOX)


def _fetch_raw(days: int = 1, retries: int = 3, backoff: float = 5.0) -> pd.DataFrame:
    url = f"{_FIRMS_BASE}/{FIRMS_MAP_KEY}/{_GOES_SOURCE}/{_BBOX_STR}/{days}"
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 429:
                wait = backoff * attempt
                log.warning("FIRMS rate limit GOES_NRT. Esperando %.0fs.", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            if not resp.text.strip():
                log.info("GOES_NRT: sin datos en el área configurada.")
                return pd.DataFrame()
            df = pd.read_csv(io.StringIO(resp.text))
            log.info("GOES_NRT: %d detecciones descargadas.", len(df))
            return df
        except requests.exceptions.Timeout:
            log.warning("Timeout GOES_NRT (intento %d/%d).", attempt, retries)
        except requests.exceptions.ConnectionError as exc:
            log.warning("Error de conexión GOES_NRT: %s (intento %d/%d).", exc, attempt, retries)
        except requests.exceptions.HTTPError as exc:
            log.error("Error HTTP GOES_NRT: %s", exc)
            return pd.DataFrame()
        if attempt < retries:
            time.sleep(backoff * attempt)
    log.error("No se pudo obtener datos de GOES_NRT tras %d intentos.", retries)
    return pd.DataFrame()


def _parse_acq_datetime(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    time_str = df["acq_time"].astype(str).str.zfill(4)
    df["acq_datetime"] = pd.to_datetime(
        df["acq_date"].astype(str) + " " + time_str.str[:2] + ":" + time_str.str[2:],
        format="%Y-%m-%d %H:%M",
        utc=True,
        errors="coerce",
    )
    return df


def fetch_goes_detections() -> gpd.GeoDataFrame:
    """
    Descarga y filtra detecciones GOES-19 del área Biobío.
    Aplica: confidence >= 50, satellite == G19FRP, daynight == D, ventana 3h.
    No filtra por 'instrument' (viene NaN en GOES_NRT).
    """
    df = _fetch_raw(days=1)
    if df.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    # confidence >= 50
    if "confidence" in df.columns:
        df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce").fillna(0)
        before = len(df)
        df = df[df["confidence"] >= _GOES_MIN_CONFIDENCE]
        log.info("GOES filtro confianza >= %d: %d → %d.", _GOES_MIN_CONFIDENCE, before, len(df))

    # satellite == "G19FRP" — confirma fuente
    if "satellite" in df.columns:
        before = len(df)
        df = df[df["satellite"] == _GOES_SATELLITE]
        log.info("GOES filtro satélite %s: %d → %d.", _GOES_SATELLITE, before, len(df))

    # daynight == "D" — mayor tasa de falsos positivos en detección nocturna geoestacionaria
    if "daynight" in df.columns:
        before = len(df)
        df = df[df["daynight"] == "D"]
        log.info("GOES filtro diurno: %d → %d.", before, len(df))

    if df.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    df = _parse_acq_datetime(df)

    # Ventana 3h (latencia típica GOES ~2h)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=3)
    before = len(df)
    df = df[df["acq_datetime"] >= cutoff]
    log.info("GOES filtro temporal 3h: %d → %d.", before, len(df))

    if df.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    df["source"] = "GOES_NRT"
    geometry = [Point(xy) for xy in zip(df["longitude"], df["latitude"])]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
    return gdf.reset_index(drop=True)


def poll() -> None:
    """Job APScheduler — ejecutar cada 20 minutos. Tier 1: genera alertas preliminares."""
    from .two_tier_engine import process_goes_detections  # lazy import evita ciclo

    gdf = fetch_goes_detections()
    n = process_goes_detections(gdf)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    print(f"[GOES-19] {ts} UTC — {n} detecciones preliminares en Biobío")
