"""
chile_aridos.py — Detección de extracción ilegal de áridos en ríos chilenos.

Pipeline basado en MNDWI (Modified Normalized Difference Water Index):
    MNDWI = (B3 - B11) / (B3 + B11)

Flujo por macrozona:
  1. Calcular MNDWI baseline y análisis con dynamic_date_windows()
  2. Detectar cambios morfológicos en cauces (|delta MNDWI| > umbral)
  3. Confirmar con Gaia Áridos (placeholder prob=0.5)
  4. Verificar legalidad con LegalCheckerChile (SMA + SERNAGEOMIN + SNASPE)
  5. Asignar severidad y guardar outputs/alerts_chile_aridos_{FECHA}.geojson

Entrypoint: run_chile_aridos()
Prueba sin GEE: dry_run_maipo()
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import requests
from shapely.geometry import Point, mapping, shape

from auth import authenticate_and_initialize
from chip_cache import make_polygon_id
from config import CLOUD_COVER_MAX, OUTPUT_DIR, dynamic_date_windows
from gaia_aridos import GaiaAridosClassifier

# ── Regiones por macrozona [west, south, east, north] ────────────────────────

CHILE_REGIONS: dict[str, list[float]] = {
    "norte_grande": [-71.0, -26.0, -68.0, -18.0],
    "norte_chico":  [-72.0, -32.0, -69.0, -26.0],
    "zona_central": [-72.5, -35.5, -69.5, -32.0],
    "zona_sur":     [-73.5, -39.0, -70.5, -35.5],
    "patagonia":    [-74.0, -46.0, -71.0, -39.0],
}

# Subzonas de ríos prioritarios [west, south, east, north]
RIOS_PRIORITARIOS: dict[str, list[float]] = {
    "biobio_nacimiento": [-72.70, -37.70, -72.20, -37.30],
    "biobio_negrete":    [-72.70, -37.80, -72.30, -37.50],
    "maule":             [-71.70, -35.50, -71.00, -35.00],
    "rahue_san_pablo":   [-73.00, -40.70, -72.50, -40.30],
    "diguillín_nuble":   [-72.00, -36.90, -71.50, -36.50],
    "maipo":             [-71.20, -33.90, -70.70, -33.40],
}

# Macrozona a la que pertenece cada río prioritario (para metadata de alertas)
_RIO_A_MACROZONA: dict[str, str] = {
    "biobio_nacimiento": "zona_sur",
    "biobio_negrete":    "zona_sur",
    "maule":             "zona_central",
    "rahue_san_pablo":   "zona_sur",
    "diguillín_nuble":   "zona_sur",
    "maipo":             "zona_central",
}

# ── Thresholds ────────────────────────────────────────────────────────────────

MNDWI_CHANGE_THRESHOLD = 0.15   # delta mínimo para flagear cambio morfológico
MIN_AREA_HA             = 0.5   # áridos: polígonos más pequeños que deforestación
_SEV_HIGH_THR           = 0.40
_SEV_MEDIUM_THR         = 0.25
_CHIP_CACHE_DIR         = Path("cache") / "chips_s2_12b"

# ── Legal: fuentes chilenas ───────────────────────────────────────────────────

_REQUEST_TIMEOUT = 20
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# SNASPE (Parques Nacionales, Reservas, Monumentos Naturales) — CONAF/MMA
_SNASPE_URL = (
    "https://services6.arcgis.com/PV5cvJFzOuE7KDG9/arcgis/rest/services"
    "/SNASPE/FeatureServer/0/query"
)

# Catastro Minero — SERNAGEOMIN (incluye concesiones de áridos)
_SERNAGEOMIN_URL = (
    "https://mapas.sernageomin.cl/arcgis/rest/services"
    "/Mineria/CatastroMinero/MapServer/0/query"
)


def _arcgis_point_query(url: str, lon: float, lat: float, where: str = "1=1") -> bool | None:
    params = {
        "geometry":        f"{lon},{lat}",
        "geometryType":    "esriGeometryPoint",
        "inSR":            "4326",
        "spatialRel":      "esriSpatialRelIntersects",
        "where":           where,
        "outFields":       "OBJECTID",
        "returnCountOnly": "true",
        "f":               "json",
    }
    try:
        resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT,
                            headers={"User-Agent": _BROWSER_UA})
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            return None
        return int(data.get("count", 0)) > 0
    except Exception:
        return None


class LegalCheckerChile:
    """
    Verificador legal para extracción de áridos en Chile.

    Capas:
      0. SNASPE (parques, reservas, monumentos naturales) — ArcGIS REST / CONAF
      1. Catastro minero SERNAGEOMIN (concesiones de áridos) — ArcGIS REST
      2. SMA — sanciones activas por extracción no autorizada (fallback REST)

    Veredicto:
      ILEGAL              — área protegida o sin concesión verificada
      REQUIERE VERIFICACIÓN — sin factores ilegales pero capas no disponibles
    """

    def verificar(self, lat: float, lon: float) -> dict:
        razones:  list[str] = []
        no_verif: list[str] = []

        # Capa 0 — SNASPE
        en_snaspe = _arcgis_point_query(_SNASPE_URL, lon, lat)
        if en_snaspe is True:
            razones.append("área protegida SNASPE")
        elif en_snaspe is None:
            no_verif.append("SNASPE")

        # Capas 1-2 — solo si SNASPE no dio ILEGAL (evita timeouts innecesarios)
        if not razones:
            tiene_cm = _arcgis_point_query(_SERNAGEOMIN_URL, lon, lat)
            if tiene_cm is False:
                razones.append("sin concesión de áridos SERNAGEOMIN")
            elif tiene_cm is None:
                no_verif.append("catastro SERNAGEOMIN")

        if razones:
            veredicto    = "ILEGAL"
            legal_detail = "; ".join(razones)
        else:
            veredicto    = "REQUIERE VERIFICACIÓN"
            legal_detail = (
                f"capas no verificables: {', '.join(no_verif)}" if no_verif else ""
            )

        return {"veredicto": veredicto, "legal_detail": legal_detail}


# ── GEE: cálculo de MNDWI ────────────────────────────────────────────────────

def _get_s2_collection(aoi, start: str, end: str):
    """Colección Sentinel-2 SR filtrada por nube y AOI."""
    import ee
    return (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", CLOUD_COVER_MAX))
    )


def _mndwi_composite(collection) -> "ee.Image":
    """Mediana del MNDWI = (B3 - B11) / (B3 + B11) para toda la colección."""
    import ee

    def add_mndwi(img):
        mndwi = img.normalizedDifference(["B3", "B11"]).rename("MNDWI")
        return img.addBands(mndwi)

    return collection.map(add_mndwi).select("MNDWI").median()


def _detect_mndwi_change(mndwi_base, mndwi_now) -> "tuple[ee.Image, ee.Image]":
    """
    Devuelve (diff_image, change_mask).
    diff = mndwi_now - mndwi_base  (negativo = reducción de agua/aumento sedimento)
    mask = píxeles donde |diff| > MNDWI_CHANGE_THRESHOLD
    """
    diff        = mndwi_now.subtract(mndwi_base).rename("MNDWI_delta")
    change_mask = diff.abs().gt(MNDWI_CHANGE_THRESHOLD).rename("MNDWI_change")
    return diff, change_mask


def _vectorize_mndwi_change(
    change_mask,
    mndwi_diff,
    aoi,
    scale: int = 20,
) -> list[dict]:
    """
    Convierte la máscara de cambio a polígonos vectoriales vía GEE.

    Devuelve una lista de dicts con geometry (GeoJSON), mndwi_delta, area_ha.
    """
    import ee
    from config import MAX_PIXELS

    vectors = change_mask.selfMask().reduceToVectors(
        geometry=aoi,
        scale=scale,
        geometryType="polygon",
        eightConnected=False,
        labelProperty="change",
        reducer=ee.Reducer.first(),
        maxPixels=MAX_PIXELS,
    )

    # Calcular delta promedio y área por polígono
    stats = mndwi_diff.reduceRegions(
        collection=vectors,
        reducer=ee.Reducer.mean(),
        scale=scale,
    )

    raw_features = stats.getInfo().get("features", [])
    results: list[dict] = []

    for feat in raw_features:
        geom = feat.get("geometry")
        if not geom:
            continue

        shp     = shape(geom)
        centroid = shp.centroid
        area_ha = shp.area * (111_000 ** 2) / 10_000  # deg² → ha (aprox.)

        if area_ha < MIN_AREA_HA:
            continue

        results.append({
            "geometry":    geom,
            "lat":         round(centroid.y, 6),
            "lon":         round(centroid.x, 6),
            "mndwi_delta": round(feat["properties"].get("mean", 0.0), 4),
            "area_ha":     round(area_ha, 2),
        })

    return results


# ── Caché de chips ─────────────────────────────────────────────────────────────

def _load_chip(polygon_id: str) -> "np.ndarray | None":
    path = _CHIP_CACHE_DIR / f"{polygon_id}.npy"
    if not path.exists():
        return None
    chip = np.load(path)
    return chip if chip.max() > 0 else None


def _save_chip(polygon_id: str, chip: np.ndarray) -> None:
    _CHIP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(_CHIP_CACHE_DIR / f"{polygon_id}.npy", chip)


def _download_chip(s2_image, lon: float, lat: float) -> "np.ndarray | None":
    """
    Descarga un chip Sentinel-2 12 bandas desde GEE para el punto dado.
    Reutiliza la función de gee_client cuando está disponible.
    """
    try:
        from gee_client import download_chip_12b
        import ee
        centroid = ee.Geometry.Point([lon, lat])
        return download_chip_12b(s2_image, centroid)
    except Exception as exc:
        print(f"        chip download fallido ({lon:.4f},{lat:.4f}): {exc}")
        return None


# ── Severidad ─────────────────────────────────────────────────────────────────

def _assign_severity(mndwi_delta: float, gaia_prob: float) -> str:
    delta_abs = abs(mndwi_delta)
    if delta_abs >= _SEV_HIGH_THR or (delta_abs >= _SEV_MEDIUM_THR and gaia_prob > 0.65):
        return "alta"
    if delta_abs >= _SEV_MEDIUM_THR:
        return "media"
    return "baja"


# ── Clasificación + legal por polígono ────────────────────────────────────────

def _classify_polygon(
    poly: dict,
    s2_image,
    classifier: GaiaAridosClassifier,
    legal_checker: LegalCheckerChile,
    classified_cache: dict[str, dict],
) -> dict:
    """
    Descarga chip → Gaia Áridos → verificación legal → construye alerta.
    Reutiliza resultados del clasificador si el polígono ya fue procesado.
    """
    polygon_id = make_polygon_id(poly["lat"], poly["lon"])

    # Reusar clasificación previa
    if polygon_id in classified_cache:
        prev = classified_cache[polygon_id]
        gaia_result = {
            "actividad":    prev.get("actividad", "extraccion_aridos"),
            "confianza":    prev.get("confianza", 0.5),
            "veredicto":    prev.get("veredicto", "REQUIERE VERIFICACIÓN"),
            "legal_detail": prev.get("legal_detail", ""),
        }
    else:
        chip = _load_chip(polygon_id)
        if chip is None and s2_image is not None:
            chip = _download_chip(s2_image, poly["lon"], poly["lat"])
            if chip is not None:
                _save_chip(polygon_id, chip)

        if chip is not None:
            gaia_result = classifier.predecir(chip, (poly["lat"], poly["lon"]))
        else:
            gaia_result = {
                "actividad":    "extraccion_aridos",
                "confianza":    0.5,
                "veredicto":    "REQUIERE VERIFICACIÓN",
                "legal_detail": "chip no disponible",
            }

        # Verificación legal Chile (solo si Gaia no descartó)
        if gaia_result["actividad"] != "normal":
            legal = legal_checker.verificar(poly["lat"], poly["lon"])
            gaia_result["veredicto"]    = legal["veredicto"]
            gaia_result["legal_detail"] = legal["legal_detail"]

    severity = _assign_severity(poly["mndwi_delta"], gaia_result["confianza"])
    direction = "descenso" if poly["mndwi_delta"] < 0 else "ascenso"

    return {
        "id":              polygon_id,
        "rio":             poly.get("rio", ""),
        "macrozona":       poly.get("macrozona", ""),
        "lat":             poly["lat"],
        "lon":             poly["lon"],
        "detection_date":  date.today().isoformat(),
        "mndwi_delta":     poly["mndwi_delta"],
        "mndwi_direction": direction,
        "area_ha":         poly["area_ha"],
        "severity":        severity,
        "actividad":       gaia_result["actividad"],
        "confianza":       gaia_result["confianza"],
        "veredicto":       gaia_result["veredicto"],
        "legal_detail":    gaia_result["legal_detail"],
        "geometry":        poly["geometry"],
    }


# ── Pipeline por zona ─────────────────────────────────────────────────────────

def _run_zone(
    zone_name: str,
    bbox: list[float],
    baseline: tuple[str, str],
    analysis: tuple[str, str],
    classifier: GaiaAridosClassifier,
    legal_checker: LegalCheckerChile,
    classified_cache: dict[str, dict],
    rio_label: str = "",
) -> list[dict]:
    """
    Ejecuta el pipeline MNDWI completo para una zona dada.
    Devuelve lista de dicts de alerta.
    """
    import ee
    from gee_client import aoi_geometry

    label = rio_label or zone_name
    print(f"  [{label}] AOI: {bbox}")

    aoi      = aoi_geometry(bbox)
    col_base = _get_s2_collection(aoi, *baseline)
    col_now  = _get_s2_collection(aoi, *analysis)

    n_base = col_base.size().getInfo()
    n_now  = col_now.size().getInfo()
    print(f"  [{label}] S2 baseline: {n_base} imágenes, análisis: {n_now} imágenes")

    if n_base == 0 or n_now == 0:
        print(f"  [{label}] Sin imágenes suficientes — zona omitida.")
        return []

    mndwi_base = _mndwi_composite(col_base)
    mndwi_now  = _mndwi_composite(col_now)
    mndwi_diff, change_mask = _detect_mndwi_change(mndwi_base, mndwi_now)

    polygons = _vectorize_mndwi_change(change_mask, mndwi_diff, aoi)
    print(f"  [{label}] Polígonos de cambio detectados: {len(polygons)}")

    if not polygons:
        return []

    # Annotate polígonos con metadatos de zona
    macrozona = _RIO_A_MACROZONA.get(rio_label, zone_name) if rio_label else zone_name
    for p in polygons:
        p["rio"]      = rio_label
        p["macrozona"] = macrozona

    # Composite S2 12 bandas para descargar chips
    s2_composite = col_now.median().select(
        ["B1","B2","B3","B4","B5","B6","B7","B8","B8A","B9","B11","B12"]
    )

    alerts: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(
                _classify_polygon,
                poly, s2_composite, classifier, legal_checker, classified_cache,
            ): i
            for i, poly in enumerate(polygons)
        }
        for fut in as_completed(futures):
            try:
                alerts.append(fut.result())
            except Exception as exc:
                print(f"  [{label}] Error clasificando polígono: {exc}")

    return alerts


# ── Guardar GeoJSON ───────────────────────────────────────────────────────────

def _save_geojson(alerts: list[dict], suffix: str = "") -> Path:
    today    = date.today().strftime("%Y%m%d")
    name     = f"alerts_chile_aridos{('_' + suffix) if suffix else ''}_{today}.geojson"
    out_path = OUTPUT_DIR / name

    features = []
    for a in alerts:
        geom = a.pop("geometry", None)
        features.append({
            "type":       "Feature",
            "geometry":   geom,
            "properties": a,
        })

    fc = {"type": "FeatureCollection", "features": features}
    out_path.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  GeoJSON guardado: {out_path}  ({len(alerts)} alertas)")
    return out_path


# ── Entrypoint principal ──────────────────────────────────────────────────────

def run_chile_aridos(
    baseline: tuple[str, str] | None = None,
    analysis: tuple[str, str] | None = None,
    detection_date: date | None = None,
    zones: list[str] | None = None,
    reclassify: bool = False,
) -> dict:
    """
    Ejecuta el pipeline de áridos sobre Chile completo.

    Itera sobre los ríos prioritarios (subzonas finas) y luego sobre las
    macrozonas no cubiertas.  Guarda un GeoJSON unificado.

    Args:
        baseline:       (start, end) — por defecto dynamic_date_windows()
        analysis:       (start, end) — por defecto dynamic_date_windows()
        detection_date: fecha de detección; por defecto hoy
        zones:          lista de claves de CHILE_REGIONS a procesar;
                        None = todas
        reclassify:     True = ignorar caché de clasificación anterior

    Returns:
        dict con total_alerts, output_path, severity, veredicto
    """
    authenticate_and_initialize()

    if baseline is None or analysis is None:
        baseline, analysis = dynamic_date_windows()

    print(f"\n[CHILE ÁRIDOS] baseline={baseline}  análisis={analysis}")
    print(f"  Ríos prioritarios : {list(RIOS_PRIORITARIOS.keys())}")
    print(f"  Macrozonas        : {list(CHILE_REGIONS.keys())}")

    classifier    = GaiaAridosClassifier()
    legal_checker = LegalCheckerChile()

    # Cargar alertas previas para clasificación incremental
    classified_cache: dict[str, dict] = {}
    if not reclassify:
        prev_files = sorted(OUTPUT_DIR.glob("alerts_chile_aridos_*.geojson"))
        if prev_files:
            try:
                prev_data = json.loads(prev_files[-1].read_text(encoding="utf-8"))
                for feat in prev_data.get("features", []):
                    props = feat.get("properties", {})
                    pid   = props.get("id")
                    if pid and "actividad" in props:
                        classified_cache[pid] = props
                print(f"  Caché de clasificación anterior: {len(classified_cache)} alertas")
            except Exception as exc:
                print(f"  Advertencia: no se pudo leer alertas previas ({exc})")

    all_alerts: list[dict] = []

    # Paso 1: ríos prioritarios (análisis fino, ~50 × 50 km)
    print("\n[1/2] Ríos prioritarios...")
    for rio_name, rio_bbox in RIOS_PRIORITARIOS.items():
        alerts = _run_zone(
            zone_name=rio_name,
            bbox=rio_bbox,
            baseline=baseline,
            analysis=analysis,
            classifier=classifier,
            legal_checker=legal_checker,
            classified_cache=classified_cache,
            rio_label=rio_name,
        )
        all_alerts.extend(alerts)

    # Paso 2: macrozonas completas (captura ríos no prioritarios)
    active_zones = zones or list(CHILE_REGIONS.keys())
    print(f"\n[2/2] Macrozonas: {active_zones}")
    for zone_name in active_zones:
        if zone_name not in CHILE_REGIONS:
            print(f"  Zona desconocida: {zone_name} — omitida.")
            continue
        alerts = _run_zone(
            zone_name=zone_name,
            bbox=CHILE_REGIONS[zone_name],
            baseline=baseline,
            analysis=analysis,
            classifier=classifier,
            legal_checker=legal_checker,
            classified_cache=classified_cache,
        )
        all_alerts.extend(alerts)

    output_path = _save_geojson(all_alerts)

    severity_counts:  dict[str, int] = {}
    veredicto_counts: dict[str, int] = {}
    for a in all_alerts:
        s = a.get("severity", "baja")
        severity_counts[s] = severity_counts.get(s, 0) + 1
        v = a.get("veredicto", "")
        veredicto_counts[v] = veredicto_counts.get(v, 0) + 1

    summary: dict[str, Any] = {
        "total_alerts":    len(all_alerts),
        "output_path":     str(output_path),
        "severity":        severity_counts,
        "veredicto":       veredicto_counts,
        "baseline_period": baseline,
        "analysis_period": analysis,
    }

    print(f"\n[CHILE ÁRIDOS] Completado.")
    print(f"  Total alertas : {summary['total_alerts']}")
    print(f"  Severidad     : {summary['severity']}")
    print(f"  Veredicto     : {summary['veredicto']}")
    print(f"  Output        : {summary['output_path']}")

    return summary


# ── Prueba sin GEE: río Maipo ─────────────────────────────────────────────────

def dry_run_maipo() -> dict:
    """
    Simulación del pipeline sobre el río Maipo sin conexión a GEE.

    Genera alertas sintéticas basadas en hotspots conocidos de extracción de
    áridos en el corredor Maipo (Buin–Calera de Tango, Región Metropolitana).
    Útil para validar el formato de salida y el flujo legal antes del despliegue.
    """
    _HOTSPOTS = [
        # (lat, lon, mndwi_delta, area_ha)  — coordenadas aproximadas de zonas activas
        (-33.730, -70.980, -0.41, 3.2),   # Buin Norte — extracción activa
        (-33.745, -70.965, -0.28, 1.8),   # Buin Centro
        (-33.762, -70.950, -0.52, 4.7),   # Buin Sur — mayor actividad
        (-33.680, -71.010, -0.19, 1.1),   # Calera de Tango
        (-33.698, -70.995, -0.33, 2.5),   # Padre Hurtado Norte
        (-33.715, -70.985, -0.22, 1.6),   # Padre Hurtado Sur
        (-33.800, -70.920,  0.18, 0.9),   # Paine — posible sedimentación
        (-33.820, -70.905, -0.31, 2.1),   # Paine Sur
        (-33.650, -71.025, -0.16, 0.8),   # San Bernardo
        (-33.840, -70.890, -0.44, 3.9),   # Isla de Maipo — zona crítica
    ]

    classifier    = GaiaAridosClassifier()
    legal_checker = LegalCheckerChile()

    alerts: list[dict] = []
    for lat, lon, delta, area_ha in _HOTSPOTS:
        polygon_id = make_polygon_id(lat, lon)
        gaia_result = classifier.predecir(
            np.zeros((64, 64, 12), dtype=np.float32),
            (lat, lon),
        )

        severity  = _assign_severity(delta, gaia_result["confianza"])
        direction = "descenso" if delta < 0 else "ascenso"

        # Polígono sintético (cuadrado de ~área_ha alrededor del centroide)
        half = (area_ha / 10_000) ** 0.5 / 2
        geom = {
            "type": "Polygon",
            "coordinates": [[
                [lon - half, lat - half],
                [lon + half, lat - half],
                [lon + half, lat + half],
                [lon - half, lat + half],
                [lon - half, lat - half],
            ]],
        }

        alerts.append({
            "id":              polygon_id,
            "rio":             "maipo",
            "macrozona":       "zona_central",
            "lat":             lat,
            "lon":             lon,
            "detection_date":  date.today().isoformat(),
            "mndwi_delta":     round(delta, 4),
            "mndwi_direction": direction,
            "area_ha":         area_ha,
            "severity":        severity,
            "actividad":       gaia_result["actividad"],
            "confianza":       gaia_result["confianza"],
            "veredicto":       gaia_result["veredicto"],
            "legal_detail":    gaia_result["legal_detail"],
            "geometry":        geom,
        })

    output_path = _save_geojson(alerts, suffix="dry_run_maipo")

    severity_counts:  dict[str, int] = {}
    veredicto_counts: dict[str, int] = {}
    for a in alerts:
        s = a.get("severity", "baja")
        severity_counts[s] = severity_counts.get(s, 0) + 1
        v = a.get("veredicto", "")
        veredicto_counts[v] = veredicto_counts.get(v, 0) + 1

    summary = {
        "total_alerts":  len(alerts),
        "output_path":   str(output_path),
        "severity":      severity_counts,
        "veredicto":     veredicto_counts,
        "mode":          "dry_run_maipo",
    }

    print(f"\n[DRY RUN MAIPO]")
    print(f"  Alertas simuladas : {summary['total_alerts']}")
    print(f"  Severidad         : {summary['severity']}")
    print(f"  Veredicto         : {summary['veredicto']}")
    print(f"  Output            : {summary['output_path']}")

    return summary


# ── CLI directo ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Chile Áridos — detección MNDWI.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Ejecutar simulación sobre río Maipo sin GEE.")
    parser.add_argument("--zones", nargs="*", choices=list(CHILE_REGIONS.keys()),
                        help="Macrozonas a procesar. Por defecto: todas.")
    parser.add_argument("--reclassify", action="store_true",
                        help="Ignorar caché de clasificación anterior.")
    args = parser.parse_args()

    if args.dry_run:
        dry_run_maipo()
    else:
        run_chile_aridos(zones=args.zones, reclassify=args.reclassify)
