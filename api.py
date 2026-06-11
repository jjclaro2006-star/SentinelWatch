import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import OUTPUT_DIR

app = FastAPI(title="SentinelWatch API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _latest_geojson() -> Path:
    files = sorted(OUTPUT_DIR.glob("alerts_*.geojson"))
    if not files:
        raise HTTPException(status_code=404, detail="No alert files found in outputs/")
    return files[-1]


@app.get("/alerts")
def get_alerts():
    path = _latest_geojson()
    return JSONResponse(content=json.loads(path.read_text(encoding="utf-8")))


@app.get("/alerts/summary")
def get_alerts_summary():
    path = _latest_geojson()
    geojson = json.loads(path.read_text(encoding="utf-8"))
    features = geojson.get("features", [])

    severity: dict[str, int] = {}
    dates: set[str] = set()
    for f in features:
        props = f.get("properties", {})
        sev = props.get("severity", "unknown")
        severity[sev] = severity.get(sev, 0) + 1
        if d := props.get("detection_date"):
            dates.add(d)

    return {
        "total_alerts": len(features),
        "severity": severity,
        "detection_date": sorted(dates)[-1] if dates else None,
        "source_file": path.name,
    }


@app.post("/run-analysis")
def run_analysis():
    from main import run_pipeline

    try:
        summary = run_pipeline()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return summary
