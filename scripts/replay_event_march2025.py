"""
Full end-to-end replay test for Module A — largest real 2025 event.

Event 19 | 89 detections | 2025-03-22 → 2025-03-25 | Araucanía, Chile
Centroid: -38.3252, -72.6105 | FRP max: 174.97 MW
"""
from __future__ import annotations

import io
import json
import logging
import math
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Force UTF-8 output so box-drawing and arrow characters render on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Project root ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.WARNING)  # suppress module-internal debug logs

# ── Redirect EventTracker state file BEFORE importing the module ──────────────
# EventTracker hardcodes its state path to data/alerts/module_a/events_state.json.
# We redirect it to data/validation/ so production state is never touched.
import modules.module_a_realtime.event_tracker as _et_mod

_REPLAY_STATE = PROJECT_ROOT / "data" / "validation" / "replay_state.json"
_et_mod._STATE_FILE = _REPLAY_STATE

# Clean any leftover state from a previous run
if _REPLAY_STATE.exists():
    _REPLAY_STATE.unlink()

# ── Mock datetime.now() inside event_tracker for historical replay ────────────
# EventTracker uses datetime.now(utc) to detect stale events (72 h window).
# Without mocking, every historical detection would appear stale relative to
# today (June 2026), so nothing would cluster. We make now() return the
# acquisition time of the detection currently being ingested.
from datetime import datetime as _RealDT

_replay_now: list[datetime | None] = [None]


