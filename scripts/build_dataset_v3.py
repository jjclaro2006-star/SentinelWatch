"""
Build ground truth CSV for Gaia Incendios v0.3 segmentation training.

Sources:
  Positivos  (2,000): gaia_incendios_v2_gt.csv + conaf_biobio_2023_2024_gt.csv  → label=1
  Neg Source A (1,094): fire_scars_segmentation_v3.geojson  → mask_type=real_polygon
  Neg Source B (18,906): gaia_incendios_v2_gt.csv + conaf_2014_2019_nacional.csv → label=0

Output: data/gaia_incendios_v3_gt.csv
"""

import json
import os
import re

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CHILE_BBOX = {"lat_min": -56, "lat_max": -17, "lon_min": -76, "lon_max": -66}
MIN_SUPERFICIE = 0.1
N_POS_TARGET = 2_000
N_NEG_TARGET = 20_000   # 1,094 real + 18,906 synthetic
RANDOM_STATE = 42

SPANISH_MONTHS = {
    "ene": "01", "feb": "02", "mar": "03", "abr": "04",
    "may": "05", "jun": "06", "jul": "07", "ago": "08",
    "sep": "09", "oct": "10", "nov": "11", "dic": "12",
}

NO_INTENCIONAL_KEYWORDS = [
    "accidente", "negligencia", "faena", "quema",
    "transito", "ferroviaria", "natural", "recreativa",
    "electrica", "pecuaria", "forestal",
]
INTENCIONAL_KEYWORDS = ["intencional", "ataque"]
EXCLUDE_KEYWORDS = ["desconocida", "desconocido"]

