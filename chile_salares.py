"""
chile_salares.py — Detección de expansión ilegal de piscinas de evaporación en salares chilenos.

Detecta extracción de litio sobre lo autorizado por la RCA (Resolución de Calificación
Ambiental) en los salares del norte de Chile.  No es minería artesanal — es sobreextracción
por grandes operadores (SQM, Albemarle y otros) respecto a sus concesiones aprobadas.

Índice: SWIR Salt Index (SSI) = (B11 + B12) / 2
  Las piscinas de evaporación tienen alta reflectancia en SWIR (sales, brine concentradas).
  La expansión se detecta cuando SSI_análisis >> SSI_baseline en píxeles fuera del área
  de concesión SERNAGEOMIN.

Flujo por salar:
  1. Calcular SSI baseline y análisis con dynamic_date_windows()
  2. Detectar expansión (SSI_delta > umbral y SSI_now > umbral absoluto)
  3. Confirmar con Gaia Salares (placeholder prob=0.5)
  4. Verificar legalidad contra concesiones SERNAGEOMIN + placeholder RCA/SEA
  5. Guardar outputs/alerts_chile_salares_{FECHA}.geojson

Entrypoint: run_chile_salares()
Prueba sin GEE: dry_run_atacama()
"""

from __future__ import annotations

import csv
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import requests
import timm
import torch
import torch.nn as nn
from shapely.geometry import Point, mapping, shape
from shapely.strtree import STRtree

from auth import authenticate_and_initialize
from chip_cache import make_polygon_id
from config import CLOUD_COVER_MAX, OUTPUT_DIR, dynamic_date_windows

# ── Salares prioritarios [west, south, east, north] ──────────────────────────

SALARES_PRIORITARIOS: dict[str, dict] = {
    "salar_atacama":     {"bbox": [-68.45, -23.65, -67.85, -23.15], "operador": "SQM/Albemarle"},
    "salar_maricunga":   {"bbox": [-69.2,  -27.1,  -68.8,  -26.8],  "operador": "múltiple"},
    "salar_pedernales":  {"bbox": [-69.4,  -26.4,  -69.0,  -26.1],  "operador": "múltiple"},
    "salar_punta_negra": {"bbox": [-68.8,  -24.8,  -68.4,  -24.5],  "operador": "múltiple"},
    "salar_aguilar":     {"bbox": [-67.7,  -26.4,  -67.4,  -26.1],  "operador": "múltiple"},
}

# ── Thresholds ────────────────────────────────────────────────────────────────

# SSI delta para considerar expansión (en unidades DN/10000 medianas)
SSI_EXPANSION_THRESHOLD  = 0.15   # cambio relativo mínimo entre baseline y análisis
SSI_ABSOLUTE_THRESHOLD   = 0.25   # SSI absoluto mínimo para ser piscina (no suelo desnudo)
MIN_AREA_HA              = 1.0    # polígonos menores se descartan

_SEV_HIGH_THR    = 0.20
_SEV_MEDIUM_THR  = 0.12
_CHIP_CACHE_DIR  = Path("cache") / "chips_salares_s2_12b"
_SALARES_MODEL_PATH = Path(__file__).parent / "models" / "gaia_salares_v01.pth"
_FALLBACK_MODEL_PATH = Path(__file__).parent / "models" / "gaia_v05_amw_ssl4eo_v4.pth"
_EMBED_DIM  = 384
_INPUT_SIZE = 224
_S2_SCALE   = 10_000.0
_GAIA_THRESHOLD = 0.50

_CANDIDATOS_DIR = Path("data") / "salares_chips" / "candidatos"
_CANDIDATOS_CSV = Path("data") / "salares_chips" / "candidatos.csv"
_CSV_LOCK       = threading.Lock()

# ── Legal: fuentes chilenas ───────────────────────────────────────────────────

_REQUEST_TIMEOUT = 20
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Catastro local SERNAGEOMIN — GeoJSON descargado de catastromineronline.sernageomin.cl
# Generado con download_sernageomin_catastro.py (requiere red chilena o VPN CL).
_SERNAGEOMIN_LOCAL = Path(__file__).parent / "model" / "legal" / "sernageomin_catastro.geojson"

