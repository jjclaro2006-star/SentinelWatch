"""
Runner secuencial: Brasil (sub-regiones) → Bolivia
Gaia v0.5.4, umbral 0.10, chips via getDownloadURL(format=NPY, scale=10).
Brasil se divide en sub-regiones para evitar timeouts de GEE.
"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

BRASIL_SUBREGIONS = [
    "brasil_norte",
    "brasil_oeste_1",
    "brasil_oeste_2",
    "brasil_oeste_3",
    "brasil_oeste_4a",
    "brasil_oeste_4b",
    "brasil_este",
    "brasil_sur_a",  # brasil_sur dividido por timeout GEE
    "brasil_sur_b",
]

# Sub-regiones ya completadas — se saltan, solo se usan para el resumen final
COMPLETED = {
    "brasil_norte":   {"total": 11282, "mineria": 3085, "ilegales": 6897},
    "brasil_oeste_1": {"total": 2619,  "mineria": 264,  "ilegales": 1419},
    "brasil_oeste_2": {"total": 3083,  "mineria": 204,  "ilegales": 2879},
    "brasil_oeste_3": {"total": 6204,  "mineria": 1093, "ilegales": 3164},
    "brasil_oeste_4a": {"total": 6608, "mineria": 272,  "ilegales": 2441},
    "brasil_oeste_4b": {"total": 6223, "mineria": 258,  "ilegales": 916},
    "brasil_este":    {"total": 8718,  "mineria": 1758, "ilegales": 4323},
}

REGIONS = BRASIL_SUBREGIONS + ["bolivia"]
results = {}

for region in REGIONS:
    if region in COMPLETED:
        print(f"\n[SKIP] {region.upper()} ya completado anteriormente.", flush=True)
        results[region] = COMPLETED[region]
        continue
    start = datetime.now()
    print(f"\n{'='*60}", flush=True)
    print(f"[{start.strftime('%H:%M:%S')}] Iniciando: {region.upper()}", flush=True)
    print(f"{'='*60}", flush=True)

    ret = subprocess.run(
        [sys.executable, "main.py", "--region", region, "--reclassify"],
        cwd=Path(__file__).parent,
    )

    elapsed = (datetime.now() - start).total_seconds() / 60
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] {region.upper()} terminado en {elapsed:.1f} min (exit={ret.returncode})", flush=True)

    today = datetime.now().strftime("%Y%m%d")
    output_files = sorted(Path("outputs").glob(f"*{region}_{today}*.geojson"))
    if not output_files:
        output_files = sorted(Path("outputs").glob(f"*{region}_2026*.geojson"))
    if output_files:
        latest = output_files[-1]
        data = json.loads(latest.read_text(encoding="utf-8"))
        feats = data.get("features", [])
        mineria = [f for f in feats if f.get("properties", {}).get("actividad") == "mineria"]
        ilegales = [f for f in feats if f.get("properties", {}).get("veredicto") == "ILEGAL"]
        results[region] = {
            "total": len(feats),
            "mineria": len(mineria),
            "ilegales": len(ilegales),
            "minutos": round(elapsed, 1),
            "archivo": latest.name,
        }
        pct = 100 * len(mineria) / max(1, len(feats))
        print(f"  Total alertas : {len(feats)}", flush=True)
        print(f"  Mineria       : {len(mineria)} ({pct:.1f}%)", flush=True)
        print(f"  ILEGAL        : {len(ilegales)}", flush=True)
    else:
        results[region] = {"error": "no output file", "minutos": round(elapsed, 1)}
        print(f"  ERROR: no se encontro archivo de output para {region}", flush=True)

# Agregar totales Brasil desde sub-regiones (completadas + nuevas)
brasil_total = brasil_mineria = brasil_ilegales = 0
for r in BRASIL_SUBREGIONS:
    if r in results and "error" not in results[r]:
        brasil_total   += results[r]["total"]
        brasil_mineria += results[r]["mineria"]
        brasil_ilegales += results[r]["ilegales"]

bolivia_r = results.get("bolivia", {})

# Resumen final con Peru y Colombia incluidos
print(f"\n{'='*60}", flush=True)
print("RESUMEN FINAL — TODOS LOS PAISES", flush=True)
print(f"{'='*60}", flush=True)

all_results = {
    "peru":     {"total": 1642,  "mineria": 505,  "ilegales": 485},
    "colombia": {"total": 11317, "mineria": 2766, "ilegales": 747},
    "brasil":   {"total": brasil_total, "mineria": brasil_mineria, "ilegales": brasil_ilegales},
    "bolivia":  bolivia_r,
}

total_alertas = total_mineria = total_ilegales = 0
for pais, r in all_results.items():
    if "error" in r or not r.get("total"):
        print(f"  {pais:<10}: ERROR o sin datos", flush=True)
        continue
    pct = 100 * r["mineria"] / max(1, r["total"])
    print(f"  {pais:<10}: {r['total']:>6} alertas  {r['mineria']:>5} mineria ({pct:.1f}%)  {r['ilegales']:>5} ILEGAL", flush=True)
    total_alertas  += r["total"]
    total_mineria  += r["mineria"]
    total_ilegales += r["ilegales"]

pct_total = 100 * total_mineria / max(1, total_alertas)
print(f"  {'TOTAL':<10}: {total_alertas:>6} alertas  {total_mineria:>5} mineria ({pct_total:.1f}%)  {total_ilegales:>5} ILEGAL", flush=True)
print(f"{'='*60}", flush=True)
