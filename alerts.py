import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import numpy as np

from chip_cache import make_polygon_id
from config import OUTPUT_DIR

if TYPE_CHECKING:
    import ee
    from sentinel_classifier import SentinelClassifier

_CHIP_CACHE = Path("cache") / "chips"


def _load_tif_chip(severity: str, idx: int) -> "np.ndarray | None":
    """Reads cache/chips/{severity}/alerta_{idx:04d}.tif as a float32 [H,W,C] array."""
    path = _CHIP_CACHE / severity / f"alerta_{idx:04d}.tif"
    if not path.exists():
        return None
    import tifffile
    data = tifffile.imread(str(path))
    return np.clip(data.astype(np.float32) / 10_000.0, 0.0, 1.0)


def build_alerts(
    gdf: gpd.GeoDataFrame,
    detection_date: date | None = None,
    classifier: "SentinelClassifier | None" = None,
    sentinel2_image: "ee.Image | None" = None,
    classified_ids: "set[str] | None" = None,
    existing_by_id: "dict[str, dict] | None" = None,
) -> list[dict]:
    """Converts a loss GeoDataFrame into a list of alert dicts.

    Classification flow (when classifier is provided):
    1. If polygon_id is in classified_ids → carry forward existing classification.
    2. Load chip from cache/chips/{severity}/alerta_{idx:04d}.tif.
       If the TIF is absent, fall back to a live sampleRectangle download
       (requires sentinel2_image).
    3. Run SentinelClassifier.predecir() and verify legality.
    """
    if detection_date is None:
        detection_date = date.today()

    date_str        = detection_date.isoformat()
    classify        = classifier is not None
    classified_ids  = classified_ids or set()
    existing_by_id  = existing_by_id or {}
    alerts          = []

    for idx, (_, row) in enumerate(gdf.iterrows()):
        centroid = row.geometry.centroid
        lat      = round(centroid.y, 6)
        lon      = round(centroid.x, 6)
        pid      = make_polygon_id(lat, lon)
        severity = row["severity"]

        alert: dict = {
            "id":             pid,
            "lat":            lat,
            "lon":            lon,
            "detection_date": date_str,
            "severity":       severity,
            "ndvi_change":    round(float(row["ndvi_change"]), 4),
            "area_ha":        round(float(row["area_ha"]), 2),
            "geometry":       row.geometry.__geo_interface__,
        }

        if classify:
            if pid in classified_ids:
                src = existing_by_id[pid]
                alert["actividad"] = src["actividad"]
                alert["confianza"] = src["confianza"]
                alert["veredicto"] = src["veredicto"]
            else:
                chip = _load_tif_chip(severity, idx)
                if chip is None and sentinel2_image is not None:
                    import ee
                    from gee_client import extract_chip
                    chip = extract_chip(sentinel2_image, ee.Geometry.Point([lon, lat]))

                if chip is not None:
                    resultado = classifier.predecir(chip, coordenadas=(lat, lon))
                    alert["actividad"] = resultado["actividad"]
                    alert["confianza"] = resultado["confianza"]
                    alert["veredicto"] = resultado["veredicto"]

        alerts.append(alert)

    return alerts


def save_geojson(alerts: list[dict], filepath: Path | None = None) -> Path:
    """Writes alerts to a GeoJSON FeatureCollection file.

    Args:
        alerts:   List of alert dicts from build_alerts().
        filepath: Destination path. Defaults to outputs/alerts_YYYYMMDD.geojson.

    Returns:
        The path where the file was written.
    """
    if filepath is None:
        filename = f"alerts_{date.today().strftime('%Y%m%d')}.geojson"
        filepath = OUTPUT_DIR / filename

    features = [
        {
            "type": "Feature",
            "geometry": alert["geometry"],
            "properties": {k: v for k, v in alert.items() if k != "geometry"},
        }
        for alert in alerts
    ]

    geojson = {"type": "FeatureCollection", "features": features}
    filepath.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
    return filepath


if __name__ == "__main__":
    from auth import authenticate_and_initialize
    from gee_client import aoi_geometry, get_sentinel2_collection, get_median_ndvi
    from ndvi import detect_loss, vectorize_loss

    authenticate_and_initialize()

    aoi = aoi_geometry()
    col_base = get_sentinel2_collection(aoi, "2023-06-01", "2023-08-31")
    col_now  = get_sentinel2_collection(aoi, "2024-06-01", "2024-08-31")
    ndvi_base = get_median_ndvi(col_base, aoi)
    ndvi_now  = get_median_ndvi(col_now,  aoi)

    ndvi_diff, loss_mask = detect_loss(ndvi_base, ndvi_now)
    print("Vectorizing (this may take ~1-2 min)...")
    gdf = vectorize_loss(loss_mask, ndvi_diff, aoi)

    alerts = build_alerts(gdf)
    print(f"Alerts generated: {len(alerts)}")
    print("Sample:", json.dumps(alerts[0], indent=2) if alerts else "none")

    output_path = save_geojson(alerts)
    print(f"Saved: {output_path}")
