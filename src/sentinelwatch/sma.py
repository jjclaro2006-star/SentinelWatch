"""Build a cautious training-candidate dataset from SMA open data exports.

The SMA catalogue identifies regulated units and their instruments. It is
valuable training evidence for known aggregate sites, but it does *not* prove
current activity or permit validity. This module preserves that distinction.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


RIVER_TOKENS = {"rio", "cauce", "fluvial", "estero"}
SMA_SOURCE = "https://snifa.sma.gob.cl/DatosAbiertos"


def read_sma_csv(path: Path) -> list[dict[str, str]]:
    """SMA open-data CSVs are currently distributed using a legacy encoding."""
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with path.open(encoding=encoding, newline="") as handle:
                return list(csv.DictReader(handle, delimiter=";"))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode {path}")


def text(row: dict[str, str]) -> str:
    return " ".join(str(value or "") for value in row.values()).lower()


def words(row: dict[str, str]) -> list[str]:
    value = unicodedata.normalize("NFKD", text(row)).encode("ascii", "ignore").decode("ascii")
    return re.findall(r"[a-z0-9]+", value)


def is_river_aggregate(row: dict[str, str]) -> bool:
    tokens = words(row)
    is_aggregate = any(token.startswith("arid") or token.startswith("arener") for token in tokens)
    return is_aggregate and any(token in RIVER_TOKENS for token in tokens)


def iso_date(value: str | None) -> str | None:
    if not value:
        return None
    for pattern in ("%d-%m-%y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            pass
    return None


def build_river_aggregate_candidates(units_path: Path, sanctions_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    units = [row for row in read_sma_csv(units_path) if is_river_aggregate(row)]
    sanctions_by_unit: dict[str, list[dict[str, str]]] = defaultdict(list)
    for sanction in read_sma_csv(sanctions_path):
        sanctions_by_unit[sanction.get("UnidadFiscalizableId", "")].append(sanction)

    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in units:
        key = (row.get("UnidadFiscalizableId", ""), row.get("Longitud", ""), row.get("Latitud", ""))
        grouped[key].append(row)

    features: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    for (unit_id, longitude, latitude), records in grouped.items():
        try:
            lon, lat = float(longitude), float(latitude)
        except (TypeError, ValueError):
            continue
        first = records[0]
        sanctions = sanctions_by_unit.get(unit_id, [])
        statuses = sorted({item.get("ProcesoSancionEstado", "") for item in sanctions if item.get("ProcesoSancionEstado")})
        instruments = sorted({item.get("InstrumentoSmaId", "") for item in records if item.get("InstrumentoSmaId")})
        descriptions = sorted({item.get("DescripcionLarga", "") for item in records if item.get("DescripcionLarga")})
        updated_at = max((iso_date(item.get("FechaActualizacion")) for item in records if iso_date(item.get("FechaActualizacion"))), default=None)
        properties = {
            "id": f"sma-uf-{unit_id}",
            "label": "known_aggregate_site",
            "label_confidence": 0.8,
            "label_basis": "SMA public regulated-unit catalogue contains aggregate-extraction and river-context terms.",
            "activity_type": "riverbed_aggregate_extraction",
            "observed_at": updated_at,
            "source_updated_at": updated_at,
            "precision": "catalogue_point",
            "source": "SMA SNIFA Datos Abiertos — Unidades Fiscalizables e Instrumentos",
            "source_url": first.get("LinkSNIFA", SMA_SOURCE).strip() or SMA_SOURCE,
            "region": first.get("RegionNombre", ""),
            "commune": first.get("ComunaNombre", ""),
            "unit_name": first.get("Nombre", ""),
            "sma_unit_id": unit_id,
            "sma_instrument_ids": instruments,
            "instrument_descriptions": descriptions,
            "related_sanction_count": len(sanctions),
            "related_sanction_ids": [item.get("ProcesoSancionId") for item in sanctions],
            "related_sanction_statuses": statuses,
            "legal_status": "unknown — an SMA instrument/RCA association is not proof of active authorisation.",
            "training_use": "positive candidate for visual aggregate-site detection; verify activity date and footprint before use as pixel-level ground truth.",
        }
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": properties})
        review_rows.append({
            "id": properties["id"], "unit_name": properties["unit_name"], "region": properties["region"],
            "commune": properties["commune"], "longitude": lon, "latitude": lat,
            "label": properties["label"], "confidence": properties["label_confidence"],
            "related_sanction_count": len(sanctions), "source_url": properties["source_url"],
            "review_action": "Inspect time series and validate footprint/activity before training.",
        })
    features.sort(key=lambda item: item["properties"]["id"])
    return {"type": "FeatureCollection", "features": features}, review_rows


def write_candidate_outputs(dataset: dict[str, Any], review_rows: list[dict[str, Any]], output: Path, review_output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")
    review_output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "unit_name", "region", "commune", "longitude", "latitude", "label", "confidence", "related_sanction_count", "source_url", "review_action"]
    with review_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(review_rows)
