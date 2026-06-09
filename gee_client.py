import ee
import numpy as np

from config import AOI, CLOUD_COVER_MAX


def aoi_geometry() -> ee.Geometry:
    """Returns the area of interest as a GEE Rectangle."""
    west, south, east, north = AOI
    return ee.Geometry.BBox(west, south, east, north)


def get_sentinel2_collection(
    aoi: ee.Geometry,
    start: str,
    end: str,
    cloud_pct: int = CLOUD_COVER_MAX,
) -> ee.ImageCollection:
    """Loads a cloud-filtered Sentinel-2 SR collection.

    Uses the COPERNICUS/S2_SR_HARMONIZED dataset, which applies
    radiometric harmonization across processing baselines so that
    images from different years are directly comparable.

    Args:
        aoi:       GEE geometry to filter by bounds.
        start:     Start date string, e.g. "2023-06-01".
        end:       End date string, e.g. "2023-08-31".
        cloud_pct: Maximum allowed cloud cover percentage per image.

    Returns:
        Filtered ee.ImageCollection.
    """
    return (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud_pct))
    )


def compute_ndvi(image: ee.Image) -> ee.Image:
    """Computes NDVI from Sentinel-2 SR bands B8 (NIR) and B4 (Red).

    NDVI = (NIR - Red) / (NIR + Red)
    Healthy vegetation: ~0.6–0.9
    Bare soil / deforested: ~0.1–0.2
    """
    return image.normalizedDifference(["B8", "B4"]).rename("NDVI")


MIN_IMAGES = 3


def get_median_ndvi(collection: ee.ImageCollection, aoi: ee.Geometry) -> ee.Image:
    """Builds a cloud-free composite and returns its NDVI clipped to the AOI.

    The median reducer naturally suppresses remaining cloud artefacts
    that passed the CLOUDY_PIXEL_PERCENTAGE filter.

    Raises:
        ValueError: if the collection has fewer than MIN_IMAGES images,
                    which would produce an empty composite with no bands.

    Args:
        collection: Filtered Sentinel-2 collection.
        aoi:        Geometry to clip the output to.

    Returns:
        Single-band ee.Image named "NDVI", clipped to aoi.
    """
    count = collection.size().getInfo()
    if count < MIN_IMAGES:
        raise ValueError(
            f"Not enough images for period: only {count} found "
            f"(minimum {MIN_IMAGES}). Try a longer date range."
        )
    median_composite = collection.median()
    return compute_ndvi(median_composite).clip(aoi)


def get_classification_composite(
    collection: ee.ImageCollection,
    bands: list[str] | None = None,
) -> ee.Image:
    """Builds a median composite pre-selected for classification bands.

    Call this once per pipeline run and pass the resulting ee.Image to
    extract_chip() for all alerts, so GEE can serve chips from a single
    cached composite instead of recomputing median() per alert.

    Args:
        collection: Cloud-filtered ee.ImageCollection for the analysis period.
        bands:      Bands to retain. Defaults to ["B4", "B3", "B2", "B8"].

    Returns:
        ee.Image with only the requested bands.
    """
    if bands is None:
        bands = ["B4", "B3", "B2", "B8"]
    return collection.median().select(bands)


