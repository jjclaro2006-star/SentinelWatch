"""
Agrupación de detecciones VIIRS en eventos de incendio — Biobío 2025.

Dos detecciones pertenecen al mismo evento si:
  - Distancia <= 2 km (haversine)
  - Diferencia temporal <= 72 horas

Estrategia:
  1. DBSCAN espacial con métrica haversine (eps = 2km) para agrupar vecinos cercanos.
  2. Dentro de cada cluster espacial, segunda pasada temporal: divide el cluster si
     hay brechas de más de 72h entre detecciones consecutivas (ordenadas por tiempo).

Uso: python scripts/cluster_events_2025.py
"""

import sys
from pathlib import Path
from datetime import timedelta

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = _ROOT / "data" / "validation" / "module_a_2025.geojson"
OUTPUT_PATH = _ROOT / "data" / "validation" / "module_a_2025_events.geojson"

_MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

SPATIAL_EPS_KM = 2.0       # radio DBSCAN en km (haversine)
TEMPORAL_GAP_HOURS = 72    # brecha máxima dentro del mismo evento


def _spatial_cluster(gdf: gpd.GeoDataFrame) -> np.ndarray:
    """Devuelve array de etiquetas espaciales DBSCAN (-1 = ruido → evento propio)."""
    coords_rad = np.radians(gdf[["latitude", "longitude"]].values)
    eps_rad = SPATIAL_EPS_KM / 6371.0  # radio terrestre medio en km

    labels = DBSCAN(
        eps=eps_rad,
        min_samples=1,   # cada punto solo forma un cluster válido
        algorithm="ball_tree",
        metric="haversine",
    ).fit_predict(coords_rad)

    return labels


def _split_by_time(sub_gdf: gpd.GeoDataFrame, base_event_id: int, gap_hours: int) -> pd.Series:
    """
    Dentro de un cluster espacial, divide en sub-eventos si la brecha temporal
    entre detecciones consecutivas supera gap_hours.
    Devuelve Serie con event_id asignado a cada índice.
    """
    sorted_idx = sub_gdf["acq_datetime"].sort_values().index
    sorted_times = sub_gdf.loc[sorted_idx, "acq_datetime"].reset_index(drop=True)

    event_ids = pd.Series(index=sorted_idx, dtype=int)
    current_id = base_event_id
    prev_time = sorted_times.iloc[0]
    event_ids.iloc[0] = current_id

    gap = timedelta(hours=gap_hours)
    for i in range(1, len(sorted_times)):
        if sorted_times.iloc[i] - prev_time > gap:
            current_id += 1
        event_ids.iloc[i] = current_id
        prev_time = sorted_times.iloc[i]

    return event_ids


def assign_events(gdf: gpd.GeoDataFrame) -> pd.Series:
    """
    Combina DBSCAN espacial + división temporal.
    Devuelve Serie 'event_id' alineada con el índice original del GDF.
    """
    spatial_labels = _spatial_cluster(gdf)
    gdf = gdf.copy()
    gdf["_spatial"] = spatial_labels

    event_col = pd.Series(index=gdf.index, dtype=int)
    next_event_id = 0

    for sp_label in sorted(gdf["_spatial"].unique()):
        cluster = gdf[gdf["_spatial"] == sp_label]
        if len(cluster) == 1:
            event_col.loc[cluster.index] = next_event_id
            next_event_id += 1
        else:
            ids = _split_by_time(cluster, next_event_id, TEMPORAL_GAP_HOURS)
            event_col.loc[ids.index] = ids.values
            next_event_id = int(ids.max()) + 1

    return event_col


# ---------------------------------------------------------------------------
# Construcción del GeoDataFrame de eventos
# ---------------------------------------------------------------------------

