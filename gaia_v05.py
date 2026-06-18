"""
Gaia v0.5.4 — Binary illegal-mining detector.

Architecture:
  Backbone  : ViT-S/16 from SSL4EO-S12, frozen at inference
  Head      : Linear(384→256) → ReLU → Dropout(0.3) → Linear(256→1) → Sigmoid
  Input     : 12-band Sentinel-2 [H, W, 12], raw DN values ÷ 10 000
  Output    : scalar probability; >0.10 → minería ilegal detectada (calibrado en campo)

Weight files (models/):
  gaia_v05_amw_ssl4eo_v4.pth  — full fine-tuned model (backbone + head, 12 ch)
  B13_vits16_moco_0099.pth    — SSL4EO MoCo-v3 pre-trained backbone (13 ch, reference)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

import numpy as np
import timm
import torch
import torch.nn as nn
import torch.nn.functional as F
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from legal_checker import LegalChecker

# ── Rutas ─────────────────────────────────────────────────────────────────────

_MODELS_DIR    = Path(__file__).parent / "models"
MODEL_PATH     = _MODELS_DIR / "gaia_v05_amw_ssl4eo_v4.pth"
BACKBONE_PATH  = _MODELS_DIR / "B13_vits16_moco_0099.pth"

WDPA_LOCAL_PATH = Path(__file__).parent / "model" / "areas_protegidas_latam.geojson"

# ── Constantes ────────────────────────────────────────────────────────────────

S2_BANDS     = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B9", "B11", "B12"]
NUM_BANDAS   = 12
INPUT_SIZE   = 224
_S2_SCALE    = 10_000.0
_EMBED_DIM   = 384   # ViT-S/16 hidden dimension
_THRESHOLD   = 0.10  # field-calibrated: Huepetuhe mining=0.198, dense forest=0.005-0.037

_SSL4EO_URL = "https://github.com/zhu-xlab/SSL4EO-S12.git"
_SSL4EO_DIR = Path(__file__).parent / "SSL4EO-S12"

WDPA_ASSET   = "WCMC/WDPA/current/polygons"
_LATAM_BBOX  = (-82, -56, -34, 13)


# ── Resultado tipado ──────────────────────────────────────────────────────────

class ResultadoClasificacion(TypedDict):
    actividad:    str
    confianza:    float
    veredicto:    str
    legal_detail: str


# ── SSL4EO repo (clona si no existe) ─────────────────────────────────────────

def _ensure_ssl4eo_repo() -> None:
    if _SSL4EO_DIR.exists():
        return
    print(f"Clonando SSL4EO-S12 en {_SSL4EO_DIR} …")
    subprocess.run(
        ["git", "clone", "--depth=1", _SSL4EO_URL, str(_SSL4EO_DIR)],
        check=True,
    )
    src = str(_SSL4EO_DIR / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


# ── Arquitectura ──────────────────────────────────────────────────────────────

class _GaiaV05Net(nn.Module):
    """ViT-S/16 backbone + binary MLP head."""

    def __init__(self) -> None:
        super().__init__()
        self.backbone = timm.create_model(
            "vit_small_patch16_224",
            in_chans=NUM_BANDAS,
            num_classes=0,        # devuelve embedding CLS [B, 384]
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
        feats = self.backbone(x)        # [B, 384]
        return self.classifier(feats)   # [B, 1]


def _build_model(device: torch.device) -> _GaiaV05Net:
    """
    Carga pesos fine-tuned desde MODEL_PATH.

    El state_dict tiene claves 'backbone.*' + 'classifier.*'.
    Se carga con strict=False para tolerar claves internas de timm que
    no tengan parámetros (e.g. Identity layers).
    """
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Pesos del modelo no encontrados: {MODEL_PATH}")

    state = torch.load(MODEL_PATH, map_location=device, weights_only=True)

    # Admite checkpoints anidados bajo 'model' o 'state_dict'
    for key in ("model", "state_dict"):
        if key in state and isinstance(state[key], dict):
            state = state[key]
            break

    model = _GaiaV05Net().to(device)

    # Cargar backbone y clasificador por separado para evitar colisiones de claves
    backbone_sd = {k[len("backbone."):]: v for k, v in state.items() if k.startswith("backbone.")}
    head_sd     = {k[len("classifier."):]: v for k, v in state.items() if k.startswith("classifier.")}

    missing_bb, unexpected_bb = model.backbone.load_state_dict(backbone_sd, strict=False)
    model.classifier.load_state_dict(head_sd, strict=True)

    if missing_bb:
        print(f"      Aviso Gaia v0.5: claves de backbone no encontradas en checkpoint: {missing_bb[:4]}")
    if unexpected_bb:
        print(f"      Aviso Gaia v0.5: claves inesperadas en backbone: {unexpected_bb[:4]}")

    # Congelar backbone durante inferencia
    for param in model.backbone.parameters():
        param.requires_grad_(False)

    print(f"Gaia v0.5.4 cargado desde {MODEL_PATH}")
    return model


# ── Preprocesado ──────────────────────────────────────────────────────────────

def _preprocesar(imagen_array: np.ndarray) -> torch.Tensor:
    """
    [H, W, 12] (DN raw S2) → tensor [1, 12, 224, 224] normalizado ÷ 10 000.

    Uses direct float32 bilinear resize (no uint8 quantisation) to match the
    training pipeline, which applied img / 10000 and then resized as float.
    """
    if imagen_array.ndim != 3 or imagen_array.shape[-1] != NUM_BANDAS:
        raise ValueError(
            f"Se esperan {NUM_BANDAS} bandas [H, W, 12], "
            f"se recibió shape {imagen_array.shape}"
        )

    arr = np.clip(imagen_array.astype(np.float32) / _S2_SCALE, 0.0, 1.0)  # [H, W, 12]

    # [12, H, W] → resize float → [1, 12, 224, 224]
    tensor = torch.tensor(arr.transpose(2, 0, 1), dtype=torch.float32).unsqueeze(0)
    tensor = torch.nn.functional.interpolate(
        tensor, size=(INPUT_SIZE, INPUT_SIZE), mode="bilinear", align_corners=False
    )
    return tensor  # [1, 12, 224, 224]


# ── WDPA (reutiliza la lógica de sentinel_classifier) ────────────────────────

_WDPA_PAGE_SIZE = 500
_WDPA_PROPS     = ["NAME", "IUCN_CAT"]


def _cargar_wdpa_tree() -> STRtree:
    with WDPA_LOCAL_PATH.open("r", encoding="utf-8") as f:
        geojson = json.load(f)
    geoms = [
        shape(feat["geometry"])
        for feat in geojson.get("features", [])
        if feat.get("geometry") is not None
    ]
    return STRtree(geoms)


def _descargar_wdpa_latam() -> None:
    import ee  # importación tardía para no requerir GEE en pruebas offline

    oeste, sur, este, norte = _LATAM_BBOX
    region = ee.Geometry.BBox(oeste, sur, este, norte)
    wdpa = (
        ee.FeatureCollection(WDPA_ASSET)
        .filterBounds(region)
        .select(_WDPA_PROPS)
        .map(lambda f: f.simplify(0.01))
    )
    print("Descargando polígonos WDPA de LATAM …")
    features: list[dict] = []
    offset = 0
    while True:
        lote: list[dict] = wdpa.toList(_WDPA_PAGE_SIZE, offset).getInfo()
        features.extend(lote)
        if len(lote) < _WDPA_PAGE_SIZE:
            break
        offset += _WDPA_PAGE_SIZE
    WDPA_LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with WDPA_LOCAL_PATH.open("w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)
    print(f"WDPA guardado: {len(features)} polígonos")


# ── Clasificador público ──────────────────────────────────────────────────────

class GaiaV05Classifier:
    """
    Clasificador binario de minería ilegal con ViT-S/16 (SSL4EO).

    Interfaz idéntica a SentinelClassifier para drop-in replacement:
      predecir(imagen_array [H,W,12], coordenadas (lat, lon)) → ResultadoClasificacion

    Atributo chip_bands = 12 para que alerts.py use el caché correcto.
    """

    chip_bands: int = NUM_BANDAS  # usado por alerts.py para elegir caché

    def __init__(
        self,
        model_path: str | Path = MODEL_PATH,
        device: str | None = None,
    ) -> None:
        _ensure_ssl4eo_repo()

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        global MODEL_PATH
        MODEL_PATH = Path(model_path)

        self.model = _build_model(self.device)
        self.model.eval()

        if not WDPA_LOCAL_PATH.exists():
            _descargar_wdpa_latam()
        self._wdpa_tree: STRtree = _cargar_wdpa_tree()
        print(f"Índice WDPA cargado ({WDPA_LOCAL_PATH.name})")

        # Verificador legal multi-capa (TI, concesiones, permisos, buffer WDPA)
        self._legal = LegalChecker(self._wdpa_tree)

    def predecir(
        self,
        imagen_array: np.ndarray,
        coordenadas: tuple[float, float],
    ) -> ResultadoClasificacion:
        """
        Clasifica un chip de 12 bandas S2 y determina veredicto legal.

        Args:
            imagen_array: [H, W, 12] — valores DN Sentinel-2 en [0, 10 000].
            coordenadas:  (latitud, longitud) del centroide del polígono.

        Returns:
            actividad    — "mineria" o "normal"
            confianza    — probabilidad en [0, 1]
            veredicto    — "ILEGAL" o "REQUIERE VERIFICACIÓN"
            legal_detail — razones del veredicto separadas por "; "
        """
        lat, lon = coordenadas

        tensor = _preprocesar(imagen_array).to(self.device)
        with torch.no_grad():
            prob = float(self.model(tensor).cpu().squeeze())

        actividad = "mineria" if prob >= _THRESHOLD else "normal"
        confianza = round(prob if prob >= _THRESHOLD else 1.0 - prob, 4)

        # Veredicto legal multi-capa
        try:
            resultado_legal = self._legal.verificar(lat, lon)
            veredicto    = resultado_legal["veredicto"]
            legal_detail = resultado_legal["legal_detail"]
        except Exception as exc:
            veredicto    = "REQUIERE VERIFICACIÓN"
            legal_detail = f"error en verificación legal: {exc}"

        return ResultadoClasificacion(
            actividad=actividad,
            confianza=confianza,
            veredicto=veredicto,
            legal_detail=legal_detail,
        )


# ── Smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=str(MODEL_PATH))
    args = parser.parse_args()

    clf = GaiaV05Classifier(model_path=args.model)
    dummy = np.random.randint(0, 5000, (64, 64, 12), dtype=np.uint16).astype(np.float32)
    res = clf.predecir(dummy, coordenadas=(-3.5, -62.0))
    print(f"actividad={res['actividad']}  confianza={res['confianza']}  veredicto={res['veredicto']}")
