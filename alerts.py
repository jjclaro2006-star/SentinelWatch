import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import numpy as np
from tqdm import tqdm

from chip_cache import make_polygon_id
from config import OUTPUT_DIR

if TYPE_CHECKING:
    import ee
    from sentinel_classifier import SentinelClassifier

_CHIP_CACHE_S1S2 = Path("cache") / "chips_s1s2"
_CHIP_CACHE_12B  = Path("cache") / "chips_s2_12b"


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


def _load_chip_12b(polygon_id: str) -> "np.ndarray | None":
    """Returns a cached [H, W, 12] chip from cache/chips_s2_12b/, or None."""
    path = _CHIP_CACHE_12B / f"{polygon_id}.npy"
    if not path.exists():
        return None
    chip = np.load(path)
    if chip.ndim != 3 or chip.shape[-1] != 12:
        return None
    return chip


def _save_chip_12b(polygon_id: str, chip: np.ndarray) -> None:
    """Persists a [H, W, 12] chip to cache/chips_s2_12b/{polygon_id}.npy."""
    _CHIP_CACHE_12B.mkdir(parents=True, exist_ok=True)
    np.save(_CHIP_CACHE_12B / f"{polygon_id}.npy", chip)


def _classify_alert(
    alert: dict,
    pid: str,
    lat: float,
    lon: float,
    classifier: "SentinelClassifier",
    classification_image: "ee.Image | None",
    chip_bands: int,
    classified_ids: set,
    existing_by_id: dict,
) -> dict:
    """Downloads a chip and runs inference for one alert. Called from threads.

    Each thread operates on its own alert dict and polygon_id, so there is no
    shared mutable state. GEE HTTP calls and PyTorch forward passes both release
    the GIL, making threads effective here despite the GIL.

    chip_bands controls which cache directory is used (6 = S2+S1, 12 = S2-only).

    Returns the alert dict, augmented with actividad/confianza/veredicto when
    classification succeeds.
    """
    if pid in classified_ids:
        src = existing_by_id[pid]
        alert["actividad"]    = src["actividad"]
        alert["confianza"]    = src["confianza"]
        alert["veredicto"]    = src["veredicto"]
        alert["legal_detail"] = src.get("legal_detail", "")
        return alert

    use_12b = chip_bands == 12
    chip = _load_chip_12b(pid) if use_12b else _load_chip_s1s2(pid)

    if chip is None and classification_image is not None:
        import ee
        centroid = ee.Geometry.Point([lon, lat])
        if use_12b:
            from gee_client import download_chip_12b
            chip = download_chip_12b(classification_image, centroid)
        else:
            from gee_client import extract_chip
            chip = extract_chip(classification_image, centroid, n_bands=chip_bands)
        if chip is not None and chip.shape[-1] == chip_bands:
            if use_12b:
                _save_chip_12b(pid, chip)
            else:
                _save_chip_s1s2(pid, chip)

    if chip is not None:
        resultado = classifier.predecir(chip, coordenadas=(lat, lon))
        alert["actividad"]    = resultado["actividad"]
        alert["confianza"]    = resultado["confianza"]
        alert["veredicto"]    = resultado["veredicto"]
        alert["legal_detail"] = resultado.get("legal_detail", "")

    return alert


