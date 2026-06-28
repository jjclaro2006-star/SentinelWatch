from pathlib import Path

# NASA FIRMS API key
FIRMS_MAP_KEY: str = "0adc0d60f32c1132462ab5ee0badf4e8"

# Bounding box Región del Biobío, Chile
BBOX = {
    "lon_min": -73.5,
    "lat_min": -38.5,
    "lon_max": -71.0,
    "lat_max": -36.5,
}

# Intervalo de polling en horas
POLL_INTERVAL_HOURS: int = 3

# Umbral mínimo de confianza VIIRS (0–100)
MIN_CONFIDENCE: int = 70

# Fuentes VIIRS a consultar
FIRMS_SOURCES: list[str] = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"]

# Ventana de deduplicación temporal (horas)
DEDUP_TIME_WINDOW_HOURS: int = 3

# Radio de deduplicación espacial (metros)
DEDUP_RADIUS_M: float = 375.0

# Raíz del proyecto (dos niveles arriba de este archivo)
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

# Directorio de salida de alertas
ALERTS_OUTPUT_PATH: Path = PROJECT_ROOT / "data" / "alerts" / "module_a"

# Directorio de logs
LOGS_PATH: Path = PROJECT_ROOT / "logs"

# ADDED: legal_context
WDPA_TOKEN: str = ""  # fill in from protectedplanet.net/requests
LEGAL_CACHE_DIR: Path = PROJECT_ROOT / "data" / "legal"
OSM_CACHE_DIR: Path = PROJECT_ROOT / "data" / "legal" / "osm_cache"
