"""
gaia_aridos.py — Clasificador Gaia Áridos (placeholder v0.1).

Será un ViT-S/16 fine-tuned sobre chips Sentinel-2 12 bandas con etiquetas de
extracción de áridos verificadas en campo (ríos chilenos).  Por ahora retorna
prob=0.5 para todas las alertas hasta que el modelo esté entrenado.

Interfaz idéntica a GaiaV05Classifier para compatibilidad con el pipeline.
"""

from __future__ import annotations

import numpy as np


class GaiaAridosClassifier:
    """
    Placeholder para el clasificador de extracción de áridos en cauces.

    chip_bands = 12 → comparte caché chips_s2_12b con Gaia V0.5.
    """

    chip_bands: int = 12

    def __init__(self, model_path=None) -> None:
        self.model_path = model_path
        print("      GaiaAridos v0.1 (placeholder) — confianza=0.5 para todas las alertas.")

    def predecir(
        self,
        imagen_array: np.ndarray,
        coordenadas: tuple[float, float],
    ) -> dict:
        """
        Retorna confianza=0.5 hasta que el modelo esté entrenado.

        Args:
            imagen_array: chip [H, W, 12] en float32 (DN / 10000)
            coordenadas:  (lat, lon) del centroide del polígono

        Returns:
            dict con actividad, confianza, veredicto, legal_detail
        """
        return {
            "actividad":    "extraccion_aridos",
            "confianza":    0.5,
            "veredicto":    "REQUIERE VERIFICACIÓN",
            "legal_detail": "Gaia Áridos no entrenado — verificar manualmente",
        }
