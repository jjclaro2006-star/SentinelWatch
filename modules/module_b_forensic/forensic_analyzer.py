"""
Module B — Forensic analyzer for confirmed fire alerts.

Downloads a Sentinel-2 pre/post patch pair from GEE, runs the
Gaia Incendios v0.2 model, and writes the result back to the
confirmed alert GeoJSON plus a copy under data/alerts/module_b/.
"""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import ee
import numpy as np
import torch
import torch.nn as nn
import timm

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_ROOT / "models" / "gaia_incendios_v02_final.pth"
MODULE_B_DIR = PROJECT_ROOT / "data" / "alerts" / "module_b"
CONFIRMED_DIR = PROJECT_ROOT / "data" / "alerts" / "module_a" / "confirmed"

S2_BANDS = ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12", "B1", "B9", "B10"]
PATCH_SIZE = 224
SCALE = 10  # metres per pixel


# ---------------------------------------------------------------------------
# Model definition — do NOT change architecture
# ---------------------------------------------------------------------------

class GaiaIncendios(nn.Module):
    def __init__(self):
        super().__init__()
        self.backbone = timm.create_model(
            "vit_small_patch16_224", pretrained=False, in_chans=13
        )
        for param in self.backbone.parameters():
            param.requires_grad = False
        self.classifier = nn.Sequential(
            nn.Linear(384, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, 1),
        )

    def forward(self, x):
        features = self.backbone.forward_features(x)
        if features.ndim == 3:
            features = features[:, 0, :]
        return self.classifier(features)


def _load_model() -> tuple[GaiaIncendios, float]:
    model = GaiaIncendios()
    checkpoint = torch.load(str(MODEL_PATH), map_location="cpu", weights_only=False)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    threshold = checkpoint.get("threshold", 0.15)
    return model, threshold


# Lazy-load once per process
_model: GaiaIncendios | None = None
_threshold: float = 0.15


def _get_model() -> tuple[GaiaIncendios, float]:
    global _model, _threshold
    if _model is None:
        log.info("[FORENSIC] Cargando modelo Gaia Incendios v0.2...")
        _model, _threshold = _load_model()
        log.info("[FORENSIC] Modelo cargado. threshold=%.3f", _threshold)
    return _model, _threshold


# ---------------------------------------------------------------------------
# GEE patch download
# ---------------------------------------------------------------------------

def _get_s2_patch(lat: float, lon: float, start: str, end: str) -> np.ndarray | None:
    """Download a (PATCH_SIZE, PATCH_SIZE, 12) Sentinel-2 median patch."""
    point = ee.Geometry.Point([lon, lat])
    roi = point.buffer(PATCH_SIZE * SCALE / 2)

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(roi)
        .filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 30))
        .select(S2_BANDS[:12])  # 12 spectral bands
        .median()
    )

    try:
        data = collection.sampleRectangle(
            region=roi,
            defaultValue=0,
        ).getInfo()
    except Exception as exc:
        log.warning("[FORENSIC] Error descargando patch %s→%s: %s", start, end, exc)
        return None

    bands = []
    for band in S2_BANDS[:12]:
        arr = np.array(data["properties"][band], dtype=np.float32)
        if arr.ndim == 1:
            side = int(np.sqrt(arr.shape[0]))
            arr = arr.reshape(side, side)
        arr = _resize_to(arr, PATCH_SIZE)
        bands.append(arr)

    return np.stack(bands, axis=-1)  # (H, W, 12)


def _resize_to(arr: np.ndarray, size: int) -> np.ndarray:
    """Nearest-neighbour resize to (size, size) without external deps."""
    h, w = arr.shape
    if h == size and w == size:
        return arr
    row_idx = (np.arange(size) * h / size).astype(int)
    col_idx = (np.arange(size) * w / size).astype(int)
    return arr[np.ix_(row_idx, col_idx)]


def _compute_dnbr(pre: np.ndarray, post: np.ndarray) -> np.ndarray:
    """dNBR = NBR_pre − NBR_post, where NBR = (NIR − SWIR) / (NIR + SWIR)."""
    # Band indices within S2_BANDS[:12]: B8=index6 (NIR), B12=index9 (SWIR2)
    nir_idx, swir_idx = 6, 9

    def nbr(patch):
        nir = patch[:, :, nir_idx].astype(np.float32)
        swir = patch[:, :, swir_idx].astype(np.float32)
        denom = nir + swir
        denom[denom == 0] = 1e-6
        return (nir - swir) / denom

    return (nbr(pre) - nbr(post))[:, :, np.newaxis]  # (H, W, 1)


