"""
Build ground truth CSV for Gaia Incendios v0.2.
Steps:
  1. Download negatives from CONAF FeatureServer (all seasons 2014-2024, 5 regions)
  2. Load existing Biobío data
  3. Validate coordinates and superficie_ha >= 0.1
  4. Build balanced dataset (496 positives stratified, 4960 negatives random → 1:10)
  5. Save data/gaia_incendios_v2_gt.csv
"""

import os
import requests
import pandas as pd
from pyproj import Transformer

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Layers 40-48 map to seasons 2014-2015 through 2022-2023; layer 43 (2017-2018) is skipped
LAYERS = {
    "2014-2015": 40,
    "2015-2016": 41,
    "2016-2017": 42,
    # 43 → 2017-2018 skipped (no data)
    "2018-2019": 44,
    "2019-2020": 45,
    "2020-2021": 46,
    "2021-2022": 47,
    "2022-2023": 48,
}
BASE = "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/INCENDIOS_MINIS_INSTI/FeatureServer/{layer}/query"

NEG_REGIONS = {
    "Biobio":    lambda r: "bio" in r.lower(),
    "Maule":     lambda r: "maule" in r.lower(),
    "OHiggins":  lambda r: "higgins" in r.lower(),
    "Araucania": lambda r: "araucani" in r.lower(),
    "LosRios":   lambda r: "r" in r.lower() and "os r" in r.lower(),
}

NO_INTENCIONAL_KEYWORDS = [
    "accidente", "negligencia", "faena", "quema",
    "transito", "ferroviaria", "natural", "recreativa",
    "electrica", "pecuaria", "forestal",
]
INTENCIONAL_KEYWORDS = ["intencional", "ataque"]
EXCLUDE_KEYWORDS = ["desconocida", "desconocido"]

CHILE_BBOX = dict(lat_min=-56, lat_max=-17, lon_min=-76, lon_max=-66)
MIN_SUPERFICIE = 0.1

UTM19S_TO_WGS84 = Transformer.from_crs("EPSG:32719", "EPSG:4326", always_xy=True)


# ---------------------------------------------------------------------------
# Helpers (reused from download_conaf_additional.py)
# ---------------------------------------------------------------------------
def fetch_all_features(url: str) -> list[dict]:
    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "json",
        "resultOffset": 0,
        "resultRecordCount": 1000,
    }
    features: list[dict] = []
    while True:
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("features", [])
        features.extend(batch)
        if len(batch) < 1000:
            break
        params["resultOffset"] += 1000
    return features


def extract_coords(feature: dict) -> tuple[float | None, float | None]:
    attrs = feature.get("attributes", {})
    utm_e = attrs.get("utm_e") or attrs.get("UTM_E") or attrs.get("UTME")
    utm_n = attrs.get("utm_n") or attrs.get("UTM_N") or attrs.get("UTMN")
    if utm_e and utm_n:
        try:
            lon, lat = UTM19S_TO_WGS84.transform(float(utm_e), float(utm_n))
            return lat, lon
        except Exception:
            pass
    geom = feature.get("geometry")
    if geom and "x" in geom and "y" in geom:
        try:
            lon, lat = UTM19S_TO_WGS84.transform(float(geom["x"]), float(geom["y"]))
            return lat, lon
        except Exception:
            pass
    return None, None


def classify_label(causa: str) -> int | None:
    if not causa:
        return None
    c = causa.lower()
    if any(k in c for k in EXCLUDE_KEYWORDS):
        return None
    if any(k in c for k in INTENCIONAL_KEYWORDS):
        return 1
    if any(k in c for k in NO_INTENCIONAL_KEYWORDS):
        return 0
    return None


