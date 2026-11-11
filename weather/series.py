"""Series horarias a partir de un snapshot, cobertura del período y relleno de la cola.

Convenciones (G07):

* Las horas vienen en GMT/UTC. Internamente todo es segundos desde el inicio de
  la construcción (t = 0 en la primera vertida), igual que el solver.
* temperature_2m y wind_speed_10m son valores instantáneos en la marca horaria.
* shortwave_radiation es la MEDIA de la hora anterior: el valor marcado 13:00
  representa 12:00–13:00, por lo que se ubica en 12:30 al interpolar.
* Cada hora lleva su origen ("forecast", "persistencia", "climatologia",
  "conservador", ...) para que un resultado nunca mezcle en silencio datos
  descargados con datos supuestos.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

HOUR = 3600.0
FIELDS = ("air_c", "wind_10m_m_s", "shortwave_w_m2")
OPEN_METEO_NAMES = {"air_c": "temperature_2m", "wind_10m_m_s": "wind_speed_10m",
                    "shortwave_w_m2": "shortwave_radiation"}


def to_epoch(moment) -> float:
    """ISO (sin zona = UTC, como entrega Open-Meteo con timezone=GMT) → segundos UTC."""
    if isinstance(moment, (int, float, np.floating)):
        return float(moment)
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def to_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


@dataclass
class WeatherSeries:
    time_s: np.ndarray                    # segundos UTC, paso horario
    air_c: np.ndarray
    wind_10m_m_s: np.ndarray
    shortwave_w_m2: np.ndarray            # media de la hora anterior a time_s
    origin: list = field(default_factory=list)
    snapshot: dict = field(default_factory=dict)

    def __post_init__(self):
        self.time_s = np.asarray(self.time_s, dtype=float)
        for name in FIELDS:
            setattr(self, name, np.asarray(getattr(self, name), dtype=float))
        if not self.origin:
            self.origin = ["dato"] * self.time_s.size
        sizes = {self.time_s.size, len(self.origin), *(getattr(self, n).size for n in FIELDS)}
        if len(sizes) != 1 or self.time_s.size < 2:
            raise ValueError("Series de distinto largo o con menos de dos horas")
        if not np.all(np.diff(self.time_s) > 0):
            raise ValueError("Las horas deben ser estrictamente crecientes")

    # --- lectura -----------------------------------------------------------------------------------
    @property
    def start_s(self):
        return float(self.time_s[0])

    @property
    def end_s(self):
        return float(self.time_s[-1])

    def missing(self):
        """Horas con algún valor faltante (Open-Meteo entrega null)."""
        return np.any([~np.isfinite(getattr(self, n)) for n in FIELDS], axis=0)

    def boundary_functions(self, construction_start, wind_floor_m_s=0.0):
        """Funciones f(t) con t en segundos desde construction_start, para SurfaceExposure.

        Fuera del rango descargado NO se extrapola: se lanza un error. Para cubrir
        el período completo hay que llamar antes a fill_tail y declarar el relleno.
        """
        if np.any(self.missing()):
            raise ValueError("La serie tiene horas sin dato; complételas y márquelas antes de usarla")
        offset = to_epoch(construction_start)
        times = self.time_s - offset
        solar_times = times - HOUR / 2           # media de la hora anterior → centro de esa hora
        solar_values = self.shortwave_w_m2
        lo, hi = float(times[0]), float(times[-1])

        def build(x, y, floor=None):
            def value(t):
                if not lo - 1e-6 <= t <= hi + 1e-6:
                    raise ValueError(f"t = {t / HOUR:.2f} h fuera de la serie ({lo / HOUR:.1f} a {hi / HOUR:.1f} h)")
                result = float(np.interp(t, x, y))
                return result if floor is None else max(result, floor)
            return value

        return {"air_c": build(times, self.air_c),
                "wind_10m_m_s": build(times, self.wind_10m_m_s, floor=wind_floor_m_s),
                "shortwave_w_m2": build(solar_times, solar_values, floor=0.0),
                "max_wind_m_s": float(np.nanmax(self.wind_10m_m_s))}

    def to_rows(self):
        return [{"time_utc": to_iso(t), "air_c": a, "wind_10m_m_s": w, "shortwave_w_m2": g, "origin": o}
                for t, a, w, g, o in zip(self.time_s, self.air_c, self.wind_10m_m_s, self.shortwave_w_m2, self.origin)]

    def summary(self):
        counts = {}
        for name in self.origin:
            counts[name] = counts.get(name, 0) + 1
        return {"first_utc": to_iso(self.start_s), "last_utc": to_iso(self.end_s), "hours": int(self.time_s.size),
                "origin_hours": counts, "air_c_min": float(np.nanmin(self.air_c)),
                "air_c_max": float(np.nanmax(self.air_c)), "wind_max_m_s": float(np.nanmax(self.wind_10m_m_s)),
                "shortwave_max_w_m2": float(np.nanmax(self.shortwave_w_m2)),
                "snapshot": self.snapshot.get("folder") or self.snapshot.get("retrieved_at")}


# --- lectura de Open-Meteo ---------------------------------------------------------------------------
def _hourly_array(hourly, name):
    return np.array([np.nan if value is None else value for value in hourly[name]], dtype=float)


def from_open_meteo(payload, metadata=None, suffix=""):
    """Serie desde la respuesta de Open-Meteo. suffix='_member03' para un miembro del ensemble."""
    hourly = payload["hourly"]
    if payload.get("utc_offset_seconds", 0) not in (0, None):
        raise ValueError("Se esperaba timezone=GMT (utc_offset_seconds = 0)")
    for key, name in OPEN_METEO_NAMES.items():
        unit = payload.get("hourly_units", {}).get(name + suffix)
        expected = {"air_c": "°C", "wind_10m_m_s": "m/s", "shortwave_w_m2": "W/m²"}[key]
        if unit is not None and unit != expected:
            raise ValueError(f"{name}: unidad {unit!r}, se esperaba {expected!r} (¿falta wind_speed_unit=ms?)")
    kind = (metadata or {}).get("kind", "dato")
    times = [to_epoch(t) for t in hourly["time"]]
    values = {key: _hourly_array(hourly, name + suffix) for key, name in OPEN_METEO_NAMES.items()}
    return WeatherSeries(times, **values, origin=[kind] * len(times), snapshot=dict(metadata or {}))


def ensemble_members(payload, metadata=None):
    """Lista de series, una por miembro del ensemble (más la principal si viene)."""
    hourly = payload["hourly"]
    suffixes = sorted({key[len("temperature_2m"):] for key in hourly if key.startswith("temperature_2m_member")})
    members = [from_open_meteo(payload, metadata, "")] if "temperature_2m" in hourly else []
    members += [from_open_meteo(payload, metadata, s) for s in suffixes]
    return members


# --- cobertura y relleno ------------------------------------------------------------------------------
def coverage(series, construction_start, days=14.0):
    """¿Cubre la serie desde el inicio hasta inicio + days? Responde en horas."""
    start = to_epoch(construction_start)
    end = start + days * 24 * HOUR
    valid = series.time_s[~series.missing()]
    covered_until = float(valid.max()) if valid.size else start
    covered_from = float(valid.min()) if valid.size else end
    starts_ok = covered_from <= start
    useful = max(0.0, min(covered_until, end) - max(covered_from, start))
    return {"start_utc": to_iso(start), "end_utc": to_iso(end), "needed_hours": (end - start) / HOUR,
            "covered_from_utc": to_iso(covered_from), "covered_until_utc": to_iso(covered_until),
            "covered_hours": useful / HOUR, "missing_hours_at_end": max(0.0, end - max(covered_until, start)) / HOUR,
            "starts_before_construction": bool(starts_ok),
            "complete": bool(starts_ok and covered_until >= end and not np.any(series.missing()))}


def _diurnal(series, last_hours=None):
    """Ciclo diario medio (24 valores por variable) por hora UTC."""
    selection = slice(None) if last_hours is None else slice(-int(last_hours), None)
    hours = ((series.time_s[selection] // HOUR) % 24).astype(int)
    cycle = {}
    for name in FIELDS:
        data = getattr(series, name)[selection]
        cycle[name] = np.array([np.nanmean(data[hours == h]) if np.any(hours == h) else np.nan for h in range(24)])
        if np.any(~np.isfinite(cycle[name])):
            raise ValueError("La referencia no tiene todas las horas del día")
    return cycle


def fill_tail(series, construction_start, days=14.0, method="persistencia", reference=None,
              cold_margin_c=2.0):
    """Extiende la serie hasta inicio + days con horas marcadas por su origen.

    method:
      * "persistencia": repite el ciclo diario medio de las últimas 72 h del pronóstico.
      * "climatologia": ciclo diario medio de `reference` (p. ej. reanálisis del mismo
        mes de años anteriores, descargado como snapshot "archive").
      * "conservador": caso frío para curado: aire = mínimo pronosticado − margen,
        viento = máximo pronosticado, sin sol. Acota por abajo la temperatura del
        hormigón; NO es conservador para el máximo térmico (para eso use un caso cálido).

    Las horas ya pronosticadas no se modifican. Los huecos internos (null) se
    rellenan por interpolación y se marcan "interpolado".
    """
    if method not in ("persistencia", "climatologia", "conservador"):
        raise ValueError("method: persistencia, climatologia o conservador")
    times = series.time_s.copy()
    values = {name: getattr(series, name).copy() for name in FIELDS}
    origin = list(series.origin)
    gaps = series.missing()
    if np.any(gaps):
        for name in FIELDS:
            ok = np.isfinite(values[name])
            values[name][~ok] = np.interp(times[~ok], times[ok], values[name][ok])
        origin = ["interpolado" if gap else o for gap, o in zip(gaps, origin)]
    end = to_epoch(construction_start) + days * 24 * HOUR
    new_times = np.arange(times[-1] + HOUR, end + 0.5 * HOUR, HOUR)
    if new_times.size == 0:
        return WeatherSeries(times, **values, origin=origin, snapshot=series.snapshot)

    hours = ((new_times // HOUR) % 24).astype(int)
    if method == "persistencia":
        base = WeatherSeries(times, **values, origin=origin)
        last = min(72, (times.size // 24) * 24)
        if last == 0:
            raise ValueError("persistencia requiere al menos 24 h pronosticadas")
        cycle = _diurnal(base, last_hours=last)
        extra = {name: cycle[name][hours] for name in FIELDS}
    elif method == "climatologia":
        if reference is None:
            raise ValueError("climatologia requiere una serie de referencia (reanálisis)")
        cycle = _diurnal(reference)
        extra = {name: cycle[name][hours] for name in FIELDS}
    else:
        extra = {"air_c": np.full(new_times.size, np.min(values["air_c"]) - cold_margin_c),
                 "wind_10m_m_s": np.full(new_times.size, np.max(values["wind_10m_m_s"])),
                 "shortwave_w_m2": np.zeros(new_times.size)}
    merged = {name: np.concatenate([values[name], extra[name]]) for name in FIELDS}
    snapshot = {**series.snapshot, "tail_method": method,
                "tail_from_utc": to_iso(new_times[0]), "tail_hours": int(new_times.size)}
    return WeatherSeries(np.concatenate([times, new_times]), **merged,
                         origin=origin + [method] * new_times.size, snapshot=snapshot)


def synthetic_series(construction_start, days=14.0, mean_c=11.0, amplitude_c=4.0, wind_m_s=3.0,
                     peak_shortwave_w_m2=650.0):
    """Serie SINTÉTICA (no es dato): solo para pruebas y para el demo sin conexión.

    Ciclo diario senoidal de aire (mínimo ~06 h local, UTC−3), viento constante y
    sol en media campana entre 07 y 20 h local. Origen marcado "sintetico".
    """
    start = to_epoch(construction_start)
    times = np.arange(start - HOUR, start + days * 24 * HOUR + 0.5 * HOUR, HOUR)
    local_hour = ((times / HOUR) - 3) % 24
    air = mean_c - amplitude_c * np.cos(2 * np.pi * (local_hour - 3) / 24)
    centre = local_hour - 0.5                  # media de la hora anterior
    sun = np.clip(np.sin(np.pi * (centre - 7) / 13), 0, None) * ((centre > 7) & (centre < 20))
    return WeatherSeries(times, air, np.full(times.size, wind_m_s), peak_shortwave_w_m2 * sun,
                         origin=["sintetico"] * times.size,
                         snapshot={"kind": "sintetico", "note": "Serie sintética, no es pronóstico ni medición"})
