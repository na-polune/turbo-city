"""Weather state machine for the city simulation.

Two modes selected automatically by the caller:
  - Markov chain (lat/lon = None): procedural imaginary cycle, seeded from config
  - Real API (lat/lon provided): Open-Meteo current-conditions, no API key required

The state dict exposed via snapshot() is identical in both modes so the rest of
the codebase doesn't need to know which source is active.
"""
import json
import random
import threading
import time
import urllib.request

# ---- state definitions --------------------------------------------------
STATES = {
    'sunny':         {'cloud_cover': 0.05, 'solar_mult': 1.00, 'temp_offset': +3.0, 'ua_mult': 1.00, 'label': 'Sunny',         'icon': '☀️'},
    'partly_cloudy': {'cloud_cover': 0.40, 'solar_mult': 0.65, 'temp_offset': +1.0, 'ua_mult': 1.00, 'label': 'Partly Cloudy', 'icon': '⛅'},
    'overcast':      {'cloud_cover': 0.80, 'solar_mult': 0.20, 'temp_offset':  0.0, 'ua_mult': 1.02, 'label': 'Overcast',      'icon': '☁️'},
    'rain':          {'cloud_cover': 0.95, 'solar_mult': 0.05, 'temp_offset': -1.0, 'ua_mult': 1.07, 'label': 'Rain',          'icon': '🌧️'},
    'heavy_rain':    {'cloud_cover': 1.00, 'solar_mult': 0.00, 'temp_offset': -2.0, 'ua_mult': 1.12, 'label': 'Heavy Rain',    'icon': '⛈️'},
}

# Relative weights per sim-minute for leaving a state (Markov mode)
_EDGES = {
    'sunny':         [('partly_cloudy', 1.0)],
    'partly_cloudy': [('sunny', 1.2), ('overcast', 0.8)],
    'overcast':      [('partly_cloudy', 0.8), ('rain', 1.6)],
    'rain':          [('overcast', 2.0), ('heavy_rain', 1.0)],
    'heavy_rain':    [('rain', 3.0)],
}

_OPEN_METEO_URL = (
    'https://api.open-meteo.com/v1/forecast'
    '?latitude={lat}&longitude={lon}'
    '&current=weather_code,cloud_cover,precipitation,wind_speed_10m'
    '&forecast_days=1'
)
_REFRESH_INTERVAL_S = 900   # re-fetch real weather every 15 real minutes


def _wmo_to_state(code: int, cloud_cover: float, precipitation: float) -> str:
    """Map WMO weather code + current conditions to one of our five states.

    WMO code reference (abridged):
      0        clear sky
      1–2      mainly clear / partly cloudy
      3        overcast
      45, 48   fog
      51–67    drizzle / rain
      71–77    snow (mapped to overcast — no snow state)
      80–82    rain showers
      95–99    thunderstorm
    """
    if code >= 95 or precipitation >= 5.0:
        return 'heavy_rain'
    if code in range(51, 83) or precipitation > 0.3:
        return 'rain'
    if code in (3, 45, 48) or cloud_cover >= 80:
        return 'overcast'
    if code in (1, 2) or cloud_cover >= 35:
        return 'partly_cloudy'
    return 'sunny'


class Weather:
    """Weather state, driven either by a Markov chain or a live API."""

    def __init__(self, rng: random.Random, period_min: float = 180.0,
                 lat: float | None = None, lon: float | None = None):
        self._rng = rng
        self._rate = 1.0 / max(1.0, period_min)
        self._lat = lat
        self._lon = lon
        self._real = lat is not None and lon is not None
        self._acc = 0.0
        self._fetching = False
        self._next_refresh = 0.0   # monotonic seconds; 0 forces immediate first refresh

        if self._real:
            # Blocking fetch at startup — acceptable; server isn't serving yet
            fetched = self._fetch()
            self.state = fetched if fetched else 'partly_cloudy'
            self._next_refresh = time.monotonic() + _REFRESH_INTERVAL_S
            self._source = 'api'
        else:
            self.state = 'sunny'
            self._source = 'markov'

    # ---- public interface -----------------------------------------------

    def tick(self, sim_dt_min: float):
        """Advance weather by sim_dt_min simulation minutes."""
        if self._real:
            self._maybe_refresh()
        else:
            self._markov_step(sim_dt_min)

    @property
    def props(self):
        return STATES[self.state]

    def snapshot(self):
        p = self.props
        return {
            'state':       self.state,
            'label':       p['label'],
            'icon':        p['icon'],
            'cloud_cover': p['cloud_cover'],
            'solar_mult':  p['solar_mult'],
            'temp_offset': p['temp_offset'],
            'ua_mult':     p['ua_mult'],
            'source':      self._source,
        }

    # ---- internal -------------------------------------------------------

    def _markov_step(self, sim_dt_min: float):
        self._acc += sim_dt_min
        while self._acc >= 1.0:
            self._acc -= 1.0
            for to_state, weight in _EDGES[self.state]:
                if self._rng.random() < weight * self._rate:
                    self.state = to_state
                    break

    def _maybe_refresh(self):
        if self._fetching or time.monotonic() < self._next_refresh:
            return
        self._fetching = True
        t = threading.Thread(target=self._bg_refresh, daemon=True)
        t.start()

    def _bg_refresh(self):
        try:
            result = self._fetch()
            if result:
                self.state = result
            self._next_refresh = time.monotonic() + _REFRESH_INTERVAL_S
        finally:
            self._fetching = False

    def _fetch(self) -> str | None:
        """Fetch Open-Meteo current conditions; return state string or None on error."""
        url = _OPEN_METEO_URL.format(lat=self._lat, lon=self._lon)
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            cur = data['current']
            return _wmo_to_state(
                int(cur.get('weather_code', 0)),
                float(cur.get('cloud_cover', 0)),
                float(cur.get('precipitation', 0)),
            )
        except Exception:
            return None