def build_alerts(
    gdf: gpd.GeoDataFrame,
    detection_date: date | None = None,
    classifier: "SentinelClassifier | None" = None,
    sentinel2_image: "ee.Image | None" = None,
    sentinel1_image: "ee.Image | None" = None,
    classified_ids: "set[str] | None" = None,
    existing_by_id: "dict[str, dict] | None" = None,
    max_workers: int = 8,
) -> list[dict]:
    """Converts a loss GeoDataFrame into a list of alert dicts.

    Classification flow (when classifier is provided):
    1. If polygon_id is in classified_ids → carry forward existing classification.
    2. Load chip from cache/chips_s1s2/{polygon_id}.npy (must be 6-band).
       If absent or < 6 bands, fall back to a live sampleRectangle download
       (requires sentinel2_image; fused with sentinel1_image when provided) and
       save the result to cache/chips_s1s2/ for future runs.
    3. Run SentinelClassifier.predecir() on a [H, W, 6] array.

    Steps 2-3 are executed in parallel across max_workers threads. GEE downloads
    are I/O-bound and release the GIL; PyTorch inference also releases the GIL
    during its C++ forward pass, so both benefit from thread-level concurrency.

    Args:
        max_workers: Thread pool size for parallel chip download + inference.
                     Default 8 reduces ~8 h serial classification to <1 h for
                     ~11 k alerts with typical GEE latency of 2-3 s per chip.
    """
    if detection_date is None:
        detection_date = date.today()

    date_str       = detection_date.isoformat()
    classify       = classifier is not None
    classified_ids = classified_ids or set()
    existing_by_id = existing_by_id or {}

    # --- Build base alert dicts (fast, no I/O) ---
    rows: list[tuple[dict, str, float, float]] = []
    for _, row in gdf.iterrows():
        centroid = row.geometry.centroid
        lat      = round(centroid.y, 6)
        lon      = round(centroid.x, 6)
        pid      = make_polygon_id(lat, lon)
        alert: dict = {
            "id":             pid,
            "lat":            lat,
            "lon":            lon,
            "detection_date": date_str,
            "severity":       row["severity"],
            "ndvi_change":    round(float(row["ndvi_change"]), 4),
            "area_ha":        round(float(row["area_ha"]), 2),
            "geometry":       row.geometry.__geo_interface__,
        }
        rows.append((alert, pid, lat, lon))

    if not classify:
        return [alert for alert, *_ in rows]

    # Detect how many bands the classifier expects (6 for S2+S1, 12 for S2-only).
    chip_bands: int = getattr(classifier, "chip_bands", 6)

    # Pre-build classification image once — EE graph construction is not
    # thread-safe, so this must happen before the executor starts.
    classification_image: "ee.Image | None" = None
    if sentinel2_image is not None:
        if chip_bands == 12:
            # 12-band S2-only composite (already built by main.py via get_s2_12band_composite)
            classification_image = sentinel2_image
        else:
            # Fuse S2 (B4/B3/B2/B8) with S1 (VV/VH) when available.
            classification_image = (
                sentinel2_image.addBands(sentinel1_image)
                if sentinel1_image is not None
                else sentinel2_image
            )

    # --- Parallel chip download + inference ---
    results: dict[int, dict] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(
                _classify_alert,
                alert, pid, lat, lon,
                classifier, classification_image, chip_bands,
                classified_ids, existing_by_id,
            ): i
            for i, (alert, pid, lat, lon) in enumerate(rows)
        }

        with tqdm(total=len(future_to_idx), desc="Classifying alerts", unit="alert") as pbar:
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    # Keep the base alert; classification is best-effort.
                    alert, pid, *_ = rows[idx]
                    tqdm.write(f"      Warning: classification failed for {pid}: {exc}")
                    results[idx] = alert
                pbar.update(1)

    return [results[i] for i in range(len(rows))]


def save_geojson(
    alerts: list[dict],
    filepath: Path | None = None,
    region: str | None = None,
) -> Path:
    """Writes alerts to a GeoJSON FeatureCollection file.

    Args:
        alerts:   List of alert dicts from build_alerts().
        filepath: Destination path. If given, region is ignored.
        region:   Region name inserted into the filename:
                  outputs/alerts_<region>_YYYYMMDD.geojson.
                  Omit for the legacy outputs/alerts_YYYYMMDD.geojson name.

    Returns:
        The path where the file was written.
    """
    if filepath is None:
        today = date.today().strftime("%Y%m%d")
        stem = f"alerts_{region}_{today}" if region else f"alerts_{today}"
        filepath = OUTPUT_DIR / f"{stem}.geojson"

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
