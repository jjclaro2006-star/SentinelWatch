from pathlib import Path

import numpy as np

CACHE_DIR = Path("cache") / "chips"


def make_polygon_id(lat: float, lon: float) -> str:
    """Stable, filename-safe ID derived from centroid rounded to 4 decimal places.

    4 decimal degrees ≈ 11 m at the equator — sufficient to recognise the same
    polygon across re-runs even when vertex coordinates shift slightly.
    """
    return f"{round(lat, 4):.4f}_{round(lon, 4):.4f}"


def load_chip(polygon_id: str) -> "np.ndarray | None":
    """Returns the cached chip array, or None if not yet cached."""
    path = CACHE_DIR / f"{polygon_id}.npy"
    return np.load(path) if path.exists() else None


def save_chip(polygon_id: str, chip: np.ndarray) -> None:
    """Persists a chip array to cache/chips/{polygon_id}.npy."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(CACHE_DIR / f"{polygon_id}.npy", chip)
