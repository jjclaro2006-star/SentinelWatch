"""Create small Sentinel-2 image patches for catalogue-labelled candidate sites."""

from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .stac import EARTH_SEARCH


def choose_scenes(point: dict[str, Any], start: str, end: str, cloud_cover: float) -> list[dict[str, Any]]:
    """Return Sentinel-2 scenes ordered from clearest to cloudiest."""
    from urllib.request import Request, urlopen

    payload = json.dumps({
        "collections": ["sentinel-2-l2a"], "intersects": point,
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z", "limit": 100,
        "query": {"eo:cloud_cover": {"lte": cloud_cover}},
    }).encode("utf-8")
    request = Request(EARTH_SEARCH, data=payload, headers={"Content-Type": "application/json", "Accept": "application/geo+json"})
    with urlopen(request, timeout=60) as response:  # nosec B310 - fixed public STAC endpoint
        scenes = json.load(response).get("features", [])
    return sorted(scenes, key=lambda item: (item.get("properties", {}).get("eo:cloud_cover", 100), item.get("properties", {}).get("datetime", "")))


def is_blank_patch(path: Path) -> bool:
    from PIL import Image
    import numpy as np
    with Image.open(path) as image:
        pixels = np.asarray(image)
    return bool(pixels.size == 0 or pixels.std() < 1)


def write_visual_patch(scene: dict[str, Any], point: tuple[float, float], output: Path, patch_size: int) -> None:
    """Read a small RGB window from a remote public COG without downloading a full scene."""
    try:
        import numpy as np
        import rasterio
        from PIL import Image
        from rasterio.enums import Resampling
        from rasterio.windows import Window
        from rasterio.warp import transform
    except ImportError as exc:
        raise RuntimeError("Patch creation needs rasterio, numpy and Pillow. Install requirements.txt.") from exc

    asset = (scene.get("assets") or {}).get("visual")
    if not asset or not asset.get("href"):
        raise ValueError(f"Scene {scene.get('id')} has no public visual asset")
    with rasterio.open(asset["href"]) as src:
        x, y = transform("EPSG:4326", src.crs, [point[0]], [point[1]])
        col, row = src.index(x[0], y[0])
        window = Window(col - patch_size // 2, row - patch_size // 2, patch_size, patch_size)
        rgb = src.read(indexes=[1, 2, 3], window=window, out_shape=(3, patch_size, patch_size), boundless=True, fill_value=0, resampling=Resampling.bilinear)
    image = np.moveaxis(rgb, 0, -1)
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(output)


def build_patches(candidates: dict[str, Any], output_dir: Path, manifest_path: Path, start: str, end: str, cloud_cover: float, patch_size: int, limit: int | None = None, offset: int = 0, only_ids: set[str] | None = None, workers: int = 1) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build patches, optionally in bounded parallel batches."""
    output_dir.mkdir(parents=True, exist_ok=True)
    good: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    features = candidates.get("features", [])[offset:]
    if limit:
        features = features[:limit]
    if only_ids:
        features = [item for item in features if str((item.get("properties") or {}).get("id")) in only_ids]
    def process(feature: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        props = feature.get("properties") or {}
        identifier = str(props.get("id", "candidate"))
        destination = output_dir / f"{identifier}.png"
        try:
            scenes = choose_scenes(feature["geometry"], start, end, cloud_cover)
            if not scenes:
                raise ValueError("No Sentinel-2 scene below cloud threshold")
            scene = None
            for candidate_scene in scenes[:10]:
                write_visual_patch(candidate_scene, tuple(feature["geometry"]["coordinates"]), destination, patch_size)
                if not is_blank_patch(destination):
                    scene = candidate_scene
                    break
            if not scene:
                destination.unlink(missing_ok=True)
                raise ValueError("Ten available Sentinel-2 scenes produced blank patches")
            return "good", {
                "id": identifier, "patch_path": str(destination), "label": props.get("label"),
                "label_confidence": props.get("label_confidence"), "scene_id": scene.get("id"),
                "acquired_at": scene.get("properties", {}).get("datetime"),
                "cloud_cover": scene.get("properties", {}).get("eo:cloud_cover"),
                "source_asset": (scene.get("assets") or {}).get("visual", {}).get("href"),
                "review_required": "yes",
            }
        except Exception as exc:  # Preserve every failure for a repeatable collection run.
            return "failed", {"id": identifier, "error": str(exc)}

    if workers <= 1:
        results = (process(feature) for feature in features)
        for kind, result in results:
            (good if kind == "good" else failed).append(result)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(process, feature) for feature in features]
            for future in as_completed(futures):
                kind, result = future.result()
                (good if kind == "good" else failed).append(result)
        good.sort(key=lambda item: item["id"])
        failed.sort(key=lambda item: item["id"])
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "patch_path", "label", "label_confidence", "scene_id", "acquired_at", "cloud_cover", "source_asset", "review_required"]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(good)
    return good, failed