OUTPUT_COLS = [
    "lat", "lon", "fecha_inicio", "label", "region", "causa", "superficie_ha",
    "mask_type", "polygon_id", "temporada", "split",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_fecha(s) -> str | None:
    """Parse Spanish date strings like '25-nov-2020 21:18' → '2020-11-25'."""
    if s is None:
        return None
    s = str(s).strip()
    if s.lower() in ("nan", "none", "nat", ""):
        return None
    for abbr, num in SPANISH_MONTHS.items():
        s = re.sub(rf"\b{abbr}\b", num, s, flags=re.IGNORECASE)
    ts = pd.to_datetime(s, dayfirst=True, errors="coerce")
    return None if pd.isna(ts) else ts.strftime("%Y-%m-%d")


def normalize_region(r) -> str:
    """Normalize region names, stripping accents for consistency."""
    if not r:
        return ""
    return (
        str(r)
        .replace("Biobío", "Biobio").replace("Biobío", "Biobio")
        .replace("Araucanía", "Araucania").replace("Araucanía", "Araucania")
        .replace("Los Ríos", "LosRios").replace("Los Ríos", "LosRios")
        .replace("Los Lagos", "LosLagos")
        .replace("O’Higgins", "OHiggins").replace("O'Higgins", "OHiggins")
        .replace("Ñuble", "Nuble").replace("Ñuble", "Nuble")
        .replace("Metropolitana de Santiago", "Metropolitana")
        .strip()
    )


def assign_temporada(fecha: str | None) -> str | None:
    """Infer fire season (Jul–Jun cycle) from ISO date string."""
    if not fecha:
        return None
    dt = pd.to_datetime(fecha, errors="coerce")
    if pd.isna(dt):
        return None
    year, month = dt.year, dt.month
    return f"{year}-{year + 1}" if month >= 7 else f"{year - 1}-{year}"


def classify_causa(causa) -> int | None:
    if not causa:
        return None
    c = str(causa).lower()
    if any(k in c for k in EXCLUDE_KEYWORDS):
        return None
    if any(k in c for k in INTENCIONAL_KEYWORDS):
        return 1
    if any(k in c for k in NO_INTENCIONAL_KEYWORDS):
        return 0
    return None


def deduplicate_500m(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Remove points within 500 m of an earlier point (first-occurrence wins).

    Uses sklearn BallTree with haversine metric for efficiency. Falls back to
    a sorted O(n·k) loop if sklearn is unavailable.
    """
    if len(df) <= 1:
        return df.reset_index(drop=True), 0

    coords = df[["lat", "lon"]].values.astype(float)
    n = len(coords)
    keep = np.ones(n, dtype=bool)

    try:
        from sklearn.neighbors import BallTree
        coords_rad = np.radians(coords)
        tree = BallTree(coords_rad, metric="haversine")
        radius_rad = 0.5 / 6371.0
        neighbors_list = tree.query_radius(coords_rad, r=radius_rad)
        for i in range(n):
            if not keep[i]:
                continue
            for j in neighbors_list[i]:
                if j > i:
                    keep[j] = False
    except ImportError:
        # Fallback: sort by lat for early-exit inner loop
        sort_idx = np.argsort(coords[:, 0])
        sc = coords[sort_idx]
        keep_sorted = np.ones(n, dtype=bool)
        for ii in range(n):
            if not keep_sorted[ii]:
                continue
            lat_i, lon_i = sc[ii]
            for jj in range(ii + 1, n):
                if sc[jj, 0] - lat_i > 0.01:
                    break
                if not keep_sorted[jj]:
                    continue
                dlat = sc[jj, 0] - lat_i
                dlon = sc[jj, 1] - lon_i
                # Fast approximate check before full haversine
                if abs(dlat) > 0.0045 or abs(dlon) > 0.006:
                    continue
                from math import asin, cos, radians, sin, sqrt
                r = 6371.0
                lat1, lat2 = radians(lat_i), radians(sc[jj, 0])
                a = sin(dlat / 2 * np.pi / 180)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2 * np.pi / 180)**2
                if 2 * r * asin(sqrt(a)) <= 0.5:
                    keep_sorted[jj] = False
        inv = np.argsort(sort_idx)
        keep = keep_sorted[inv]

    n_removed = int((~keep).sum())
    return df[keep].reset_index(drop=True), n_removed


def _ensure_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for col in cols:
        if col not in df.columns:
            df[col] = None
    return df


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_positivos() -> pd.DataFrame:
    print("\n[1/5] Cargando positivos (label=1)...")
    frames = []
    sources = [
        "data/gaia_incendios_v2_gt.csv",
        "data/conaf_biobio_2023_2024_gt.csv",
    ]
    for path in sources:
        if not os.path.exists(path):
            print(f"  {path}: no encontrado, omitiendo")
            continue
        df = pd.read_csv(path, encoding="utf-8-sig")
        df["label"] = pd.to_numeric(df.get("label", pd.Series(dtype=float)), errors="coerce")
        pos = df[df["label"] == 1].copy()
        print(f"  {path}: {len(pos)} positivos")
        frames.append(pos)

    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLS)
    combined = pd.concat(frames, ignore_index=True)
    combined["region"] = combined.get("region", pd.Series(dtype=str)).apply(normalize_region)
    combined["mask_type"] = "synthetic_dnbr"
    combined["polygon_id"] = None
    return combined


def load_fire_scars() -> pd.DataFrame:
    """Source A: Landscape Fire Scars GeoJSON → real polygon masks."""
    path = "data/fire_scars_segmentation_v3.geojson"
    print("\n[2/5] Cargando Landscape Fire Scars (Source A)...")
    if not os.path.exists(path):
        print(f"  {path}: no encontrado - Source A vacio")
        return pd.DataFrame(columns=OUTPUT_COLS)

    with open(path, "r", encoding="utf-8") as fh:
        gj = json.load(fh)

    features = gj.get("features", [])
    print(f"  {len(features)} polígonos en archivo")
    rows = []

    for feat in features:
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})

        # Centroid from polygon coords
        lat, lon = None, None
        if geom:
            gtype = geom.get("type", "")
            raw = geom.get("coordinates", [])
            flat: list = []
            if gtype == "Polygon":
                for ring in raw:
                    flat.extend(ring)
            elif gtype == "MultiPolygon":
                for poly in raw:
                    for ring in poly:
                        flat.extend(ring)
            if flat:
                arr = np.array(flat, dtype=float)
                lon = float(np.mean(arr[:, 0]))
                lat = float(np.mean(arr[:, 1]))

        fecha_raw = (
            props.get("date") or props.get("fecha") or props.get("fecha_inicio")
            or props.get("acq_date") or props.get("start_date") or props.get("fire_date")
            or props.get("FECHA") or props.get("DATE") or props.get("ignition_date")
        )
        fecha = parse_fecha(fecha_raw)

        polygon_id = str(
            props.get("scar_id") or props.get("id") or props.get("ID")
            or props.get("FID") or props.get("OBJECTID") or props.get("gid") or ""
        ).strip() or None

        superficie = pd.to_numeric(
            props.get("area_ha") or props.get("superficie_ha") or props.get("burned_area_ha")
            or props.get("area") or props.get("superficie"),
            errors="coerce",
        )
        region = normalize_region(
            props.get("region") or props.get("REGION") or props.get("nom_region")
            or props.get("region_name") or ""
        )
        causa = props.get("causa") or props.get("CAUSA") or "no intencional"
        temporada = props.get("temporada") or assign_temporada(fecha)

        rows.append({
            "lat": lat, "lon": lon,
            "fecha_inicio": fecha,
            "label": 0,
            "region": region, "causa": causa,
            "superficie_ha": superficie,
            "mask_type": "real_polygon",
            "polygon_id": polygon_id,
            "temporada": temporada,
        })

    df = pd.DataFrame(rows)
    print(f"  Source A cargado: {len(df)} filas")
    return df


def load_conaf_no_intencionales() -> pd.DataFrame:
    """Source B: CONAF no-intentional fires for synthetic-mask negatives."""
    print("\n[3/5] Cargando negativos CONAF no intencionales (Source B)...")
    frames = []
    sources = [
        "data/gaia_incendios_v2_gt.csv",
        "data/conaf_2014_2019_nacional.csv",
    ]
    for path in sources:
        if not os.path.exists(path):
            print(f"  {path}: no encontrado, omitiendo")
            continue
        df = pd.read_csv(path, encoding="utf-8-sig")
        if "label" in df.columns:
            df["label"] = pd.to_numeric(df["label"], errors="coerce")
            neg = df[df["label"] == 0].copy()
        else:
            # Infer label from cause column
            causa_col = next(
                (c for c in df.columns if "causa" in c.lower()), None
            )
            df["label"] = df[causa_col].apply(classify_causa) if causa_col else 0
            neg = df[df["label"] == 0].copy()

        neg["region"] = neg.get("region", pd.Series(dtype=str)).apply(normalize_region)
        print(f"  {path}: {len(neg)} no intencionales")
        frames.append(neg)

    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLS)
    combined = pd.concat(frames, ignore_index=True)
    combined["mask_type"] = "synthetic_dnbr"
    combined["polygon_id"] = None
    return combined


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(df: pd.DataFrame, tag: str) -> tuple[pd.DataFrame, dict[str, int]]:
    stats: dict[str, int] = {"bbox": 0, "fecha": 0, "area": 0}
    if df.empty:
        return df, stats

    df = df.copy()
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["superficie_ha"] = pd.to_numeric(df["superficie_ha"], errors="coerce")
    df["fecha_inicio"] = df["fecha_inicio"].apply(
        lambda x: parse_fecha(x) if pd.notna(x) else None
    )

    bbox_mask = (
        df["lat"].between(CHILE_BBOX["lat_min"], CHILE_BBOX["lat_max"])
        & df["lon"].between(CHILE_BBOX["lon_min"], CHILE_BBOX["lon_max"])
    )
    stats["bbox"] = int((~bbox_mask).sum())
    df = df[bbox_mask]

    fecha_mask = df["fecha_inicio"].notna()
    stats["fecha"] = int((~fecha_mask).sum())
    df = df[fecha_mask]

    area_mask = df["superficie_ha"] >= MIN_SUPERFICIE
    stats["area"] = int((~area_mask).sum())
    df = df[area_mask]

    print(f"  [{tag}] {stats['bbox']} bbox | {stats['fecha']} fecha | {stats['area']} area -> {len(df)} validos")
    return df.reset_index(drop=True), stats


# ---------------------------------------------------------------------------
# Stratified sample by two columns
# ---------------------------------------------------------------------------

def stratified_sample(df: pd.DataFrame, n: int, cols: list[str]) -> pd.DataFrame:
    if len(df) <= n:
        return df.copy()
    df = df.copy()
    strata = df[cols].fillna("__NA__").astype(str).agg("-".join, axis=1)
    df["_strata"] = strata
    counts = strata.value_counts()
    proportional = (counts / counts.sum() * n).apply(lambda x: max(1, round(x)))
    parts = []
    for s, target in proportional.items():
        grp = df[df["_strata"] == s]
        parts.append(grp.sample(min(int(target), len(grp)), random_state=RANDOM_STATE))
    result = pd.concat(parts, ignore_index=True).drop(columns="_strata")
    # Trim or top-up to exact n
    if len(result) > n:
        result = result.sample(n, random_state=RANDOM_STATE)
    elif len(result) < n:
        remaining = df[~df.index.isin(result.index)].drop(columns="_strata")
        need = min(n - len(result), len(remaining))
        if need > 0:
            result = pd.concat(
                [result, remaining.sample(need, random_state=RANDOM_STATE)],
                ignore_index=True,
            )
    return result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs("data", exist_ok=True)

    # ── Load ──────────────────────────────────────────────────────────────────
    pos_raw = _ensure_cols(load_positivos(), OUTPUT_COLS)
    neg_a_raw = _ensure_cols(load_fire_scars(), OUTPUT_COLS)
    neg_b_raw = _ensure_cols(load_conaf_no_intencionales(), OUTPUT_COLS)

    # ── Validate ──────────────────────────────────────────────────────────────
    print("\n[4/5] Validando...")
    pos_v, s_pos = validate(pos_raw, "positivos")
    neg_a_v, s_na = validate(neg_a_raw, "neg_real")
    neg_b_v, s_nb = validate(neg_b_raw, "neg_synth")

    total_discards = {
        k: s_pos[k] + s_na[k] + s_nb[k]
        for k in ("bbox", "fecha", "area")
    }

    # ── Global deduplication (priority: pos → neg_real → neg_synth) ───────────
    print("\n  Deduplicando globalmente (500 m)...")

    # Assign priority order so first-occurrence wins correctly
    pos_v["_pri"] = 0
    neg_a_v["_pri"] = 1
    neg_b_v["_pri"] = 2

    combined_all = pd.concat(
        [pos_v, neg_a_v, neg_b_v], ignore_index=True
    )
    combined_dedup, n_dupes = deduplicate_500m(combined_all)
    total_discards["dupes"] = n_dupes
    combined_dedup = combined_dedup.drop(columns="_pri", errors="ignore")

    # ── Re-segregate after global dedup ───────────────────────────────────────
    pos_dedup = combined_dedup[combined_dedup["label"] == 1].copy()
    neg_real_dedup = combined_dedup[
        (combined_dedup["label"] == 0) & (combined_dedup["mask_type"] == "real_polygon")
    ].copy()
    neg_synth_dedup = combined_dedup[
        (combined_dedup["label"] == 0) & (combined_dedup["mask_type"] == "synthetic_dnbr")
    ].copy()

    # ── Sample to targets ──────────────────────────────────────────────────────
    print("\n[5/5] Muestreando...")

    pos_final = stratified_sample(pos_dedup, N_POS_TARGET, ["region", "temporada"])

    # Negatives: Source A first (all available), Source B fills remainder
    neg_real_final = neg_real_dedup.reset_index(drop=True)
    n_synth_needed = max(0, N_NEG_TARGET - len(neg_real_final))
    neg_synth_final = (
        neg_synth_dedup.sample(
            min(n_synth_needed, len(neg_synth_dedup)), random_state=RANDOM_STATE
        )
        if not neg_synth_dedup.empty and n_synth_needed > 0
        else pd.DataFrame(columns=OUTPUT_COLS)
    )

    # ── Combine final dataset ──────────────────────────────────────────────────
    dataset = pd.concat(
        [pos_final, neg_real_final, neg_synth_final], ignore_index=True
    )

    # Fill missing temporada
    missing_t = dataset["temporada"].isna()
    if missing_t.any():
        dataset.loc[missing_t, "temporada"] = (
            dataset.loc[missing_t, "fecha_inicio"].apply(assign_temporada)
        )

    # ── Train / val split (stratified by label) ────────────────────────────────
    from sklearn.model_selection import train_test_split

    try:
        train_idx, val_idx = train_test_split(
            dataset.index,
            test_size=0.2,
            random_state=RANDOM_STATE,
            stratify=dataset["label"],
        )
        dataset["split"] = "val"
        dataset.loc[train_idx, "split"] = "train"
    except Exception:
        dataset = dataset.sample(frac=1, random_state=RANDOM_STATE).reset_index(drop=True)
        n_train = int(len(dataset) * 0.8)
        dataset["split"] = "val"
        dataset.iloc[:n_train, dataset.columns.get_loc("split")] = "train"

    # ── Report ─────────────────────────────────────────────────────────────────
    pos = dataset[dataset["label"] == 1]
    neg = dataset[dataset["label"] == 0]
    pos_real_cnt = int((pos["mask_type"] == "real_polygon").sum())
    pos_synth_cnt = int((pos["mask_type"] == "synthetic_dnbr").sum())
    neg_real_cnt = int((neg["mask_type"] == "real_polygon").sum())
    neg_synth_cnt = int((neg["mask_type"] == "synthetic_dnbr").sum())
    ratio = len(neg) / max(len(pos), 1)
    n_train = int((dataset["split"] == "train").sum())
    n_val = int((dataset["split"] == "val").sum())

    report = (
        "\n=== Dataset Gaia Incendios v0.3 ===\n"
        "Positivos (label=1):\n"
        f"  Con mascara real:      {pos_real_cnt}\n"
        f"  Con mascara sintetica: {pos_synth_cnt}\n"
        f"  Total:                 {len(pos)}\n"
        "\nNegativos (label=0):\n"
        f"  Con mascara real:      {neg_real_cnt}  (Landscape Fire Scars)\n"
        f"  Con mascara sintetica: {neg_synth_cnt}  (CONAF no intencionales)\n"
        f"  Total:                 {len(neg)}\n"
        f"\nRatio:                   1:{ratio:.0f}\n"
        f"Total dataset:           {len(dataset)}\n"
        f"Split train:             {n_train}\n"
        f"Split val:               {n_val}\n"
        f"\nDescartados por bbox:    {total_discards['bbox']}\n"
        f"Descartados por fecha:   {total_discards['fecha']}\n"
        f"Descartados por area:    {total_discards['area']}\n"
        f"Descartados duplicados:  {total_discards['dupes']}\n"
    )
    print(report)

    out_path = "data/gaia_incendios_v3_gt.csv"
    dataset[OUTPUT_COLS].to_csv(out_path, index=False, encoding="utf-8")
    print(f"Guardado en: {out_path}")


if __name__ == "__main__":
    main()
