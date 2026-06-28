from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

# Area of interest: Peruvian Amazon [west, south, east, north]
AOI = [-75.5, -5.0, -73.5, -3.0]

# Named regions for --region CLI flag [west, south, east, north]
REGIONS: dict[str, list[float]] = {
    "peru":          [-75.5, -5.0,  -73.5,  -3.0],
    "colombia":      [-77.0, -1.0,  -67.0,   7.0],
    "brasil":        [-74.0, -15.0, -44.0,   5.0],
    "brasil_norte":  [-74.0,  -5.0, -52.0,   5.0],
    "brasil_oeste":   [-74.0, -15.0, -52.0,  -5.0],
    "brasil_oeste_1": [-74.0, -10.0, -63.0,  -5.0],
    "brasil_oeste_2": [-63.0, -10.0, -52.0,  -5.0],
    "brasil_oeste_3": [-74.0, -15.0, -63.0, -10.0],
    "brasil_oeste_4": [-63.0, -15.0, -52.0, -10.0],
    "brasil_oeste_4a": [-63.0, -15.0, -57.5, -10.0],
    "brasil_oeste_4b": [-57.5, -15.0, -52.0, -10.0],
    "brasil_este":   [-52.0,  -5.0, -44.0,   5.0],
    "brasil_sur":    [-52.0, -15.0, -44.0,  -5.0],
    "brasil_sur_a":  [-52.0, -15.0, -48.0,  -5.0],
    "brasil_sur_b":  [-48.0, -15.0, -44.0,  -5.0],
    "bolivia":       [-70.0, -18.0, -57.0,  -9.0],
    # Chile — extracción de áridos en ríos (dispatched to chile_aridos.py)
    "chile_aridos":  [-74.0, -46.0, -68.0, -18.0],
    "chile_norte":   [-70.5, -26.5, -68.5, -23.5],  # Atacama/Antofagasta
    # Chile — expansión piscinas de evaporación en salares (dispatched to chile_salares.py)
    "chile_salares": [-69.4, -27.1, -67.4, -23.1],  # envuelve los 5 salares prioritarios
}

def dynamic_date_windows(window_days: int = 60) -> tuple[tuple[str, str], tuple[str, str]]:
    """Return windows ending two years ago and today, respectively."""
    today = date.today()

    def months_ago(value: date, months: int) -> date:
        month_index = value.year * 12 + value.month - 1 - months
        year, month_zero_based = divmod(month_index, 12)
        month = month_zero_based + 1
        day = min(value.day, monthrange(year, month)[1])
        return value.replace(year=year, month=month, day=day)

    analysis_end   = today
    analysis_start = analysis_end - timedelta(days=window_days)
    baseline_end   = months_ago(today, 24)
    baseline_start = baseline_end - timedelta(days=window_days)
    fmt = lambda d: d.isoformat()
    return (fmt(baseline_start), fmt(baseline_end)), (fmt(analysis_start), fmt(analysis_end))


DATE_BASELINE, DATE_ANALYSIS = dynamic_date_windows()


# Maximum cloud cover percentage to accept an image
CLOUD_COVER_MAX = 20

# Minimum NDVI delta to flag as vegetation loss (15%)
NDVI_LOSS_THRESHOLD = 0.15

# Minimum area in hectares to generate an alert
MIN_AREA_HA = 1.0

# GEE reduceToVectors pixel budget — keeps requests within Colaborador quota
MAX_PIXELS = 1_000_000

# Directory where GeoJSON outputs are written
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

# Google Drive folder used for batch chip export (created automatically by GEE)
DRIVE_FOLDER = "SentinelWatch_chips"

# Local cache directory for downloaded chips (created on first write)
CACHE_DIR = Path("cache") / "chips"
