from datetime import date, timedelta
from pathlib import Path

# Area of interest: Peruvian Amazon [west, south, east, north]
AOI = [-75.5, -5.0, -73.5, -3.0]

# Named regions for --region CLI flag [west, south, east, north]
REGIONS: dict[str, list[float]] = {
    "peru":     [-75.5, -5.0,  -73.5,  -3.0],
    "colombia": [-77.0, -1.0,  -67.0,   7.0],
    "brasil":   [-74.0, -15.0, -44.0,   5.0],
    "bolivia":  [-70.0, -18.0, -57.0,  -9.0],
}

# Static periods that are known-good (June-August: low cloud cover in the Amazon).
# Used as fallback until the adaptive window logic is wired into the API.
DATE_BASELINE = ("2023-06-01", "2023-08-31")
DATE_ANALYSIS  = ("2024-06-01", "2024-08-31")


def dynamic_date_windows(window_days: int = 60) -> tuple[tuple[str, str], tuple[str, str]]:
    """Returns (baseline, analysis) date tuples relative to today.

    Adaptive window logic (up to 120 days) will replace this in the
    FastAPI iteration. Called explicitly by the API layer; not used at
    import time so the static fallback above remains active.
    """
    today = date.today()
    analysis_end   = today
    analysis_start = today - timedelta(days=window_days)
    baseline_end   = analysis_start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=window_days)
    fmt = lambda d: d.isoformat()
    return (fmt(baseline_start), fmt(baseline_end)), (fmt(analysis_start), fmt(analysis_end))


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
