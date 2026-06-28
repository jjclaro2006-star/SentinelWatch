"""Small dependency-free GeoJSON helpers for pilot-scale spatial screening."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any


def coordinates(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    """Flatten Point, Polygon and MultiPolygon coordinate arrays."""
    kind = geometry.get("type")
    value = geometry.get("coordinates", [])
    if kind == "Point":
        return [(float(value[0]), float(value[1]))]
    if kind == "Polygon":
        return [(float(x), float(y)) for ring in value for x, y, *_ in ring]
    if kind == "MultiPolygon":
        return [(float(x), float(y)) for polygon in value for ring in polygon for x, y, *_ in ring]
    raise ValueError(f"Unsupported geometry type: {kind!r}")


def centroid(geometry: dict[str, Any]) -> tuple[float, float]:
    points = coordinates(geometry)
    if not points:
        raise ValueError("Geometry has no coordinates")
    return (sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points))


def haversine_meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(radians, (*a, *b))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    value = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6_371_000 * 2 * asin(sqrt(value))


def point_in_ring(point: tuple[float, float], ring: list[list[float]]) -> bool:
    """Ray-casting test. Boundary handling is adequate for alert triage."""
    x, y = point
    inside = False
    for index in range(len(ring)):
        x1, y1 = ring[index - 1][0], ring[index - 1][1]
        x2, y2 = ring[index][0], ring[index][1]
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing:
                inside = not inside
    return inside


def contains_point(geometry: dict[str, Any], point: tuple[float, float]) -> bool:
    kind = geometry.get("type")
    if kind == "Point":
        return haversine_meters(centroid(geometry), point) < 1
    if kind == "Polygon":
        return bool(geometry["coordinates"]) and point_in_ring(point, geometry["coordinates"][0])
    if kind == "MultiPolygon":
        return any(point_in_ring(point, polygon[0]) for polygon in geometry["coordinates"] if polygon)
    return False