def extract_chip(
    image: ee.Image,
    centroid: ee.Geometry,
    size_m: int = 640,
) -> np.ndarray:
    """Extracts a Sentinel-2 chip centred on a point from a pre-built composite.

    Accepts the ee.Image returned by get_classification_composite() so that
    the median composite is computed only once per pipeline run instead of
    once per alert.

    sampleRectangle is limited to ~262 144 total pixels. At 10 m/px a 640 m
    window is 64×64 = 4 096 pixels per band, well within the limit.

    Args:
        image:    Pre-built ee.Image (output of get_classification_composite()).
        centroid: ee.Geometry.Point at the polygon centroid.
        size_m:   Side length of the chip in metres (default 640 → 64×64 px).

    Returns:
        Float32 numpy array [H, W, C] with values scaled to [0, 1].
        Returns a zero array of the expected shape if the download fails.
    """
    fallback_size = max(1, size_m // 10)

    try:
        region = centroid.buffer(size_m / 2).bounds()
        chip_info = image.sampleRectangle(
            region=region,
            defaultValue=0,
        ).getInfo()

        props = chip_info.get("properties", {})
        # Use the band names actually present in the response
        bands = [k for k in props if isinstance(props[k], list)]
        fallback = np.zeros((fallback_size, fallback_size, len(bands)), dtype=np.float32)

        arrays = [np.array(props[b], dtype=np.float32) for b in bands]

        if arrays[0].ndim != 2 or arrays[0].size == 0:
            return fallback

        # Scale Sentinel-2 SR [0, 10000] → [0, 1]
        chip = np.stack(arrays, axis=-1) / 10_000.0
        return np.clip(chip, 0.0, 1.0).astype(np.float32)

    except Exception:
        return np.zeros((fallback_size, fallback_size, 4), dtype=np.float32)


# ---------------------------------------------------------------------------
# Batch export to Google Drive
# ---------------------------------------------------------------------------

_CHIP_SCALE_M = 10   # Sentinel-2 native resolution (10 m/px)
_CHIP_SIZE_M  = 640  # 640 m × 640 m → 64 × 64 pixels per band


def _chip_region(lon: float, lat: float) -> ee.Geometry:
    return ee.Geometry.Point([lon, lat]).buffer(_CHIP_SIZE_M / 2).bounds()


def export_chips_batch(
    image: ee.Image,
    chips: list[dict],
    drive_folder: str,
) -> list:
    """Submits one GEE export task per chip to Google Drive.

    Args:
        image:        Pre-built classification composite from get_classification_composite().
        chips:        List of {"polygon_id": str, "lat": float, "lon": float}.
        drive_folder: Google Drive folder name to export into.

    Returns:
        List of started ee.batch.Task objects.
    """
    tasks = []
    for c in chips:
        task = ee.batch.Export.image.toDrive(
            image=image,
            description=f"chip_{c['polygon_id']}",
            folder=drive_folder,
            fileNamePrefix=c["polygon_id"],
            region=_chip_region(c["lon"], c["lat"]),
            scale=_CHIP_SCALE_M,
            fileFormat="GeoTIFF",
            maxPixels=1_000_000,
        )
        task.start()
        tasks.append(task)
    print(f"      Submitted {len(tasks)} export tasks to Drive folder '{drive_folder}'.")
    return tasks


def wait_for_tasks(tasks: list, timeout_s: int = 3600, poll_s: int = 30) -> None:
    """Polls GEE task statuses until all reach a terminal state or timeout."""
    import time

    terminal = {"COMPLETED", "FAILED", "CANCELLED"}
    pending = list(tasks)
    t_start = time.time()

    while pending:
        if time.time() - t_start > timeout_s:
            print(f"      Timeout ({timeout_s}s). {len(pending)} tasks still running.")
            break
        still_pending = []
        for task in pending:
            status = task.status()
            state = status.get("state", "UNKNOWN")
            if state not in terminal:
                still_pending.append(task)
            elif state == "FAILED":
                desc = status.get("description", "?")
                err  = status.get("error_message", "unknown error")
                print(f"      Task '{desc}' FAILED: {err}")
        pending = still_pending
        if pending:
            done = len(tasks) - len(pending)
            print(f"      Export: {done}/{len(tasks)} complete — checking again in {poll_s}s...")
            time.sleep(poll_s)

    print(f"      All export tasks finished.")


def download_chips_from_drive(polygon_ids: list[str], drive_folder: str) -> None:
    """Downloads GeoTIFF chips from Google Drive and saves them to local cache.

    Requires that auth.authenticate() was run with GEE_SCOPES (includes Drive).

    Args:
        polygon_ids:  IDs of chips to download (must match Drive file name prefixes).
        drive_folder: Google Drive folder name where chips were exported.
    """
    import io
    import os
    import tempfile

    import numpy as np
    import tifffile
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    from auth import get_drive_credentials
    from chip_cache import CACHE_DIR, save_chip

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    creds   = get_drive_credentials()
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    # Locate the target Drive folder
    q_folder = (
        f"name='{drive_folder}' "
        "and mimeType='application/vnd.google-apps.folder' "
        "and trashed=false"
    )
    folders = service.files().list(q=q_folder, fields="files(id)").execute().get("files", [])
    if not folders:
        print(f"      Drive folder '{drive_folder}' not found — no chips downloaded.")
        return
    folder_id = folders[0]["id"]

    # Build a name→id map for all files in the folder
    q_files = f"'{folder_id}' in parents and trashed=false"
    file_list = service.files().list(q=q_files, fields="files(id,name)").execute().get("files", [])
    file_map: dict[str, str] = {f["name"].rsplit(".", 1)[0]: f["id"] for f in file_list}

    downloaded = 0
    for pid in polygon_ids:
        if pid not in file_map:
            print(f"      Warning: Drive file for chip '{pid}' not found.")
            continue

        # Stream file into BytesIO then write to a temp file for tifffile
        request = service.files().get_media(fileId=file_map[pid])
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
            tmp.write(buf.getvalue())
            tmp_path = tmp.name
        try:
            # GEE exports: (C, H, W) band-sequential → transpose to (H, W, C)
            data = tifffile.imread(tmp_path)
            if data.ndim == 3:
                data = data.transpose(1, 2, 0)
        finally:
            os.unlink(tmp_path)

        chip = np.clip(data.astype("float32") / 10_000.0, 0.0, 1.0)
        save_chip(pid, chip)
        downloaded += 1

    print(f"      Downloaded {downloaded}/{len(polygon_ids)} chips from Drive.")


if __name__ == "__main__":
    from auth import authenticate_and_initialize

    authenticate_and_initialize()

    aoi = aoi_geometry()
    col = get_sentinel2_collection(aoi, "2024-06-01", "2024-08-31")
    count = col.size().getInfo()
    print(f"Images found: {count}")
    assert count > 0, "No images returned — check AOI or date range."

    ndvi = get_median_ndvi(col, aoi)
    band_names = ndvi.bandNames().getInfo()
    print(f"NDVI bands: {band_names}")
    assert band_names == ["NDVI"], f"Unexpected bands: {band_names}"

    print("gee_client smoke test passed.")
