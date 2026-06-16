"""
SentinelWatch — clasificador principal basado en EfficientNet-B2 propio.

Modelo gaia_v04_s1s2.pth — fusión Sentinel-2 + Sentinel-1.
6 bandas de entrada: B4/B3/B2/B8 (S2) + VV/VH (S1)
6 clases de salida : normal | deforestacion | agricultura | mineria | incendio | asentamiento

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
from torchvision import models

# ── Constantes ────────────────────────────────────────────────────────────────

MODEL_PATH = Path(__file__).parent / "model" / "gaia_v04_s1s2.pth"
WDPA_LOCAL_PATH = Path(__file__).parent / "model" / "areas_protegidas_latam.geojson"

CLASES = ["normal", "deforestacion", "agricultura", "mineria", "incendio", "asentamiento"]
NUM_CLASES = len(CLASES)

# Nombres de clase por número de salidas — extender al entrenar nuevas versiones
_CLASES_POR_N: dict[int, list[str]] = {
    6: CLASES,
    8: ["normal", "deforestacion", "agricultura", "mineria", "incendio", "asentamiento",
        "coca", "pesca"],
}

NUM_BANDAS = 6          # B4, B3, B2, B8 (S2) + VV, VH (S1)
TAMANIO_ENTRADA = 224   # píxeles

_S2_SCALE = 10_000.0
# Normalización S1: (x + 30) / 60  →  rango típico dB [-30, 30] → [0, 1]
_S1_OFFSET = 30.0
_S1_SCALE  = 60.0


WDPA_ASSET = "WCMC/WDPA/current/polygons"

# Bounding box de LATAM (oeste, sur, este, norte)
_LATAM_BBOX = (-82, -56, -34, 13)


# ── Resultado tipado ──────────────────────────────────────────────────────────

class ResultadoClasificacion(TypedDict):
    actividad: str
    confianza: float
    veredicto: str


# ── Arquitectura: EfficientNet-B2 con 6 bandas de entrada ────────────────────

def _crear_modelo_6b(num_clases: int) -> nn.Module:
    """
    torchvision EfficientNet-B2 adaptado para 6 canales de entrada y 6 clases.

    Cambios respecto al modelo base:
      - features[0][0]: Conv2d 3→6 canales; bandas extra inicializadas con el canal rojo.
      - classifier: Dropout(0.3) + Linear(in_features, num_clases)
    """
    model = models.efficientnet_b2(weights=None)

    # --- Primera capa conv: 3 → 6 canales ---
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
        conv_nuevo.weight[:, 3:, :, :] = conv_orig.weight[:, :1, :, :].expand(
            -1, NUM_BANDAS - 3, -1, -1
        )

    model.features[0][0] = conv_nuevo

    # --- Classifier: Dropout(0.3) + Linear → num_clases ---
    in_features = model.classifier[1].in_features
    model.classifier = nn.Sequential(
        nn.Dropout(p=0.3, inplace=True),
        nn.Linear(in_features, num_clases),
    )

    return model


# ── Preprocesado ──────────────────────────────────────────────────────────────

def _preprocesar(imagen_array: np.ndarray) -> torch.Tensor:
    """
    Convierte un array [H, W, C] (C=6) en un tensor [1, 6, H, W] normalizado.

    Bandas 0-3 (S2): dividir por 10 000; rango esperado [0, 10000].
    Bandas 4-5 (S1): (x + 30) / 60; rango esperado dB [-30, 30].
    """
    if imagen_array.ndim != 3 or imagen_array.shape[-1] != NUM_BANDAS:
        raise ValueError(
            f"Se esperan {NUM_BANDAS} bandas [H, W, 6], "
            f"se recibió shape {imagen_array.shape}"
        )

    arr = imagen_array.astype(np.float32)

    # Normalización por grupo de bandas
    s2 = np.clip(arr[:, :, :4] / _S2_SCALE, 0.0, 1.0)
    s1 = np.clip((arr[:, :, 4:] + _S1_OFFSET) / _S1_SCALE, 0.0, 1.0)
    arr_norm = np.concatenate([s2, s1], axis=-1)  # [H, W, 6]

    # Redimensionar canal a canal con PIL
    canales = []
    for c in range(NUM_BANDAS):
        img_canal = Image.fromarray(
            (arr_norm[:, :, c] * 255).astype(np.uint8)
        ).resize((TAMANIO_ENTRADA, TAMANIO_ENTRADA), Image.BILINEAR)
        canales.append(np.array(img_canal, dtype=np.float32) / 255.0)

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
    Clasificador de actividad basado en EfficientNet-B2 entrenado con 6 bandas (S2+S1).

    Clases: normal | deforestacion | agricultura | mineria | incendio | asentamiento
    Veredicto legal determinado por cruce con WDPA vía Google Earth Engine.
    """

    def __init__(
        self,
        model_path: str | Path = MODEL_PATH,
        device: str | None = None,
        clases: list[str] | None = None,
    ):
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        ruta = Path(model_path)
        if not ruta.exists():
            raise FileNotFoundError(f"No se encontró el modelo en: {ruta}")

        state = torch.load(ruta, map_location=self.device, weights_only=True)
        # Admite checkpoints guardados como state_dict o como {'model': state_dict}
        if isinstance(state, dict) and "model" in state and not any(
            k.startswith("conv_stem") for k in state
        ):
            state = state["model"]

        # Auto-detectar número de clases desde el checkpoint
        num_clases = int(state["classifier.1.bias"].shape[0])
        if clases is not None:
            self.clases = clases
        elif num_clases in _CLASES_POR_N:
            self.clases = _CLASES_POR_N[num_clases]
        else:
            self.clases = [f"clase_{i}" for i in range(num_clases)]
            print(
                f"      Aviso: modelo con {num_clases} clases desconocidas. "
                f"Usa el parámetro 'clases' para asignar nombres. "
                f"Usando nombres genéricos: {self.clases}"
            )

        self.model = _crear_modelo_6b(num_clases)
        self.model.to(self.device)
        self.model.load_state_dict(state)
        print(f"Modelo cargado desde {ruta}  ({num_clases} clases)")

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
            imagen_array: Array numpy [H, W, 6].
                          Bandas 0-3: S2 (B4/B3/B2/B8) en [0, 10000].
                          Bandas 4-5: S1 (VV/VH) en dB, típicamente [-30, 30].
            coordenadas:  Tupla (latitud, longitud) del punto analizado.

        Returns:
            Diccionario con:
              actividad  — clase predicha
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
        actividad = self.clases[idx]
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
    import argparse as _argparse
    _parser = _argparse.ArgumentParser(description="Smoke test del clasificador.")
    _parser.add_argument(
        "--model",
        default=str(MODEL_PATH),
        help="Ruta al archivo de pesos del modelo. Default: %(default)s.",
    )
    _args = _parser.parse_args()
    clf = SentinelClassifier(model_path=_args.model)

    # Bandas 0-3: S2 en [0, 10000]; bandas 4-5: S1 en dB [-30, 30]
    s2 = np.random.randint(0, 5000, (64, 64, 4), dtype=np.int16)
    s1 = np.random.uniform(-25, 0, (64, 64, 2)).astype(np.float32)
    dummy_6b = np.concatenate([s2, s1], axis=-1)

    # Sin GEE inicializado — el veredicto usa la rama de excepción
    res = clf.predecir(dummy_6b, coordenadas=(-3.5, -62.0))
    print(
        f"[6 bandas] actividad={res['actividad']}  "
        f"confianza={res['confianza']}  veredicto={res['veredicto']}"
    )