def features_to_df(features: list[dict], season: str) -> pd.DataFrame:
    rows = []
    for feat in features:
        attrs = feat.get("attributes", {})
        causa_gene = attrs.get("causa_gene") or attrs.get("CAUSA_GENE") or ""
        causa_espe = attrs.get("causa_espe") or attrs.get("CAUSA_ESPE") or ""
        causa = f"{causa_gene} {causa_espe}".strip() if causa_espe else causa_gene

        fecha_raw = (
            attrs.get("fh_inicio") or attrs.get("inicio_in")
            or attrs.get("FH_INICIO") or attrs.get("INICIO_IN")
        )
        if isinstance(fecha_raw, (int, float)) and fecha_raw:
            ts = pd.to_datetime(fecha_raw, unit="ms", errors="coerce")
            fecha_inicio = ts.strftime("%Y-%m-%d") if not pd.isna(ts) else str(fecha_raw)
        else:
            fecha_inicio = str(fecha_raw) if fecha_raw else None

        superficie = attrs.get("superficie") or attrs.get("SUPERFICIE")
        region = (
            attrs.get("region") or attrs.get("REGION")
            or attrs.get("nom_region") or attrs.get("NOM_REGION")
        )
        comuna = (
            attrs.get("comuna") or attrs.get("COMUNA")
            or attrs.get("nom_comuna") or attrs.get("NOM_COMUNA")
        )
        lat, lon = extract_coords(feat)
        label = classify_label(causa)

        rows.append({
            "lat": lat,
            "lon": lon,
            "fecha_inicio": fecha_inicio,
            "causa": causa.strip() or None,
            "label": label,
            "superficie_ha": superficie,
            "region": region,
            "comuna": comuna,
            "temporada": season,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Step 1 — Download negatives for all 5 regions, all seasons 2014-2023
# ---------------------------------------------------------------------------
def download_extra_negatives() -> pd.DataFrame:
    print("\n=== STEP 1: Descargando negativos (5 regiones x 8 temporadas) ===")
    all_dfs: list[pd.DataFrame] = []

    for season, layer in LAYERS.items():
        url = BASE.format(layer=layer)
        print(f"  Temporada {season} (layer {layer})...", end=" ", flush=True)
        try:
            features = fetch_all_features(url)
        except Exception as e:
            print(f"ERROR: {e}")
            continue
        print(f"{len(features)} registros")
        df = features_to_df(features, season)
        df = df[df["label"] == 0].copy()

        region_frames: list[pd.DataFrame] = []
        for reg_name, matcher in NEG_REGIONS.items():
            mask = df["region"].apply(lambda r: matcher(str(r)) if r else False)
            sub = df[mask].copy()
            sub["region"] = reg_name
            if len(sub):
                region_frames.append(sub)

        if region_frames:
            all_dfs.append(pd.concat(region_frames, ignore_index=True))

    result = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    print(f"  Total negativos descargados: {len(result)}")
    return result


# ---------------------------------------------------------------------------
# Step 2 — Load existing Biobío data
# ---------------------------------------------------------------------------
def load_existing() -> pd.DataFrame:
    print("\n=== STEP 2: Cargando datos existentes ===")
    frames: list[pd.DataFrame] = []
    COLS = ["lat", "lon", "fecha_inicio", "causa", "label", "superficie_ha", "region", "comuna", "temporada"]

    for path in ["data/conaf_biobio_2023_2024_gt.csv", "data/conaf_additional_biobio.csv"]:
        if not os.path.exists(path):
            print(f"  {path}: no encontrado, omitiendo")
            continue
        df = pd.read_csv(path)
        # Normalise columns — keep only what we need, fill missing
        for col in COLS:
            if col not in df.columns:
                df[col] = None
        df = df[COLS].copy()
        if "label" in df.columns:
            df["label"] = pd.to_numeric(df["label"], errors="coerce")
        print(f"  {path}: {len(df)} filas  |  positivos={int((df['label']==1).sum())}  negativos={int((df['label']==0).sum())}")
        frames.append(df)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLS)


# ---------------------------------------------------------------------------
# Step 4 — Coordinate / surface validation
# ---------------------------------------------------------------------------
def validate(df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    n_before = len(df)

    bbox_mask = (
        df["lat"].between(CHILE_BBOX["lat_min"], CHILE_BBOX["lat_max"])
        & df["lon"].between(CHILE_BBOX["lon_min"], CHILE_BBOX["lon_max"])
    )
    n_bbox = (~bbox_mask).sum()

    sup = pd.to_numeric(df["superficie_ha"], errors="coerce")
    sup_mask = sup >= MIN_SUPERFICIE
    n_sup = (~sup_mask).sum()

    df = df[bbox_mask & sup_mask].copy()
    return df, int(n_bbox), int(n_sup)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    os.makedirs("data", exist_ok=True)

    # --- Step 1 ---
    extra_neg = download_extra_negatives()

    # --- Step 2 ---
    existing = load_existing()

    # Combine all available data
    COLS = ["lat", "lon", "fecha_inicio", "causa", "label", "superficie_ha", "region", "comuna", "temporada"]
    all_frames = [existing]
    if not extra_neg.empty:
        for col in COLS:
            if col not in extra_neg.columns:
                extra_neg[col] = None
        all_frames.append(extra_neg[COLS])

    df = pd.concat(all_frames, ignore_index=True)
    df["label"] = pd.to_numeric(df["label"], errors="coerce")
    df = df[df["label"].notna()].copy()
    df["label"] = df["label"].astype(int)

    # --- Step 4 — Validate (before sampling) ---
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df, n_bbox, n_sup = validate(df)

    print(f"\n=== STEP 3: Dataset combinado pre-balance (post-validacion) ===")
    print(f"  Positivos totales: {(df['label']==1).sum()}")
    print(f"  Negativos totales: {(df['label']==0).sum()}")

    # --- Step 3 — Balanced sampling ---
    positivos_all = df[df["label"] == 1]
    negativos_all = df[df["label"] == 0]

    N_POS_TARGET = 496
    N_NEG_TARGET = 4960

    # Stratified by causa — guarantee at least 1 per group
    positivos_sampled = (
        positivos_all
        .groupby("causa", group_keys=False)
        .apply(
            lambda x: x.sample(
                min(len(x), max(1, int(N_POS_TARGET * len(x) / max(len(positivos_all), 1)))),
                random_state=42,
            )
        )
        .head(N_POS_TARGET)
    )

    negativos_sampled = negativos_all.sample(
        min(N_NEG_TARGET, len(negativos_all)), random_state=42
    )

    balanced = pd.concat([positivos_sampled, negativos_sampled], ignore_index=True)

    # --- Step 5 — Report ---
    pos = balanced[balanced["label"] == 1]
    neg = balanced[balanced["label"] == 0]
    ratio = len(neg) / max(len(pos), 1)

    print("\n=== Dataset Gaia Incendios v0.2 ===")
    print(f"Positivos:         {len(pos)}")
    top5 = pos["causa"].value_counts().head(5)
    print("  Por tipo:")
    for causa, cnt in top5.items():
        print(f"    [{cnt:>3}] {str(causa)[:70]}")

    print(f"Negativos:         {len(neg)}")
    reg_counts = neg["region"].value_counts()
    biobio_n  = reg_counts.get("Biobio", 0) + reg_counts.get("Biobio", 0)
    maule_n   = reg_counts.get("Maule", 0)
    ohig_n    = reg_counts.get("OHiggins", 0)
    arauc_n   = reg_counts.get("Araucania", 0)
    rios_n    = reg_counts.get("LosRios", 0)
    print(f"  Por region:      Biobio: {biobio_n} | Maule: {maule_n} | OHiggins: {ohig_n} | Araucania: {arauc_n} | LosRios: {rios_n}")

    print("  Por temporada:")
    for temp, cnt in neg["temporada"].value_counts().sort_index().items():
        print(f"    {temp}: {cnt}")

    print(f"Total:             {len(balanced)}")
    print(f"Ratio:             1:{ratio:.1f}")
    print(f"Coords invalidas:  {n_bbox} descartadas por bbox")
    print(f"Superficie minima: {n_sup} descartadas por <0.1ha")

    out_path = "data/gaia_incendios_v2_gt.csv"
    balanced[COLS].to_csv(out_path, index=False)
    print(f"\nGuardado en: {out_path}")


if __name__ == "__main__":
    main()
