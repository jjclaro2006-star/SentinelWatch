import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import OUTPUT_DIR

_FIRE_STATE_FILE = Path("data/alerts/module_a/events_state.json")
_FIRE_CONFIRMED_DIR = Path("data/alerts/module_a/confirmed")

app = FastAPI(title="SentinelWatch API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_gee_initialized = False


def _ensure_gee() -> None:
    global _gee_initialized
    if not _gee_initialized:
        from auth import initialize
        initialize()
        _gee_initialized = True


# Regions approved for mining alerts and their minimum confidence thresholds.
# Anything not listed is archived on disk and never served to the frontend.
_MINING_APPROVED: dict[str, float] = {
    "peru":           0.30,
    "bolivia":        0.30,
    "brasil_norte":   0.30,
    "brasil_oeste_1": 0.30,
    "brasil_oeste_2": 0.30,
    "brasil_oeste_3": 0.30,
    "colombia":       0.50,
    "brasil_este":    0.50,
}


def _mining_passes(f: dict) -> bool:
    props = f.get("properties", {})
    min_conf = _MINING_APPROVED.get(props.get("_source_region", ""))
    return min_conf is not None and (props.get("confianza") or 0) >= min_conf


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
    for region_key, path in latest_per_region.items():
        data = json.loads(path.read_text(encoding="utf-8"))
        for feature in data.get("features", []):
            feature.setdefault("properties", {})["_source_region"] = region_key
        features.extend(data.get("features", []))
        source_files.append(path.name)

    return features, source_files


def _load_fire_state() -> dict:
    """Load Module A events_state.json; return empty structure if file is missing or corrupt."""
    if not _FIRE_STATE_FILE.exists():
        return {"active": {}, "closed_today": 0, "closed_today_date": ""}
    try:
        return json.loads(_FIRE_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"active": {}, "closed_today": 0, "closed_today_date": ""}


@app.get("/alerts")
def get_alerts(actividad: Optional[str] = Query(None)):
    features, _ = _load_all_alerts()
    if actividad is not None:
        features = [f for f in features if f.get("properties", {}).get("actividad") == actividad]
    # Only serve actionable activity types; drop negative-class and unsupported modules.
    _ALLOWED = {"mineria", "incendios"}
    features = [f for f in features if f.get("properties", {}).get("actividad") in _ALLOWED]
    # Only pass through mining alerts that are in an approved region with sufficient confidence.
    features = [
        f for f in features
        if f.get("properties", {}).get("actividad") != "mineria" or _mining_passes(f)
    ]
    return JSONResponse(content={"type": "FeatureCollection", "features": features})


@app.get("/alerts/summary")
def get_alerts_summary():
    features, source_files = _load_all_alerts()
    mining = [
        f for f in features
        if f.get("properties", {}).get("actividad") == "mineria" and _mining_passes(f)
    ]

    severity: dict[str, int] = {}
    dates: set[str] = set()
    for f in mining:
        props = f.get("properties", {})
        sev = props.get("severity", "unknown")
        severity[sev] = severity.get(sev, 0) + 1
        if d := props.get("detection_date"):
            dates.add(d)

    fire_state = _load_fire_state()
    active_events = fire_state.get("active", {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    confirmed_today = sum(
        1 for ev in active_events.values()
        if ev.get("tier") == "confirmed" and (ev.get("last_seen") or "").startswith(today)
    )
    max_frp = max((ev.get("max_frp", 0.0) for ev in active_events.values()), default=0.0)

    return {
        "total_alerts":   len(mining),
        "severity":       severity,
        "detection_date": sorted(dates)[-1] if dates else None,
        "source_files":   sorted(source_files),
        "incendios": {
            "active_events":    len(active_events),
            "confirmed_today":  confirmed_today,
            "max_frp":          max_frp,
        },
    }


@app.get("/fire/events")
def get_fire_events():
    state = _load_fire_state()
    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [ev.get("centroid_lon", 0), ev.get("centroid_lat", 0)],
            },
            "properties": {
                "event_id":        ev.get("event_id"),
                "tier":            ev.get("tier"),
                "detection_count": ev.get("detection_count", 0),
                "max_frp":         ev.get("max_frp", 0.0),
                "duration_hours":  ev.get("duration_hours", 0.0),
                "start_date":      ev.get("start_date"),
                "last_seen":       ev.get("last_seen"),
                "sources":         ev.get("sources", []),
            },
        }
        for ev in state.get("active", {}).values()
    ]
    return JSONResponse(content={"type": "FeatureCollection", "features": features})


