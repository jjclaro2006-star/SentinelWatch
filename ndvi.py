import ee
import geopandas as gpd

from config import MIN_AREA_HA, MAX_PIXELS, NDVI_LOSS_THRESHOLD

# Scale in metres used for vectorization and region reduction.
# At 100 m over the ~200x200 km AOI, ~4.9 M pixels would be needed;
# bestEffort=True lets GEE auto-coarsen to fit within MAX_PIXELS.
_SCALE = 100

# GEE's server hard-caps getInfo() at 5,000 features per call.
# _MAX_FEATURES guards against runaway paging on very large regions.
_PAGE_SIZE = 5_000
_MAX_FEATURES = 50_000


def detect_loss(
    ndvi_baseline: ee.Image,
    ndvi_analysis: ee.Image,
    threshold: float = NDVI_LOSS_THRESHOLD,
) -> tuple[ee.Image, ee.Image]:
    """Computes per-pixel NDVI change and a binary loss mask.

    Args:
        ndvi_baseline: NDVI composite for the reference period.
        ndvi_analysis: NDVI composite for the analysis period.
        threshold:     Minimum NDVI drop to classify as loss.

    Returns:
        (ndvi_diff, loss_mask) where ndvi_diff is the signed delta
        (positive = vegetation loss) and loss_mask is a binary Int image.
    """
    ndvi_diff = ndvi_baseline.subtract(ndvi_analysis).rename("ndvi_change")
    loss_mask = ndvi_diff.gt(threshold).rename("loss").toInt()
    return ndvi_diff, loss_mask


def _paginated_features(fc: ee.FeatureCollection) -> list[dict]:
    """Pages through a GEE FeatureCollection in batches of _PAGE_SIZE.

    GEE's getInfo() is hard-capped at 5,000 features per call. Fetches at
    most _MAX_FEATURES total to avoid runaway requests on large regions.
    Each page costs one synchronous GEE API call.
    """
    total = min(fc.size().getInfo(), _MAX_FEATURES)
    if total == 0:
        return []

    pages = -(-total // _PAGE_SIZE)  # ceiling division
    print(f"      Fetching {total} polygons in {pages} page(s)...")

    features: list[dict] = []
    offset = 0
    while offset < total:
        batch: list[dict] = fc.toList(_PAGE_SIZE, offset).getInfo()
        if not batch:
            break
        features.extend(batch)
        offset += len(batch)
        print(f"      {offset}/{total} polygons fetched", end="\r")

    print()  # newline after the progress line
    return features


def _classify_severity(delta: float) -> str:
    if delta >= 0.40:
        return "high"
    if delta >= 0.25:
        return "medium"
    return "low"


def vectorize_loss(
    loss_mask: ee.Image,
    ndvi_diff: ee.Image,
    aoi: ee.Geometry,
) -> gpd.GeoDataFrame:
    """Converts the loss mask into a GeoDataFrame of affected polygons.

    Steps:
      1. reduceToVectors — groups connected loss pixels into polygons
         (bestEffort=True keeps the request within quota).
      2. reduceRegions — computes mean NDVI delta per polygon.
      3. Area filter — drops polygons smaller than MIN_AREA_HA.
      4. Severity classification — assigns low / medium / high label.

    Args:
        loss_mask: Binary Int image (1 = loss) from detect_loss().
        ndvi_diff: Signed NDVI delta image from detect_loss().
        aoi:       GEE geometry bounding the analysis area.

    Returns:
        GeoDataFrame with columns: geometry, ndvi_change, severity, area_ha.
        Returns an empty GeoDataFrame if no loss polygons are found.
    """
    # Step 1 — stack bands so reduceToVectors has the required 1+1 bands:
    # band 0 "loss" drives the grouping, band 1 "ndvi_change" is extracted
    # by Reducer.first() so we get the delta per polygon without a second
    # reduceRegions call.
    stacked = loss_mask.addBands(ndvi_diff)  # bands: ["loss", "ndvi_change"]

    vectors = stacked.reduceToVectors(
        geometry=aoi,
        scale=_SCALE,
        maxPixels=MAX_PIXELS,
        bestEffort=True,
        geometryType="polygon",
        eightConnected=False,
        labelProperty="loss",
        reducer=ee.Reducer.first(),
    )

    # Keep only pixels labelled as loss (value=1)
    loss_polygons = vectors.filter(ee.Filter.eq("loss", 1))

    # Step 2 — attach area in hectares and filter by minimum size
    def add_area(feature: ee.Feature) -> ee.Feature:
        area_ha = feature.geometry().area(maxError=10).divide(10_000)
        return feature.set("area_ha", area_ha)

    filtered = loss_polygons.map(add_area).filter(
        ee.Filter.gte("area_ha", MIN_AREA_HA)
    )

    features = _paginated_features(filtered)

    if not features:
        return gpd.GeoDataFrame(
            columns=["geometry", "ndvi_change", "severity", "area_ha"],
            geometry="geometry",
        )

    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")

    # Reducer.first() names the output after the reducer, not the band: "first"
    gdf = gdf.rename(columns={"first": "ndvi_change"})

    # Step 4 — severity label
    gdf["severity"] = gdf["ndvi_change"].apply(_classify_severity)

    return gdf[["geometry", "ndvi_change", "severity", "area_ha"]].copy()


if __name__ == "__main__":
    from auth import authenticate_and_initialize
    from gee_client import aoi_geometry, get_sentinel2_collection, get_median_ndvi

    authenticate_and_initialize()

    aoi = aoi_geometry()
    col_base = get_sentinel2_collection(aoi, "2023-06-01", "2023-08-31")
    col_now  = get_sentinel2_collection(aoi, "2024-06-01", "2024-08-31")

    ndvi_base = get_median_ndvi(col_base, aoi)
    ndvi_now  = get_median_ndvi(col_now,  aoi)

    ndvi_diff, loss_mask = detect_loss(ndvi_base, ndvi_now)
    print("Loss mask computed — vectorizing (this may take ~1-2 min)...")

    gdf = vectorize_loss(loss_mask, ndvi_diff, aoi)
    print(f"Loss polygons found: {len(gdf)}")
    if not gdf.empty:
        print(gdf[["ndvi_change", "severity", "area_ha"]].describe())

    print("ndvi smoke test passed.")
