import logging
import math

import requests

log = logging.getLogger(__name__)

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

_CARDINAL_DIRS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]

_FAILURE = {
    "wind_speed_kmh": -1.0,
    "wind_direction_deg": -1.0,
    "wind_direction_cardinal": "?",
    "humidity_pct": -1.0,
    "temperature_c": -1.0,
    "spread_rate_mha": -1.0,
    "spread_vector_lat": -1.0,
    "spread_vector_lon": -1.0,
    "threat_radius_km": -1.0,
    "fire_weather_index": "DESCONOCIDO",
    "spread_summary": "Datos meteorológicos no disponibles.",
}


def _to_cardinal(deg: float) -> str:
    idx = round(deg / 22.5) % 16
    return _CARDINAL_DIRS[idx]


class SpreadEstimator:
    def estimate(self, lat: float, lon: float, frp_mw: float) -> dict:
        try:
            resp = requests.get(
                _OPEN_METEO_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "wind_speed_10m,wind_direction_10m,relative_humidity_2m,temperature_2m",
                    "wind_speed_unit": "kmh",
                    "forecast_days": 1,
                },
                timeout=10,
            )
            resp.raise_for_status()
            current = resp.json()["current"]
            wind_speed_kmh   = float(current["wind_speed_10m"])
            wind_dir_deg     = float(current["wind_direction_10m"])
            humidity_pct     = float(current["relative_humidity_2m"])
            temperature_c    = float(current["temperature_2m"])
        except Exception as exc:
            log.warning("[SpreadEstimator] Open-Meteo falló: %s", exc)
            return dict(_FAILURE)

        # Humidity modifier
        if humidity_pct < 20:
            humidity_mod = 2.0
        elif humidity_pct < 35:
            humidity_mod = 1.5
        elif humidity_pct < 50:
            humidity_mod = 1.0
        else:
            humidity_mod = 0.6

        frp_mod = 1.0 + min(frp_mw / 200.0, 1.5)
        base_rate = 0.5 + (wind_speed_kmh * 0.15)
        spread_rate_mha = base_rate * humidity_mod * frp_mod

        # Spread vector — project fire front 2 hours downwind
        spread_bearing = (wind_dir_deg + 180) % 360
        distance_km = (spread_rate_mha * 2) ** 0.5 / 10

        spread_vector_lat = lat + (distance_km / 111.0) * math.cos(math.radians(spread_bearing))
        spread_vector_lon = lon + (distance_km / (111.0 * math.cos(math.radians(lat)))) * math.sin(math.radians(spread_bearing))
        threat_radius_km = distance_km

        # Fire weather index
        fwi_score = (wind_speed_kmh / 10) + ((100 - humidity_pct) / 20)
        if fwi_score < 2:
            fire_weather_index = "BAJO"
        elif fwi_score < 4:
            fire_weather_index = "MODERADO"
        elif fwi_score < 6:
            fire_weather_index = "ALTO"
        else:
            fire_weather_index = "EXTREMO"

        wind_cardinal = _to_cardinal(wind_dir_deg)
        spread_cardinal = _to_cardinal(spread_bearing)

        if fire_weather_index in ("ALTO", "EXTREMO"):
            spread_summary = (
                f"Viento {wind_cardinal} {wind_speed_kmh:.0f} km/h, humedad {humidity_pct:.0f}% "
                f"— propagación {fire_weather_index} hacia el {spread_cardinal} "
                f"— frente estimado a {threat_radius_km:.1f} km en 2h"
            )
        else:
            spread_summary = (
                f"Viento {wind_cardinal} {wind_speed_kmh:.0f} km/h, humedad {humidity_pct:.0f}% "
                f"— propagación {fire_weather_index} — riesgo contenido"
            )

        return {
            "wind_speed_kmh": round(wind_speed_kmh, 1),
            "wind_direction_deg": round(wind_dir_deg, 1),
            "wind_direction_cardinal": wind_cardinal,
            "humidity_pct": round(humidity_pct, 1),
            "temperature_c": round(temperature_c, 1),
            "spread_rate_mha": round(spread_rate_mha, 2),
            "spread_vector_lat": round(spread_vector_lat, 6),
            "spread_vector_lon": round(spread_vector_lon, 6),
            "threat_radius_km": round(threat_radius_km, 3),
            "fire_weather_index": fire_weather_index,
            "spread_summary": spread_summary,
        }


spread_estimator = SpreadEstimator()
