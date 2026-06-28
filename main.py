import argparse
import json
from datetime import date
from pathlib import Path

from auth import authenticate_and_initialize
from config import DATE_BASELINE, DATE_ANALYSIS, OUTPUT_DIR, REGIONS
from gee_client import (
    aoi_geometry,
    get_classification_composite,
    get_median_ndvi,
    get_s2_12band_composite,
    get_sentinel1_collection,
    get_sentinel2_collection,
)
from ndvi import detect_loss, vectorize_loss
from alerts import build_alerts, save_geojson


def run_pipeline(
    baseline: tuple[str, str] = DATE_BASELINE,
    analysis: tuple[str, str] = DATE_ANALYSIS,
    detection_date: date | None = None,
    reclassify: bool = False,
    region: str = "peru",
    model_path: str | Path | None = None,
) -> dict:
    """Runs the deforestation detection pipeline in incremental mode.

    Alerts that were already classified in the previous GeoJSON keep their
    classification.  Only genuinely new polygons (by centroid-based polygon_id)
    trigger a GEE export + Drive download + ML inference.

    Args:
        baseline:       (start, end) date strings for the reference period.
        analysis:       (start, end) date strings for the analysis period.
        detection_date: Date stamped on each alert. Defaults to today.
        reclassify:     When True, ignore all previous classifications and
                        re-run inference on every polygon with the current model.
                        Use this after a model upgrade.
        region:         Named region to process. Must be a key in config.REGIONS.
                        Defaults to "peru".
        model_path:     Path to model weights file. Defaults to
                        model/gaia_v04_s1s2.pth if None.

    Returns:
        Summary dict with alert count, output path, severity/activity breakdown.
    """
    # Chile áridos usa pipeline MNDWI independiente
    if region == "chile_aridos":
        from chile_aridos import run_chile_aridos
        return run_chile_aridos(
            baseline=baseline,
            analysis=analysis,
            detection_date=detection_date,
            reclassify=reclassify,
        )

    # Chile salares usa pipeline SWIR SSI independiente
    if region == "chile_salares":
        from chile_salares import run_chile_salares
        return run_chile_salares(
            baseline=baseline,
            analysis=analysis,
            detection_date=detection_date,
            reclassify=reclassify,
        )

    authenticate_and_initialize()

    aoi_bbox = REGIONS.get(region, REGIONS["peru"])
    print(f"[0/5] Region: {region}  AOI: {aoi_bbox}")

    print("[1/5] Loading Sentinel-2 and Sentinel-1 collections...")
    aoi      = aoi_geometry(aoi_bbox)
    col_base = get_sentinel2_collection(aoi, *baseline)
    col_now  = get_sentinel2_collection(aoi, *analysis)
    col_s1   = get_sentinel1_collection(aoi, *analysis)
    print(f"      Baseline S2 images : {col_base.size().getInfo()}")
    print(f"      Analysis S2 images : {col_now.size().getInfo()}")
    print(f"      Analysis S1 images : {col_s1.size().getInfo()}")

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
    # With --reclassify, treat every polygon as new regardless of prior results.
    existing_features  = _load_existing_alerts()
    existing_by_id     = {f["properties"]["id"]: f["properties"] for f in existing_features}
    if reclassify:
        classified_ids = set()
        print("      --reclassify: all polygons will be re-classified.")
    else:
        classified_ids = {
            pid for pid, props in existing_by_id.items() if "actividad" in props
        }
        print(f"      Previously classified : {len(classified_ids)}")

    classifier           = _load_classifier(model_path)
    classification_image = None

    if classifier:
        chip_bands = getattr(classifier, "chip_bands", 6)
        if chip_bands == 12:
            print("      Clasificador 12 bandas (Gaia v0.5) — composite S2-only.")
            classification_image = get_s2_12band_composite(col_now)
        else:
            classification_image = get_classification_composite(col_now, s1_collection=col_s1)

    alerts = build_alerts(
        gdf,
        detection_date=detection_date,
        classifier=classifier,
        sentinel2_image=classification_image,
        classified_ids=classified_ids,
        existing_by_id=existing_by_id,
    )
    output_path = save_geojson(alerts, region=region)

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


_DEFAULT_MODEL = Path("models") / "gaia_v05_amw_ssl4eo_v4.pth"
_GAIA_V05_MARKERS = ("gaia_v05", "ssl4eo")


def _load_classifier(model_path: str | Path | None = None):
    """Returns a classifier instance if model weights exist, otherwise None.

    Loads GaiaV05Classifier for paths containing 'gaia_v05' or 'ssl4eo',
    and SentinelClassifier (EfficientNet-B2, 6-band) for all other paths.
    """
    weights_path = Path(model_path) if model_path else _DEFAULT_MODEL
    if not weights_path.exists():
        print(f"      Warning: model weights not found at {weights_path}. Skipping classification.")
        return None

    name_lower = weights_path.name.lower()
    use_gaia_v05 = any(m in name_lower for m in _GAIA_V05_MARKERS)

    try:
        if use_gaia_v05:
            from gaia_v05 import GaiaV05Classifier
            return GaiaV05Classifier(model_path=weights_path)
        else:
            from sentinel_classifier import SentinelClassifier
            return SentinelClassifier(model_path=weights_path)
    except Exception as exc:
        print(f"      Warning: could not load classifier ({exc}). Skipping classification.")
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SentinelWatch deforestation pipeline.")
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="Ignore previous classifications and re-run inference on all polygons. "
             "Use after a model upgrade.",
    )
    parser.add_argument(
        "--region",
        choices=list(REGIONS.keys()),
        default="peru",
        help="Region to process. Options: %(choices)s. Default: %(default)s.",
    )
    parser.add_argument(
        "--model",
        default=str(_DEFAULT_MODEL),
        help="Path to model weights file. Default: %(default)s.",
    )
    args = parser.parse_args()
    run_pipeline(reclassify=args.reclassify, region=args.region, model_path=args.model)
