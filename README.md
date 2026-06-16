# SentinelWatch

Sistema de detección de deforestación en la Amazonía usando imágenes satelitales Sentinel-1/Sentinel-2 y un clasificador de deep learning (Gaia).

## Archivos pesados NO incluidos en este repositorio

GitHub limita los archivos a 100MB. Los siguientes archivos superan ese límite o son demasiado grandes para distribuir por git y se excluyeron vía `.gitignore`:

| Archivo | Tamaño | Motivo |
|---|---|---|
| `forestnet_data/ForestNetDataset.zip` | ~3.2 GB | Dataset de entrenamiento (ForestNet), demasiado grande para git |
| `model/areas_protegidas_latam.geojson` | ~707 MB | Capa de áreas protegidas de Latinoamérica, demasiado grande para git |
| `model/modelo_v02_completo.pth` | ~30 MB | Checkpoint de modelo antiguo (v0.2), no esencial — se mantiene el más reciente |

Si necesitas estos archivos, contacta al autor del repo para que te los comparta por otro medio (Drive, etc).

## Estructura del proyecto

- `main.py` — pipeline principal de detección de alertas
- `sentinel_classifier.py` — clasificador Gaia (CNN sobre chips Sentinel-1/2)
- `gee_client.py` — cliente de Google Earth Engine
- `ndvi.py`, `alerts.py`, `chip_cache.py`, `config.py` — utilidades del pipeline
- `api.py` — API web
- `index.html` — demo web interactiva con mapa de alertas
- `model/` — checkpoints del modelo entrenado
- `outputs/` — alertas generadas en formato GeoJSON por región
- `ground_truth.py` — utilidades de validación contra datos de referencia
