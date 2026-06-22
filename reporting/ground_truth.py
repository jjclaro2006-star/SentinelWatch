"""
Seleccion aleatoria de 50 alertas de alta confianza para verificacion manual en Google Earth.
Carga todos los GeoJSON de outputs/, filtra confianza > 0.85 y excluye clase 'normal'.
"""

import json
import random
from pathlib import Path

OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"
MIN_CONFIANZA = 0.85
N_SAMPLE = 50
SEED = 42  # reproducible; cambia o elimina para nueva muestra aleatoria


def cargar_alertas(directorio: Path) -> list:
    alertas = []
    for geojson_path in sorted(directorio.glob("*.geojson")):
        with open(geojson_path, encoding="utf-8") as f:
            data = json.load(f)
        features = data.get("features", [])
        count = 0
        for feat in features:
            props = feat.get("properties", {})
            if "confianza" not in props or "actividad" not in props:
                continue
            alertas.append(props)
            count += 1
        print(f"  {geojson_path.name}: {len(features)} features ({count} con clasificacion)")
    return alertas


def filtrar(alertas: list) -> list:
    return [
        a for a in alertas
        if a["confianza"] > MIN_CONFIANZA and a["actividad"].lower() == "mineria"
    ]


def main():
    print(f"Cargando GeoJSON desde '{OUTPUTS_DIR}/'...\n")
    todas = cargar_alertas(OUTPUTS_DIR)
    print(f"\nTotal alertas con clasificacion: {len(todas)}")

    candidatas = filtrar(todas)
    print(f"Alertas de mineria con confianza > {MIN_CONFIANZA}: {len(candidatas)}")

    if len(candidatas) < N_SAMPLE:
        print(f"\nATENCION: solo hay {len(candidatas)} candidatas, mostrando todas.")
        muestra = candidatas
    else:
        random.seed(SEED)
        muestra = random.sample(candidatas, N_SAMPLE)

    print(f"\n{'-'*88}")
    print(f"{'#':>3}  {'Actividad':<28}  {'Conf':>6}  {'Lat':>10}  {'Lon':>11}  Fecha")
    print(f"{'-'*88}")
    for i, a in enumerate(muestra, start=1):
        print(
            f"{i:>3}  {a['actividad']:<28}  {a['confianza']:>6.4f}"
            f"  {a['lat']:>10.6f}  {a['lon']:>11.6f}  {a.get('detection_date', 'N/A')}"
        )
    print(f"{'-'*88}")
    print(f"\nTotal mostradas: {len(muestra)}")

    print("\n--- Coordenadas para Google Earth (lat,lon) ---")
    for i, a in enumerate(muestra, start=1):
        print(f"{i}. {a['lat']},{a['lon']}")


if __name__ == "__main__":
    main()


# --- Distribucion por umbral de confianza ---
import os

todas_alertas = []
for archivo in os.listdir(OUTPUTS_DIR):
    if archivo.endswith(".geojson"):
        with open(OUTPUTS_DIR / archivo) as f:
            data = json.load(f)
            todas_alertas.extend(data["features"])

umbrales = [0.90, 0.95, 0.97, 0.99]
print(f"\n{'='*40}")
print("Distribucion por umbral de confianza (excluye 'normal')")
print(f"{'='*40}")
for umbral in umbrales:
    filtradas = [a for a in todas_alertas
                 if a["properties"].get("confianza", 0) >= umbral
                 and a["properties"].get("actividad") != "normal"]
    print(f"Confianza >= {umbral}: {len(filtradas):,} alertas")
