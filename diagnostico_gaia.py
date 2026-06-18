"""
Diagnostico Gaia v0.5 - compara chip de Huepetuhe (pipeline) vs sample entrenamiento.

Ejecutar:
    python diagnostico_gaia.py

Para el sample de entrenamiento:
    Descarga manualmente desde Colab/Drive: data_amw_oficial/mineria/0000.npy
    Coloca el archivo como: debug_train_0000.npy en esta carpeta.
"""
from __future__ import annotations
import sys
import os

# Forzar UTF-8 en stdout Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).parent))
from gaia_v05 import GaiaV05Classifier, _preprocesar

print("=" * 60)
print("DIAGNOSTICO GAIA v0.5")
print("=" * 60)

clf = GaiaV05Classifier()
model = clf.model


def run_chip(label: str, chip: np.ndarray) -> float:
    print(f"\n{'--'*25}")
    print(f"[{label}]")
    print(f"  shape raw         : {chip.shape}")
    print(f"  dtype             : {chip.dtype}")
    print(f"  min / max / mean  : {chip.min():.1f} / {chip.max():.1f} / {chip.mean():.1f}")

    # Detect channel order
    if chip.ndim == 3 and chip.shape[-1] == 12:
        hwc = chip  # [H, W, 12] - pipeline format
    elif chip.ndim == 3 and chip.shape[0] == 12:
        hwc = chip.transpose(1, 2, 0)  # [12, H, W] - Colab format
    elif chip.ndim == 2:
        # Single band - unlikely but handle
        hwc = chip[:, :, np.newaxis]
    else:
        hwc = chip

    normed = np.clip(hwc.astype(np.float32) / 10_000.0, 0.0, 1.0)
    print(f"  norm min/max/mean : {normed.min():.4f} / {normed.max():.4f} / {normed.mean():.4f}")

    n_bands = normed.shape[-1] if normed.ndim == 3 else 1
    for i in range(min(n_bands, 12)):
        b = normed[:, :, i] if normed.ndim == 3 else normed
        print(f"    B[{i:02d}]: min={b.min():.4f}  max={b.max():.4f}  mean={b.mean():.4f}")

    tensor = _preprocesar(hwc)
    with torch.no_grad():
        prob = float(model(tensor.to(clf.device)).cpu().squeeze())

    flag = "MINERIA" if prob >= 0.5 else "normal"
    print(f"  => prob_mine = {prob:.6f}  ({flag})")
    return prob


# ── 1. Chip Huepetuhe desde GEE ──────────────────────────────────────────────
print("\n[Paso 1] Extrayendo chip Huepetuhe desde GEE...")
prob_640 = None
prob_160 = None

try:
    from auth import authenticate_and_initialize
    import ee
    from gee_client import get_s2_12band_composite, extract_chip

    authenticate_and_initialize()

    LAT, LON = -13.0205, -70.5223
    aoi = ee.Geometry.Point([LON, LAT]).buffer(5000).bounds()
    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate("2023-06-01", "2023-09-30")
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", 20))
    )
    n_imgs = col.size().getInfo()
    print(f"  Imagenes S2 encontradas: {n_imgs}")

    composite = get_s2_12band_composite(col)
    centroid  = ee.Geometry.Point([LON, LAT])

    chip_640 = extract_chip(composite, centroid, size_m=640, n_bands=12)
    np.save("debug_huepetuhe_640.npy", chip_640)
    prob_640 = run_chip("Huepetuhe 640m (pipeline actual)", chip_640)

    chip_160 = extract_chip(composite, centroid, size_m=160, n_bands=12)
    np.save("debug_huepetuhe_160.npy", chip_160)
    prob_160 = run_chip("Huepetuhe 160m (chip pequenio)", chip_160)

except Exception as e:
    import traceback
    print(f"  ERROR GEE: {e}")
    traceback.print_exc()


# ── 2. Sample de entrenamiento ────────────────────────────────────────────────
print("\n[Paso 2] Sample de entrenamiento...")
LOCAL_TRAIN = Path("debug_train_0000.npy")
prob_train = None

