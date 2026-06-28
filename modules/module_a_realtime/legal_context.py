"""
Enriquecimiento de contexto legal para alertas de incendio confirmadas del Módulo A.

Fuentes:
  - WDPA (Protected Planet API / GEE fallback): áreas protegidas de Chile
  - OSM vía osmnx: distancia a caminos cercanos

Cache agresivo:
  - WDPA se re-descarga solo si tiene más de 30 días → data/legal/wdpa_chile.gpkg
  - OSM se cachea por celda de grilla 0.1° → data/legal/osm_cache/
"""

import logging
import math
import time
from pathlib import Path

log = logging.getLogger(__name__)

try:
    import geopandas as gpd
    from shapely.geometry import Point
    _GEO_OK = True
except ImportError:
    _GEO_OK = False
    log.warning("[LegalContext] geopandas/shapely no disponibles — enriquecimiento deshabilitado.")

try:
    import osmnx as ox
    _OSM_OK = True
except ImportError:
    _OSM_OK = False
    log.warning("[LegalContext] osmnx no disponible — road_distance_km no disponible.")

from .config import LEGAL_CACHE_DIR, OSM_CACHE_DIR, WDPA_TOKEN

_WDPA_CACHE: Path = LEGAL_CACHE_DIR / "wdpa_chile.gpkg"
_OSM_CACHE_DIR: Path = OSM_CACHE_DIR
_WDPA_MAX_AGE_DAYS = 30
_CRS_PROJECTED = "EPSG:32719"  # UTM zona 19S — metros, válido para Chile centro-sur

_STRICT_IUCN = {"I", "IA", "IB", "II"}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_fresh(path: Path, max_days: int) -> bool:
    if not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) / 86400 < max_days


# ---------------------------------------------------------------------------
# WDPA download strategies
# ---------------------------------------------------------------------------

def _download_wdpa_api(token: str) -> "gpd.GeoDataFrame | None":
    """Descarga áreas protegidas de Chile vía Protected Planet API paginada."""
    try:
        import requests
        from shapely.geometry import shape as shapely_shape
    except ImportError:
        return None

    records = []
    page = 1
    per_page = 50
    log.info("[LegalContext] Descargando WDPA Chile desde Protected Planet API...")

    while True:
        url = (
            f"https://api.protectedplanet.net/v3/protected_areas"
            f"?with_geometry=true&country=CHL&token={token}"
            f"&per_page={per_page}&page={page}"
        )
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            areas = resp.json().get("protected_areas", [])
        except Exception as exc:
            log.warning("[LegalContext] Error en página %d WDPA API: %s", page, exc)
            break

        if not areas:
            break

        for area in areas:
            geom_raw = area.get("geojson") or area.get("geometry")
            if not geom_raw:
                continue
            try:
                geom = shapely_shape(geom_raw) if isinstance(geom_raw, dict) else None
            except Exception:
                continue
            if geom is None:
                continue
            iucn = area.get("iucn_category")
            records.append({
                "geometry": geom,
                "name": area.get("name"),
                "iucn_cat": iucn.get("name") if isinstance(iucn, dict) else iucn,
                "wdpaid": area.get("wdpaid"),
            })

        if len(areas) < per_page:
            break
        page += 1

    if not records:
        log.warning("[LegalContext] WDPA API devolvió 0 registros con geometría.")
        return None

    gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")
    log.info("[LegalContext] WDPA Chile descargado: %d áreas.", len(gdf))
    return gdf


def _download_wdpa_gee() -> "gpd.GeoDataFrame | None":
    """Fallback GEE: obtiene áreas protegidas de Chile vía Earth Engine."""
    try:
        import ee
        from shapely.geometry import shape as shapely_shape
    except ImportError:
        log.warning("[LegalContext] earthengine-api no instalado — GEE no disponible.")
        return None

    try:
        # Use project-aware initializer from auth.py when available
        try:
            from auth import initialize as _ee_init
            _ee_init()
        except Exception:
            import ee as _ee
            _ee.Initialize()
        # Filter to Biobío + buffer instead of all Chile — avoids GEE memory limit
        from .config import BBOX
        aoi = ee.Geometry.BBox(
            BBOX["lon_min"] - 1.0, BBOX["lat_min"] - 1.0,
            BBOX["lon_max"] + 1.0, BBOX["lat_max"] + 1.0,
        )
        features = (
            ee.FeatureCollection("WCMC/WDPA/current/polygons")
            .filterBounds(aoi)
            .getInfo()
            .get("features", [])
        )
        records = []
        for f in features:
            try:
                geom = shapely_shape(f["geometry"])
                props = f.get("properties", {})
                records.append({
                    "geometry": geom,
                    "name": props.get("NAME"),
                    "iucn_cat": props.get("IUCN_CAT"),
                    "wdpaid": props.get("WDPAID"),
                })
            except Exception:
                continue
        if not records:
            return None
        gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")
        log.info("[LegalContext] WDPA Chile vía GEE: %d áreas.", len(gdf))
        return gdf
    except Exception as exc:
        log.warning("[LegalContext] GEE fallback falló: %s", exc)
        return None