@app.get("/fire/confirmed")
def get_fire_confirmed():
    if not _FIRE_CONFIRMED_DIR.exists():
        return JSONResponse(content={"type": "FeatureCollection", "features": []})
    features: list[dict] = []
    for path in sorted(_FIRE_CONFIRMED_DIR.glob("*.geojson")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            features.extend(data.get("features", []))
        except Exception:
            pass
    return JSONResponse(content={"type": "FeatureCollection", "features": features})


@app.get("/fire/stats")
def get_fire_stats():
    state = _load_fire_state()
    active = state.get("active", {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month = datetime.now(timezone.utc).month

    confirmed_today = sum(
        1 for ev in active.values()
        if ev.get("tier") == "confirmed" and (ev.get("last_seen") or "").startswith(today)
    )
    preliminary_today = sum(
        1 for ev in active.values()
        if ev.get("tier") == "preliminary" and (ev.get("last_seen") or "").startswith(today)
    )
    max_frp_today = max(
        (
            ev.get("max_frp", 0.0)
            for ev in active.values()
            if (ev.get("last_seen") or "").startswith(today)
        ),
        default=0.0,
    )
    top_event = max(active.values(), key=lambda e: e.get("detection_count", 0), default=None)
    top_region = top_event["event_id"] if top_event else ""

    return {
        "active_events":    len(active),
        "confirmed_today":  confirmed_today,
        "preliminary_today": preliminary_today,
        "max_frp_today":    max_frp_today,
        "top_region":       top_region,
        "season_active":    month in (12, 1, 2, 3),
    }


@app.get("/alert/thumbnail")
async def alert_thumbnail(lat: float, lon: float, date: str, actividad: Optional[str] = Query(None)):
    try:
        _ensure_gee()
        import ee

        point  = ee.Geometry.Point([lon, lat])
        region = point.buffer(500).bounds()

        date_obj   = datetime.strptime(date[:10], "%Y-%m-%d")
        post_start = date_obj.strftime("%Y-%m-%d")
        post_end   = (date_obj + timedelta(days=90)).strftime("%Y-%m-%d")
        pre_start  = (date_obj - timedelta(days=60)).strftime("%Y-%m-%d")
        pre_end    = date_obj.strftime("%Y-%m-%d")

        bands = ["B4", "B3", "B2"]

        def _build_collection(start: str, end: str) -> ee.ImageCollection:
            return (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(point)
                .filterDate(start, end)
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 50))
                .select(bands)
            )

        post_col = _build_collection(post_start, post_end)
        col = post_col if post_col.size().getInfo() > 0 else _build_collection(pre_start, pre_end)
        img = col.median()

        url = img.getThumbURL({
            "region": region,
            "dimensions": 512,
            "format": "png",
            "min": 0,
            "max": 3000,
        })

        import requests as _requests
        import base64 as _base64
        response = _requests.get(url, timeout=15)
        if response.status_code == 200:
            img_b64 = _base64.b64encode(response.content).decode("utf-8")
            return {"url": f"data:image/png;base64,{img_b64}"}
        return {"url": None, "error": f"Image download failed ({response.status_code})"}
    except Exception as e:
        return {"url": None, "error": str(e)}


@app.get("/fire/thumbnail")
async def fire_thumbnail(lat: float, lon: float, date: str):
    return await alert_thumbnail(lat=lat, lon=lon, date=date, actividad="incendios")


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
