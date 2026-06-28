"""
Download additional CONAF wildfire data from IDEMINAGRI ArcGIS FeatureServer
for Gaia Incendios v0.2 training — seasons 2020-2021, 2021-2022, 2022-2023.
Filters to Biobío region and classifies intentional vs non-intentional.
"""

import os
import requests
import pandas as pd
from pyproj import Transformer

BASE_URLS = {
    "2020-2021": "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/INCENDIOS_MINIS_INSTI/FeatureServer/46/query",
    "2021-2022": "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/INCENDIOS_MINIS_INSTI/FeatureServer/47/query",
    "2022-2023": "https://esri.ciren.cl/server/rest/services/IDEMINAGRI/INCENDIOS_MINIS_INSTI/FeatureServer/48/query",
}

NO_INTENCIONAL_KEYWORDS = [
    "accidente", "negligencia", "faena", "quema",
    "transito", "ferroviaria", "natural", "recreativa",
    "electrica", "pecuaria", "forestal",
]
INTENCIONAL_KEYWORDS = ["intencional", "ataque"]
EXCLUDE_KEYWORDS = ["desconocida", "desconocido"]

UTM19S_TO_WGS84 = Transformer.from_crs("EPSG:32719", "EPSG:4326", always_xy=True)


def fetch_all_features(url: str) -> list[dict]:
    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "json",
        "resultOffset": 0,
        "resultRecordCount": 1000,
    }
    features = []
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
    causa_lower = causa.lower()
    if any(k in causa_lower for k in EXCLUDE_KEYWORDS):
        return None
    if any(k in causa_lower for k in INTENCIONAL_KEYWORDS):
        return 1
    if any(k in causa_lower for k in NO_INTENCIONAL_KEYWORDS):
        return 0
    return None


def is_biobio(region_val) -> bool:
    if not region_val:
        return False
    r = str(region_val).lower()
    return "bío" in r or "bio" in r or "biobío" in r or "biobio" in r or r == "08"


def process_season(season: str, url: str, first_season: bool) -> pd.DataFrame:
    print(f"\nDescargando temporada {season}...")
    features = fetch_all_features(url)
    print(f"  {len(features)} registros descargados")

    rows = []
    for feat in features:
        attrs = feat.get("attributes", {})

        # Resolve field names flexibly
        causa_gene = attrs.get("causa_gene") or attrs.get("CAUSA_GENE") or ""
        causa_espe = attrs.get("causa_espe") or attrs.get("CAUSA_ESPE") or ""
        causa = f"{causa_gene} {causa_espe}".strip() if causa_espe else causa_gene

        fecha_raw = (
            attrs.get("fh_inicio")
            or attrs.get("inicio_in")
            or attrs.get("FH_INICIO")
            or attrs.get("INICIO_IN")
        )
        if isinstance(fecha_raw, (int, float)) and fecha_raw:
            fecha_inicio = pd.to_datetime(fecha_raw, unit="ms", errors="coerce")
            fecha_inicio = fecha_inicio.strftime("%Y-%m-%d") if not pd.isna(fecha_inicio) else str(fecha_raw)
        else:
            fecha_inicio = str(fecha_raw) if fecha_raw else None

        superficie = attrs.get("superficie") or attrs.get("SUPERFICIE")
        region = attrs.get("region") or attrs.get("REGION") or attrs.get("nom_region") or attrs.get("NOM_REGION")
        comuna = attrs.get("comuna") or attrs.get("COMUNA") or attrs.get("nom_comuna") or attrs.get("NOM_COMUNA")

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
            "_causa_gene_raw": causa_gene,
        })

    df = pd.DataFrame(rows)

    if first_season:
        print(f"\n=== Schema temporada {season} ===")
        print(f"Columnas: {list(pd.DataFrame([f['attributes'] for f in features[:1]]).columns)}")
        sample_attrs = pd.DataFrame([f["attributes"] for f in features[:3]])
        print(f"Primeras 3 filas:\n{sample_attrs.to_string()}\n")
        unique_causa = df["_causa_gene_raw"].dropna().unique().tolist()
        print(f"Valores únicos causa_gene: {unique_causa}\n")

    df = df[[is_biobio(r) for r in df["region"]]]
    df = df[df["label"].notna()].copy()
    df["label"] = df["label"].astype(int)
    df = df.drop(columns=["_causa_gene_raw"])

    return df


def main():
    os.makedirs("data", exist_ok=True)

    all_dfs = []
    first = True
    season_stats = []

    for season, url in BASE_URLS.items():
        df = process_season(season, url, first_season=first)
        first = False
        n_no_int = (df["label"] == 0).sum()
        n_int = (df["label"] == 1).sum()
        season_stats.append((season, n_no_int, n_int))
        all_dfs.append(df)

    combined = pd.concat(all_dfs, ignore_index=True)

    out_path = "data/conaf_additional_biobio.csv"
    cols = ["lat", "lon", "fecha_inicio", "causa", "label", "superficie_ha", "region", "comuna", "temporada"]
    combined[cols].to_csv(out_path, index=False)

    print("\n=== Dataset Adicional CONAF — Biobío ===")
    for season, n_no, n_in in season_stats:
        print(f"Temporada {season}:   {n_no:>4} no intencionales | {n_in:>4} intencionales")
    print("-" * 45)
    total_no = sum(s[1] for s in season_stats)
    total_in = sum(s[2] for s in season_stats)
    print(f"Total no intencionales: {total_no}")
    print(f"Total intencionales:    {total_in}")
    print(f"Total combinado:        {total_no + total_in}")
    print(f"\nGuardado en: {out_path}")


if __name__ == "__main__":
    main()
