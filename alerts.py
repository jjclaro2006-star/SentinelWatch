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

_CHIP_CACHE_S1S2 = Path("cache") / "chips_s1s2"


def _load_chip_s1s2(polygon_id: str) -> "np.ndarray | None":
    """Returns a cached [H, W, 6] chip from cache/chips_s1s2/, or None.

    Ignores any cached file that does not have exactly 6 bands so that stale
    4-band chips never reach the classifier.
    """
    path = _CHIP_CACHE_S1S2 / f"{polygon_id}.npy"
    if not path.exists():
        return None
    chip = np.load(path)
    if chip.ndim != 3 or chip.shape[-1] != 6:
        return None
    return chip


def _save_chip_s1s2(polygon_id: str, chip: np.ndarray) -> None:
    """Persists a [H, W, 6] chip to cache/chips_s1s2/{polygon_id}.npy."""
    _CHIP_CACHE_S1S2.mkdir(parents=True, exist_ok=True)
    np.save(_CHIP_CACHE_S1S2 / f"{polygon_id}.npy", chip)


def build_alerts(
    gdf: gpd.GeoDataFrame,
    detection_date: date | None = None,
    classifier: "SentinelClassifier | None" = None,
    sentinel2_image: "ee.Image | None" = None,
    sentinel1_image: "ee.Image | None" = None,
    classified_ids: "set[str] | None" = None,
    existing_by_id: "dict[str, dict] | None" = None,
) -> list[dict]:
    """Converts a loss GeoDataFrame into a list of alert dicts.

    Classification flow (when classifier is provided):
    1. If polygon_id is in classified_ids → carry forward existing classification.
    2. Load chip from cache/chips_s1s2/{polygon_id}.npy (must be 6-band).
       If absent or < 6 bands, fall back to a live sampleRectangle download
       (requires sentinel2_image; fused with sentinel1_image when provided) and
       save the result to cache/chips_s1s2/ for future runs.
    3. Run SentinelClassifier.predecir() on a [H, W, 6] array and verify legality.
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
                chip = _load_chip_s1s2(pid)
                if chip is None and sentinel2_image is not None:
                    import ee
                    from gee_client import extract_chip
                    # Fuse S2 (B4/B3/B2/B8) with S1 (VV/VH) when available.
                    classification_image = (
                        sentinel2_image.addBands(sentinel1_image)
                        if sentinel1_image is not None
                        else sentinel2_image
                    )
                    n_bands = 6 if sentinel1_image is not None else 4
                    chip = extract_chip(
                        classification_image,
                        ee.Geometry.Point([lon, lat]),
                        n_bands=n_bands,
                    )
                    if chip is not None and chip.shape[-1] == 6:
                        _save_chip_s1s2(pid, chip)

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
