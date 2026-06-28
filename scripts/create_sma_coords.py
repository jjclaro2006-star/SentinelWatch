"""Create the index-to-coordinate manifest for SMA NPY patches."""

import csv
import json
from pathlib import Path


geojson_path = Path("data/processed/sma_river_aggregate_candidates.geojson")
imagery_dir = Path("data/imagery/sma_npy")
output_path = Path("data/processed/sma_coords.csv")

features = json.loads(geojson_path.read_text(encoding="utf-8"))["features"]
if len(features) != 108:
    raise ValueError(f"Expected 108 GeoJSON features, found {len(features)}")

missing = [f"{index:04d}.npy" for index in range(len(features))
           if not (imagery_dir / f"{index:04d}.npy").is_file()]
if missing:
    raise FileNotFoundError(f"Missing imagery files: {missing}")

with output_path.open("w", newline="", encoding="utf-8") as csv_file:
    writer = csv.DictWriter(
        csv_file,
        fieldnames=["file_index", "filename", "latitude", "longitude", "nombre_proyecto"],
    )
    writer.writeheader()
    for index, feature in enumerate(features):
        longitude, latitude = feature["geometry"]["coordinates"]
        properties = feature.get("properties", {})
        writer.writerow({
            "file_index": index,
            "filename": f"{index:04d}.npy",
            "latitude": latitude,
            "longitude": longitude,
            "nombre_proyecto": properties.get("unit_name", ""),
        })
