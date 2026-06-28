"""
Validación histórica Módulo A — Biobío 2025.
Consulta el archivo NASA FIRMS para todo 2025 y simula cuántas alertas
habría generado el Módulo A con su lógica de filtrado y deduplicación.

Uso: python -m scripts.validate_module_a_2025
     o bien: python scripts/validate_module_a_2025.py
"""

import io
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point
from tqdm import tqdm

# Asegura que el raíz del proyecto esté en el path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.module_a_realtime.config import (
    BBOX,
    DEDUP_RADIUS_M,
    DEDUP_TIME_WINDOW_HOURS,
    FIRMS_MAP_KEY,
    PROJECT_ROOT,
)
from modules.module_a_realtime.alert_manager import _is_duplicate
from modules.module_a_realtime.firms_client import _parse_acq_datetime
from modules.module_a_realtime.geo_filter import filter_biobio

logging.basicConfig(
    level=logging.WARNING,  # silenciar logs internos del módulo durante la validación
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("validate_module_a")

# ---------------------------------------------------------------------------
# Constantes de la validación
# ---------------------------------------------------------------------------

# Fuentes de archivo Standard Processing (sufijo _SP, para datos > 2 meses)
# Max 5 días por request en el endpoint de área CSV
ARCHIVE_SOURCES = ["VIIRS_SNPP_SP", "VIIRS_NOAA20_SP"]

BBOX_STR = "{lon_min},{lat_min},{lon_max},{lat_max}".format(**BBOX)
FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

CHUNK_DAYS = 5  # límite real del API archive _SP
START_DATE = date(2025, 1, 1)
END_DATE = date(2025, 12, 31)

OUTPUT_PATH = PROJECT_ROOT / "data" / "validation" / "module_a_2025.geojson"

REQUIRED_COLS = {"latitude", "longitude", "confidence", "acq_date", "acq_time"}

_MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_chunks(start: date, end: date, chunk_days: int):
    """Genera tuplas (fecha_inicio, n_dias) cubriendo el rango completo."""
    current = start
    while current <= end:
        remaining = (end - current).days + 1
        days = min(chunk_days, remaining)
        yield current, days
        current += timedelta(days=days)


def _fetch_archive_chunk(
    source: str,
    chunk_start: date,
    num_days: int,
    retries: int = 3,
) -> pd.DataFrame | None:
    """
    Descarga un chunk del archivo FIRMS.
    Retorna DataFrame, DataFrame vacío si no hay datos, o None si hubo error.
    """
    url = (
        f"{FIRMS_BASE}/{FIRMS_MAP_KEY}/{source}/{BBOX_STR}"
        f"/{num_days}/{chunk_start.strftime('%Y-%m-%d')}"
    )
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=60)
            if resp.status_code == 429:
                wait = 30 * attempt
                log.warning("Rate limit FIRMS (%s %s). Esperando %ds.", source, chunk_start, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            if not resp.text.strip():
                return pd.DataFrame()
            df = pd.read_csv(io.StringIO(resp.text))
            missing = REQUIRED_COLS - set(df.columns)
            if missing:
                log.warning("Columnas faltantes en %s %s: %s", source, chunk_start, missing)
                return pd.DataFrame()
            return df
        except requests.exceptions.Timeout:
            log.warning("Timeout %s %s (intento %d/%d).", source, chunk_start, attempt, retries)
        except requests.exceptions.HTTPError as exc:
            log.error("HTTP error %s %s: %s", source, chunk_start, exc)
            return None  # error definitivo, no reintentar
        except requests.exceptions.RequestException as exc:
            log.warning("Error de red %s %s: %s (intento %d/%d).", source, chunk_start, exc, attempt, retries)
        if attempt < retries:
            time.sleep(5 * attempt)
    log.error("Chunk fallido tras %d intentos: %s %s", retries, source, chunk_start)
    return None


def _to_geodataframe(df: pd.DataFrame) -> gpd.GeoDataFrame:
    """Convierte DataFrame FIRMS a GeoDataFrame con CRS WGS84."""
    geometry = [Point(lon, lat) for lon, lat in zip(df["longitude"], df["latitude"])]
    return gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")


def _append_accepted(
    accepted: gpd.GeoDataFrame | None,
    new_alerts: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    if accepted is None:
        return new_alerts.copy()
    return gpd.GeoDataFrame(
        pd.concat([accepted, new_alerts], ignore_index=True),
        crs="EPSG:4326",
    )


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def main() -> None:
    chunks = list(_generate_chunks(START_DATE, END_DATE, CHUNK_DAYS))
    total_chunks = len(chunks) * len(ARCHIVE_SOURCES)

    raw_counts: dict[str, int] = {s: 0 for s in ARCHIVE_SOURCES}
    total_filtered = 0
    failed_chunks: list[str] = []
    accepted_alerts: gpd.GeoDataFrame | None = None

    print(f"\nConsultando NASA FIRMS — {len(chunks)} chunks ({CHUNK_DAYS}d c/u) x {len(ARCHIVE_SOURCES)} fuentes = {total_chunks} requests")
    print(f"Rango: {START_DATE} -> {END_DATE}  |  Bbox Biobio: {BBOX_STR}\n")

    with tqdm(total=len(chunks), unit="chunk", ncols=80, desc="Descargando") as pbar:
        for chunk_start, num_days in chunks:
            chunk_end = chunk_start + timedelta(days=num_days - 1)
            pbar.set_description(f"{chunk_start} ({num_days}d)")

            chunk_frames: list[pd.DataFrame] = []

            for source in ARCHIVE_SOURCES:
                df = _fetch_archive_chunk(source, chunk_start, num_days)
                if df is None:
                    failed_chunks.append(f"{source} {chunk_start}+{num_days}d")
                    continue
                if df.empty:
                    continue
                raw_counts[source] += len(df)
                df["source"] = source
                chunk_frames.append(df)

            if not chunk_frames:
                pbar.update(1)
                continue

            combined = pd.concat(chunk_frames, ignore_index=True)
            combined = _parse_acq_datetime(combined)
            gdf = _to_geodataframe(combined)

            filtered = filter_biobio(gdf)
            if filtered.empty:
                pbar.update(1)
                continue

            total_filtered += len(filtered)

            # Deduplicación incremental: igual lógica que Module A en producción
            existing_for_dedup = (
                accepted_alerts
                if accepted_alerts is not None
                else gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs="EPSG:4326"))
            )
            dup_mask = _is_duplicate(
                filtered, existing_for_dedup, DEDUP_RADIUS_M, DEDUP_TIME_WINDOW_HOURS
            )
            new_alerts = filtered[~dup_mask]

            if not new_alerts.empty:
                accepted_alerts = _append_accepted(accepted_alerts, new_alerts)

            pbar.update(1)

    # ---------------------------------------------------------------------------
    # Estadísticas finales
    # ---------------------------------------------------------------------------
    n_raw_snpp = raw_counts["VIIRS_SNPP_SP"]
    n_raw_noaa = raw_counts["VIIRS_NOAA20_SP"]
    n_raw_total = n_raw_snpp + n_raw_noaa
    n_filtered = total_filtered
    n_deduped = len(accepted_alerts) if accepted_alerts is not None else 0

    # Top 3 meses
    top_months_str = "N/A"
    if accepted_alerts is not None and "acq_datetime" in accepted_alerts.columns:
        ac = accepted_alerts.copy()
        ac["month"] = pd.to_datetime(ac["acq_datetime"], utc=True, errors="coerce").dt.month
        monthly = ac["month"].value_counts().sort_values(ascending=False).head(3)
        top_months_str = ", ".join(
            f"{_MESES_ES.get(m, m)} ({c})" for m, c in monthly.items()
        )

    # Coordenada mas activa (rounding a ~0.01 grados, aprox 1 km)
    hotspot_str = "N/A"
    if accepted_alerts is not None and not accepted_alerts.empty:
        ac = accepted_alerts.copy()
        ac["lat_r"] = ac.geometry.y.round(2)
        ac["lon_r"] = ac.geometry.x.round(2)
        coord_counts = ac.groupby(["lat_r", "lon_r"]).size().sort_values(ascending=False)
        top_lat, top_lon = coord_counts.index[0]
        top_n = coord_counts.iloc[0]
        hotspot_str = f"{top_lat:.2f}, {top_lon:.2f} ({top_n} alertas)"

    sep = "-" * 42
    print(f"\n{'=' * 42}")
    print("=== Validacion Modulo A - Biobio 2025 ===")
    print(f"{'=' * 42}")
    print(f"Periodo:                               {START_DATE} -> {END_DATE}")
    print(f"Detecciones brutas VIIRS_SNPP:         {n_raw_snpp:>6}")
    print(f"Detecciones brutas VIIRS_NOAA20:       {n_raw_noaa:>6}")
    print(f"Total bruto combinado:                 {n_raw_total:>6}")
    print(f"Despues de filtro confianza >=70%:     {n_filtered:>6}")
    print(f"Despues de deduplicacion (375m/3h):    {n_deduped:>6}")
    print(sep)
    print(f"ALERTAS QUE HABRIA GENERADO:           {n_deduped:>6}")
    print(f"Meses con mas actividad:               {top_months_str}")
    print(f"Coordenada mas activa:                 {hotspot_str}")

    if failed_chunks:
        print(f"\nChunks fallidos ({len(failed_chunks)}):")
        for fc in failed_chunks:
            print(f"  - {fc}")

    # ---------------------------------------------------------------------------
    # Guardar GeoJSON
    # ---------------------------------------------------------------------------
    if accepted_alerts is not None and not accepted_alerts.empty:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        save_gdf = accepted_alerts.copy()
        if "acq_datetime" in save_gdf.columns:
            save_gdf["acq_datetime"] = save_gdf["acq_datetime"].astype(str)
        save_gdf.to_file(OUTPUT_PATH, driver="GeoJSON")
        print(f"\nResultados guardados en: {OUTPUT_PATH}")
    else:
        print("\nSin alertas que guardar.")

    print()


if __name__ == "__main__":
    main()
