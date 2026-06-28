# SentinelWatch

Sistema de detección de deforestación/minería no autorizada usando imágenes satelitales Sentinel-1/Sentinel-2 y un clasificador de deep learning (Gaia). Incluye pipelines para incendios (Amazonía), salares (Chile Norte) y áridos en cauces (Chile).

## Módulos principales

### Pipeline de alertas (raíz)
- `main.py` — pipeline principal de detección de alertas
- `gee_client.py` — cliente de Google Earth Engine
- `chile_salares.py`, `chile_aridos.py` — pipelines especializados Chile
- `ndvi.py`, `alerts.py`, `chip_cache.py`, `config.py` — utilidades del pipeline
- `api.py` + `auth.py` — API web + autenticación
- `frontend/` — dashboard React/Vite/Tailwind
- `scheduler.py` — scheduler de alertas automáticas

### módulo A — Tiempo real (`modules/module_a_realtime/`)
Detección de incendios en tiempo real con FIRMS/GOES, scoring de intencionalidad, contexto legal.

### Módulo B — Forense (`modules/module_b_forensic/`)
Análisis forense post-evento con Sentinel-2.

### Áridos en cauces (`src/sentinelwatch/`)
MVP de inteligencia geoespacial para priorizar posibles extracciones no autorizadas de áridos en ríos de Chile. El sistema **no declara que una actividad sea ilegal** — produce alertas `possible_unpermitted_extraction` para revisión humana.

```powershell
python -m sentinelwatch init
python -m sentinelwatch build-sma-labels
python -m sentinelwatch sample-river-negatives --ratio 10
python -m sentinelwatch build-patches
python -m sentinelwatch search-sentinel --aoi examples/aoi.geojson --start 2026-01-01 --end 2026-01-31
python -m sentinelwatch download-assets --catalog data/imagery/sentinel_catalog.geojson --assets blue,green,red,nir
python -m sentinelwatch make-labels --cases examples/cases.geojson --out data/processed/label_manifest.csv
python -m sentinelwatch screen --detections examples/detections.geojson --permits examples/permits.geojson --observed-at 2026-06-01
```

Los resultados quedan en `outputs/aridos/`. Consulta `docs/colab_contract.md` para conectar predicciones desde Colab.

### ML / Modelos (`models/`, `SSL4EO-S12/`)
- `models/` — checkpoints Gaia v02, Gaia Salares v01, SSL4EO backbone
- `SSL4EO-S12/` — framework de pretraining SSL (externo, no modificar)
- `scripts/` — build de datasets, validación, replay de eventos

## Archivos pesados NO incluidos en git

| Archivo | Tamaño aprox. | Dónde obtener |
|---|---|---|
| `models/*.pth` | ~80–164 GB c/u | Compartido por Drive |
| `data/fire_scars_segmentation_v3.geojson` | ~81 MB | SW2 / Drive |
| `data/conaf_2014_2019_nacional.csv` | ~15 MB | CONAF / SW2 |
| `data/conaf_simef_2023_2024/` | ~18 MB | SERNAGEOMIN SIMEF |
| `model/legal/sernageomin_catastro.geojson` | ~57 MB | `download_sernageomin_catastro.py` |
| `data/landscape_fire_scars_pangaea/` | ~7+ GB | Zenodo 14195737 |
| `data/imagery/` | variable | Descarga SMA/STAC |
| `outputs/*.geojson` | variable | Generados por pipeline |
| `cache/` | variable | Generado automáticamente |
| `SSL4EO-S12/` | grande | https://github.com/zhu-xlab/SSL4EO-S12 |

## Docs y referencia

- `docs/data_collection.md` — fuentes de datos, licencias, políticas de etiquetado
- `docs/colab_contract.md` — contrato de integración Colab ↔ SentinelWatch
- `docs/sma_pilot.md` — diseño de piloto con SMA
- `config/sources.json` — registro de fuentes con políticas de etiquetado
- `data/legal/rca_salares/` — RCAs Albemarle y SQM (referencia legal salares)
