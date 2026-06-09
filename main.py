import json
from datetime import date
from pathlib import Path

from auth import authenticate_and_initialize
from config import DATE_BASELINE, DATE_ANALYSIS, OUTPUT_DIR
from gee_client import (
    aoi_geometry,
    get_classification_composite,
    get_median_ndvi,
    get_sentinel2_collection,
)
from ndvi import detect_loss, vectorize_loss
from alerts import build_alerts, save_geojson


def run_pipeline(
    baseline: tuple[str, str] = DATE_BASELINE,
    analysis: tuple[str, str] = DATE_ANALYSIS,
    detection_date: date | None = None,
) -> dict:
    """Runs the deforestation detection pipeline in incremental mode.

    Alerts that were already classified in the previous GeoJSON keep their
    classification.  Only genuinely new polygons (by centroid-based polygon_id)
    trigger a GEE export + Drive download + ML inference.

    Args:
        baseline:       (start, end) date strings for the reference period.
        analysis:       (start, end) date strings for the analysis period.
        detection_date: Date stamped on each alert. Defaults to today.

    Returns:
        Summary dict with alert count, output path, severity/activity breakdown.
    """
    authenticate_and_initialize()

    print("[1/5] Loading Sentinel-2 collections...")
    aoi      = aoi_geometry()
    col_base = get_sentinel2_collection(aoi, *baseline)
    col_now  = get_sentinel2_collection(aoi, *analysis)
    print(f"      Baseline images : {col_base.size().getInfo()}")
    print(f"      Analysis images : {col_now.size().getInfo()}")

    print("[2/5] Computing NDVI composites...")
    ndvi_base = get_median_ndvi(col_base, aoi)
    ndvi_now  = get_median_ndvi(col_now,  aoi)

    print("[3/5] Detecting vegetation loss...")
    ndvi_diff, loss_mask = detect_loss(ndvi_base, ndvi_now)

    print("[4/5] Vectorizing loss polygons (may take 1-2 min)...")
    gdf = vectorize_loss(loss_mask, ndvi_diff, aoi)
    print(f"      Polygons found  : {len(gdf)}")

    print("[5/5] Building alerts (incremental)...")

    # Load previously classified alerts to avoid re-running inference on them.
    existing_features  = _load_existing_alerts()
    existing_by_id     = {f["properties"]["id"]: f["properties"] for f in existing_features}
    classified_ids     = {
        pid for pid, props in existing_by_id.items() if "actividad" in props
    }
    print(f"      Previously classified : {len(classified_ids)}")

    classifier         = _load_classifier()
    classification_image = None

    if classifier:
        classification_image = get_classification_composite(col_now)

    alerts = build_alerts(
        gdf,
        detection_date=detection_date,
        classifier=classifier,
        sentinel2_image=classification_image,
        classified_ids=classified_ids,
        existing_by_id=existing_by_id,
    )
    output_path = save_geojson(alerts)

    severity_counts:  dict[str, int] = {}
    activity_counts:  dict[str, int] = {}
    veredicto_counts: dict[str, int] = {}
    for alert in alerts:
        s = alert["severity"]
        severity_counts[s] = severity_counts.get(s, 0) + 1
        if "actividad" in alert:
            a = alert["actividad"]
            activity_counts[a] = activity_counts.get(a, 0) + 1
        if "veredicto" in alert:
            v = alert["veredicto"]
            veredicto_counts[v] = veredicto_counts.get(v, 0) + 1

    summary: dict = {
        "total_alerts":    len(alerts),
        "output_path":     str(output_path),
        "severity":        severity_counts,
        "baseline_period": baseline,
        "analysis_period": analysis,
    }
    if activity_counts:
        summary["actividad"] = activity_counts
    if veredicto_counts:
        summary["veredicto"] = veredicto_counts

    print("\nPipeline complete.")
    print(f"  Alerts    : {summary['total_alerts']}")
    print(f"  Severity  : {summary['severity']}")
    if activity_counts:
        print(f"  Actividad : {summary['actividad']}")
    if veredicto_counts:
        print(f"  Veredicto : {summary['veredicto']}")
    print(f"  Output    : {summary['output_path']}")

    return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_existing_alerts() -> list[dict]:
    """Returns features from the most recent alerts GeoJSON, or [] if none."""
    files = sorted(OUTPUT_DIR.glob("alerts_*.geojson"))
    if not files:
        return []
    try:
        data = json.loads(files[-1].read_text(encoding="utf-8"))
        return data.get("features", [])
    except Exception as exc:
        print(f"      Warning: could not read existing alerts ({exc}).")
        return []


def _load_classifier():
    """Returns a SentinelClassifier if model weights exist, otherwise None."""
    weights_path = Path("model") / "modelo_v02_completo.pth"
    if not weights_path.exists():
        print(f"      Warning: model weights not found at {weights_path}. Skipping classification.")
        return None
    try:
        from sentinel_classifier import SentinelClassifier
        return SentinelClassifier(model_path=weights_path)
    except Exception as exc:
        print(f"      Warning: could not load SentinelClassifier ({exc}). Skipping classification.")
        return None


if __name__ == "__main__":
    run_pipeline()
