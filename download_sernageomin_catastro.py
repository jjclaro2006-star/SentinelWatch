"""
download_sernageomin_catastro.py — Descarga el catastro de concesiones mineras de SERNAGEOMIN.

Requiere acceso a la red chilena (o VPN CL). Los servidores de SERNAGEOMIN no son
accesibles desde fuera de Chile en muchos casos.

Uso:
    python download_sernageomin_catastro.py

Guarda el resultado en:
    model/legal/sernageomin_catastro.geojson

Fuentes intentadas en orden:
  1. catastromineronline.sernageomin.cl  — ArcGIS REST MapServer oficial
  2. portalgeomin.sernageomin.cl         — Portal GeoMin WFS
  3. Fallback: mantiene el placeholder aproximado existente
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

_OUT = Path(__file__).parent / "model" / "legal" / "sernageomin_catastro.geojson"
_UA  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Bbox que cubre los 5 salares monitoreados [xmin, ymin, xmax, ymax] en EPSG:4326
_SALARES_BBOX = "-69.4,-27.1,-67.4,-23.1"

# Endpoint 1 — ArcGIS REST MapServer (catastromineronline)
_ARCGIS_BASE = (
    "https://catastromineronline.sernageomin.cl/arcgismin/rest/services"
    "/MINERIA/WMS_PROPIEDAD_MINERA_18S/MapServer"
)
# Layer 0 = Concesiones de Explotación, Layer 1 = Concesiones de Exploración
_ARCGIS_LAYERS = [0, 1]

# Endpoint 2 — WFS GeoServer de SERNAGEOMIN
_WFS_BASE = "https://portalgeomin.sernageomin.cl/geoserver/ows"
_WFS_TYPENAMES = [
    "sernageomin:concesiones_explotacion",
    "sernageomin:concesiones_exploracion",
    "sernageomin:pertenencias_mineras",
]


def _try_arcgis(layer_id: int, bbox: str) -> list[dict]:
    """Descarga features de una capa ArcGIS REST como GeoJSON."""
    url = f"{_ARCGIS_BASE}/{layer_id}/query"
    params = {
        "geometry":     bbox,
        "geometryType": "esriGeometryEnvelope",
        "inSR":         "4326",
        "outSR":        "4326",
        "spatialRel":   "esriSpatialRelIntersects",
        "where":        "1=1",
        "outFields":    "*",
        "f":            "geojson",
        "resultRecordCount": "5000",
    }
    r = requests.get(url, params=params, timeout=30, headers={"User-Agent": _UA})
    r.raise_for_status()
    return r.json().get("features", [])


def _try_wfs(typename: str, bbox: str) -> list[dict]:
    """Descarga features de un WFS 1.0 filtrando por bbox."""
    xmin, ymin, xmax, ymax = bbox.split(",")
    params = {
        "service":      "WFS",
        "version":      "1.0.0",
        "request":      "GetFeature",
        "typeName":     typename,
        "outputFormat": "application/json",
        "BBOX":         f"{ymin},{xmin},{ymax},{xmax}",
        "maxFeatures":  "5000",
    }
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    r = requests.get(_WFS_BASE, params=params, timeout=30, headers={"User-Agent": _UA}, verify=False)
    r.raise_for_status()
    return r.json().get("features", [])


def download() -> bool:
    all_features: list[dict] = []

    # Intento 1 — ArcGIS REST
    print("Intentando ArcGIS REST catastromineronline.sernageomin.cl...")
    for layer_id in _ARCGIS_LAYERS:
        try:
            feats = _try_arcgis(layer_id, _SALARES_BBOX)
            print(f"  Layer {layer_id}: {len(feats)} features")
            all_features.extend(feats)
        except Exception as e:
            print(f"  Layer {layer_id}: ERROR — {e}")

    # Intento 2 — WFS (si ArcGIS falló)
    if not all_features:
        print("\nIntentando WFS portalgeomin.sernageomin.cl...")
        for typename in _WFS_TYPENAMES:
            try:
                feats = _try_wfs(typename, _SALARES_BBOX)
                print(f"  {typename}: {len(feats)} features")
                all_features.extend(feats)
                if feats:
                    break
            except Exception as e:
                print(f"  {typename}: ERROR — {e}")

    if not all_features:
        print("\nAmbos endpoints fallaron. El placeholder aproximado se mantiene.")
        print(f"Archivo existente: {_OUT}")
        return False

    # Deduplicar por geometry hash aproximado
    seen: set[str] = set()
    unique: list[dict] = []
    for f in all_features:
        key = str(f.get("geometry", ""))[:80]
        if key not in seen:
            seen.add(key)
            unique.append(f)

    fc = {
        "type": "FeatureCollection",
        "_source": "SERNAGEOMIN catastromineronline — descarga oficial",
        "_generated": __import__("datetime").date.today().isoformat(),
        "_coverage": "salares_prioritarios_chile",
        "features": unique,
    }
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGuardado: {_OUT}  ({len(unique)} concesiones)")
    return True


if __name__ == "__main__":
    ok = download()
    sys.exit(0 if ok else 1)
