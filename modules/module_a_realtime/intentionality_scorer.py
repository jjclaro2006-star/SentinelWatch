"""
Preliminary signal-based intentionality score for confirmed fire alerts.
Full forensic analysis in Module B.
"""

import math
from datetime import datetime


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(min(a, 1.0)))


class IntentionalityScorer:
    """
    Preliminary signal-based score. Full forensic analysis in Module B.

    score(event, legal_context, active_events) → dict with intentionality_score,
    intentionality_level, signals_triggered, and intentionality_summary.
    """

    def score(self, event: dict, legal_context: dict, active_events: list) -> dict:
        signals: list[str] = []
        score: int = 0

        # 1. Hora de ignición — atardecer/noche (18:00-23:00 hora Chile = UTC-3)
        start_date = event.get("start_date")
        if isinstance(start_date, str):
            try:
                start_date = datetime.fromisoformat(start_date)
            except (ValueError, TypeError):
                start_date = None

        if isinstance(start_date, datetime):
            ignition_hour_local = (start_date.hour - 3) % 24
            if 18 <= ignition_hour_local <= 23:
                score += 20
                signals.append("ignición_nocturna")

        # 2. Acceso vial cercano
        road_km = legal_context.get("road_distance_km")
        if road_km is not None:
            if road_km < 0.5:
                score += 25
                signals.append("acceso_vial_inmediato")
            elif road_km < 2.0:
                score += 10
                signals.append("acceso_vial_cercano")

        # 3. Dentro de área protegida
        if legal_context.get("wdpa_overlap"):
            score += 20
            signals.append("area_protegida")

        # 4. Múltiples focos simultáneos — otros eventos activos a <10 km en misma hora
        ev_lat = event.get("centroid_lat", 0.0)
        ev_lon = event.get("centroid_lon", 0.0)
        ev_id = event.get("event_id", "")
        ev_start = start_date

        nearby_simultaneous = []
        for e in active_events:
            if e.get("event_id") == ev_id:
                continue
            dist = _haversine_km(ev_lat, ev_lon,
                                 e.get("centroid_lat", 0.0),
                                 e.get("centroid_lon", 0.0))
            if dist >= 10.0:
                continue
            if ev_start is not None:
                e_start = e.get("start_date")
                if isinstance(e_start, str):
                    try:
                        e_start = datetime.fromisoformat(e_start)
                    except (ValueError, TypeError):
                        e_start = None
                if isinstance(e_start, datetime):
                    if abs((e_start - ev_start).total_seconds()) >= 3600:
                        continue
            nearby_simultaneous.append(e)

        if len(nearby_simultaneous) >= 2:
            score += 30
            signals.append("focos_multiples_simultaneos")
        elif len(nearby_simultaneous) == 1:
            score += 15
            signals.append("foco_simultaneo_cercano")

        # 5. Expansión rápida — alta FRP desde primera detección
        max_frp = event.get("max_frp", 0)
        duration_hours = event.get("duration_hours", 0)
        if max_frp > 100 and duration_hours < 1.0:
            score += 15
            signals.append("expansion_rapida")

        score = min(score, 100)

        if score < 25:
            level = "BAJO"
        elif score < 50:
            level = "MODERADO"
        elif score < 75:
            level = "ALTO"
        else:
            level = "MUY ALTO"

        if signals:
            summary = (
                f"Score {score}/100 — {level} — "
                f"señales: {' + '.join(signals)}"
            )
        else:
            summary = f"Score {score}/100 — {level} — sin señales de intencionalidad"

        return {
            "intentionality_score": score,
            "intentionality_level": level,
            "signals_triggered": signals,
            "intentionality_summary": summary,
        }


intentionality_scorer = IntentionalityScorer()
