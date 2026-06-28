import logging
import time
from datetime import datetime

import schedule

from config import OUTPUT_DIR
from main import run_pipeline
from modules.module_b_forensic.sentinel2_monitor import sentinel2_monitor  # ADDED: module_b

LOG_FILE = OUTPUT_DIR / "sentinel_watch.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

log = logging.getLogger(__name__)


def _run() -> None:
    log.info("Pipeline started.")
    try:
        summary = run_pipeline()
        log.info(
            "Pipeline complete. alerts=%d severity=%s output=%s",
            summary["total_alerts"],
            summary["severity"],
            summary["output_path"],
        )
    except Exception as exc:
        log.error("Pipeline failed: %s", exc, exc_info=True)
        log.info("Next attempt in 5 days.")


if __name__ == "__main__":
    log.info("SentinelWatch scheduler starting.")

    # Run immediately on startup, then every 5 days
    _run()
    schedule.every(5).days.do(_run)
    schedule.every(6).hours.do(sentinel2_monitor.monitor_loop)  # ADDED: module_b

    while True:
        schedule.run_pending()
        time.sleep(60)
