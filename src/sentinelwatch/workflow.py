"""Normalize labels and turn Colab detections into reviewable alerts."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from .geometry import centroid, contains_point, haversine_meters


VALID_LABELS = {
    "confirmed_extraction", "authorized_extraction", "known_aggregate_site",
    "suspected_extraction", "hard_negative", "background_river_candidate",
}


def read_geojson(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection":
        raise ValueError(f"{path} must be a GeoJSON FeatureCollection")
    return data


def write_geojson(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def make_label_manifest(cases: dict[str, Any], output: Path, before_days: int = 90, after_days: int = 90) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for feature in cases.get("features", []):
        props = feature.get("properties") or {}
        label = props.get("label")
        if label not in VALID_LABELS:
            raise ValueError(f"Case {props.get('id', '<missing id>')} has invalid label {label!r}")
        lon, lat = centroid(feature["geometry"])
        rows.append({
            "id": props.get("id", ""), "lon": lon, "lat": lat, "label": label,
            "observed_at": props.get("observed_at", ""), "window_before_days": before_days,
            "window_after_days": after_days, "confidence": props.get("confidence", ""),
            "precision": props.get("precision", "unknown"), "source_url": props.get("source_url", ""),
        })
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["id", "lon", "lat", "label", "observed_at", "window_before_days", "window_after_days", "confidence", "precision", "source_url"])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def permit_is_active(properties: dict[str, Any], observed_at: str) -> bool:
    if str(properties.get("status", "active")).lower() not in {"active", "vigente", "valid"}:
        return False
    current = date.fromisoformat(observed_at[:10])
    starts = properties.get("valid_from")
    ends = properties.get("valid_to")
    return (not starts or date.fromisoformat(starts[:10]) <= current) and (not ends or current <= date.fromisoformat(ends[:10]))


def matching_permits(detection: dict[str, Any], permits: list[dict[str, Any]], observed_at: str, nearby_meters: float) -> list[dict[str, Any]]:
    point = centroid(detection["geometry"])
    matches = []
    for permit in permits:
        properties = permit.get("properties") or {}
        if not permit_is_active(properties, observed_at):
            continue
        geometry = permit.get("geometry")
        if not geometry:
            continue
        distance = haversine_meters(point, centroid(geometry))
        if contains_point(geometry, point) or distance <= nearby_meters:
            matches.append(permit)
    return matches


def severity(score: float, area_ha: float, has_permit: bool) -> str:
    if has_permit:
        return "review"
    value = score + min(area_ha / 20, 0.2)
    if value >= 0.9:
        return "high"
    if value >= 0.7:
        return "medium"
    return "low"


def screen_detections(detections: dict[str, Any], permits: dict[str, Any], observed_at: str, minimum_score: float = 0.65, nearby_meters: float = 250) -> dict[str, Any]:
    alerts = []
    permit_features = permits.get("features", [])
    for feature in detections.get("features", []):
        props = feature.get("properties") or {}
        score = float(props.get("score", 0))
        if score < minimum_score:
            continue
        observed = str(props.get("observed_at") or observed_at)
        matches = matching_permits(feature, permit_features, observed, nearby_meters)
        area = float(props.get("area_ha", 0) or 0)
        state = "permitted_activity_candidate" if matches else "possible_unpermitted_extraction"
        alert_props = {
            "id": props.get("id", "detection"),
            "alert_type": state,
            "severity": severity(score, area, bool(matches)),
            "model_score": score,
            "observed_at": observed,
            "area_ha": area,
            "change_type": props.get("change_type", "riverbed_extraction"),
            "model_version": props.get("model_version", "unknown"),
            "matched_permit_ids": [(item.get("properties") or {}).get("id") for item in matches],
            "review_note": "Requires human and legal review; satellite/model output is not a finding of illegality.",
        }
        alerts.append({"type": "Feature", "geometry": feature["geometry"], "properties": alert_props})
    return {"type": "FeatureCollection", "features": alerts}


def write_report(alerts: dict[str, Any], output: Path) -> None:
    features = alerts.get("features", [])
    potential = [item for item in features if item["properties"]["alert_type"] == "possible_unpermitted_extraction"]
    lines = [
        "# SentinelWatch — Alertas de extracción de áridos", "",
        f"Alertas para revisión: **{len(features)}**", f"Posibles actividades sin permiso coincidente: **{len(potential)}**", "",
        "Las alertas priorizan revisión. No constituyen una determinación de ilegalidad.", "",
        "| ID | Fecha | Puntaje modelo | Área ha | Estado | Severidad | Permisos coincidentes |", "|---|---|---:|---:|---|---|---|",
    ]
    for item in features:
        p = item["properties"]
        permit_ids = ", ".join(str(value) for value in p["matched_permit_ids"] if value) or "—"
        lines.append(f"| {p['id']} | {p['observed_at']} | {p['model_score']:.2f} | {p['area_ha']:.2f} | {p['alert_type']} | {p['severity']} | {permit_ids} |")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
