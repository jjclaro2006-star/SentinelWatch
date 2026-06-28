# Contrato de entrada y salida para Google Colab

Tu modelo puede seguir viviendo en Colab. Este repositorio solo exige una salida GeoJSON homogénea.

## Entrada de etiquetas

Ejecuta:

```powershell
python -m sentinelwatch make-labels --cases data/processed/cases.geojson --out data/processed/label_manifest.csv
```

El CSV contiene `id`, `lon`, `lat`, `label`, `observed_at`, `window_before_days`, `window_after_days`, `confidence` y `source_url`. Úsalo para descargar/recortar los pares o series de imágenes de tu notebook.

## Salida obligatoria del modelo

Exporta un `FeatureCollection` GeoJSON. Cada detección debe tener un punto o polígono y estas propiedades:

```json
{
  "type": "Feature",
  "geometry": {"type": "Point", "coordinates": [-70.61, -33.42]},
  "properties": {
    "id": "colab-0001",
    "score": 0.91,
    "observed_at": "2026-06-01",
    "area_ha": 1.7,
    "change_type": "riverbed_extraction",
    "model_version": "aridos-v0.1"
  }
}
```

Después ejecuta:

```powershell
python -m sentinelwatch screen --detections data/processed/colab_detections.geojson --permits data/processed/permits.geojson --observed-at 2026-06-01
```

El resultado es una lista priorizada para revisión. No es una acusación ni un expediente sancionatorio.
