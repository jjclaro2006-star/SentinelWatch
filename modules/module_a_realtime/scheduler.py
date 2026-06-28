"""
Módulo A — Punto de entrada del scheduler de incendios Biobío.
Uso: python -m modules.module_a_realtime.scheduler
"""

import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

# Asegura que el raíz del proyecto esté en el path cuando se corre directamente
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.module_a_realtime.config import LOGS_PATH, POLL_INTERVAL_HOURS
from modules.module_a_realtime.alert_manager import process_and_save
from modules.module_a_realtime.firms_client import fetch_last_24h
from modules.module_a_realtime.geo_filter import filter_biobio
from modules.module_a_realtime.goes_client import poll as goes_poll
from modules.module_a_realtime.two_tier_engine import check_confirmations


def _setup_logging() -> logging.Logger:
    LOGS_PATH.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_PATH / "module_a.log"

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    return logging.getLogger("module_a")


log = _setup_logging()


def run_pipeline() -> None:
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log.info("=== Iniciando ciclo de detección de incendios Biobío [batch=%s] ===", batch_id)

    try:
        raw_gdf = fetch_last_24h()
        log.info("Detecciones crudas obtenidas: %d puntos.", len(raw_gdf))

        filtered_gdf = filter_biobio(raw_gdf)
        log.info("Detecciones tras filtrado geoespacial y de confianza: %d puntos.", len(filtered_gdf))

        summary = process_and_save(filtered_gdf, batch_id)
        log.info(
            "Ciclo completado — nuevas: %d | duplicadas: %d | entrada total: %d",
            summary["nuevas"],
            summary["duplicadas"],
            summary["total_entrada"],
        )
    except Exception as exc:
        log.exception("Error inesperado en el ciclo de detección: %s", exc)


def main() -> None:
    log.info("Módulo A — Detector de incendios Biobío iniciado. Intervalo: %dh.", POLL_INTERVAL_HOURS)

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        run_pipeline,
        trigger="interval",
        hours=POLL_INTERVAL_HOURS,
        id="biobio_fire_detection",
        name="Detección incendios Biobío",
        next_run_time=datetime.now(timezone.utc),  # ejecuta inmediatamente en el primer arranque
    )
    scheduler.add_job(
        goes_poll,
        trigger="interval",
        minutes=20,
        id="goes19_poll",
        name="GOES-19 polling (Tier 1)",
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.add_job(
        check_confirmations,
        trigger="interval",
        minutes=20,
        id="tier2_check",
        name="Verificación Tier 2 VIIRS",
        next_run_time=datetime.now(timezone.utc),
    )

    log.info("Scheduler configurado. Primera ejecución: inmediata.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Módulo A detenido por el usuario.")


if __name__ == "__main__":
    main()
