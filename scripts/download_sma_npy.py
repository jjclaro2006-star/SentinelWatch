"""Download SMA Sentinel-2 patches from Earth Engine as raw-DN NPY arrays."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
import time
from pathlib import Path

import ee
import numpy as np
import requests


PROJECT = "gen-lang-client-0350293091"
BANDS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B9", "B11", "B12"]
INPUT = Path("data/processed/sma_river_aggregate_candidates.geojson")
OUTPUT = Path("data/imagery/sma_npy")


def load_patch(lon: float, lat: float) -> np.ndarray:
    # The Earth Engine image construction intentionally matches the requested code.
    geom = ee.Geometry.Point([lon, lat]).buffer(1120)
    s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(geom)
        .filterDate('2023-01-01', '2025-12-31')
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        .median()
        .select(["B1","B2","B3","B4","B5","B6","B7","B8","B8A","B9","B11","B12"])
    )
    # The literal scale-only request uses the median image's EPSG:4326 default
    # projection and returns a variable (non-square) pixel grid.  Asking for
    # 224x224 samples over the same 2,240-m buffer yields the required
    # approximately 10-m square patch.  Earth Engine disallows scale and
    # dimensions in the same download request.
    url = s2.getDownloadURL({"region": geom, "dimensions": [224, 224], "format": "NPY"})

    response = requests.get(url, timeout=180)
    response.raise_for_status()
    downloaded = np.load(io.BytesIO(response.content), allow_pickle=False)
    if downloaded.dtype.names is not None:
        if tuple(downloaded.dtype.names) != tuple(BANDS):
            raise ValueError(f"Unexpected band layout: {downloaded.dtype.names}")
        patch = np.stack([downloaded[band] for band in BANDS], axis=-1)
    else:
        patch = downloaded
    if patch.shape != (224, 224, 12):
        raise ValueError(f"Expected (224, 224, 12), got {patch.shape}")
    return patch


def download_one(index: int, feature: dict) -> None:
    output_path = OUTPUT / f"{index:04d}.npy"
    if output_path.exists():
        existing = np.load(output_path, mmap_mode="r", allow_pickle=False)
        if existing.shape == (224, 224, 12):
            print(f"{index:04d}: already valid", flush=True)
            return
        output_path.unlink()

    lon, lat = feature["geometry"]["coordinates"]
    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            patch = load_patch(lon, lat)
            temporary_path = output_path.with_suffix(".part.npy")
            np.save(temporary_path, patch)
            temporary_path.replace(output_path)
            print(f"{index:04d}: saved {patch.dtype} {patch.shape}", flush=True)
            return
        except Exception as error:  # retry transient EE/network errors
            last_error = error
            print(f"{index:04d}: attempt {attempt}/4 failed: {error}", flush=True)
            time.sleep(5 * attempt)
    raise RuntimeError(f"{index:04d}: download failed after retries") from last_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=None, help="exclusive index")
    parser.add_argument("--workers", type=int, default=1)
    arguments = parser.parse_args()

    features = json.loads(INPUT.read_text(encoding="utf-8"))["features"]
    if len(features) != 108:
        raise ValueError(f"Expected 108 SMA features, got {len(features)}")
    end = len(features) if arguments.end is None else arguments.end
    if not (0 <= arguments.start <= end <= len(features)):
        raise ValueError("Invalid index range")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    ee.Initialize(project=PROJECT)
    indexes = range(arguments.start, end)
    if arguments.workers == 1:
        for index in indexes:
            download_one(index, features[index])
    else:
        with ThreadPoolExecutor(max_workers=arguments.workers) as executor:
            futures = [executor.submit(download_one, index, features[index]) for index in indexes]
            for future in as_completed(futures):
                future.result()


if __name__ == "__main__":
    main()