def _load_wdpa() -> "gpd.GeoDataFrame | None":
    """Carga WDPA Chile desde caché, o lo descarga si está desactualizado."""
    if not _GEO_OK:
        return None

    if _cache_fresh(_WDPA_CACHE, _WDPA_MAX_AGE_DAYS):
        try:
            return gpd.read_file(_WDPA_CACHE)
        except Exception as exc:
            log.warning("[LegalContext] Error leyendo caché WDPA: %s — re-descargando.", exc)

    _WDPA_CACHE.parent.mkdir(parents=True, exist_ok=True)
    gdf = _download_wdpa_api(WDPA_TOKEN) if WDPA_TOKEN else None
    if gdf is None:
        gdf = _download_wdpa_gee()

    if gdf is not None:
        try:
            gdf.to_file(_WDPA_CACHE, driver="GPKG")
            log.info("[LegalContext] WDPA Chile guardado en caché: %s", _WDPA_CACHE)
        except Exception as exc:
            log.warning("[LegalContext] No se pudo guardar caché WDPA: %s", exc)

    return gdf


# ---------------------------------------------------------------------------
# OSM roads
# ---------------------------------------------------------------------------

def _osm_cache_path(lat: float, lon: float) -> Path:
    grid_lat = math.floor(lat * 10) / 10
    grid_lon = math.floor(lon * 10) / 10
    return _OSM_CACHE_DIR / f"roads_{grid_lat:.1f}_{grid_lon:.1f}.gpkg"


def _load_osm_roads(lat: float, lon: float) -> "gpd.GeoDataFrame | None":
    """Carga caminos OSM desde caché de celda 0.1° o descarga si no existe."""
    if not _GEO_OK or not _OSM_OK:
        return None

    cache_file = _osm_cache_path(lat, lon)

    if cache_file.exists():
        try:
            return gpd.read_file(cache_file)
        except Exception as exc:
            log.warning("[LegalContext] Error leyendo caché OSM: %s", exc)

    try:
        roads = ox.features_from_point((lat, lon), tags={"highway": True}, dist=5000)
        if roads.empty:
            return None
        roads = roads[
            roads.geometry.geom_type.isin(["LineString", "MultiLineString"])
        ].copy()
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        roads.to_file(cache_file, driver="GPKG")
        log.info("[LegalContext] OSM roads cacheadas: %s (%d features)", cache_file, len(roads))
        return roads
    except Exception as exc:
        log.warning("[LegalContext] No se pudo obtener roads OSM: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _compute_risk_score(
    wdpa_overlap: bool,
    iucn_cat: str | None,
    wdpa_distance_km: float | None,
    road_distance_km: float | None,
) -> int:
    score = 0
    road_near = road_distance_km is not None and road_distance_km < 0.5
    wdpa_dist = wdpa_distance_km if wdpa_distance_km is not None else 9999

    if wdpa_overlap:
        normalized = (iucn_cat or "").strip().upper().replace(" ", "")
        score += 40 if normalized in _STRICT_IUCN else 25
        if road_near:
            score += 20 + 15  # road bonus + inside-PA multiplier
    else:
        if 0 < wdpa_dist <= 1.0:
            score += 15
        if road_near:
            score += 20

    return min(score, 100)


def _risk_label(score: int) -> str:
    if score < 0:
        return "DESCONOCIDO"
    if score >= 60:
        return "ALTO"
    if score >= 30:
        return "MEDIO"
    return "BAJO"


# ---------------------------------------------------------------------------
# Enricher
# ---------------------------------------------------------------------------

