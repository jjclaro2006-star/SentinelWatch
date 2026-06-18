"""
Runner secuencial: Colombia → Brasil → Bolivia
Corre cada región con Gaia v0.5.4, umbral 0.10, chips via getDownloadURL.
Imprime resumen al final.
"""
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

REGIONS = ["colombia", "brasil", "bolivia"]

results = {}

for region in REGIONS:
    start = datetime.now()
    print(f"\n{'='*60}")
    print(f"[{start.strftime('%H:%M:%S')}] Iniciando: {region.upper()}")
    print(f"{'='*60}", flush=True)

    ret = subprocess.run(
        [sys.executable, "main.py", "--region", region, "--reclassify"],
        cwd=Path(__file__).parent,
    )

    elapsed = (datetime.now() - start).total_seconds() / 60
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] {region.upper()} terminado en {elapsed:.1f} min (exit={ret.returncode})", flush=True)

    # Leer output para stats
    output_files = sorted(Path("outputs").glob(f"*{region}*"))
    if output_files:
        latest = output_files[-1]
        data = json.loads(latest.read_text())
        feats = data.get("features", [])
        mineria = [f for f in feats if f.get("properties", {}).get("actividad") == "mineria"]
        ilegales = [f for f in mineria if f.get("properties", {}).get("veredicto") == "ILEGAL"]
        results[region] = {
            "total": len(feats),
            "mineria": len(mineria),
            "ilegales": len(ilegales),
            "archivo": latest.name,
            "minutos": round(elapsed, 1),
        }
        print(f"  Total alertas : {len(feats)}")
        print(f"  Mineria       : {len(mineria)} ({100*len(mineria)/max(1,len(feats)):.1f}%)")
        print(f"  ILEGAL        : {len(ilegales)}", flush=True)
    else:
        results[region] = {"error": "no output file"}

# Resumen final
print(f"\n{'='*60}")
print("RESUMEN FINAL")
print(f"{'='*60}")
header = f"{'Region':<12} {'Total':>7} {'Mineria':>8} {'%':>5} {'ILEGAL':>7} {'Minutos':>8}"
print(header)
print("-" * len(header))
for region, r in results.items():
    if "error" in r:
        print(f"{region:<12}  ERROR: {r['error']}")
    else:
        pct = 100 * r["mineria"] / max(1, r["total"])
        print(f"{region:<12} {r['total']:>7} {r['mineria']:>8} {pct:>4.1f}% {r['ilegales']:>7} {r['minutos']:>7.1f}m")
print(f"{'='*60}")
