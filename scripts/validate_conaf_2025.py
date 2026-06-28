"""
Validación de Módulo A contra datos oficiales CONAF SIMEF — Biobío 2025.

Descarga el shapefile de incendios de la temporada 2024-2025, filtra a
Biobío + año 2025, y cruza contra los eventos detectados por Módulo A.

Uso: python scripts/validate_conaf_2025.py
"""

import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Paths y constantes
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent

RAW_DIR = _ROOT / "data" / "conaf" / "raw"
EVENTS_PATH = _ROOT / "data" / "validation" / "module_a_2025_events.geojson"
MISSED_PATH = _ROOT / "data" / "validation" / "conaf_missed.geojson"

CONAF_URL = "https://ide.minagri.gob.cl/geoweb/wp-content/uploads/2026/01/if_temporada_2024_2025.rar"
RAR_FILENAME = "if_temporada_2024_2025.rar"

BIOBIO_REGION = "Biobío"
YEAR_FILTER = 2025

MATCH_DIST_KM = 5.0
MATCH_DAYS_BUFFER = 7

# UTM zona 19S para distancias en metros (igual que Module A)
_CRS_PROJ = "EPSG:32719"

# Meses abreviados en español presentes en las fechas CONAF
_MESES_ES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_7z() -> str:
    """Busca el ejecutable 7z disponible en el sistema."""
    for candidate in ["7z", "7za", "7zr"]:
        path = shutil.which(candidate)
        if path:
            return path
    raise FileNotFoundError(
        "No se encontro 7z en PATH. Instala 7-Zip y asegurate de que este en PATH."
    )


