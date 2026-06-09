"""
SentinelWatch — clasificador principal basado en EfficientNet-B2 propio.

Reemplaza el flujo ForestNet con el modelo entrenado localmente (modelo_v02_completo.pth).
4 bandas de entrada: B4/B3/B2/B8 (R, G, B, NIR)
4 clases de salida : normal | deforestacion | agricultura | mineria

Veredicto legal:
  ILEGAL              → coordenadas dentro de un área protegida (WDPA)
  Requiere verificación → coordenadas fuera de área protegida
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

import ee
import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from shapely.geometry import Point, shape
from shapely.strtree import STRtree
from torchvision import models, transforms

# ── Constantes ────────────────────────────────────────────────────────────────

MODEL_PATH = Path(__file__).parent / "model" / "modelo_v02_completo.pth"
WDPA_LOCAL_PATH = Path(__file__).parent / "model" / "areas_protegidas_latam.geojson"

CLASES = ["normal", "deforestacion", "agricultura", "mineria"]
NUM_CLASES = len(CLASES)
NUM_BANDAS = 4          # B4, B3, B2, B8
TAMANIO_ENTRADA = 224   # píxeles

_S2_SCALE = 10_000.0

# Estadísticas de normalización calculadas sobre las 4 bandas del modelo v02.
# Canal 4 (NIR/B8) usa la media/std de la banda "red" de ImageNet como proxy.
_MEAN_4B = [0.485, 0.456, 0.406, 0.485]
_STD_4B  = [0.229, 0.224, 0.225, 0.229]

WDPA_ASSET = "WCMC/WDPA/current/polygons"

# Bounding box de LATAM (oeste, sur, este, norte)
_LATAM_BBOX = (-82, -56, -34, 13)


# ── Resultado tipado ──────────────────────────────────────────────────────────

class ResultadoClasificacion(TypedDict):
    actividad: str
    confianza: float
    veredicto: str


# ── Arquitectura: EfficientNet-B2 con 4 bandas de entrada ────────────────────

def _crear_modelo_4b(num_clases: int) -> nn.Module:
    """
    torchvision EfficientNet-B2 adaptado para 4 canales de entrada y 4 clases.

    Cambios respecto al modelo base:
      - features[0][0]: Conv2d 3→4 canales; el 4.º canal se inicializa con el 1.º (rojo).
      - classifier: Dropout(0.3) + Linear(in_features, num_clases)
    """
    model = models.efficientnet_b2(weights=None)

    # --- Primera capa conv: 3 → 4 canales ---
    conv_orig = model.features[0][0]
    conv_nuevo = nn.Conv2d(
        in_channels=NUM_BANDAS,
        out_channels=conv_orig.out_channels,
        kernel_size=conv_orig.kernel_size,
        stride=conv_orig.stride,
        padding=conv_orig.padding,
        bias=conv_orig.bias is not None,
    )
    with torch.no_grad():
        conv_nuevo.weight[:, :3, :, :] = conv_orig.weight
        conv_nuevo.weight[:, 3:, :, :] = conv_orig.weight[:, :1, :, :]

    model.features[0][0] = conv_nuevo

    # --- Classifier: Dropout(0.3) + Linear → num_clases ---
    in_features = model.classifier[1].in_features
    model.classifier = nn.Sequential(
        nn.Dropout(p=0.3, inplace=True),
        nn.Linear(in_features, num_clases),
    )

    return model


# ── Preprocesado ──────────────────────────────────────────────────────────────

_transform = transforms.Compose([
    transforms.Resize((TAMANIO_ENTRADA, TAMANIO_ENTRADA)),
    transforms.ToTensor(),
    transforms.Normalize(_MEAN_4B[:3], _STD_4B[:3]),   # solo para PIL (3 canales)
])


def _preprocesar(imagen_array: np.ndarray) -> torch.Tensor:
    """
    Convierte un array [H, W, C] (C=3 o 4) en un tensor [1, 4, H, W] normalizado.

    Entrada: uint16 [0, 10000] o float32 [0, 1].
    Si solo hay 3 canales, el 4.º (NIR) se replica desde el canal rojo.
    """
    arr = imagen_array.astype(np.float32)
    if arr.max() > 1.0:
        arr = arr / _S2_SCALE
    arr = np.clip(arr, 0.0, 1.0)

    # Asegurar 4 canales
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr, arr], axis=-1)
    elif arr.shape[-1] == 3:
        arr = np.concatenate([arr, arr[:, :, :1]], axis=-1)
    elif arr.shape[-1] != 4:
        raise ValueError(f"Se esperan 3 o 4 bandas, se recibieron {arr.shape[-1]}")

    # Normalizar cada canal individualmente
    mean = np.array(_MEAN_4B, dtype=np.float32)
    std  = np.array(_STD_4B,  dtype=np.float32)

    # Redimensionar con PIL canal a canal
    canales = []
    for c in range(NUM_BANDAS):
        canal = (arr[:, :, c] - mean[c]) / std[c]
        img_canal = Image.fromarray(
            np.clip(canal * 127.5 + 127.5, 0, 255).astype(np.uint8)
        ).resize((TAMANIO_ENTRADA, TAMANIO_ENTRADA), Image.BILINEAR)
        canales.append(np.array(img_canal, dtype=np.float32) / 127.5 - 1.0)

    tensor = torch.tensor(np.stack(canales, axis=0), dtype=torch.float32)
    return tensor.unsqueeze(0)


# ── Áreas protegidas WDPA (descarga única + verificación local) ───────────────

_WDPA_PAGE_SIZE = 500
_WDPA_SIMPLIFY_M = 0.01   # tolerancia en grados (~1 km); reduce vértices sin perder forma
_WDPA_PROPS = ["NAME", "IUCN_CAT"]


def _paginar_coleccion(coleccion: ee.FeatureCollection) -> list[dict]:
    """
    Descarga una FeatureCollection de GEE en páginas de _WDPA_PAGE_SIZE para
    evitar el límite de respuesta. Usa toList(count, offset).
    """
    features: list[dict] = []
    offset = 0
    while True:
        lote: list[dict] = coleccion.toList(_WDPA_PAGE_SIZE, offset).getInfo()
        features.extend(lote)
        print(f"  …página offset={offset}: {len(lote)} polígonos recibidos")
        if len(lote) < _WDPA_PAGE_SIZE:
            break
        offset += _WDPA_PAGE_SIZE
    return features


def _descargar_wdpa_latam() -> None:
    """
    Descarga todos los polígonos WDPA de LATAM desde GEE y los guarda en
    WDPA_LOCAL_PATH. Aplica simplificación de geometría y selección de atributos
    para mantenerse dentro de los límites de respuesta de GEE.
    """
    oeste, sur, este, norte = _LATAM_BBOX
    region = ee.Geometry.BBox(oeste, sur, este, norte)
    wdpa = (
        ee.FeatureCollection(WDPA_ASSET)
        .filterBounds(region)
        .select(_WDPA_PROPS)
        .map(lambda f: f.simplify(_WDPA_SIMPLIFY_M))
    )

    print("Descargando polígonos WDPA de LATAM desde GEE (solo primera vez)…")
    features = _paginar_coleccion(wdpa)

    geojson = {"type": "FeatureCollection", "features": features}
    WDPA_LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with WDPA_LOCAL_PATH.open("w", encoding="utf-8") as f:
        json.dump(geojson, f)
    print(f"Guardado: {WDPA_LOCAL_PATH} ({len(features)} polígonos)")


def _cargar_wdpa_tree() -> STRtree:
    """
    Carga el GeoJSON local y construye un STRtree de shapely para búsquedas rápidas.
    """
    with WDPA_LOCAL_PATH.open("r", encoding="utf-8") as f:
        geojson = json.load(f)
    geometrias = [
        shape(feat["geometry"])
        for feat in geojson.get("features", [])
        if feat.get("geometry") is not None
    ]
    return STRtree(geometrias)


# ── Clasificador principal ────────────────────────────────────────────────────

class SentinelClassifier:
    """
    Clasificador de actividad basado en EfficientNet-B2 entrenado con 4 bandas.

    Clases: normal | deforestacion | agricultura | mineria
    Veredicto legal determinado por cruce con WDPA vía Google Earth Engine.
    """

    def __init__(
        self,
        model_path: str | Path = MODEL_PATH,
        device: str | None = None,
    ):
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        self.model = _crear_modelo_4b(NUM_CLASES)
        self.model.to(self.device)

        ruta = Path(model_path)
        if not ruta.exists():
            raise FileNotFoundError(f"No se encontró el modelo en: {ruta}")

        state = torch.load(ruta, map_location=self.device, weights_only=True)
        # Admite checkpoints guardados como state_dict o como {'model': state_dict}
        if isinstance(state, dict) and "model" in state and not any(
            k.startswith("conv_stem") for k in state
        ):
            state = state["model"]
        self.model.load_state_dict(state)
        print(f"Modelo cargado desde {ruta}")

        # Polígonos WDPA: descarga única si no existe el archivo local
        if not WDPA_LOCAL_PATH.exists():
            _descargar_wdpa_latam()
        self._wdpa_tree: STRtree | None = _cargar_wdpa_tree()
        print(f"Índice WDPA cargado ({WDPA_LOCAL_PATH.name})")

    def predecir(
        self,
        imagen_array: np.ndarray,
        coordenadas: tuple[float, float],
    ) -> ResultadoClasificacion:
        """
        Clasifica una imagen satelital y determina su estado legal.

        Args:
            imagen_array: Array numpy [H, W, C] con C=3 (RGB) o C=4 (RGB+NIR).
                          Valores en [0, 10000] (SR Sentinel-2) o [0, 1].
            coordenadas:  Tupla (latitud, longitud) del punto analizado.

        Returns:
            Diccionario con:
              actividad  — clase predicha (normal/deforestacion/agricultura/mineria)
              confianza  — probabilidad en [0, 1]
              veredicto  — "ILEGAL" o "Requiere verificación"
        """
        lat, lon = coordenadas

        # Inferencia
        tensor = _preprocesar(imagen_array).to(self.device)
        self.model.eval()
        with torch.no_grad():
            probs = torch.softmax(self.model(tensor), dim=-1).cpu()[0]

        idx = int(probs.argmax())
        actividad = CLASES[idx]
        confianza = round(float(probs[idx]), 4)

        # Veredicto legal (verificación local, sin llamadas GEE por alerta)
        try:
            punto = Point(lon, lat)
            candidatos = self._wdpa_tree.query(punto)
            protegida = any(
                self._wdpa_tree.geometries[i].contains(punto)
                for i in candidatos
            )
            veredicto = "ILEGAL" if protegida else "Requiere verificación"
        except Exception as exc:
            veredicto = f"Requiere verificación (error WDPA: {exc})"

        return ResultadoClasificacion(
            actividad=actividad,
            confianza=confianza,
            veredicto=veredicto,
        )


# ── Smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    clf = SentinelClassifier()

    dummy_rgb  = np.random.randint(0, 5000, (64, 64, 3), dtype=np.uint16)
    dummy_rgbn = np.random.randint(0, 5000, (64, 64, 4), dtype=np.uint16)

    # Sin GEE inicializado — el veredicto usa la rama de excepción
    for arr, nombre in [(dummy_rgb, "3 bandas"), (dummy_rgbn, "4 bandas")]:
        res = clf.predecir(arr, coordenadas=(-3.5, -62.0))
        print(
            f"[{nombre}] actividad={res['actividad']}  "
            f"confianza={res['confianza']}  veredicto={res['veredicto']}"
        )