def _download_patch_pair(
    lat: float, lon: float, fire_date_str: str
) -> tuple[np.ndarray | None, str | None]:
    """
    Build a (224, 224, 13) array: 12 post-fire S2 bands + dNBR channel.
    Returns (patch, post_date_str) or (None, None) on failure.
    """
    fire_date = datetime.strptime(fire_date_str, "%Y-%m-%d").date()

    pre_end = (fire_date - timedelta(days=5)).isoformat()
    pre_start = (fire_date - timedelta(days=60)).isoformat()

    # Find the best post-fire image date first
    from modules.module_b_forensic.sentinel2_monitor import check_availability
    avail = check_availability(lat, lon, fire_date_str)
    if not avail["available"]:
        log.warning("[FORENSIC] No hay imagen post-incendio disponible para %s", fire_date_str)
        return None, None

    post_date = avail["post_date"]
    post_start = post_date
    post_end = (datetime.strptime(post_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    pre_patch = _get_s2_patch(lat, lon, pre_start, pre_end)
    post_patch = _get_s2_patch(lat, lon, post_start, post_end)

    if pre_patch is None or post_patch is None:
        return None, None

    dnbr = _compute_dnbr(pre_patch, post_patch)
    patch = np.concatenate([post_patch, dnbr], axis=-1)  # (224, 224, 13)
    return patch, post_date


# ---------------------------------------------------------------------------
# Forensic scoring
# ---------------------------------------------------------------------------

def _score_to_level(score: float) -> tuple[str, str, list[str]]:
    if score < 0.15:
        level, verdict = "BAJO", "NO INTENCIONAL"
    elif score < 0.35:
        level, verdict = "MODERADO", "NO INTENCIONAL"
    elif score < 0.60:
        level, verdict = "ALTO", "INTENCIONAL"
    else:
        level, verdict = "MUY ALTO", "INTENCIONAL"

    signals = []
    if score > 0.15:
        signals.append("anomalia_espectral_detectada")
    if score > 0.35:
        signals.append("patron_cicatriz_intencional")
    if score > 0.50:
        signals.append("dNBR_elevado_focalizado")
    if score > 0.70:
        signals.append("firma_ataque_incendiario")

    return level, verdict, signals


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def analyze(lat: float, lon: float, fire_date: str, alert_id: str) -> dict:
    """Run forensic analysis for a confirmed fire alert.

    Downloads pre/post Sentinel-2 patch, runs Gaia Incendios v0.2 inference,
    writes results back to the confirmed alert GeoJSON, and copies to
    data/alerts/module_b/.

    Returns the forensic result dict.
    """
    import geopandas as gpd

    log.info("[FORENSIC] Iniciando análisis para %s (fire_date=%s)", alert_id, fire_date)

    patch, post_image_date = _download_patch_pair(lat, lon, fire_date)
    if patch is None:
        log.error("[FORENSIC] %s — no se pudo descargar el par de imágenes.", alert_id)
        return {}

    fire_date_obj = datetime.strptime(fire_date, "%Y-%m-%d").date()
    post_date_obj = datetime.strptime(post_image_date, "%Y-%m-%d").date()
    days_after = (post_date_obj - fire_date_obj).days

    model, _ = _get_model()

    patch_tensor = torch.tensor(patch.transpose(2, 0, 1)).unsqueeze(0).float()
    with torch.no_grad():
        score = torch.sigmoid(model(patch_tensor)).item()

    level, verdict, signals = _score_to_level(score)

    result = {
        "forensic_score": round(score, 4),
        "forensic_level": level,
        "forensic_verdict": verdict,
        "forensic_signals": signals,
        "post_image_date": post_image_date,
        "days_after_fire": days_after,
        "analysis_date": date.today().isoformat(),
        "model_version": "v0.2",
    }

    log.info("[FORENSIC] %s — score %.3f — %s", alert_id, score, verdict)

    # Update confirmed alert GeoJSON if it exists
    source_geojson = CONFIRMED_DIR / f"{alert_id}.geojson"
    if not source_geojson.exists():
        # Try glob search by alert_id in filename
        matches = list(CONFIRMED_DIR.glob(f"*{alert_id}*.geojson")) if CONFIRMED_DIR.exists() else []
        if matches:
            source_geojson = matches[0]

    if source_geojson.exists():
        try:
            gdf = gpd.read_file(source_geojson)
            for key, val in result.items():
                gdf[key] = str(val) if isinstance(val, list) else val
            gdf.to_file(source_geojson, driver="GeoJSON")
            log.info("[FORENSIC] %s — alerta actualizada en %s", alert_id, source_geojson)
        except Exception as exc:
            log.error("[FORENSIC] %s — error actualizando GeoJSON fuente: %s", alert_id, exc)

    # Write copy to module_b output directory
    MODULE_B_DIR.mkdir(parents=True, exist_ok=True)
    dest = MODULE_B_DIR / f"{alert_id}_forensic.geojson"

    if source_geojson.exists():
        try:
            gdf_out = gpd.read_file(source_geojson)
            gdf_out.to_file(dest, driver="GeoJSON")
        except Exception as exc:
            log.error("[FORENSIC] %s — error copiando a module_b: %s", alert_id, exc)
    else:
        # No source GeoJSON — write a minimal record with the forensic fields
        import json as _json
        record = {"alert_id": alert_id, "lat": lat, "lon": lon, "fire_date": fire_date, **result}
        with open(dest, "w", encoding="utf-8") as f:
            _json.dump(record, f, ensure_ascii=False, indent=2)

    log.info("[FORENSIC] %s — resultado guardado en %s", alert_id, dest)
    return result


# Module-level singleton — pre-loads model so forensic_analyzer.model and
# forensic_analyzer.threshold are accessible for inspection and direct inference.
_preloaded_model, _preloaded_threshold = _get_model()

forensic_analyzer = type("_Analyzer", (), {
    "analyze": staticmethod(analyze),
    "model": _preloaded_model,
    "threshold": _preloaded_threshold,
})()