# Endpoint REST de respaldo (solo si el archivo local no existe).
_SERNAGEOMIN_REST_URL = (
    "https://catastromineronline.sernageomin.cl/arcgismin/rest/services"
    "/MINERIA/WMS_PROPIEDAD_MINERA_18S/MapServer/0/query"
)

# SEA — Sistema de Evaluación Ambiental (RCA): no hay endpoint ArcGIS público estable.
_SEA_RCA_URL_PLACEHOLDER = None

# Resultado tipado para consulta REST: True/False/str(error)
_QueryResult = bool | str


def _arcgis_point_query_rest(url: str, lon: float, lat: float) -> _QueryResult:
    """Consulta ArcGIS REST por punto. Devuelve True/False o str con causa del error."""
    params = {
        "geometry":        f"{lon},{lat}",
        "geometryType":    "esriGeometryPoint",
        "inSR":            "4326",
        "spatialRel":      "esriSpatialRelIntersects",
        "where":           "1=1",
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
            return f"ERROR:arcgis code={data['error'].get('code')}"
        return int(data.get("count", 0)) > 0
    except requests.exceptions.ConnectionError as e:
        cause = "DNS_FAIL" if "getaddrinfo failed" in str(e) else "CONN_REFUSED"
        return f"ERROR:{cause}"
    except requests.exceptions.Timeout:
        return f"ERROR:TIMEOUT>{_REQUEST_TIMEOUT}s"
    except requests.exceptions.HTTPError as e:
        return f"ERROR:HTTP_{e.response.status_code}"
    except Exception as e:
        return f"ERROR:{type(e).__name__}"


class LegalCheckerSalares:
    """
    Verificador legal para expansión de piscinas de evaporación en salares.

    Estrategia (en orden de prioridad):
      1. Catastro local SERNAGEOMIN (STRtree sobre model/legal/sernageomin_catastro.geojson)
         → Fast, offline, mismo patrón que WDPA en legal_checker.py
         → Generar con: python download_sernageomin_catastro.py (requiere red CL)
      2. Endpoint REST catastromineronline.sernageomin.cl (si el archivo local no existe)
         → Lento, requiere red chilena
      3. Registra el error explícito en legal_detail si ambos fallan

    Veredictos:
      ILEGAL               — expansión fuera de toda concesión SERNAGEOMIN conocida
      REQUIERE VERIFICACIÓN — dentro de concesión pero RCA/SEA no verificable
      ERROR INFRAESTRUCTURA — ni local ni REST disponibles; causa en legal_detail
    """

    def __init__(self) -> None:
        self._tree:      STRtree | None = None
        self._geoms:     list           = []
        self._props:     list[dict]     = []
        self._usar_rest: bool           = False
        self._load_catastro()

    def _load_catastro(self) -> None:
        if not _SERNAGEOMIN_LOCAL.exists():
            print(f"      [legal] Catastro local no encontrado: {_SERNAGEOMIN_LOCAL}")
            print("      [legal] Usando endpoint REST (requiere red CL).")
            self._usar_rest = True
            return

        try:
            data     = json.loads(_SERNAGEOMIN_LOCAL.read_text(encoding="utf-8"))
            features = data.get("features", [])
            source   = data.get("_source", "desconocido")
            geoms    = []
            props    = []
            for f in features:
                if f.get("geometry"):
                    geoms.append(shape(f["geometry"]))
                    props.append(f.get("properties", {}))
            self._geoms = geoms
            self._props = props
            self._tree  = STRtree(geoms)
            print(f"      [legal] Catastro SERNAGEOMIN: {len(geoms)} concesiones cargadas.")
            print(f"      [legal] Fuente: {source}")
        except Exception as e:
            print(f"      [legal] Error cargando catastro local ({e}). Usando REST.")
            self._usar_rest = True

    def _point_in_catastro(self, lon: float, lat: float) -> tuple[bool | str, str]:
        """
        Verifica si (lon, lat) está dentro de alguna concesión.

        Returns:
            (tiene_concesion, nombre_concesion)
            tiene_concesion puede ser True, False, o str(error) si REST falló.
        """
        punto = Point(lon, lat)

        # Estrategia 1: STRtree local
        if self._tree is not None:
            candidates = self._tree.query(punto)
            for i in candidates:
                if self._geoms[i].contains(punto):
                    nombre = self._props[i].get("nombre", "concesión sin nombre")
                    return True, nombre
            return False, ""

        # Estrategia 2: REST (solo si no hay local)
        resultado = _arcgis_point_query_rest(_SERNAGEOMIN_REST_URL, lon, lat)
        return resultado, ""

    def verificar(self, lat: float, lon: float, salar: str = "") -> dict:
        razones:  list[str] = []
        errores:  list[str] = []
        no_verif: list[str] = []

        # Capa 0 — Concesión SERNAGEOMIN (local STRtree o REST)
        resultado, nombre_concesion = self._point_in_catastro(lon, lat)

        if resultado is False:
            razones.append("expansión fuera de concesión SERNAGEOMIN")
        elif resultado is True:
            pass  # dentro de concesión — no ilegal por esta capa
        elif isinstance(resultado, str):
            print(f"        [legal] SERNAGEOMIN no disponible: {resultado}")
            errores.append(f"SERNAGEOMIN:{resultado}")

        # Capa 1 — RCA/SEA (placeholder)
        if _SEA_RCA_URL_PLACEHOLDER is None:
            no_verif.append("RCA/SEA (endpoint no disponible)")

        if razones:
            veredicto    = "ILEGAL"
            detail_parts = razones[:]
            if nombre_concesion:
                detail_parts.append(f"última concesión cercana: {nombre_concesion}")
            legal_detail = "; ".join(detail_parts)
        elif errores:
            veredicto    = "ERROR INFRAESTRUCTURA"
            legal_detail = "; ".join(errores)
        else:
            veredicto    = "REQUIERE VERIFICACIÓN"
            parts = []
            if nombre_concesion:
                parts.append(f"dentro de: {nombre_concesion}")
            if no_verif:
                parts.append(f"capas no verificables: {', '.join(no_verif)}")
            legal_detail = "; ".join(parts)

        return {"veredicto": veredicto, "legal_detail": legal_detail}


# ── Arquitectura Gaia Salares ─────────────────────────────────────────────────

class _GaiaSalaresNet(nn.Module):
    """ViT-S/16 backbone + binary MLP head (idéntico a GaiaV05)."""

    def __init__(self) -> None:
        super().__init__()
        self.backbone = timm.create_model(
            "vit_small_patch16_224",
            in_chans=12,
            num_classes=0,
            global_pool="token",
            pretrained=False,
        )
        self.classifier = nn.Sequential(
            nn.Linear(_EMBED_DIM, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.backbone(x))


def _build_salares_model(device: torch.device, model_path: Path) -> _GaiaSalaresNet:
    state = torch.load(model_path, map_location=device, weights_only=True)
    for key in ("model", "state_dict"):
        if key in state and isinstance(state[key], dict):
            state = state[key]
            break

    net = _GaiaSalaresNet().to(device)
    backbone_sd = {k[len("backbone."):]: v for k, v in state.items() if k.startswith("backbone.")}
    head_sd     = {k[len("classifier."):]: v for k, v in state.items() if k.startswith("classifier.")}

    net.backbone.load_state_dict(backbone_sd, strict=False)
    if head_sd:
        net.classifier.load_state_dict(head_sd, strict=True)

    for param in net.backbone.parameters():
        param.requires_grad_(False)
    return net


def _preprocess_chip(arr: np.ndarray) -> torch.Tensor:
    arr = np.clip(arr.astype(np.float32) / _S2_SCALE, 0.0, 1.0)
    t   = torch.tensor(arr.transpose(2, 0, 1), dtype=torch.float32).unsqueeze(0)
    return nn.functional.interpolate(t, size=(_INPUT_SIZE, _INPUT_SIZE), mode="bilinear", align_corners=False)


# ── Clasificador real ──────────────────────────────────────────────────────────

class GaiaSalaresClassifier:
    """
    Clasificador de piscinas de evaporación en salares.
    ViT-S/16 fine-tuned sobre chips S2 12 bandas con labels de expansión verificada.

    Carga gaia_salares_v01.pth si existe; si no, usa gaia_v05_amw_ssl4eo_v4.pth
    como backbone de transferencia (mismo backbone, head de minería amazónica —
    los resultados son indicativos, no calibrados para salares).
    """

    chip_bands: int = 12

    def __init__(self, model_path: Path | None = None) -> None:
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        if model_path is None:
            model_path = _SALARES_MODEL_PATH

        if Path(model_path).exists():
            self._model = _build_salares_model(self.device, Path(model_path))
            self._model.eval()
            self._label = f"GaiaSalares v0.1 [{Path(model_path).name}]"
            self._calibrated = True
        elif _FALLBACK_MODEL_PATH.exists():
            self._model = _build_salares_model(self.device, _FALLBACK_MODEL_PATH)
            self._model.eval()
            self._label = "GaiaSalares fallback [gaia_v05 backbone — no calibrado salares]"
            self._calibrated = False
        else:
            self._model = None
            self._label = "GaiaSalares sin pesos — prob=0.5"
            self._calibrated = False

        print(f"      {self._label}")

    def predecir(
        self,
        imagen_array: np.ndarray,
        coordenadas: tuple[float, float],
    ) -> dict:
        if self._model is None or imagen_array is None or imagen_array.max() == 0:
            return {
                "actividad":    "expansion_piscinas",
                "confianza":    0.5,
                "veredicto":    "REQUIERE VERIFICACIÓN",
                "legal_detail": "sin modelo — verificar manualmente",
            }

        tensor = _preprocess_chip(imagen_array).to(self.device)
        with torch.no_grad():
            prob = float(self._model(tensor).cpu().squeeze())

        actividad = "expansion_piscinas" if prob >= _GAIA_THRESHOLD else "normal"
        confianza = round(prob, 4)

        return {
            "actividad": actividad,
            "confianza": confianza,
            "veredicto": "REQUIERE VERIFICACIÓN",
            "legal_detail": "",
        }


# ── GEE: índice SWIR Salt Index ───────────────────────────────────────────────

def _get_s2_collection(aoi, start: str, end: str):
    """Colección Sentinel-2 SR filtrada por nube y AOI."""
    import ee
    return (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", CLOUD_COVER_MAX))
    )


def _ssi_composite(collection) -> "ee.Image":
    """
    Mediana del SWIR Salt Index = (B11 + B12) / 2 para toda la colección.

    Valores altos (>0.25 en DN/10000) indican sales o brine en superficie.
    Las piscinas de evaporación activas son muy brillantes en B11/B12.
    """
    import ee

    def add_ssi(img):
        b11 = img.select("B11")
        b12 = img.select("B12")
        ssi = b11.add(b12).divide(2).divide(10000).rename("SSI")
        return img.addBands(ssi)

    return collection.map(add_ssi).select("SSI").median()


def _detect_expansion(ssi_base, ssi_now) -> "tuple[ee.Image, ee.Image]":
    """
    Devuelve (delta_image, expansion_mask).

    expansion_mask = píxeles donde:
      - delta > SSI_EXPANSION_THRESHOLD  (crecimiento relativo)
      - ssi_now > SSI_ABSOLUTE_THRESHOLD (es realmente piscina/sal, no cambio de suelo)
    """
    import ee
    delta          = ssi_now.subtract(ssi_base).rename("SSI_delta")
    is_pool        = ssi_now.gt(SSI_ABSOLUTE_THRESHOLD)
    is_expanding   = delta.gt(SSI_EXPANSION_THRESHOLD)
    expansion_mask = is_pool.And(is_expanding).rename("SSI_expansion")
    return delta, expansion_mask


def _vectorize_expansion(
    expansion_mask,
    ssi_delta,
    aoi,
    scale: int = 20,
) -> list[dict]:
    """
    Convierte la máscara de expansión a polígonos vectoriales vía GEE.
    Devuelve lista de dicts con geometry (GeoJSON), ssi_delta, area_ha.
    """
    import ee
    from config import MAX_PIXELS

    vectors = expansion_mask.selfMask().reduceToVectors(
        geometry=aoi,
        scale=scale,
        geometryType="polygon",
        eightConnected=True,
        labelProperty="expansion",
        maxPixels=MAX_PIXELS,
        bestEffort=True,
    )

    stats = ssi_delta.reduceRegions(
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

        shp      = shape(geom)
        centroid = shp.centroid
        area_ha  = shp.area * (111_000 ** 2) / 10_000

        if area_ha < MIN_AREA_HA:
            continue

        results.append({
            "geometry":  geom,
            "lat":       round(centroid.y, 6),
            "lon":       round(centroid.x, 6),
            "ssi_delta": round(feat["properties"].get("mean", 0.0), 4),
            "area_ha":   round(area_ha, 2),
        })

    return results


# ── Severidad ──────────────────────────────────────────────────────────────────

def _assign_severity(ssi_delta: float, gaia_prob: float) -> str:
    if ssi_delta >= _SEV_HIGH_THR or (ssi_delta >= _SEV_MEDIUM_THR and gaia_prob > 0.65):
        return "alta"
    if ssi_delta >= _SEV_MEDIUM_THR:
        return "media"
    return "baja"


# ── Exportación de chips para entrenamiento ────────────────────────────────────

def _export_candidato(
    polygon_id: str,
    chip: np.ndarray,
    lat: float,
    lon: float,
    salar: str,
    ssi_delta: float,
    gaia_prob: float,
) -> None:
    _CANDIDATOS_DIR.mkdir(parents=True, exist_ok=True)
    _CANDIDATOS_CSV.parent.mkdir(parents=True, exist_ok=True)

    chip_filename = f"{polygon_id}.npy"
    np.save(_CANDIDATOS_DIR / chip_filename, chip)

    sev = _assign_severity(ssi_delta, gaia_prob)
    with _CSV_LOCK:
        write_header = not _CANDIDATOS_CSV.exists()
        with _CANDIDATOS_CSV.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(["chip_filename", "lat", "lon", "salar", "ssi_delta", "gaia_prob", "severidad"])
            writer.writerow([chip_filename, round(lat, 6), round(lon, 6), salar, round(ssi_delta, 4), round(gaia_prob, 4), sev])


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
    try:
        from gee_client import download_chip_12b
        import ee
        centroid = ee.Geometry.Point([lon, lat])
        return download_chip_12b(s2_image, centroid)
    except Exception as exc:
        print(f"        chip download fallido ({lon:.4f},{lat:.4f}): {exc}")
        return None


# ── Severidad ─────────────────────────────────────────────────────────────────

# ── Clasificación + legal por polígono ────────────────────────────────────────

def _classify_polygon(
    poly: dict,
    s2_image,
    classifier: GaiaSalaresClassifier,
    legal_checker: LegalCheckerSalares,
    classified_cache: dict[str, dict],
    salar_name: str = "",
    operador: str = "",
) -> dict | None:
    polygon_id = make_polygon_id(poly["lat"], poly["lon"])

    if polygon_id in classified_cache:
        prev = classified_cache[polygon_id]
        gaia_result = {
            "actividad":    prev.get("actividad", "expansion_piscinas"),
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
            _export_candidato(
                polygon_id, chip,
                poly["lat"], poly["lon"],
                salar_name, poly["ssi_delta"],
                gaia_result["confianza"],
            )
        else:
            gaia_result = {
                "actividad":    "expansion_piscinas",
                "confianza":    0.5,
                "veredicto":    "REQUIERE VERIFICACIÓN",
                "legal_detail": "chip no disponible",
            }

        legal = legal_checker.verificar(poly["lat"], poly["lon"], salar=salar_name)
        gaia_result["veredicto"]    = legal["veredicto"]
        gaia_result["legal_detail"] = legal["legal_detail"]

    # Descartar si Gaia no confirma presencia de piscina (aplica caché y nueva clasificación)
    if gaia_result["confianza"] < _GAIA_THRESHOLD:
        return None

    severity = _assign_severity(poly["ssi_delta"], gaia_result["confianza"])

    return {
        "id":             polygon_id,
        "salar":          salar_name,
        "operador":       operador,
        "lat":            poly["lat"],
        "lon":            poly["lon"],
        "detection_date": date.today().isoformat(),
        "ssi_delta":      poly["ssi_delta"],
        "area_ha":        poly["area_ha"],
        "severity":       severity,
        "actividad":      gaia_result["actividad"],
        "confianza":      gaia_result["confianza"],
        "veredicto":      gaia_result["veredicto"],
        "legal_detail":   gaia_result["legal_detail"],
        "geometry":       poly["geometry"],
    }


# ── Pipeline por salar ────────────────────────────────────────────────────────

def _run_salar(
    salar_name: str,
    salar_info: dict,
    baseline: tuple[str, str],
    analysis: tuple[str, str],
    classifier: GaiaSalaresClassifier,
    legal_checker: LegalCheckerSalares,
    classified_cache: dict[str, dict],
) -> list[dict]:
    """
    Ejecuta el pipeline SSI completo para un salar dado.
    Devuelve lista de dicts de alerta.
    """
    import ee
    from gee_client import aoi_geometry

    bbox     = salar_info["bbox"]
    operador = salar_info["operador"]
    print(f"  [{salar_name}] operador={operador}  AOI: {bbox}")

    aoi      = aoi_geometry(bbox)
    col_base = _get_s2_collection(aoi, *baseline)
    col_now  = _get_s2_collection(aoi, *analysis)

    n_base = col_base.size().getInfo()
    n_now  = col_now.size().getInfo()
    print(f"  [{salar_name}] S2 baseline: {n_base} imágenes, análisis: {n_now} imágenes")

    if n_base == 0 or n_now == 0:
        print(f"  [{salar_name}] Sin imágenes suficientes — salar omitido.")
        return []

    ssi_base = _ssi_composite(col_base)
    ssi_now  = _ssi_composite(col_now)
    ssi_delta, expansion_mask = _detect_expansion(ssi_base, ssi_now)

    polygons = _vectorize_expansion(expansion_mask, ssi_delta, aoi)
    print(f"  [{salar_name}] Polígonos de expansión detectados: {len(polygons)}")

    if not polygons:
        return []

    s2_composite = col_now.median().select(
        ["B1","B2","B3","B4","B5","B6","B7","B8","B8A","B9","B11","B12"]
    )

    alerts: list[dict] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(
                _classify_polygon,
                poly, s2_composite, classifier, legal_checker,
                classified_cache, salar_name, operador,
            ): i
            for i, poly in enumerate(polygons)
        }
        for fut in as_completed(futures):
            try:
                result = fut.result()
                if result is not None:
                    alerts.append(result)
            except Exception as exc:
                print(f"  [{salar_name}] Error clasificando polígono: {exc}")

    return alerts


# ── Guardar GeoJSON ───────────────────────────────────────────────────────────

def _save_geojson(alerts: list[dict], suffix: str = "") -> Path:
    today    = date.today().strftime("%Y%m%d")
    name     = f"alerts_chile_salares{('_' + suffix) if suffix else ''}_{today}.geojson"
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

def run_chile_salares(
    baseline: tuple[str, str] | None = None,
    analysis: tuple[str, str] | None = None,
    detection_date: date | None = None,
    salares: list[str] | None = None,
    reclassify: bool = False,
) -> dict:
    """
    Ejecuta el pipeline de expansión de piscinas sobre todos los salares priorizados.

    Args:
        baseline:       (start, end) — por defecto dynamic_date_windows()
        analysis:       (start, end) — por defecto dynamic_date_windows()
        detection_date: fecha de detección; por defecto hoy
        salares:        lista de claves de SALARES_PRIORITARIOS a procesar;
                        None = todos
        reclassify:     True = ignorar caché de clasificación anterior

    Returns:
        dict con total_alerts, output_path, severity, veredicto
    """
    authenticate_and_initialize()

    if baseline is None or analysis is None:
        baseline, analysis = dynamic_date_windows()

    active_salares = salares or list(SALARES_PRIORITARIOS.keys())
    print(f"\n[CHILE SALARES] baseline={baseline}  análisis={analysis}")
    print(f"  Salares a procesar: {active_salares}")

    classifier    = GaiaSalaresClassifier()
    legal_checker = LegalCheckerSalares()

    classified_cache: dict[str, dict] = {}
    if not reclassify:
        prev_files = sorted(OUTPUT_DIR.glob("alerts_chile_salares_*.geojson"))
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

    for salar_name in active_salares:
        if salar_name not in SALARES_PRIORITARIOS:
            print(f"  Salar desconocido: {salar_name} — omitido.")
            continue
        alerts = _run_salar(
            salar_name=salar_name,
            salar_info=SALARES_PRIORITARIOS[salar_name],
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

    print(f"\n[CHILE SALARES] Completado.")
    print(f"  Total alertas : {summary['total_alerts']}")
    print(f"  Severidad     : {summary['severity']}")
    print(f"  Veredicto     : {summary['veredicto']}")
    print(f"  Output        : {summary['output_path']}")

    return summary


# ── Prueba sin GEE: salar Atacama ─────────────────────────────────────────────

def dry_run_atacama() -> dict:
    """
    Simulación del pipeline sobre el Salar de Atacama sin conexión a GEE.

    Genera alertas sintéticas basadas en zonas conocidas de expansión de
    piscinas de evaporación (sector norte y sur del salar).
    Útil para validar el formato de salida y el flujo legal.
    """
    _HOTSPOTS = [
        # (lat, lon, ssi_delta, area_ha)
        (-23.30, -68.15, 0.22, 45.0),   # sector norte — zona SQM activa
        (-23.45, -68.12, 0.18, 32.0),   # sector norte-centro
        (-23.60, -68.10, 0.31, 78.5),   # sector central — mayor expansión reciente
        (-23.75, -68.08, 0.14, 21.3),   # sector centro-sur
        (-23.90, -68.06, 0.25, 56.8),   # sector sur — zona Albemarle
        (-23.20, -68.18, 0.09, 11.2),   # borde norte — expansión leve
        (-24.00, -68.04, 0.19, 38.7),   # extremo sur
    ]

    classifier    = GaiaSalaresClassifier()
    legal_checker = LegalCheckerSalares()

    alerts: list[dict] = []
    for lat, lon, delta, area_ha in _HOTSPOTS:
        polygon_id  = make_polygon_id(lat, lon)
        gaia_result = classifier.predecir(
            np.zeros((64, 64, 12), dtype=np.float32),
            (lat, lon),
        )

        severity = _assign_severity(delta, gaia_result["confianza"])
        half     = (area_ha / 10_000) ** 0.5 / 2
        geom     = {
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
            "id":             polygon_id,
            "salar":          "salar_atacama",
            "operador":       "SQM/Albemarle",
            "lat":            lat,
            "lon":            lon,
            "detection_date": date.today().isoformat(),
            "ssi_delta":      round(delta, 4),
            "area_ha":        area_ha,
            "severity":       severity,
            "actividad":      gaia_result["actividad"],
            "confianza":      gaia_result["confianza"],
            "veredicto":      gaia_result["veredicto"],
            "legal_detail":   gaia_result["legal_detail"],
            "geometry":       geom,
        })

    output_path = _save_geojson(alerts, suffix="dry_run_atacama")

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
        "mode":          "dry_run_atacama",
    }

    print(f"\n[DRY RUN ATACAMA]")
    print(f"  Alertas simuladas : {summary['total_alerts']}")
    print(f"  Severidad         : {summary['severity']}")
    print(f"  Veredicto         : {summary['veredicto']}")
    print(f"  Output            : {summary['output_path']}")

    return summary


# ── CLI directo ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Chile Salares — detección de expansión de piscinas de evaporación (SWIR SSI)."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Ejecutar simulación sobre salar Atacama sin GEE.")
    parser.add_argument("--salares", nargs="*", choices=list(SALARES_PRIORITARIOS.keys()),
                        help="Salares a procesar. Por defecto: todos.")
    parser.add_argument("--reclassify", action="store_true",
                        help="Ignorar caché de clasificación anterior.")
    args = parser.parse_args()

    if args.dry_run:
        dry_run_atacama()
    else:
        run_chile_salares(salares=args.salares, reclassify=args.reclassify)
