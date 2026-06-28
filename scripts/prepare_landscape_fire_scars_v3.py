import json
import re
import struct
import time
import zlib
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.ops import unary_union


BASE_URL = "https://download.pangaea.de/dataset/941127/files"
DATA_DIR = Path(__file__).resolve().parent
WORK_DIR = DATA_DIR / "landscape_fire_scars_pangaea"
VECTOR_DIR = WORK_DIR / "vectors_2015_2018"
OUT_GEOJSON = DATA_DIR / "fire_scars_segmentation_v3.geojson"

REGION_ARCHIVES = {
    "CL-BI": {
        "name": "BioBio",
        "archive": "FireScar_CL-BI-BioBio_2009-2018.zip",
    },
    "CL-ML": {
        "name": "Maule",
        "archive": "FireScar_CL-ML_Maule_2009-2018.zip",
    },
    "CL-AR": {
        "name": "Araucania",
        "archive": "FireScar_CL-AR_Araucania_2009-2018.zip",
    },
}

VECTOR_EXTENSIONS = {".cpg", ".dbf", ".prj", ".shp", ".shx"}


def ensure_download(filename: str) -> Path:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    path = WORK_DIR / filename
    if path.exists() and path.stat().st_size > 0:
        return path
    url = f"{BASE_URL}/{filename}"
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    return path


def parse_zip64_eocd(session: requests.Session, url: str, tail: bytes, tail_start: int, eocd_pos: int):
    loc_pos = eocd_pos - 20
    loc = tail[loc_pos : loc_pos + 20]
    if loc[:4] != b"PK\x06\x07":
        raise RuntimeError("ZIP64 locator not found")
    _, _, zip64_eocd_offset, _ = struct.unpack("<4sLQL", loc)
    record = range_get(session, url, zip64_eocd_offset, zip64_eocd_offset + 200)
    if record[:4] != b"PK\x06\x06":
        raise RuntimeError("ZIP64 EOCD record not found")
    record_size = struct.unpack("<Q", record[4:12])[0]
    record = record[: 12 + record_size]
    values = struct.unpack("<4sQ2H2L4Q", record[:56])
    return values[7], values[8], values[9]


def request_with_retries(session: requests.Session, method: str, url: str, **kwargs):
    last_error = None
    for attempt in range(8):
        try:
            response = session.request(method, url, timeout=120, **kwargs)
            if response.status_code in {429, 500, 502, 503, 504}:
                last_error = requests.HTTPError(f"{response.status_code} for {url}", response=response)
                time.sleep(min(90, 2**attempt))
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(min(90, 2**attempt))
    raise last_error


def range_get(session: requests.Session, url: str, start: int, end: int) -> bytes:
    response = request_with_retries(
        session,
        "GET",
        url,
        headers={"Range": f"bytes={start}-{end}"},
    )
    return response.content


def get_zip_index(archive: str) -> list[dict]:
    cache_path = WORK_DIR / f"{archive}.index.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    session = requests.Session()
    url = f"{BASE_URL}/{archive}"
    head = request_with_retries(session, "HEAD", url, allow_redirects=True)
    size = int(head.headers["Content-Length"])
    tail_len = min(size, 2_000_000)
    tail_start = size - tail_len
    tail = range_get(session, url, tail_start, size - 1)
    eocd_pos = tail.rfind(b"PK\x05\x06")
    if eocd_pos < 0:
        raise RuntimeError(f"EOCD not found in {archive}")

    eocd = tail[eocd_pos : eocd_pos + 22]
    fields = struct.unpack("<4s4H2LH", eocd)
    total_entries = fields[4]
    cd_size = fields[5]
    cd_offset = fields[6]
    if total_entries == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
        total_entries, cd_size, cd_offset = parse_zip64_eocd(session, url, tail, tail_start, eocd_pos)

    central_dir = range_get(session, url, cd_offset, cd_offset + cd_size - 1)
    entries = []
    pos = 0
    while pos < len(central_dir):
        if central_dir[pos : pos + 4] != b"PK\x01\x02":
            raise RuntimeError(f"Bad central directory signature at {pos} in {archive}")
        values = struct.unpack("<4s6H3L5H2L", central_dir[pos : pos + 46])
        method = values[4]
        compressed_size = values[8]
        uncompressed_size = values[9]
        name_len = values[10]
        extra_len = values[11]
        comment_len = values[12]
        local_header_offset = values[16]
        name_start = pos + 46
        extra_start = name_start + name_len
        name = central_dir[name_start:extra_start].decode("utf-8", errors="replace")
        extra = central_dir[extra_start : extra_start + extra_len]

        if (
            compressed_size == 0xFFFFFFFF
            or uncompressed_size == 0xFFFFFFFF
            or local_header_offset == 0xFFFFFFFF
        ):
            cursor = 0
            while cursor + 4 <= len(extra):
                header_id, data_size = struct.unpack("<HH", extra[cursor : cursor + 4])
                payload = extra[cursor + 4 : cursor + 4 + data_size]
                if header_id == 0x0001:
                    p = 0
                    if uncompressed_size == 0xFFFFFFFF:
                        uncompressed_size = struct.unpack("<Q", payload[p : p + 8])[0]
                        p += 8
                    if compressed_size == 0xFFFFFFFF:
                        compressed_size = struct.unpack("<Q", payload[p : p + 8])[0]
                        p += 8
                    if local_header_offset == 0xFFFFFFFF:
                        local_header_offset = struct.unpack("<Q", payload[p : p + 8])[0]
                    break
                cursor += 4 + data_size

        entries.append(
            {
                "name": name,
                "method": method,
                "compressed_size": compressed_size,
                "uncompressed_size": uncompressed_size,
                "local_header_offset": local_header_offset,
            }
        )
        pos += 46 + name_len + extra_len + comment_len

    if len(entries) != total_entries:
        raise RuntimeError(f"Expected {total_entries} entries, parsed {len(entries)} in {archive}")
    cache_path.write_text(json.dumps(entries), encoding="utf-8")
    return entries


