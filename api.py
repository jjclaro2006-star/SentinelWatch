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


def _load_all_alerts() -> tuple[list[dict], list[str]]:
    """Combines the latest alerts file per region into a single feature list.

    Filename convention:
      alerts_<region>_YYYYMMDD.geojson  — per-region run
      alerts_YYYYMMDD.geojson           — legacy (no region token)

    For each distinct region key the most recent file (by sort order) is used,
    so re-running a region replaces its previous results without duplicating them.

    Returns:
        (features, source_files) where source_files lists every file loaded.
    """
    files = sorted(OUTPUT_DIR.glob("alerts_*.geojson"))
    if not files:
        raise HTTPException(status_code=404, detail="No alert files found in outputs/")

    # Pick the latest file per region key.
    # Filename format: alerts_<region>_YYYYMMDD.geojson
    # The date is always the last 8-digit token; everything between "alerts" and
    # the date is the region key (handles sub-regions like brasil_norte).
    # Legacy: alerts_YYYYMMDD.geojson → region_key = ""
    latest_per_region: dict[str, Path] = {}
    for path in files:
        parts = path.stem.split("_")
        # Drop leading "alerts" and trailing date (8 digits); join the rest.
        if len(parts) >= 3 and parts[-1].isdigit() and len(parts[-1]) == 8:
            region_key = "_".join(parts[1:-1])
        else:
            region_key = ""
        latest_per_region[region_key] = path  # sorted asc, so last wins

    features: list[dict] = []
    source_files: list[str] = []
    for path in latest_per_region.values():
        data = json.loads(path.read_text(encoding="utf-8"))
        features.extend(data.get("features", []))
        source_files.append(path.name)

    return features, source_files


@app.get("/alerts")
def get_alerts():
    features, _ = _load_all_alerts()
    mining = [f for f in features if f.get("properties", {}).get("actividad") == "mineria"]
    return JSONResponse(content={"type": "FeatureCollection", "features": mining})


@app.get("/alerts/summary")
def get_alerts_summary():
    features, source_files = _load_all_alerts()
    mining = [f for f in features if f.get("properties", {}).get("actividad") == "mineria"]

    severity: dict[str, int] = {}
    dates: set[str] = set()
    for f in mining:
        props = f.get("properties", {})
        sev = props.get("severity", "unknown")
        severity[sev] = severity.get(sev, 0) + 1
        if d := props.get("detection_date"):
            dates.add(d)

    return {
        "total_alerts":   len(mining),
        "severity":       severity,
        "detection_date": sorted(dates)[-1] if dates else None,
        "source_files":   sorted(source_files),
    }


@app.post("/run-analysis")
def run_analysis(region: str = "peru"):
    from config import REGIONS
    from main import run_pipeline

    if region not in REGIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown region '{region}'. Valid options: {list(REGIONS.keys())}",
        )
    try:
        summary = run_pipeline(region=region)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return summary
