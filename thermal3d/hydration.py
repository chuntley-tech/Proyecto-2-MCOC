"""Curvas de fuente volumétrica obtenidas por inversión térmica."""

from dataclasses import dataclass
import numpy as np

NAMES = tuple(f"M{i}_{campaign}" for campaign in ("SS", "22A") for i in range(1, 5))
REFERENCE_MJ_M3 = (88.1, 95.7, 94.1, 100.2, 61.2, 82.4, 73.3, 73.6)


@dataclass(frozen=True)
class TabulatedHydration:
    age_s: np.ndarray
    source_w_m3: np.ndarray
    tail_s: float

    @property
    def duration_s(self):
        """Escala de integración usada por el solver constructivo."""
        return self.age_s[-1]

    def rate(self, age_s):
        age = np.asarray(age_s)
        end = self.age_s[-1]
        return np.where(age <= end, np.interp(age, self.age_s, self.source_w_m3, left=0),
                        self.source_w_m3[-1] * np.exp(-np.maximum(age-end, 0) / self.tail_s))


def load_curves(path, *, offset_h=2.0, tail_h=24.0):
    """Preserva el tramo registrado y añade rampas/colas explícitas de modelo."""
    if not np.isfinite([offset_h, tail_h]).all() or min(offset_h, tail_h) <= 0:
        raise ValueError("Desfase y constante de cola deben ser positivos")
    table = np.loadtxt(path, ndmin=2)
    time_h = table[:, 0]
    if (table.shape[1] != 9 or time_h.size < 2 or not np.isfinite(time_h).all()
            or time_h[0] != 0 or not np.allclose(np.diff(time_h), 1/6, atol=.001)):
        raise ValueError("Se requieren tiempo en horas (10 min) y ocho curvas en W/m³")
    curves, audit = {}, {}
    for name, expected, values in zip(NAMES, REFERENCE_MJ_M3, table[:, 1:].T):
        stop = int(np.count_nonzero(np.isfinite(values)))
        measured = values[:stop]
        if stop < 2 or not np.isfinite(measured).all() or np.any(measured < 0) or not np.isnan(values[stop:]).all():
            raise ValueError(f"{name}: hueco interno o valor inválido")
        recorded = float(np.trapezoid(measured, time_h[:stop]) * 0.0036)
        if abs(recorded - expected) > .055:
            raise ValueError(f"{name}: integral {recorded:g} MJ/m³ incompatible con la cabecera")
        ages = np.r_[0, (time_h[:stop] + offset_h) * 3600]
        source = np.r_[0, measured]
        curves[name] = TabulatedHydration(ages, source, tail_h * 3600)
        audit[name] = {"record_end_h": float(time_h[stop-1]), "record_samples": stop,
                       "record_heat_mj_m3": recorded, "header_heat_mj_m3": expected,
                       "initial_model_heat_mj_m3": float(measured[0] * offset_h * .0018),
                       "tail_model_heat_mj_m3": float(measured[-1] * tail_h * .0036)}
    return curves, audit
