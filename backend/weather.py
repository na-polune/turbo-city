"""Markov-chain weather state machine for the city simulation.

Each state carries physical multipliers consumed by the energy model:
  solar_mult  — scales solar gain through windows (0 = total overcast)
  ua_mult     — scales envelope UA (rain + wind increases convective loss)
  temp_offset — offset added to the synthetic outdoor temperature [°C]

Transition probabilities are per simulated minute; average dwell time in each
state is roughly (period_min / outgoing_weight_sum).
"""
import random

STATES = {
    'sunny':         {'cloud_cover': 0.05, 'solar_mult': 1.00, 'temp_offset': +3.0, 'ua_mult': 1.00, 'label': 'Sunny',         'icon': '☀️'},
    'partly_cloudy': {'cloud_cover': 0.40, 'solar_mult': 0.65, 'temp_offset': +1.0, 'ua_mult': 1.00, 'label': 'Partly Cloudy', 'icon': '⛅'},
    'overcast':      {'cloud_cover': 0.80, 'solar_mult': 0.20, 'temp_offset':  0.0, 'ua_mult': 1.02, 'label': 'Overcast',      'icon': '☁️'},
    'rain':          {'cloud_cover': 0.95, 'solar_mult': 0.05, 'temp_offset': -1.0, 'ua_mult': 1.07, 'label': 'Rain',          'icon': '🌧️'},
    'heavy_rain':    {'cloud_cover': 1.00, 'solar_mult': 0.00, 'temp_offset': -2.0, 'ua_mult': 1.12, 'label': 'Heavy Rain',    'icon': '⛈️'},
}

# Relative weights for leaving each state; actual prob/min = weight / period_min
_EDGES = {
    'sunny':         [('partly_cloudy', 1.0)],
    'partly_cloudy': [('sunny', 1.2), ('overcast', 0.8)],
    'overcast':      [('partly_cloudy', 0.8), ('rain', 1.6)],
    'rain':          [('overcast', 2.0), ('heavy_rain', 1.0)],
    'heavy_rain':    [('rain', 3.0)],
}


class Weather:
    """Markov-chain weather that ticks forward in simulation time."""

    def __init__(self, rng: random.Random, period_min: float = 180.0, start: str = 'sunny'):
        self._rng = rng
        self._rate = 1.0 / max(1.0, period_min)
        self.state = start
        self._acc = 0.0   # fractional sim-minutes accumulated

    def tick(self, sim_dt_min: float):
        """Advance by sim_dt_min simulation minutes; may transition state."""
        self._acc += sim_dt_min
        while self._acc >= 1.0:
            self._acc -= 1.0
            for to_state, weight in _EDGES[self.state]:
                if self._rng.random() < weight * self._rate:
                    self.state = to_state
                    break

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
        }