class LegalContextEnricher:
    """
    Singleton de enriquecimiento legal para alertas confirmadas.
    Carga WDPA en memoria al primer uso; OSM se cachea por celda de grilla.
    """

    def __init__(self) -> None:
        self._wdpa: "gpd.GeoDataFrame | None" = None
        self._wdpa_proj: "gpd.GeoDataFrame | None" = None
        self._wdpa_loaded = False

    def _ensure_wdpa(self) -> None:
        if self._wdpa_loaded:
            return
        self._wdpa_loaded = True
        self._wdpa = _load_wdpa()
        if self._wdpa is not None and not self._wdpa.empty:
            try:
                self._wdpa_proj = self._wdpa.to_crs(_CRS_PROJECTED)
            except Exception as exc:
                log.warning("[LegalContext] No se pudo proyectar WDPA: %s", exc)

    def enrich(self, lat: float, lon: float) -> dict:
        """
        Retorna contexto legal para la coordenada.
        Devuelve resultado parcial con legal_risk_score = -1 si las fuentes fallan.
        """
        result: dict = {
            "wdpa_overlap": False,
            "wdpa_name": None,
            "wdpa_iucn_cat": None,
            "wdpa_distance_km": None,
            "conaf_forest_type": None,
            "road_distance_km": None,
            "legal_risk_score": -1,
            "legal_summary": "Contexto legal no disponible",
        }

        if not _GEO_OK:
            return result

        # --- WDPA ---
        wdpa_ok = False
        try:
            self._ensure_wdpa()
            if self._wdpa_proj is not None and not self._wdpa_proj.empty:
                point_proj = (
                    gpd.GeoDataFrame(geometry=[Point(lon, lat)], crs="EPSG:4326")
                    .to_crs(_CRS_PROJECTED)
                    .geometry.iloc[0]
                )
                contains_mask = self._wdpa_proj.geometry.contains(point_proj)
                if contains_mask.any():
                    hit = self._wdpa_proj[contains_mask].iloc[0]
                    result["wdpa_overlap"] = True
                    result["wdpa_name"] = hit.get("name")
                    result["wdpa_iucn_cat"] = hit.get("iucn_cat")
                    result["wdpa_distance_km"] = 0.0
                else:
                    dists_m = self._wdpa_proj.geometry.distance(point_proj)
                    nearest_idx = dists_m.idxmin()
                    nearest = self._wdpa_proj.loc[nearest_idx]
                    result["wdpa_distance_km"] = round(dists_m[nearest_idx] / 1000, 3)
                    result["wdpa_name"] = nearest.get("name")
                    result["wdpa_iucn_cat"] = nearest.get("iucn_cat")
                wdpa_ok = True
        except Exception as exc:
            log.warning("[LegalContext] Error consultando WDPA en (%.4f, %.4f): %s", lat, lon, exc)

        # --- OSM roads ---
        road_ok = False
        try:
            roads = _load_osm_roads(lat, lon)
            if roads is not None and not roads.empty:
                point_proj = (
                    gpd.GeoDataFrame(geometry=[Point(lon, lat)], crs="EPSG:4326")
                    .to_crs(_CRS_PROJECTED)
                    .geometry.iloc[0]
                )
                roads_proj = roads.to_crs(_CRS_PROJECTED)
                result["road_distance_km"] = round(
                    roads_proj.geometry.distance(point_proj).min() / 1000, 3
                )
                road_ok = True
        except Exception as exc:
            log.warning("[LegalContext] Error consultando OSM roads en (%.4f, %.4f): %s", lat, lon, exc)

        # --- Score + summary ---
        # Keep -1 only if every data source failed entirely
        if wdpa_ok or road_ok:
            score = _compute_risk_score(
                result["wdpa_overlap"],
                result["wdpa_iucn_cat"],
                result["wdpa_distance_km"],
                result["road_distance_km"],
            )
            result["legal_risk_score"] = score
        else:
            score = -1
        label = _risk_label(score)

        wdpa_dist = result["wdpa_distance_km"]
        road_dist = result["road_distance_km"]

        if result["wdpa_overlap"]:
            area_part = (
                f"Dentro de {result['wdpa_name'] or 'área protegida'}"
                + (f" (IUCN {result['wdpa_iucn_cat']})" if result["wdpa_iucn_cat"] else "")
            )
        elif wdpa_dist is not None and wdpa_dist < 1.0:
            area_part = (
                f"A {wdpa_dist:.1f}km de {result['wdpa_name'] or 'área protegida'}"
                + (f" (IUCN {result['wdpa_iucn_cat']})" if result["wdpa_iucn_cat"] else "")
            )
        else:
            area_part = "Sin área protegida cercana"

        if road_dist is not None and road_dist < 1.0:
            road_part = f"carretera a {road_dist * 1000:.0f}m"
        elif road_dist is not None:
            road_part = f"carretera a {road_dist:.1f}km"
        else:
            road_part = "sin acceso vial cercano"

        result["legal_summary"] = f"{area_part} — {road_part} — riesgo legal {label}"
        log.info("[LegalContext] (%.4f, %.4f) → score=%d %s", lat, lon, score, label)

        return result


# Singleton — importar directamente desde otros módulos:
#   from .legal_context import legal_enricher
legal_enricher = LegalContextEnricher()