class _ReplayDT(_RealDT):
    """Subclass that overrides now() to return the replay cursor."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        if _replay_now[0] is not None:
            t = _replay_now[0]
            if tz is not None and t.tzinfo is None:
                t = t.replace(tzinfo=tz)
            return t
        return _RealDT.now(tz)


_et_mod.datetime = _ReplayDT  # patch the name used inside event_tracker.py

# ── Fresh module imports (after patching) ─────────────────────────────────────
from modules.module_a_realtime.event_tracker import EventTracker
from modules.module_a_realtime.legal_context import LegalContextEnricher
from modules.module_a_realtime.spread_estimator import SpreadEstimator
from modules.module_a_realtime.intentionality_scorer import IntentionalityScorer
from modules.module_a_realtime.fp_mask import FalsePositiveMask


# ── Geometry helper ───────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(min(a, 1.0)))


def _parse_dt(s: str) -> datetime:
    dt = _RealDT.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Load target event and extract its matching detections
# ═══════════════════════════════════════════════════════════════════════════════

EVENTS_FILE = PROJECT_ROOT / "data" / "validation" / "module_a_2025_events.geojson"
DETECTIONS_FILE = PROJECT_ROOT / "data" / "validation" / "module_a_2025.geojson"

events_fc = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
target = next(
    f["properties"]
    for f in events_fc["features"]
    if f["properties"]["detection_count"] == 89
)

ev_lat = target["centroid_lat"]
ev_lon = target["centroid_lon"]
ev_start = _parse_dt(target["start_date"])
ev_end = _parse_dt(target["end_date"])

detections_fc = json.loads(DETECTIONS_FILE.read_text(encoding="utf-8"))

MATCH_RADIUS_KM = 5.0
MATCH_WINDOW_DAYS = 7

window_lo = ev_start - timedelta(days=MATCH_WINDOW_DAYS)
window_hi = ev_end + timedelta(days=MATCH_WINDOW_DAYS)

event_detections: list[dict] = []
for feat in detections_fc["features"]:
    p = feat["properties"]
    acq_dt = _parse_dt(p["acq_datetime"])
    dist_km = _haversine_km(p["latitude"], p["longitude"], ev_lat, ev_lon)
    if dist_km <= MATCH_RADIUS_KM and window_lo <= acq_dt <= window_hi:
        event_detections.append(p)

event_detections.sort(key=lambda d: _parse_dt(d["acq_datetime"]))

max_frp = max(d["frp"] for d in event_detections)
print(
    f"Evento cargado: {len(event_detections)} detecciones | "
    f"{target['start_date']} → {target['end_date']} | "
    f"FRP max: {max_frp:.1f} MW"
)
print()

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Replay through the full pipeline
# ═══════════════════════════════════════════════════════════════════════════════

tracker = EventTracker()
enricher = LegalContextEnricher()
estimator = SpreadEstimator()
scorer = IntentionalityScorer()
mask = FalsePositiveMask()

print("── Iniciando replay ──────────────────────────────────────────────────")

for i, det in enumerate(event_detections, start=1):
    lat = det["latitude"]
    lon = det["longitude"]
    acq_dt = _parse_dt(det["acq_datetime"])

    # Advance replay clock so stale-event checks work correctly
    _replay_now[0] = acq_dt

    # False-positive check
    if mask.is_masked(lat, lon):
        print(f"  [{i:02d}] FILTRADO por FP mask — lat={lat:.4f} lon={lon:.4f}")
        continue

    tracker.ingest(det)

    if i % 10 == 0:
        print(f"  [{i:02d}/{len(event_detections)}] {tracker.get_event_summary()}")

print("── Replay completo ───────────────────────────────────────────────────")
print()

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Final enrichment on the main event
# ═══════════════════════════════════════════════════════════════════════════════

# Use the last detection timestamp so get_active_events() sees events as recent
_replay_now[0] = _parse_dt(event_detections[-1]["acq_datetime"])
active = tracker.get_active_events()

if not active:
    # Fallback: read directly from internal state (shouldn't be needed)
    active = list(tracker._active.values())

event = max(active, key=lambda e: e.get("detection_count", 0))

print("Enriqueciendo evento principal…")
legal = enricher.enrich(event["centroid_lat"], event["centroid_lon"])
spread = estimator.estimate(event["centroid_lat"], event["centroid_lon"], event["max_frp"])
intent = scorer.score(event, legal, [e for e in active if e["event_id"] != event["event_id"]])
print()

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Print full alert card
# ═══════════════════════════════════════════════════════════════════════════════

W = 60  # inner width

def _bar(label: str, value: str, width: int = W) -> str:
    content = f"  {label}: {value}"
    return f"║ {content:<{width}} ║"


def _section(title: str, width: int = W) -> str:
    return f"║ {title:<{width}} ║"


def _divider(width: int = W) -> str:
    return f"╠{'═' * (width + 2)}╣"


start_str = _parse_dt(event["start_date"]).strftime("%Y-%m-%d")
end_str = _parse_dt(event["last_seen"]).strftime("%Y-%m-%d")
duration_days = event.get("duration_hours", 0) / 24

tier_label = {"confirmed": "CONFIRMADO", "preliminary": "PRELIMINAR"}.get(
    event.get("tier", ""), "NO CONFIRMADO"
)

legal_summary = legal.get("legal_summary", "Sin datos legales disponibles")
legal_risk = legal.get("legal_risk_score", -1)
spread_summary = spread.get("spread_summary", "Sin datos de propagación disponibles")
fwi = spread.get("fire_weather_index", "DESCONOCIDO")
intent_summary = intent.get("intentionality_summary", "Sin señales analizadas")

print(f"╔{'═' * (W + 2)}╗")
title = "ALERTA SENTINELWATCH — MÓDULO A"
print(f"║ {title:^{W}} ║")
print(_divider())
print(_bar("Evento", event["event_id"]))
print(_bar("Estado", tier_label))
print(_bar("Período", f"{start_str} → {end_str} ({duration_days:.1f} días)"))
print(_bar("Detecciones", f"{event['detection_count']} | FRP máx: {event['max_frp']:.0f} MW"))
print(_divider())
print(_section("PROPAGACIÓN"))
# Wrap spread_summary to width
def _wrap_lines(text: str, width: int = W, indent: str = "  ") -> None:
    for line in textwrap.wrap(text, width=width - len(indent)):
        print(f"║ {indent}{line:<{width - len(indent)}} ║")

_wrap_lines(spread_summary)
print(_bar("Fire Weather Index", fwi))
print(_divider())
print(_section("CONTEXTO LEGAL"))
_wrap_lines(legal_summary)
risk_str = f"{legal_risk}/100" if legal_risk >= 0 else "N/D"
print(_bar("Riesgo legal", risk_str))
print(_divider())
print(_section("INTENCIONALIDAD PRELIMINAR"))
_wrap_lines(intent_summary)
if intent.get("signals_triggered"):
    signals = "Señales: " + ", ".join(intent["signals_triggered"])
    _wrap_lines(signals)
score_str = f"{intent.get('intentionality_score', 0)}/100 — {intent.get('intentionality_level', 'N/D')}"
print(_bar("Score", score_str))
print(f"╚{'═' * (W + 2)}╝")

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Cleanup
# ═══════════════════════════════════════════════════════════════════════════════

if _REPLAY_STATE.exists():
    _REPLAY_STATE.unlink()
    print(f"\nEstado de replay eliminado: {_REPLAY_STATE.name}")
