"""Command-line interface for the SentinelWatch pilot workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .stac import download_assets, search_sentinel, write_catalog
from .sma import build_river_aggregate_candidates, write_candidate_outputs
from .patches import build_patches
from .negatives import sample_background_candidates, write_geojson as write_negative_geojson
from .workflow import make_label_manifest, read_geojson, screen_detections, write_geojson, write_report


def path(value: str) -> Path:
    return Path(value)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="sentinelwatch", description="MVP de alertas para extracción de áridos en cauces")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Crea la estructura local de datos y salidas")
    labels = commands.add_parser("make-labels", help="Crea un manifiesto de etiquetas para Colab")
    labels.add_argument("--cases", required=True, type=path)
    labels.add_argument("--out", default=Path("data/processed/label_manifest.csv"), type=path)
    labels.add_argument("--before-days", default=90, type=int)
    labels.add_argument("--after-days", default=90, type=int)
    stac = commands.add_parser("search-sentinel", help="Busca escenas Sentinel por AOI GeoJSON")
    stac.add_argument("--aoi", required=True, type=path, help="GeoJSON geometry, Feature o FeatureCollection")
    stac.add_argument("--start", required=True, help="YYYY-MM-DD")
    stac.add_argument("--end", required=True, help="YYYY-MM-DD")
    stac.add_argument("--limit", default=100, type=int)
    stac.add_argument("--endpoint", default=None, help="Endpoint STAC compatible")
    stac.add_argument("--out", default=Path("data/imagery/sentinel_catalog.geojson"), type=path)
    download = commands.add_parser("download-assets", help="Descarga bandas desde un catálogo STAC existente")
    download.add_argument("--catalog", required=True, type=path)
    download.add_argument("--assets", default="B02,B03,B04,B08", help="Nombres STAC separados por coma")
    download.add_argument("--limit", type=int, default=None, help="Máximo de escenas; útil para pruebas")
    download.add_argument("--out-dir", default=Path("data/imagery/scenes"), type=path)
    screen = commands.add_parser("screen", help="Cruza detecciones de Colab con permisos")
    screen.add_argument("--detections", required=True, type=path)
    screen.add_argument("--permits", required=True, type=path)
    screen.add_argument("--observed-at", required=True, help="Fecha de corte YYYY-MM-DD")
    screen.add_argument("--minimum-score", default=0.65, type=float)
    screen.add_argument("--nearby-meters", default=250, type=float)
    screen.add_argument("--out", default=Path("outputs/aridos/alerts.geojson"), type=path)
    screen.add_argument("--report", default=Path("outputs/aridos/alert_report.md"), type=path)
    sma = commands.add_parser("build-sma-labels", help="Crea candidatos de extracción fluvial desde exportaciones públicas de SMA")
    sma.add_argument("--units", default=Path("data/raw/sma/UF_Instrumentos.csv"), type=path)
    sma.add_argument("--sanctions", default=Path("data/raw/sma/Sancionatorios.csv"), type=path)
    sma.add_argument("--out", default=Path("data/processed/sma_river_aggregate_candidates.geojson"), type=path)
    sma.add_argument("--review-out", default=Path("data/processed/sma_river_aggregate_review.csv"), type=path)
    patches = commands.add_parser("build-patches", help="Descarga recortes Sentinel-2 para candidatos ya etiquetados")
    patches.add_argument("--candidates", default=Path("data/processed/sma_river_aggregate_candidates.geojson"), type=path)
    patches.add_argument("--start", default="2025-01-01")
    patches.add_argument("--end", default="2026-06-21")
    patches.add_argument("--cloud-cover", default=20, type=float)
    patches.add_argument("--patch-size", default=256, type=int, help="Pixeles RGB de 10 m aprox.")
    patches.add_argument("--limit", default=None, type=int, help="Para ejecutar un lote pequeño o reanudar")
    patches.add_argument("--offset", default=0, type=int, help="Indice inicial para ejecutar lotes consecutivos")
    patches.add_argument("--only-id", action="append", default=[], help="ID de candidato especifico; repetir para varios")
    patches.add_argument("--workers", default=1, type=int, help="Descargas concurrentes; 1 es la opcion conservadora")
    patches.add_argument("--out-dir", default=Path("data/imagery/sma_river_aggregate_patches"), type=path)
    patches.add_argument("--manifest", default=Path("data/processed/sma_river_aggregate_patches.csv"), type=path)
    negatives = commands.add_parser("sample-river-negatives", help="Muestrea negativos candidatos desde la red hidrografica oficial")
    negatives.add_argument("--positives", default=Path("data/processed/sma_river_aggregate_candidates.geojson"), type=path)
    negatives.add_argument("--ratio", default=10, type=int)
    negatives.add_argument("--min-distance-meters", default=10_000, type=float)
    negatives.add_argument("--seed", default=42, type=int)
    negatives.add_argument("--out", default=Path("data/processed/river_background_candidates.geojson"), type=path)
    return root


def extract_geometry(document: dict) -> dict:
    if document.get("type") == "Feature":
        return document["geometry"]
    if document.get("type") == "FeatureCollection":
        if not document.get("features"):
            raise ValueError("AOI FeatureCollection has no features")
        return document["features"][0]["geometry"]
    return document


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "init":
        for directory in ("data/raw", "data/processed", "data/imagery", "outputs/aridos"):
            Path(directory).mkdir(parents=True, exist_ok=True)
        print("Estructura creada: data/raw, data/processed, data/imagery, outputs/aridos")
        return 0
    if args.command == "make-labels":
        total = make_label_manifest(read_geojson(args.cases), args.out, args.before_days, args.after_days)
        print(f"Etiquetas exportadas: {total} -> {args.out}")
        return 0
    if args.command == "search-sentinel":
        aoi = extract_geometry(json.loads(args.aoi.read_text(encoding="utf-8")))
        options = {"aoi": aoi, "start": args.start, "end": args.end, "limit": args.limit}
        if args.endpoint:
            options["endpoint"] = args.endpoint
        catalog = search_sentinel(**options)
        total = write_catalog(catalog, args.out)
        print(f"Escenas encontradas: {total} -> {args.out}")
        return 0
    if args.command == "download-assets":
        assets = [item.strip() for item in args.assets.split(",") if item.strip()]
        saved = download_assets(read_geojson(args.catalog), args.out_dir, assets, args.limit)
        print(f"Archivos descargados: {len(saved)} -> {args.out_dir}")
        return 0
    if args.command == "screen":
        alerts = screen_detections(read_geojson(args.detections), read_geojson(args.permits), args.observed_at, args.minimum_score, args.nearby_meters)
        write_geojson(alerts, args.out)
        write_report(alerts, args.report)
        print(f"Alertas generadas: {len(alerts['features'])} -> {args.out}")
        return 0
    if args.command == "build-sma-labels":
        dataset, review_rows = build_river_aggregate_candidates(args.units, args.sanctions)
        write_candidate_outputs(dataset, review_rows, args.out, args.review_out)
        print(f"Candidatos SMA de extraccion fluvial: {len(dataset['features'])} -> {args.out}")
        return 0
    if args.command == "build-patches":
        good, failed = build_patches(read_geojson(args.candidates), args.out_dir, args.manifest, args.start, args.end, args.cloud_cover, args.patch_size, args.limit, args.offset, set(args.only_id), args.workers)
        failure_path = args.manifest.with_name(args.manifest.stem + "_failures.json")
        failure_path.write_text(json.dumps(failed, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Recortes Sentinel-2: {len(good)} listos, {len(failed)} fallidos -> {args.out_dir}")
        return 0
    if args.command == "sample-river-negatives":
        positives = read_geojson(args.positives)
        dataset = sample_background_candidates(positives, len(positives["features"]) * args.ratio, args.min_distance_meters, args.seed)
        write_negative_geojson(dataset, args.out)
        print(f"Negativos candidatos: {len(dataset['features'])} -> {args.out}")
        return 0
    return 1