def _download_rar(url: str, dest: Path) -> None:
    """Descarga el archivo RAR si no existe ya."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"  RAR ya descargado: {dest}")
        return
    print(f"  Descargando {url} ...")
    try:
        r = requests.get(url, timeout=120, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"  Descarga completa ({dest.stat().st_size // 1024} KB)")
    except requests.exceptions.HTTPError as exc:
        print(f"\nERROR HTTP al descargar CONAF: {exc}")
        print(f"URL intentada: {url}")
        sys.exit(1)
    except requests.exceptions.RequestException as exc:
        print(f"\nERROR de red al descargar CONAF: {exc}")
        sys.exit(1)


def _extract_rar(rar_path: Path, out_dir: Path, z7: str) -> None:
    """Extrae el RAR usando 7z."""
    shp_files = list(out_dir.glob("*.shp"))
    if shp_files:
        print(f"  Shapefile ya extraido: {shp_files[0].name}")
        return
    print(f"  Extrayendo con 7z ...")
    result = subprocess.run(
        [z7, "x", str(rar_path), f"-o{out_dir}", "-y"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"\nERROR al extraer RAR:\n{result.stderr}")
        sys.exit(1)
    print("  Extraccion completa.")


def _parse_conaf_date(date_str: str) -> datetime | None:
    """
    Parsea fechas CONAF como '5-dic-2024 13:03'.
    Retorna None si el valor esta vacio o no parseable.
    """
    if not date_str or pd.isna(date_str):
        return None
    s = str(date_str).strip().lower()
    try:
        parts = s.split()
        day_mon_yr = parts[0].split("-")
        day = int(day_mon_yr[0])
        month = _MESES_ES.get(day_mon_yr[1][:3])
        year = int(day_mon_yr[2])
        if month is None:
            return None
        if len(parts) > 1:
            hh, mm = parts[1].split(":")
            return datetime(year, month, day, int(hh), int(mm))
        return datetime(year, month, day)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Carga y filtrado CONAF
# ---------------------------------------------------------------------------

def load_conaf(shp_path: Path) -> gpd.GeoDataFrame:
    """Carga shapefile CONAF, parsea fechas, filtra Biobio + 2025."""
    print(f"  Cargando shapefile: {shp_path.name}")
    gdf = gpd.read_file(shp_path, encoding="latin-1")

    # Parsear fechas
    gdf["dt_inicio"] = gdf["FH_INICIO"].apply(_parse_conaf_date)
    gdf["dt_extinci"] = gdf["FH_EXTINCI"].apply(_parse_conaf_date)

    # Filtrar region Biobio
    biobio = gdf[gdf["REGION"] == BIOBIO_REGION].copy()

    # Filtrar año 2025 por fecha de inicio
    biobio_2025 = biobio[
        biobio["dt_inicio"].apply(lambda d: d is not None and d.year == YEAR_FILTER)
    ].copy()

    biobio_2025 = biobio_2025.reset_index(drop=True)
    print(f"  Incendios CONAF en Biobio 2025: {len(biobio_2025)}")
    return biobio_2025


# ---------------------------------------------------------------------------
# Cross-matching
# ---------------------------------------------------------------------------

def _dates_overlap(
    c_start: datetime,
    c_end: datetime | None,
    e_start_raw,
    e_end_raw,
    buffer_days: int,
) -> bool:
    """
    True si el incendio CONAF [c_start, c_end] y el evento Module A
    [e_start, e_end] se solapan con un buffer de buffer_days dias.
    Acepta fechas como str 'YYYY-MM-DD' o Timestamp/datetime.
    """
    def _to_dt(v):
        if isinstance(v, datetime):
            return v
        if hasattr(v, "to_pydatetime"):
            return v.to_pydatetime().replace(tzinfo=None)
        return datetime.strptime(str(v)[:10], "%Y-%m-%d")

    e_start = _to_dt(e_start_raw)
    e_end = _to_dt(e_end_raw)
    buf = timedelta(days=buffer_days)

    c_end_eff = c_end if c_end is not None else c_start
    return (c_start - buf) <= e_end and e_start <= (c_end_eff + buf)


def cross_match(
    conaf: gpd.GeoDataFrame,
    events: gpd.GeoDataFrame,
    dist_km: float,
    days_buf: int,
) -> tuple[set, set]:
    """
    Devuelve (matched_conaf_indices, matched_event_indices).
    Un par matchea si distancia <= dist_km Y fechas se solapan +-days_buf dias.
    """
    conaf_proj = conaf.to_crs(_CRS_PROJ)
    events_proj = events.to_crs(_CRS_PROJ)
    eps_m = dist_km * 1000.0

    matched_conaf: set = set()
    matched_events: set = set()

    for ci, crow in conaf_proj.iterrows():
        c_start = conaf.at[ci, "dt_inicio"]
        c_end = conaf.at[ci, "dt_extinci"]
        if c_start is None:
            continue

        dists = events_proj.geometry.distance(crow.geometry)
        spatial_candidates = events_proj[dists <= eps_m].index

        for ei in spatial_candidates:
            erow = events.loc[ei]
            if _dates_overlap(c_start, c_end, erow["start_date"], erow["end_date"], days_buf):
                matched_conaf.add(ci)
                matched_events.add(ei)
                break  # un match es suficiente por incendio CONAF

    return matched_conaf, matched_events


# ---------------------------------------------------------------------------
# Reporte por tier
# ---------------------------------------------------------------------------

AREA_COL = "SUPERFICIE"  # hectareas totales quemadas en el shapefile CONAF

TIERS = [
    ("Tier 1 - todos        (>=0 ha)",   0),
    ("Tier 2 - medianos    (>=10 ha)",  10),
    ("Tier 3 - grandes     (>=50 ha)",  50),
    ("Tier 4 - mayores    (>=200 ha)", 200),
]


def _run_tier(
    label: str,
    min_ha: float,
    conaf_all: gpd.GeoDataFrame,
    events: gpd.GeoDataFrame,
) -> set:
    """Cross-match para un tier dado. Devuelve matched_conaf indices."""
    subset = conaf_all[conaf_all[AREA_COL] >= min_ha].copy().reset_index(drop=True)
    if subset.empty:
        print(f"\n{label}:")
        print(f"  CONAF: 0 | Modulo A matches: 0 | Recall: N/A")
        return set()

    matched_conaf, _ = cross_match(subset, events, MATCH_DIST_KM, MATCH_DAYS_BUFFER)
    n_match = len(matched_conaf)
    recall = n_match / len(subset) * 100

    print(f"\n{label}:")
    print(f"  CONAF: {len(subset)} | Modulo A matches: {n_match} | Recall: {recall:.1f}%")
    return matched_conaf


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    z7 = _find_7z()

    rar_path = RAW_DIR / RAR_FILENAME
    print("\n[1/4] Descargando datos CONAF ...")
    _download_rar(CONAF_URL, rar_path)

    print("[2/4] Extrayendo RAR ...")
    _extract_rar(rar_path, RAW_DIR, z7)

    shp_path = next(RAW_DIR.glob("*.shp"))

    print("[3/4] Cargando y filtrando datos CONAF ...")
    conaf = load_conaf(shp_path)

    if AREA_COL not in conaf.columns:
        print(f"\nERROR: columna '{AREA_COL}' no encontrada.")
        print("Columnas disponibles:", list(conaf.columns))
        sys.exit(1)

    print("[4/4] Cargando eventos Modulo A ...")
    events = gpd.read_file(EVENTS_PATH)
    print(f"  Eventos Modulo A cargados: {len(events)}")

    # Reporte por tier
    sep = "-" * 50
    print(f"\n{'=' * 50}")
    print("=== Recall por tamano de incendio - Biobio 2025 ===")
    print(f"{'=' * 50}")
    print(f"  (radio match: {MATCH_DIST_KM}km | buffer temporal: +-{MATCH_DAYS_BUFFER} dias)")

    tier1_matched = None
    for label, min_ha in TIERS:
        matched = _run_tier(label, min_ha, conaf, events)
        if min_ha == 0:
            tier1_matched = matched  # guardar para conaf_missed.geojson

    print(f"\n{sep}")

    # Guardar CONAF no detectados (Tier 1 — baseline completo)
    if tier1_matched is not None:
        conaf_reset = conaf.reset_index(drop=True)
        missed = conaf_reset[~conaf_reset.index.isin(tier1_matched)].copy()
        if not missed.empty:
            for col in ["dt_inicio", "dt_extinci"]:
                missed[col] = missed[col].apply(
                    lambda d: d.strftime("%Y-%m-%d %H:%M") if d is not None else None
                )
            MISSED_PATH.parent.mkdir(parents=True, exist_ok=True)
            missed.to_file(MISSED_PATH, driver="GeoJSON")
            print(f"Incendios CONAF no detectados (Tier 1) guardados en: {MISSED_PATH}")

    print()


if __name__ == "__main__":
    main()