if LOCAL_TRAIN.exists():
    print(f"  Cargando: {LOCAL_TRAIN}")
    colab_chip = np.load(LOCAL_TRAIN)
    prob_train = run_chip("Sample entrenamiento (mineria/0000.npy)", colab_chip)
else:
    print(f"  FALTA: {LOCAL_TRAIN}")
    print("  Descarga el archivo desde Colab/Drive y coloca como debug_train_0000.npy")
    print("  En Colab:")
    print("    import numpy as np")
    print("    arr = np.load('/content/drive/MyDrive/SentinelWatch/data_amw_oficial/mineria/0000.npy')")
    print("    print(arr.shape, arr.dtype, arr.min(), arr.max())")


# ── 3. Test con datos sinteticos conocidos ────────────────────────────────────
print("\n[Paso 3] Tests con datos sinteticos...")

# Datos de mineria tipicos (suelo desnudo, NDVI bajo)
# B4 alto (red reflectance), B8 bajo (NIR), tipico de suelo desnudo/agua turbia
sintetico_mineria = np.zeros((64, 64, 12), dtype=np.float32)
sintetico_mineria[:, :, 1] = 1000   # B2 blue
sintetico_mineria[:, :, 2] = 1200   # B3 green
sintetico_mineria[:, :, 3] = 1500   # B4 red (alto - suelo desnudo)
sintetico_mineria[:, :, 7] = 1200   # B8 NIR (bajo - sin vegetacion)
sintetico_mineria[:, :, 10] = 1800  # B11 SWIR (alto - suelo/mineria)
sintetico_mineria[:, :, 11] = 1200  # B12 SWIR2
run_chip("Sintetico: suelo desnudo/mineria (NDVI~-0.11)", sintetico_mineria)

# Datos de selva tipicos
sintetico_selva = np.zeros((64, 64, 12), dtype=np.float32)
sintetico_selva[:, :, 1] = 400    # B2 blue
sintetico_selva[:, :, 2] = 600    # B3 green
sintetico_selva[:, :, 3] = 350    # B4 red (bajo)
sintetico_selva[:, :, 7] = 3500   # B8 NIR (alto - vegetacion densa)
sintetico_selva[:, :, 10] = 600   # B11 SWIR (bajo)
sintetico_selva[:, :, 11] = 300   # B12 SWIR2
run_chip("Sintetico: selva densa (NDVI~0.82)", sintetico_selva)

# Datos Huepetuhe reales (de sesion anterior): B4=1384, B8=3199, NDVI=0.40
sintetico_hue = np.zeros((64, 64, 12), dtype=np.float32)
sintetico_hue[:, :, 1] = 500     # B2
sintetico_hue[:, :, 2] = 800     # B3
sintetico_hue[:, :, 3] = 1384    # B4 (valor real anterior)
sintetico_hue[:, :, 7] = 3199    # B8 NIR (valor real anterior)
sintetico_hue[:, :, 10] = 1100   # B11
sintetico_hue[:, :, 11] = 700    # B12
run_chip("Sintetico: valores reales Huepetuhe (B4=1384 B8=3199)", sintetico_hue)

# Ruido aleatorio [0-5000] - el modelo daba prob~0.9 con esto
np.random.seed(42)
ruido = np.random.randint(0, 5000, (64, 64, 12), dtype=np.int32).astype(np.float32)
run_chip("Ruido aleatorio [0-5000]", ruido)


# ── 4. Resumen ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("RESUMEN")
print("=" * 60)
print(f"  Huepetuhe 640m  : {prob_640}")
print(f"  Huepetuhe 160m  : {prob_160}")
print(f"  Train 0000.npy  : {prob_train}")
print()
if prob_train is not None:
    if prob_train > 0.5:
        print("OK: el sample de entrenamiento da >0.5 (modelo carga bien)")
        if prob_640 is not None and prob_640 < 0.1:
            print("PROBLEMA: chip de GEE da <0.1 -> diferencia en preprocesado o rango DN")
    else:
        print("PROBLEMA: el sample de entrenamiento da <0.5 -> los pesos son incorrectos")
else:
    print("PENDIENTE: coloca debug_train_0000.npy y vuelve a ejecutar")