def extract_member(session: requests.Session, archive: str, entry: dict, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size == entry["uncompressed_size"]:
        return
    url = f"{BASE_URL}/{archive}"
    offset = entry["local_header_offset"]
    local_header = range_get(session, url, offset, offset + 30 - 1)
    if local_header[:4] != b"PK\x03\x04":
        raise RuntimeError(f"Bad local file header for {entry['name']}")
    values = struct.unpack("<4s5H3L2H", local_header)
    name_len = values[9]
    extra_len = values[10]
    data_start = offset + 30 + name_len + extra_len
    compressed = range_get(
        session,
        url,
        data_start,
        data_start + entry["compressed_size"] - 1,
    )
    if entry["method"] == 0:
        data = compressed
    elif entry["method"] == 8:
        data = zlib.decompress(compressed, -15)
    else:
        raise RuntimeError(f"Unsupported ZIP method {entry['method']} for {entry['name']}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    time.sleep(0.03)


def extract_stem_bundle(session: requests.Session, archive: str, entries: list[dict], stem: str, dest_dir: Path) -> None:
    target_exts = {".cpg", ".dbf", ".prj", ".shp", ".shx"}
    targets = {ext: dest_dir / f"{stem}{ext}" for ext in target_exts}
    if all(path.exists() and path.stat().st_size > 0 for path in targets.values()):
        return

    entries = sorted(entries, key=lambda entry: entry["local_header_offset"])
    first = entries[0]["local_header_offset"]
    tif_entry = next((entry for entry in entries if Path(entry["name"]).suffix.lower() == ".tif"), None)
    if tif_entry is not None:
        last = tif_entry["local_header_offset"] - 1
    else:
        last_vector = entries[-1]
        header = range_get(
            session,
            f"{BASE_URL}/{archive}",
            last_vector["local_header_offset"],
            last_vector["local_header_offset"] + 29,
        )
        values = struct.unpack("<4s5H3L2H", header)
        last = (
            last_vector["local_header_offset"]
            + 30
            + values[9]
            + values[10]
            + last_vector["compressed_size"]
            - 1
        )

    blob = range_get(session, f"{BASE_URL}/{archive}", first, last)
    central_by_basename = {entry["name"].split("/")[-1]: entry for entry in entries}
    cursor = 0
    while cursor < len(blob):
        if blob[cursor : cursor + 4] != b"PK\x03\x04":
            break
        values = struct.unpack("<4s5H3L2H", blob[cursor : cursor + 30])
        method = values[3]
        name_len = values[9]
        extra_len = values[10]
        name_start = cursor + 30
        data_start = name_start + name_len + extra_len
        name = blob[name_start : name_start + name_len].decode("utf-8", errors="replace")
        basename = name.split("/")[-1]
        central = central_by_basename.get(basename)
        if central is None:
            break
        compressed_size = central["compressed_size"]
        payload = blob[data_start : data_start + compressed_size]
        ext = Path(basename).suffix.lower()
        if ext in target_exts:
            if method == 0:
                data = payload
            elif method == 8:
                data = zlib.decompress(payload, -15)
            else:
                raise RuntimeError(f"Unsupported ZIP method {method} for {name}")
            dest = targets[ext]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        cursor = data_start + compressed_size
    time.sleep(0.03)


def normalize_region(value):
    if pd.isna(value):
        return None
    text = str(value)
    replacements = {
        "BioBio": "Biobío",
        "Biobio": "Biobío",
        "Araucania": "Araucanía",
    }
    return replacements.get(text, text)


def load_summary() -> pd.DataFrame:
    ensure_download("File_Description.txt")
    summary_path = ensure_download("FireScar_CL_Summary_1985-2018.xlsx")
    df = pd.read_excel(summary_path, sheet_name="Fire_Summary")
    df["date"] = pd.to_datetime(df["IgnitionDate_CONAF"], errors="coerce")
    df["year"] = df["date"].dt.year
    df["region"] = df["Region_CONAF"].map(normalize_region)
    df["area_ha"] = pd.to_numeric(df["TotalArea [m2]"], errors="coerce") / 10000
    df.loc[df["area_ha"].isna(), "area_ha"] = pd.to_numeric(
        df.loc[df["area_ha"].isna(), "Area_CONAF [ha]"], errors="coerce"
    )
    return df


def filename_stem(filename: str) -> str:
    return Path(str(filename)).stem


def extract_needed_vectors(filtered: pd.DataFrame) -> dict[str, Path]:
    VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    result = {}
    session = requests.Session()
    for code, meta in REGION_ARCHIVES.items():
        archive = meta["archive"]
        region_rows = filtered[filtered["RegionCode"] == code]
        if region_rows.empty:
            continue
        index = get_zip_index(archive)
        by_name = {entry["name"].split("/")[-1]: entry for entry in index}
        by_stem: dict[str, list[dict]] = {}
        for entry in index:
            basename = entry["name"].split("/")[-1]
            if not basename or "." not in basename:
                continue
            by_stem.setdefault(Path(basename).stem, []).append(entry)
        needed_stems = set(region_rows["FireScarVectorName"].dropna().map(filename_stem))
        for stem in sorted(needed_stems):
            entries = by_stem.get(stem)
            if entries:
                extract_stem_bundle(session, archive, entries, stem, VECTOR_DIR / code)
            else:
                for ext in VECTOR_EXTENSIONS:
                    member_name = f"{stem}{ext}"
                    entry = by_name.get(member_name)
                    if not entry:
                        continue
                    dest = VECTOR_DIR / code / member_name
                    extract_member(session, archive, entry, dest)
            shp = VECTOR_DIR / code / f"{stem}.shp"
            if shp.exists():
                result[stem] = shp
    return result


def build_geometries(filtered: pd.DataFrame, shapefiles: dict[str, Path]) -> gpd.GeoDataFrame:
    records = []
    for _, row in filtered.iterrows():
        stem = filename_stem(row["FireScarVectorName"])
        shp = shapefiles.get(stem)
        if shp is None:
            continue
        try:
            gdf = gpd.read_file(shp)
        except Exception as exc:
            print(f"WARNING: could not read {shp}: {exc}")
            continue
        if gdf.empty:
            continue
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        gdf = gdf.to_crs("EPSG:4326")
        geom = unary_union([geom for geom in gdf.geometry if geom is not None and not geom.is_empty])
        if geom.is_empty:
            continue
        records.append(
            {
                "scar_id": row["FireID"],
                "date": row["date"].date().isoformat() if pd.notna(row["date"]) else None,
                "area_ha": float(row["area_ha"]) if pd.notna(row["area_ha"]) else None,
                "region": row["region"],
                "RegionCode": row["RegionCode"],
                "latitude": row["Latitude [°]"],
                "longitude": row["Longitude [°]"],
                "geometry": geom,
            }
        )
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


def load_conaf() -> gpd.GeoDataFrame | None:
    preferred = DATA_DIR / "conaf_additional_biobio.csv"
    fallback = DATA_DIR.parent / "conaf_biobio_2023_2024_gt.csv"
    path = preferred if preferred.exists() else fallback if fallback.exists() else None
    if path is None:
        print("WARNING: data/conaf_additional_biobio.csv not found; CONAF matching skipped.")
        return None
    df = pd.read_csv(path, encoding="utf-8")
    lat_col = next((c for c in df.columns if c.lower() in {"lat", "latitude", "latitud"}), None)
    lon_col = next((c for c in df.columns if c.lower() in {"lon", "lng", "longitude", "longitud"}), None)
    date_col = next((c for c in df.columns if c.lower() in {"fecha_inicio", "fecha", "date", "ignitiondate"}), None)
    if lat_col is None or lon_col is None or date_col is None:
        print(f"WARNING: CONAF file {path} lacks lat/lon/date columns; matching skipped.")
        return None
    df["conaf_date"] = pd.to_datetime(df[date_col], errors="coerce")
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(pd.to_numeric(df[lon_col], errors="coerce"), pd.to_numeric(df[lat_col], errors="coerce")),
        crs="EPSG:4326",
    )
    gdf = gdf[gdf.geometry.notna() & gdf["conaf_date"].notna()].copy()
    gdf["_source_file"] = str(path)
    return gdf


def match_conaf(scars: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    scars = scars.copy()
    scars["label"] = -1
    scars["conaf_match"] = False
    scars["conaf_causa"] = None
    conaf = load_conaf()
    if conaf is None or conaf.empty or scars.empty:
        return scars

    scars_metric = scars.to_crs("EPSG:32718")
    conaf_metric = conaf.to_crs("EPSG:32718")
    scar_centroids = scars_metric.geometry.centroid
    scar_dates = pd.to_datetime(scars["date"], errors="coerce")

    for idx, centroid in scar_centroids.items():
        date = scar_dates.loc[idx]
        if pd.isna(date):
            continue
        temporal = (conaf_metric["conaf_date"] - date).abs().dt.days <= 30
        candidates = conaf_metric[temporal].copy()
        if candidates.empty:
            continue
        distances = candidates.geometry.distance(centroid)
        within = distances[distances <= 5000]
        if within.empty:
            continue
        best_idx = within.idxmin()
        record = conaf.loc[best_idx]
        causa = record.get("causa", None)
        label_value = record.get("label", None)
        try:
            label_value = int(label_value)
        except Exception:
            label_value = 1 if causa and "intenc" in str(causa).lower() else 0
        scars.loc[idx, "label"] = label_value
        scars.loc[idx, "conaf_match"] = True
        scars.loc[idx, "conaf_causa"] = None if pd.isna(causa) else str(causa)
    return scars


def main():
    summary = load_summary()
    reconstructed = summary[summary["FireScar"] == 1].copy()

    print("=== Schema inspection ===")
    print("Column names:")
    print(list(summary.columns))
    print("\nFirst 3 rows:")
    print(summary.head(3).to_string())
    print(f"\nTotal record count: {len(summary)}")
    print(f"Reconstructed fire scar count: {len(reconstructed)}")
    print(
        "Date range available:",
        f"{summary['date'].min().date()} -> {summary['date'].max().date()}",
    )
    print("Coverage by region:")
    print(reconstructed.groupby("region").size().sort_index().to_string())

    target = reconstructed[
        reconstructed["RegionCode"].isin(REGION_ARCHIVES)
        & reconstructed["year"].between(2015, 2018)
        & (reconstructed["area_ha"] >= 10)
        & reconstructed["FireScarVectorName"].notna()
    ].copy()

    shapefiles = extract_needed_vectors(target)
    scars = build_geometries(target, shapefiles)
    scars = match_conaf(scars)

    if not scars.empty:
        scars["geometry_type"] = scars.geometry.geom_type
        output = scars[
            [
                "scar_id",
                "date",
                "area_ha",
                "region",
                "label",
                "conaf_match",
                "conaf_causa",
                "geometry",
            ]
        ].copy()
        output.to_file(OUT_GEOJSON, driver="GeoJSON")

    region_counts = reconstructed[reconstructed["RegionCode"].isin(REGION_ARCHIVES)].groupby("region").size()
    matched = int(scars["conaf_match"].sum()) if not scars.empty else 0
    intentional = int(((scars["conaf_match"]) & (scars["label"] == 1)).sum()) if not scars.empty else 0
    non_intentional = int(((scars["conaf_match"]) & (scars["label"] == 0)).sum()) if not scars.empty else 0
    unmatched = int((~scars["conaf_match"]).sum()) if not scars.empty else 0

    print("\n=== Landscape Fire Scars Database Chile ===")
    print(f"Total cicatrices:              {len(reconstructed)}")
    print(f"Rango fechas:                  {summary['year'].min()} -> {summary['year'].max()}")
    print("─────────────────────────────────────────")
    print(f"Biobío:                        {int(region_counts.get('Biobío', 0))}")
    print(f"Maule:                         {int(region_counts.get('Maule', 0))}")
    print(f"Araucanía:                     {int(region_counts.get('Araucanía', 0))}")
    print("─────────────────────────────────────────")
    print(f"Filtradas (2015-2018, ≥10ha):  {len(scars)}")
    print(f"Con match CONAF (causa):       {matched}  ({intentional} intencional | {non_intentional} no intencional)")
    print(f"Sin match CONAF:               {unmatched}  (cicatriz sin label de causa)")
    print("─────────────────────────────────────────")
    print(f"Listas para segmentación:      {len(scars)}")
    print(f"\nGeometry types: {scars.geometry.geom_type.value_counts().to_dict() if not scars.empty else {}}")
    print(f"Saved: {OUT_GEOJSON}")


if __name__ == "__main__":
    main()
