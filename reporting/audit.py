import json, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"

files = {
    "Peru":         OUTPUTS / "alerts_peru_20260617.geojson",
    "Colombia":     OUTPUTS / "alerts_colombia_20260617.geojson",
    "Brasil Norte": OUTPUTS / "alerts_brasil_norte_20260618.geojson",
    "Brasil O1":    OUTPUTS / "alerts_brasil_oeste_1_20260618.geojson",
    "Brasil O2":    OUTPUTS / "alerts_brasil_oeste_2_20260618.geojson",
    "Brasil O3":    OUTPUTS / "alerts_brasil_oeste_3_20260618.geojson",
    "Brasil O4a":   OUTPUTS / "alerts_brasil_oeste_4a_20260619.geojson",
    "Brasil O4b":   OUTPUTS / "alerts_brasil_oeste_4b_20260619.geojson",
    "Brasil Este":  OUTPUTS / "alerts_brasil_este_20260620.geojson",
    "Brasil Sur A": OUTPUTS / "alerts_brasil_sur_a_20260620.geojson",
    "Brasil Sur B": OUTPUTS / "alerts_brasil_sur_b_20260620.geojson",
    "Bolivia":      OUTPUTS / "alerts_bolivia_20260621.geojson",
}

by_country = {}
total = 0
total_mineria = 0

for name, fp in files.items():
    with open(fp, encoding="utf-8") as f:
        data = json.load(f)
    feats = data["features"]
    mineria = sum(1 for feat in feats if feat["properties"].get("actividad", "") == "mineria")
    country = name.split()[0]
    if country not in by_country:
        by_country[country] = {"total": 0, "mineria": 0}
    by_country[country]["total"] += len(feats)
    by_country[country]["mineria"] += mineria
    total += len(feats)
    total_mineria += mineria

print("=== ALERTAS CLASIFICADAS (modelo Gaia v0.5.4, post-bugfix) ===")
for country, v in by_country.items():
    t = v["total"]
    m = v["mineria"]
    pct = round(100 * m / t, 1) if t else 0
    print(f"  {country}: {t} alertas totales | {m} mineria ({pct}%)")

print(f"\nTOTAL: {total} alertas | {total_mineria} clasificadas como mineria")

# Veredictos Bolivia (latest, has legal_detail)
print("\n=== VEREDICTOS Bolivia 20260621 ===")
with open(OUTPUTS / "alerts_bolivia_20260621.geojson", encoding="utf-8") as f:
    data = json.load(f)
feats = data["features"]
verd = collections.Counter(feat["properties"].get("veredicto", "?") for feat in feats)
for k, v in verd.most_common():
    print(f"  {k!r}: {v}")
