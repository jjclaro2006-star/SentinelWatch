"""STAC catalog search; downloading imagery is intentionally separate from training."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


EARTH_SEARCH = "https://earth-search.aws.element84.com/v1/search"

# Earth Search names Sentinel-2 assets semantically; other STAC providers
# commonly use band names. Supporting both keeps the Colab handoff simple.
ASSET_ALIASES = {
    "B02": "blue", "B03": "green", "B04": "red", "B08": "nir",
    "B11": "swir16", "B12": "swir22", "B09": "nir09",
}


def search_sentinel(aoi: dict, start: str, end: str, limit: int = 100, endpoint: str = EARTH_SEARCH) -> dict:
    payload = json.dumps({
        "collections": ["sentinel-2-l2a", "sentinel-1-grd"],
        "intersects": aoi,
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": limit,
    }).encode("utf-8")
    request = Request(endpoint, data=payload, headers={"Content-Type": "application/json", "Accept": "application/geo+json"})
    with urlopen(request, timeout=60) as response:  # nosec B310 - endpoint comes from explicit CLI argument
        return json.load(response)


def write_catalog(catalog: dict, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return len(catalog.get("features", []))


def download_assets(catalog: dict, output_dir: Path, asset_names: list[str], limit: int | None = None) -> list[Path]:
    """Download named HTTP(S) STAC assets, preserving the scene ID in each path.

    Some STAC endpoints publish cloud-native assets as s3:// URIs. Those are not
    silently handled here: users should use an endpoint with HTTPS assets or
    explicitly sign URLs through its documented client.
    """
    saved: list[Path] = []
    features = catalog.get("features", [])[:limit] if limit else catalog.get("features", [])
    for feature in features:
        scene_id = str(feature.get("id", "scene")).replace("/", "_")
        for requested_name in asset_names:
            asset_name = requested_name
            assets = feature.get("assets") or {}
            asset = assets.get(asset_name)
            if not asset:
                asset_name = ASSET_ALIASES.get(requested_name.upper(), requested_name)
                asset = assets.get(asset_name)
            if not asset or not asset.get("href"):
                continue
            href = asset["href"]
            if urlparse(href).scheme not in {"http", "https"}:
                continue
            suffix = Path(urlparse(href).path).suffix or ".bin"
            destination = output_dir / scene_id / f"{asset_name}{suffix}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                request = Request(href, headers={"User-Agent": "SentinelWatch-MVP/0.1"})
                with urlopen(request, timeout=180) as response:  # nosec B310 - URL originates in user-selected STAC catalog
                    destination.write_bytes(response.read())
            saved.append(destination)
    return saved
