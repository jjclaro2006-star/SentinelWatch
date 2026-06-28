"""
Filtrado geoespacial y por confianza de detecciones FIRMS.
"""

import logging

import geopandas as gpd
from shapely.geometry import box

from .config import BBOX, MIN_CONFIDENCE

log = logging.getLogger(__name__)

_BIOBIO_BOX = box(BBOX["lon_min"], BBOX["lat_min"], BBOX["lon_max"], BBOX["lat_max"])


def filter_biobio(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Filtra el GeoDataFrame al bounding box del Biobío y aplica el umbral
    de confianza configurado. Agrega la columna 'region'.
    """
    if gdf.empty:
        return gdf

    before = len(gdf)

    # Clip al bbox
    gdf = gdf[gdf.geometry.within(_BIOBIO_BOX)].copy()
    log.info("Filtro geoespacial Biobío: %d → %d detecciones.", before, len(gdf))

    # Normalizar columna confidence (VIIRS la entrega como int o como string "n","l","h")
    if gdf["confidence"].dtype == object:
        # MODIS usa 'l'/'n'/'h', VIIRS NRT usa porcentaje entero; mapear strings a valores numéricos
        _str_map = {"l": 30, "n": 60, "h": 90}
        gdf["confidence"] = gdf["confidence"].apply(
            lambda v: _str_map.get(str(v).lower(), 0) if not str(v).isdigit() else int(v)
        )
    else:
        gdf["confidence"] = gdf["confidence"].astype(int)

    before_conf = len(gdf)
    gdf = gdf[gdf["confidence"] >= MIN_CONFIDENCE].copy()
    log.info("Filtro confianza >= %d: %d → %d detecciones.", MIN_CONFIDENCE, before_conf, len(gdf))

    gdf["region"] = "biobio_chile"

    # ADDED: fp_mask
    from modules.module_a_realtime.fp_mask import fp_mask
    before_fp = len(gdf)
    gdf = gdf[~gdf.apply(lambda r: fp_mask.is_masked(r.latitude, r.longitude), axis=1)]
    log.info("Filtro fp_mask: %d → %d detecciones.", before_fp, len(gdf))

    return gdf.reset_index(drop=True)
