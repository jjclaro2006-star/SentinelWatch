"""Sample spatially separated river-background candidates from Chile's official hydrography WFS."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from .geometry import centroid, haversine_meters


HYDRO_WFS = "https://geoportal.cl/geoserver/Hidrografia/wfs"
HYDRO_TYPENAME = "Hidrografia:hidrografa"


def fetch_hydro_page(start_index: int, count: int = 1000) -> list[dict[str, Any]]:
    query = urlencode({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": HYDRO_TYPENAME, "outputFormat": "application/json",
        "srsName": "EPSG:4326", "startIndex": start_index, "count": count,
    })
    with urlopen(f"{HYDRO_WFS}?{query}", timeout=90) as response:  # nosec B310 - fixed public government endpoint
        return json.load(response).get("features", [])


def fetch_hydro_bbox(latitude_min: float, latitude_max: float, count: int = 3000) -> list[dict[str, Any]]:
    """Fetch one latitudinal stratum so background examples span Chile."""
    query = urlencode({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": HYDRO_TYPENAME, "outputFormat": "application/json",
        "srsName": "EPSG:4326", "bbox": f"-76,{latitude_min},-66,{latitude_max},EPSG:4326",
        "count": count,
    })
    with urlopen(f"{HYDRO_WFS}?{query}", timeout=90) as response:  # nosec B310 - fixed public government endpoint
        return json.load(response).get("features", [])


def line_points(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    if kind == "LineString":
        return [(float(x), float(y)) for x, y, *_ in coordinates]
    if kind == "MultiLineString":
        return [(float(x), float(y)) for line in coordinates for x, y, *_ in line]
    return []


def sample_background_candidates(positives: dict[str, Any], target: int, minimum_distance_meters: float, seed: int = 42, minimum_spacing_meters: float = 1_000) -> dict[str, Any]:
    """Return river points far from known candidate sites.

    These are weak/background candidates, not certified negatives. A site can
    be unknown to public catalogues, so every example remains review-required.
    """
    rng = random.Random(seed)
    positive_points = [centroid(item["geometry"]) for item in positives.get("features", [])]
    selected: list[dict[str, Any]] = []
    selected_points: list[tuple[float, float]] = []
    seen_feature_ids: set[str] = set()
    main_types = {"rio", "estero", "arroyo"}
    main_target = round(target * 0.75)
    type_counts = {"main": 0, "quebrada": 0}

    def add_candidate(feature: dict[str, Any]) -> bool:
        properties = feature.get("properties") or {}
        feature_type = str(properties.get("tipo", "")).lower()
        bucket = "main" if feature_type in main_types else "quebrada" if feature_type == "quebrada" else None
        if not bucket or (bucket == "main" and type_counts["main"] >= main_target) or (bucket == "quebrada" and type_counts["quebrada"] >= target - main_target):
            return False
        hydro_id = str(feature.get("id", ""))
        if hydro_id in seen_feature_ids:
            return False
        points = line_points(feature.get("geometry") or {})
        if not points:
            return False
        point = rng.choice(points)
        if any(haversine_meters(point, other) < minimum_distance_meters for other in positive_points):
            return False
        if any(haversine_meters(point, other) < minimum_spacing_meters for other in selected_points):
            return False
        identifier = f"hydro-background-{len(selected) + 1:04d}"
        selected.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [point[0], point[1]]}, "properties": {
            "id": identifier, "label": "background_river_candidate", "label_confidence": 0.55,
            "label_basis": "Official hydrographic-network point >= configured distance from SMA known aggregate-site candidates.",
            "activity_type": "river_background", "precision": "hydrography_vertex", "source": "Geoportal de Chile — Red hidrográfica", "source_url": HYDRO_WFS,
            "hydro_feature_id": hydro_id, "river_name": properties.get("nombre", ""), "basin_name": properties.get("nom_cuen", ""), "river_type": properties.get("tipo", ""),
            "sampling_strategy": "75% river/estero/arroyo, 25% quebrada; >=10 km from known SMA aggregate candidates.",
            "minimum_distance_from_known_site_m": minimum_distance_meters, "training_use": "Background candidate only. Visual review required before treating as a negative training label.", "review_required": True,
        }})
        selected_points.append(point)
        seen_feature_ids.add(hydro_id)
        type_counts[bucket] += 1
        return True

    # The official source contains a very large number of quebradas. Use large
    # random pages and type quotas so the negative class resembles rivers more
    # closely instead of being dominated by dry channels.
    attempts = 0
    while len(selected) < target and attempts < 40:
        features = fetch_hydro_page(rng.randrange(0, 118_000), count=5_000)
        rng.shuffle(features)
        for feature in features:
            add_candidate(feature)
            if len(selected) == target:
                break
        attempts += 1
    if len(selected) < target:
        raise RuntimeError(f"Only sampled {len(selected)} of {target} requested river-background candidates")
    return {"type": "FeatureCollection", "features": selected}


def write_geojson(dataset: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")