def build_events_gdf(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Agrega detecciones por event_id y construye un GeoDataFrame de eventos."""
    records = []

    for event_id, group in gdf.groupby("event_id"):
        times = pd.to_datetime(group["acq_datetime"], utc=True)
        start = times.min()
        end = times.max()
        duration_days = (end - start).total_seconds() / 86400.0

        centroid_lat = group.geometry.y.mean()
        centroid_lon = group.geometry.x.mean()

        frp_col = group["frp"] if "frp" in group.columns else pd.Series(dtype=float)
        max_frp = float(frp_col.max()) if not frp_col.isna().all() else float("nan")

        probable_fp = duration_days > 7.0

        records.append({
            "event_id": int(event_id),
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "duration_days": round(duration_days, 2),
            "detection_count": len(group),
            "centroid_lat": round(centroid_lat, 4),
            "centroid_lon": round(centroid_lon, 4),
            "max_frp": round(max_frp, 2) if not np.isnan(max_frp) else None,
            "probable_false_positive": probable_fp,
        })

    df = pd.DataFrame(records)
    from shapely.geometry import Point
    geometry = [Point(r["centroid_lon"], r["centroid_lat"]) for r in records]
    return gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")


# ---------------------------------------------------------------------------
# Resumen por consola
# ---------------------------------------------------------------------------

def _print_summary(gdf: gpd.GeoDataFrame, events_gdf: gpd.GeoDataFrame) -> None:
    n_det = len(gdf)
    n_events = len(events_gdf)

    # Mes de inicio de cada evento
    events_gdf = events_gdf.copy()
    events_gdf["start_month"] = pd.to_datetime(events_gdf["start_date"]).dt.month

    monthly = events_gdf.groupby("start_month").size()

    # Top 5 eventos más grandes
    top5 = events_gdf.nlargest(5, "detection_count")

    # Falsos positivos (> 7 días)
    fps = events_gdf[events_gdf["probable_false_positive"]]

    # Distribución por tamaño
    small = events_gdf[events_gdf["detection_count"].between(1, 3)]
    medium = events_gdf[events_gdf["detection_count"].between(4, 10)]
    large = events_gdf[events_gdf["detection_count"] > 10]

    sep = "-" * 41

    print(f"\n{'=' * 41}")
    print("=== Eventos de Incendio - Biobio 2025 ===")
    print(f"{'=' * 41}")
    print(f"Detecciones totales:           {n_det:>5}")
    print(f"Eventos unicos identificados:  {n_events:>5}")
    print(sep)
    print("Eventos por mes:")
    for month in range(1, 13):
        count = int(monthly.get(month, 0))
        nombre = _MESES_ES[month]
        print(f"  {nombre:<12} {count:>4}")
    print(sep)
    print("Top 5 eventos mas grandes:")
    for i, (_, row) in enumerate(top5.iterrows(), 1):
        print(
            f"  {i}. {row['start_date']} | "
            f"{row['centroid_lat']:.2f}, {row['centroid_lon']:.2f} | "
            f"{row['detection_count']} detecciones | "
            f"{row['duration_days']:.1f} dias activo"
        )
    print(sep)
    if fps.empty:
        print("Eventos probables falso positivo:  Ninguno")
    else:
        print(f"Eventos probables falso positivo ({len(fps)} evento(s) activos > 7 dias):")
        for _, row in fps.iterrows():
            print(
                f"  Coordenada: {row['centroid_lat']:.2f}, {row['centroid_lon']:.2f} | "
                f"{row['duration_days']:.1f} dias | "
                f"{row['detection_count']} detecciones"
            )
    print(sep)
    print("Distribucion por tamano:")
    pct = lambda n: f"{n / n_events * 100:.1f}%" if n_events > 0 else "0%"
    print(f"  Pequeno  (1-3 detecciones):  {len(small):>4} eventos  ({pct(len(small))})")
    print(f"  Mediano  (4-10 detecciones): {len(medium):>4} eventos  ({pct(len(medium))})")
    print(f"  Grande   (>10 detecciones):  {len(large):>4} eventos  ({pct(len(large))})")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Leyendo detecciones desde: {INPUT_PATH}")
    gdf = gpd.read_file(INPUT_PATH)

    gdf["acq_datetime"] = pd.to_datetime(gdf["acq_datetime"], utc=True, errors="coerce")
    gdf = gdf.dropna(subset=["acq_datetime"]).reset_index(drop=True)

    print(f"Detecciones cargadas: {len(gdf)}")
    print("Ejecutando clustering espaciotemporal (DBSCAN 2km + ventana 72h)...")


    gdf["event_id"] = assign_events(gdf)

    events_gdf = build_events_gdf(gdf)

    _print_summary(gdf, events_gdf)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    events_gdf.to_file(OUTPUT_PATH, driver="GeoJSON")
    print(f"Eventos guardados en: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
