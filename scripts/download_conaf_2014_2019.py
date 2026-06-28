"""Download CONAF fire records and label the Gaia Incendios v0.3 scars."""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import requests
from pyproj import Transformer
from shapely import STRtree


SERVICE_URL = (
    "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/"
    "INCENDIOS_MINIS_INSTI/FeatureServer"
)
LAYERS = {
    40: "2014-2015",
    41: "2015-2016",
    42: "2016-2017",
    # Layer 43 (2017-2018) is intentionally omitted: causa is empty.
    44: "2018-2019",
    45: "2019-2020",
}
PAGE_SIZE = 2_000
MAX_DISTANCE_M = 5_000
MAX_DATE_DELTA_DAYS = 30
TARGET_CRS = "EPSG:32718"

REGION_BY_CODE = {
    "01": "Tarapacá",
    "02": "Antofagasta",
    "03": "Atacama",
    "04": "Coquimbo",
    "05": "Valparaíso",
    "06": "O'Higgins",
    "07": "Maule",
    "08": "Biobío",
    "09": "Araucanía",
    "10": "Los Lagos",
    "11": "Aysén",
    "12": "Magallanes",
    "13": "Metropolitana",
    "14": "Los Ríos",
    "15": "Arica y Parinacota",
    "16": "Ñuble",
}

SPANISH_MONTHS = {
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Download CONAF 2014-2019 records and match fire scars."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=repo_root / "data",
        help="Directory containing fire_scars_segmentation_v3.geojson.",
    )
    return parser.parse_args()


def api_get(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    retries: int = 5,
) -> dict[str, Any]:
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, timeout=120)
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(str(payload["error"]))
            return payload
        except (requests.RequestException, ValueError, RuntimeError):
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Unreachable")


def download_layer(
    session: requests.Session, layer_id: int, season: str
) -> list[dict[str, Any]]:
    layer_url = f"{SERVICE_URL}/{layer_id}"
    metadata = api_get(session, layer_url, {"f": "json"})
    object_id_field = metadata["objectIdField"]
    expected_count = api_get(
        session,
        f"{layer_url}/query",
        {"where": "1=1", "returnCountOnly": "true", "f": "json"},
    )["count"]

    records: list[dict[str, Any]] = []
    offset = 0
    while offset < expected_count:
        payload = api_get(
            session,
            f"{layer_url}/query",
            {
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "orderByFields": f"{object_id_field} ASC",
                "resultOffset": offset,
                "resultRecordCount": PAGE_SIZE,
                "f": "json",
            },
        )
        features = payload.get("features", [])
        if not features:
            break

        for feature in features:
            attributes = dict(feature.get("attributes", {}))
            geometry = feature.get("geometry") or {}
            attributes.update(
                {
                    "source_layer": layer_id,
                    "source_season": season,
                    "source_objectid": attributes.get(object_id_field),
                    "_api_lon": geometry.get("x"),
                    "_api_lat": geometry.get("y"),
                }
            )
            records.append(attributes)

        offset += len(features)
        print(
            f"  Capa {layer_id} ({season}): "
            f"{min(offset, expected_count)}/{expected_count}"
        )
        if not payload.get("exceededTransferLimit") and len(features) < PAGE_SIZE:
            break

    object_ids = [row["source_objectid"] for row in records]
    if len(records) != expected_count or len(set(object_ids)) != expected_count:
        raise RuntimeError(
            f"Capa {layer_id}: se esperaban {expected_count} registros únicos "
            f"y se obtuvieron {len(records)}."
        )
    return records


def clean_text(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def ascii_lower(value: Any) -> str:
    text = clean_text(value) or ""
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    ).lower()


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        text = clean_text(value)
        if not text:
            return None
        try:
            if "," in text:
                text = text.replace(".", "").replace(",", ".")
            result = float(text)
        except ValueError:
            return None
    return result if math.isfinite(result) else None


def parse_date(value: Any) -> pd.Timestamp:
    text = clean_text(value)
    if not text:
        return pd.NaT

    normalized = ascii_lower(text)
    match = re.match(
        r"^(\d{1,2})[-/ ]([a-z]+|\d{1,2})[-/ ](\d{2,4})"
        r"(?:[ T]+(\d{1,2}):(\d{2}))?",
        normalized,
    )
    if match:
        day, month_raw, year, hour, minute = match.groups()
        month = (
            SPANISH_MONTHS.get(month_raw)
            if month_raw.isalpha()
            else int(month_raw)
        )
        if month:
            year_number = int(year)
            if year_number < 100:
                year_number += 2000
            try:
                return pd.Timestamp(
                    year=year_number,
                    month=month,
                    day=int(day),
                    hour=int(hour or 0),
                    minute=int(minute or 0),
                )
            except ValueError:
                return pd.NaT

    return pd.to_datetime(text, dayfirst=True, errors="coerce")


