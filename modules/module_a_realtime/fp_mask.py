"""
Persistent false positive mask for Module A.

Filters known recurring heat sources (industrial sites, volcanoes, etc.)
before detections become alerts.
"""

import json
import logging
import math
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MASK_PATH = _PROJECT_ROOT / "data" / "legal" / "fp_mask.geojson"

# Biobío bbox for coverage area calculation
_LON_MIN, _LAT_MIN, _LON_MAX, _LAT_MAX = -73.5, -38.5, -71.0, -36.5


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


class FalsePositiveMask:
    def __init__(self) -> None:
        self._locations: list[dict] = []
        if _MASK_PATH.exists():
            self._load()

    def _load(self) -> None:
        try:
            fc = json.loads(_MASK_PATH.read_text(encoding="utf-8"))
            self._locations = [f["properties"] for f in fc.get("features", [])]
            log.info("fp_mask: %d ubicaciones cargadas.", len(self._locations))
        except Exception as exc:
            log.warning("fp_mask: no se pudo cargar %s: %s", _MASK_PATH, exc)
            self._locations = []

    def _save(self) -> None:
        _MASK_PATH.parent.mkdir(parents=True, exist_ok=True)
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [loc["lon"], loc["lat"]]},
                "properties": loc,
            }
            for loc in self._locations
        ]
        fc = {"type": "FeatureCollection", "features": features}
        _MASK_PATH.write_text(json.dumps(fc, indent=2, ensure_ascii=False), encoding="utf-8")

    def build_from_history(self, geojson_path: str, min_days: int = 7) -> int:
        """
        Loads module_a_2025_events.geojson and extracts confirmed false positives
        with duration_days >= min_days. Saves centroids to fp_mask.geojson.
        Returns the count of locations added.
        """
        path = Path(geojson_path)
        if not path.exists():
            log.warning("fp_mask: archivo de historial no encontrado: %s", path)
            return 0

        fc = json.loads(path.read_text(encoding="utf-8"))
        added = 0
        today = date.today().isoformat()

        for feature in fc.get("features", []):
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})

            if not props.get("probable_false_positive", False):
                continue
            if props.get("duration_days", 0) < min_days:
                continue

            coords = geom.get("coordinates", [])
            if geom.get("type") == "Point" and len(coords) >= 2:
                lon, lat = coords[0], coords[1]
            else:
                continue

            # Skip if already masked (within 1 km)
            if self.is_masked(lat, lon, radius_km=1.0):
                continue

            entry = {
                "lat": lat,
                "lon": lon,
                "duration_days": props.get("duration_days", min_days),
                "detection_count": props.get("detection_count", 1),
                "added_date": today,
                "source": "auto_2025",
            }
            self._locations.append(entry)
            added += 1

        if added:
            self._save()
            log.info("fp_mask: %d nuevas ubicaciones guardadas desde historial.", added)

        return added

    def is_masked(self, lat: float, lon: float, radius_km: float = 2.0) -> bool:
        """Returns True if (lat, lon) is within radius_km of any known false positive."""
        for loc in self._locations:
            if _haversine_km(lat, lon, loc["lat"], loc["lon"]) <= radius_km:
                return True
        return False

    def add_manual(self, lat: float, lon: float, reason: str) -> None:
        """Manually flag a location as a false positive (operator use)."""
        entry = {
            "lat": lat,
            "lon": lon,
            "duration_days": 0,
            "detection_count": 0,
            "added_date": date.today().isoformat(),
            "source": "manual",
            "reason": reason,
        }
        self._locations.append(entry)
        self._save()
        log.info("fp_mask: ubicación manual agregada (%.4f, %.4f): %s", lat, lon, reason)

    def get_summary(self) -> str:
        total = len(self._locations)
        auto = sum(1 for loc in self._locations if loc.get("source") == "auto_2025")
        manual = sum(1 for loc in self._locations if loc.get("source") == "manual")

        # Coverage: sum of circle areas (radius 2 km) clipped to bbox, approx in km²
        area_km2 = total * math.pi * (2.0 ** 2)

        # Rough bbox area for context
        bbox_width_km = _haversine_km(_LAT_MIN, _LON_MIN, _LAT_MIN, _LON_MAX)
        bbox_height_km = _haversine_km(_LAT_MIN, _LON_MIN, _LAT_MAX, _LON_MIN)
        bbox_area_km2 = bbox_width_km * bbox_height_km

        coverage_pct = (area_km2 / bbox_area_km2 * 100) if bbox_area_km2 > 0 else 0.0

        return (
            f"Máscara FP: {total} ubicaciones | {auto} automáticas (historial 2025) | {manual} manuales\n"
            f"Cobertura: {area_km2:.0f} km² excluidos del bbox Biobío "
            f"({coverage_pct:.2f}% de {bbox_area_km2:.0f} km²)"
        )


fp_mask = FalsePositiveMask()
