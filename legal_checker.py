"""
legal_checker.py — Verificación legal multi-capa para alertas de minería ilegal.

Capas implementadas:
  0. Áreas protegidas WDPA          — STRtree pasado desde el clasificador
  1. Territorios indígenas           — IBC Perú / FUNAI Brasil / IGAC Colombia
  2. Concesiones mineras activas     — INGEMMET / ANM Brasil / ANM Colombia
  3. Permisos ambientales vigentes   — SENACE / IBAMA
  4. Zonas de amortiguamiento        — buffer ~10 km sobre polígonos WDPA

Lógica del veredicto:
  Sin concesión minera (verificado)           → ILEGAL
  En territorio indígena                      → ILEGAL
  En área protegida WDPA                      → ILEGAL
  En zona de amortiguamiento                  → ILEGAL
  Con concesión, sin permiso ambiental        → ILEGAL
  Con concesión, sin conflictos verificados   → REQUIERE VERIFICACIÓN

  Nota: si una capa retorna None (no verificable), no se cuenta como ILEGAL
  por sí sola — se reporta en legal_detail para seguimiento manual.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

# ── Rutas de caché ────────────────────────────────────────────────────────────

_LEGAL_DIR = Path(__file__).parent / "model" / "legal"
_REQUEST_TIMEOUT = 20  # segundos por consulta REST

# ── Constantes de veredicto ───────────────────────────────────────────────────

VEREDICTO_ILEGAL    = "ILEGAL"
VEREDICTO_VERIFICAR = "REQUIERE VERIFICACIÓN"

# Buffer de zona de amortiguamiento: ~10 km expresado en grados geográficos.
# A latitudes ecuatoriales 1° ≈ 111 km; 0.09° ≈ 10 km.
_BUFFER_DEG = 0.09


# ── Bounding boxes por país (lon_min, lat_min, lon_max, lat_max) ──────────────

_COUNTRY_BBOX: dict[str, tuple[float, float, float, float]] = {
    "peru":     (-82.0, -18.5, -68.0,  0.5),
    "brazil":   (-74.0, -34.0, -28.0,  6.0),
    "colombia": (-79.5,  -4.5, -66.0, 13.0),
    "bolivia":  (-69.7, -22.9, -57.5, -9.7),
}


def _infer_country(lon: float, lat: float) -> str | None:
    for country, (lon_min, lat_min, lon_max, lat_max) in _COUNTRY_BBOX.items():
        if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
            return country
    return None


# ── Helpers WFS / ArcGIS REST ─────────────────────────────────────────────────

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _wfs_fetch(
    base_url: str,
    typename: str,
    max_features: int = 20_000,
    timeout: int = 15,
) -> list[dict]:
    """Descarga features de un endpoint WFS 1.0. Devuelve [] en error."""
    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": typename,
        "outputFormat": "application/json",
        "maxFeatures": str(max_features),
    }
    try:
        resp = requests.get(
            base_url, params=params, timeout=timeout,
            headers={"User-Agent": _BROWSER_UA},
        )
        resp.raise_for_status()
        return resp.json().get("features", [])
    except Exception as exc:
        print(f"      WFS {typename}: no disponible ({exc})")
        return []


def _arcgis_point_query(url: str, lon: float, lat: float, where: str = "1=1") -> bool | None:
    """
    Consulta ArcGIS REST MapServer por punto.

    Returns:
        True  — existe al menos una feature que contiene el punto.
        False — ninguna feature en ese punto.
        None  — consulta falló (servicio no disponible).
    """
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "where": where,
        "outFields": "OBJECTID",
        "returnCountOnly": "true",
        "f": "json",
    }
    try:
        resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            return None
        return int(data.get("count", 0)) > 0
    except Exception:
        return None


def _wfs_point_query(base_url: str, typename: str, lon: float, lat: float) -> bool | None:
    """Consulta WFS con filtro CQL INTERSECTS para verificar permisos puntuales."""
    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": typename,
        "outputFormat": "application/json",
        "maxFeatures": "1",
        "CQL_FILTER": f"INTERSECTS(the_geom,POINT({lon} {lat}))",
    }
    try:
        resp = requests.get(base_url, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return len(resp.json().get("features", [])) > 0
    except Exception:
        return None


# ── Caché local de capas poligonales ─────────────────────────────────────────

def _cache_path(layer: str) -> Path:
    return _LEGAL_DIR / f"{layer}.geojson"


def _load_cached(layer: str) -> list[dict] | None:
    p = _cache_path(layer)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("features", [])
    except Exception:
        return None


def _save_cached(layer: str, features: list[dict]) -> None:
    _LEGAL_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(layer).write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )


def _build_tree(features: list[dict]) -> STRtree:
    geoms = [shape(f["geometry"]) for f in features if f.get("geometry")]
    return STRtree(geoms)


def _point_in_tree(tree: STRtree, punto: Point) -> bool:
    candidates = tree.query(punto)
    return any(tree.geometries[i].contains(punto) for i in candidates)


# ── Fuentes de datos ──────────────────────────────────────────────────────────

# Territorios indígenas — WFS (descarga única, caché local)
_TI_SOURCES: list[dict] = [
    {
        "layer":    "ti_brazil",
        "url":      "https://geoserver.funai.gov.br/geoserver/Funai/ows",
        "typenames": [
            "Funai:tis_amazonia_legal_poligonais",  # TI na Amazônia Legal (actualizado mensalmente)
            "Funai:tis_poligonais",                 # fallback: todas as TI do Brasil
        ],
        "desc": "FUNAI Brasil — terras indígenas Amazônia Legal",
    },
]
# Nota: IBC Perú (geo.ibcperu.org) y IGAC Colombia (geoportal.igac.gov.co) no responden
# desde este entorno. El respaldo pan-amazónico es RAISG REST (_check_ti_raisg).

# Territorios indígenas — RAISG ArcGIS REST (toda la Amazonia, consulta por punto)
# Fuente: https://www.raisg.org — actualizado mensualmente, acceso público
_RAISG_TI_BASE = (
    "https://geo.socioambiental.org/webadaptor2/rest/services/raisg/raisg_tis_N/MapServer"
)
_RAISG_TI_LAYERS = [2, 1]   # 2=Territorios Indígenas (pan-Amazonia), 1=CN Perú inscritas

# Concesiones mineras — ArcGIS REST (consulta por punto)
_CM_ENDPOINTS: dict[str, str] = {
    "peru": (
        "https://geocatmin.ingemmet.gob.pe/arcgis/rest/services"
        "/SERV_CONCESIONES_MINERAS/MapServer/0/query"
    ),
    "brazil": (
        "https://geo.anm.gov.br/arcgis/rest/services"
        "/ProcessosMinerarios/MapServer/0/query"
    ),
    "colombia": (
        "https://serviciodatos.anm.gov.co/arcgis/rest/services"
        "/ANM/CatastroMinero/MapServer/0/query"
    ),
    "bolivia": (
        "https://geo.minenergias.gob.bo/arcgis/rest/services"
        "/Mineria/ConcesionesMineras/MapServer/0/query"
    ),
}

# Permisos ambientales — WFS/REST (consulta por punto)
_PA_SOURCES: dict[str, dict] = {
    "peru": {
        "url":      "https://geo.senace.gob.pe/geoserver/senace/ows",
        "typename": "senace:certificaciones_ambientales",
    },
    "brazil": {
        "url":      "https://geogft.ibama.gov.br/geoserver/ibama/ows",
        "typename": "ibama:licencas_ativas",
    },
}


# ── Clase principal ───────────────────────────────────────────────────────────

class LegalChecker:
    """
    Verificador legal multi-capa para alertas de deforestación/minería.

    Se instancia una vez por sesión (en el clasificador). Descarga y cachea
    territorios indígenas la primera vez; hace consultas REST por punto para
    concesiones mineras y permisos ambientales.

    Args:
        wdpa_tree: STRtree ya construido con polígonos WDPA.
    """

    def __init__(self, wdpa_tree: STRtree) -> None:
        self._wdpa_tree = wdpa_tree
        # Capa 4: Zona de amortiguamiento — se evalúa por distancia al vuelo,
        # sin pre-bufferizar todos los polígonos WDPA (evita O(n) init lento).

        # Capa 1: Territorios indígenas
        self._ti_trees: dict[str, STRtree] = self._load_all_ti()

    # ── Inicialización de capas poligonales ───────────────────────────────────

    def _load_all_ti(self) -> dict[str, STRtree]:
        trees: dict[str, STRtree] = {}
        for src in _TI_SOURCES:
            layer = src["layer"]
            features = _load_cached(layer)

            if features is None:
                print(f"      Descargando {src['desc']}…")
                features = []
                for typename in src["typenames"]:
                    features = _wfs_fetch(src["url"], typename)
                    if features:
                        break
                if features:
                    _save_cached(layer, features)
                    print(f"      {layer}: {len(features)} territorios guardados en caché.")
                else:
                    print(f"      {layer}: no disponible — capa omitida.")
                    continue
            else:
                print(f"      {layer}: {len(features)} territorios desde caché.")

            trees[layer] = _build_tree(features)
        return trees

    # ── Verificaciones individuales ───────────────────────────────────────────

    def _check_area_protegida(self, punto: Point) -> bool:
        candidates = self._wdpa_tree.query(punto)
        return any(self._wdpa_tree.geometries[i].contains(punto) for i in candidates)

    def _check_zona_amortiguamiento(self, punto: Point) -> bool:
        # Expandir el bbox de búsqueda por _BUFFER_DEG para capturar candidatos cercanos.
        # Solo se evalúa la distancia real para los polígonos que el STRtree devuelve,
        # evitando pre-bufferizar todos los polígonos WDPA en init.
        query_area = punto.buffer(_BUFFER_DEG)
        candidates = self._wdpa_tree.query(query_area)
        return any(
            self._wdpa_tree.geometries[i].distance(punto) <= _BUFFER_DEG
            for i in candidates
        )

    def _check_territorio_indigena(self, punto: Point) -> bool:
        return any(_point_in_tree(tree, punto) for tree in self._ti_trees.values())

    def _check_ti_raisg(self, lon: float, lat: float) -> bool | None:
        """
        Consulta RAISG ArcGIS REST para territorios indígenas en toda la Amazonia.

        Cubre Perú, Colombia, Venezuela, Bolivia, Ecuador, Brasil y demás países.
        Se usa como respaldo cuando no hay caché WFS local disponible.

        Returns True/False si el servicio responde; None si no está disponible.
        """
        any_responded = False
        for layer_id in _RAISG_TI_LAYERS:
            result = _arcgis_point_query(
                f"{_RAISG_TI_BASE}/{layer_id}/query", lon, lat
            )
            if result is True:
                return True
            if result is False:
                any_responded = True
        return False if any_responded else None

    def _check_concesion_minera(self, lon: float, lat: float, country: str | None) -> bool | None:
        """
        Consulta ArcGIS REST para concesiones mineras activas.

        Returns True/False si el servicio responde; None si no está disponible.
        """
        endpoint = _CM_ENDPOINTS.get(country) if country else None
        if not endpoint:
            return None
        return _arcgis_point_query(endpoint, lon, lat)

    def _check_permiso_ambiental(self, lon: float, lat: float, country: str | None) -> bool | None:
        """
        Consulta SENACE (Perú) o IBAMA (Brasil) por permisos ambientales vigentes.

        Returns True/False si el servicio responde; None si no está disponible.
        """
        src = _PA_SOURCES.get(country) if country else None
        if not src:
            return None
        return _wfs_point_query(src["url"], src["typename"], lon, lat)

    # ── Veredicto principal ───────────────────────────────────────────────────

    def verificar(self, lat: float, lon: float) -> dict:
        """
        Ejecuta todas las capas y devuelve veredicto detallado.

        Returns:
            {
                "veredicto":    "ILEGAL" | "REQUIERE VERIFICACIÓN",
                "legal_detail": "motivo1, motivo2" | "" | "capas no verificables: ...",
                "capas": {
                    "area_protegida":       bool,
                    "zona_amortiguamiento": bool,
                    "territorio_indigena":  bool,
                    "concesion_minera":     bool | None,
                    "permiso_ambiental":    bool | None,
                }
            }
        """
        punto   = Point(lon, lat)
        country = _infer_country(lon, lat)
        razones:    list[str] = []
        no_verif:   list[str] = []
        capas:      dict      = {}

        # Capa 0 — Área protegida WDPA
        en_ap = self._check_area_protegida(punto)
        capas["area_protegida"] = en_ap
        if en_ap:
            razones.append("área protegida WDPA")

        # Capa 4 — Zona de amortiguamiento (solo si no está ya dentro del AP)
        en_za = (not en_ap) and self._check_zona_amortiguamiento(punto)
        capas["zona_amortiguamiento"] = en_za
        if en_za:
            razones.append("zona de amortiguamiento")

        # Capa 1 — Territorio indígena
        # Primero revisa caché WFS local (FUNAI Brasil); si no encuentra, consulta RAISG REST.
        en_ti_local = self._check_territorio_indigena(punto)
        if en_ti_local:
            en_ti: bool | None = True
        else:
            en_ti = self._check_ti_raisg(lon, lat)   # bool | None
        capas["territorio_indigena"] = en_ti
        if en_ti is True:
            razones.append("territorio indígena")
        elif en_ti is None:
            no_verif.append("territorio indígena")

        # Capas 2-3 — Solo se consultan si las capas locales (0/1/4) no dan ILEGAL.
        # Evita 20 s de timeout por punto cuando el veredicto ya está resuelto.
        if razones:
            capas["concesion_minera"] = None
            capas["permiso_ambiental"] = None
        else:
            # Capa 2 — Concesión minera
            tiene_cm = self._check_concesion_minera(lon, lat, country)
            capas["concesion_minera"] = tiene_cm
            if tiene_cm is False:
                razones.append("sin concesión minera vigente")
            elif tiene_cm is None:
                no_verif.append("concesión minera")

            # Capa 3 — Permiso ambiental (solo relevante cuando hay concesión)
            if tiene_cm is True:
                tiene_pa = self._check_permiso_ambiental(lon, lat, country)
                capas["permiso_ambiental"] = tiene_pa
                if tiene_pa is False:
                    razones.append("sin permiso ambiental vigente (SENACE/IBAMA)")
                elif tiene_pa is None:
                    no_verif.append("permiso ambiental")
            else:
                capas["permiso_ambiental"] = None

        # ── Veredicto ────────────────────────────────────────────────────────
        if razones:
            veredicto    = VEREDICTO_ILEGAL
            legal_detail = "; ".join(razones)
        else:
            veredicto = VEREDICTO_VERIFICAR
            legal_detail = (
                f"capas no verificables: {', '.join(no_verif)}" if no_verif else ""
            )

        return {
            "veredicto":    veredicto,
            "legal_detail": legal_detail,
            "capas":        capas,
        }