def cause_label(cause_general: Any, cause_specific: Any) -> int | None:
    general = ascii_lower(cause_general)
    specific = ascii_lower(cause_specific)
    if not general and not specific:
        return None

    if (
        "intencional" in general
        or re.match(r"^0?2[.\s-]*0?1(?:\D|$)", general)
        or re.match(r"^0?2[.\s-]*0?1(?:\D|$)", specific)
    ):
        return 1
    return 0


def inferred_utm_zone(api_lon: float | None, huso: Any) -> int | None:
    zone_match = re.search(r"\d{1,2}", clean_text(huso) or "")
    if zone_match:
        zone = int(zone_match.group())
        if 1 <= zone <= 60:
            return zone
    if api_lon is not None and -180 <= api_lon <= 180:
        return min(60, max(1, int((api_lon + 180) // 6) + 1))
    return None


def coordinates_from_record(
    row: dict[str, Any],
    transformers: dict[int, Transformer],
) -> tuple[float | None, float | None, str]:
    api_lon = parse_number(row.get("_api_lon"))
    api_lat = parse_number(row.get("_api_lat"))
    easting = parse_number(row.get("utm_e"))
    northing = parse_number(row.get("utm_n"))
    zone = inferred_utm_zone(api_lon, row.get("huso"))

    if (
        easting is not None
        and northing is not None
        and zone is not None
        and 100_000 <= easting <= 900_000
        and 1_000_000 <= northing <= 10_000_000
    ):
        transformer = transformers.setdefault(
            zone,
            Transformer.from_crs(f"EPSG:327{zone:02d}", "EPSG:4326", always_xy=True),
        )
        lon, lat = transformer.transform(easting, northing)
        if -80 <= lon <= -65 and -60 <= lat <= -15:
            if api_lon is None or api_lat is None:
                return lon, lat, "utm"
            if abs(lon - api_lon) <= 0.25 and abs(lat - api_lat) <= 0.25:
                return lon, lat, "utm"

    if (
        api_lon is not None
        and api_lat is not None
        and -80 <= api_lon <= -65
        and -60 <= api_lat <= -15
    ):
        return api_lon, api_lat, "esri_geometry"
    return None, None, "missing"


def normalized_region_name(value: Any, region_code: str) -> str | None:
    if region_code in REGION_BY_CODE:
        return REGION_BY_CODE[region_code]

    source = clean_text(value)
    aliases = {
        "araucania": "Araucanía",
        "bio bio": "Biobío",
        "bio-bio": "Biobío",
        "biobio": "Biobío",
        "maule": "Maule",
    }
    return aliases.get(ascii_lower(source).replace("’", "'"), source)


def normalize_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    transformers: dict[int, Transformer] = {}
    normalized: list[dict[str, Any]] = []
    for row in records:
        lon, lat, coordinate_source = coordinates_from_record(row, transformers)
        region_code = (clean_text(row.get("codreg")) or "").zfill(2)
        region = normalized_region_name(row.get("region"), region_code)

        cause_general = clean_text(row.get("causa_gene"))
        cause_specific = clean_text(row.get("causa_espe"))
        cause = " | ".join(
            part for part in (cause_general, cause_specific) if part is not None
        )
        label = cause_label(cause_general, cause_specific)
        date = parse_date(row.get("inicio_in"))

        output = {
            key: value
            for key, value in row.items()
            if key not in {"_api_lon", "_api_lat"}
        }
        output.update(
            {
                "conaf_id": (
                    f"{row['source_season']}:{row['source_objectid']}"
                ),
                "fecha_inicio": (
                    date.isoformat() if not pd.isna(date) else None
                ),
                "causa": cause or None,
                "label": label,
                "region_normalizada": region,
                "lat": lat,
                "lon": lon,
                "coordinate_source": coordinate_source,
            }
        )
        normalized.append(output)

    frame = pd.DataFrame(normalized)
    leading_columns = [
        "conaf_id",
        "source_layer",
        "source_season",
        "source_objectid",
        "fecha_inicio",
        "causa",
        "label",
        "region_normalizada",
        "lat",
        "lon",
        "coordinate_source",
    ]
    remaining = [column for column in frame.columns if column not in leading_columns]
    return frame[leading_columns + remaining]


def match_fire_scars(
    scars: gpd.GeoDataFrame, conaf: pd.DataFrame
) -> gpd.GeoDataFrame:
    result = scars.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["label"] = -1
    result["conaf_match"] = False
    result["conaf_causa"] = None

    valid = conaf[
        conaf["fecha_inicio"].notna()
        & conaf["lat"].notna()
        & conaf["lon"].notna()
        & conaf["label"].notna()
    ].copy()
    if valid.empty:
        return result

    valid["fecha_inicio_dt"] = pd.to_datetime(
        valid["fecha_inicio"], errors="coerce"
    )
    valid = valid[valid["fecha_inicio_dt"].notna()].reset_index(drop=True)
    points = gpd.GeoDataFrame(
        valid,
        geometry=gpd.points_from_xy(valid["lon"], valid["lat"]),
        crs="EPSG:4326",
    ).to_crs(TARGET_CRS)

    projected_scars = result.to_crs(TARGET_CRS)
    centroids = projected_scars.geometry.centroid
    point_geometries = points.geometry.to_numpy()
    tree = STRtree(point_geometries)

    for position, (scar_index, centroid) in enumerate(centroids.items(), start=1):
        scar_date = result.at[scar_index, "date"]
        if pd.isna(scar_date) or centroid is None or centroid.is_empty:
            continue

        candidate_positions = tree.query(
            centroid, predicate="dwithin", distance=MAX_DISTANCE_M
        )
        candidates: list[tuple[int, float, int]] = []
        for candidate_position in candidate_positions:
            conaf_date = points.iloc[candidate_position]["fecha_inicio_dt"]
            day_delta = abs((conaf_date.normalize() - scar_date.normalize()).days)
            if day_delta <= MAX_DATE_DELTA_DAYS:
                distance = centroid.distance(point_geometries[candidate_position])
                candidates.append(
                    (day_delta, distance, int(candidate_position))
                )

        if candidates:
            _, _, best_position = min(candidates)
            match = points.iloc[best_position]
            result.at[scar_index, "label"] = int(match["label"])
            result.at[scar_index, "conaf_match"] = True
            result.at[scar_index, "conaf_causa"] = match["causa"]

        if position % 200 == 0 or position == len(result):
            print(f"  Matching: {position}/{len(result)} cicatrices")

    return result


def atomic_write_geojson(frame: gpd.GeoDataFrame, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.stem}.tmp.geojson")
    try:
        frame.to_file(temporary, driver="GeoJSON")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def print_report(conaf: pd.DataFrame, scars: gpd.GeoDataFrame) -> None:
    matched = int(scars["conaf_match"].sum())
    intentional = int((scars["label"] == 1).sum())
    non_intentional = int((scars["label"] == 0).sum())
    unmatched = int((scars["label"] == -1).sum())
    total = len(scars)
    matched_pct = 100 * matched / total if total else 0
    unmatched_pct = 100 * unmatched / total if total else 0

    print()
    print("=== Match CONAF 2014-2019 × Fire Scars Chile ===")
    print(f"CONAF descargados:             {len(conaf)} registros")
    print("Regiones cubiertas:            Biobío, Maule, Araucanía, otras")
    print("─────────────────────────────────────────────")
    print(f"Cicatrices con match:          {matched}  ({matched_pct:.1f}%)")
    print(f"  Intencionales (label=1):     {intentional}")
    print(f"  No intencionales (label=0):  {non_intentional}")
    print(f"Sin match (label=-1):          {unmatched}  ({unmatched_pct:.1f}%)")
    print("─────────────────────────────────────────────")
    print("Dataset v0.3 final:")
    print(f"  Positivos con polígono:      {intentional}")
    print(f"  Negativos con polígono:      {non_intentional}")
    print(f"  Sin label:                   {unmatched}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    data_dir = args.data_dir.resolve()
    scars_path = data_dir / "fire_scars_segmentation_v3.geojson"
    conaf_path = data_dir / "conaf_2014_2019_nacional.csv"
    if not scars_path.exists():
        raise FileNotFoundError(f"No existe {scars_path}")

    print("Descargando capas CONAF...")
    session = requests.Session()
    session.headers["User-Agent"] = "Gaia-Incendios-v0.3/1.0"
    all_records: list[dict[str, Any]] = []
    for layer_id, season in LAYERS.items():
        all_records.extend(download_layer(session, layer_id, season))

    conaf = normalize_records(all_records)
    conaf.to_csv(conaf_path, index=False, encoding="utf-8-sig")

    missing_dates = (
        conaf.groupby("source_layer")["fecha_inicio"]
        .apply(lambda values: int(values.isna().sum()))
        .to_dict()
    )
    for layer_id in LAYERS:
        if missing_dates.get(layer_id):
            print(
                f"  Aviso: capa {layer_id} tiene "
                f"{missing_dates[layer_id]} fechas vacías."
            )

    print("Cruzando registros CONAF con cicatrices...")
    scars = gpd.read_file(scars_path)
    matched_scars = match_fire_scars(scars, conaf)
    atomic_write_geojson(matched_scars, scars_path)
    print_report(conaf, matched_scars)


if __name__ == "__main__":
    main()
