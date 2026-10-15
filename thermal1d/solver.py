"""Balance térmico 1D, propiedades constantes y extremos Dirichlet."""

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class Parameters:
    length_m: float
    nodes: int
    conductivity_w_mk: float
    density_kg_m3: float
    specific_heat_j_kgk: float
    dt_s: float
    duration_s: float
    bottom_c: float
    top_c: float

    def __post_init__(self):
        positive = ("length_m", "conductivity_w_mk", "density_kg_m3",
                    "specific_heat_j_kgk", "dt_s", "duration_s")
        for name in positive:
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} debe ser finito y positivo")
        if isinstance(self.nodes, bool) or not isinstance(self.nodes, int) or self.nodes < 3:
            raise ValueError("nodes debe ser un entero >= 3")
        if not all(math.isfinite(v) for v in (self.bottom_c, self.top_c)):
            raise ValueError("Temperaturas de borde no finitas")
        if self.fourier > 0.5 + 1e-12:
            raise ValueError(f"Paso inestable: Fo={self.fourier:.6g} > 0.5")

    @property
    def alpha_m2_s(self):
        return self.conductivity_w_mk / (self.density_kg_m3 * self.specific_heat_j_kgk)

    @property
    def dx_m(self):
        return self.length_m / (self.nodes - 1)

    @property
    def fourier(self):
        return self.alpha_m2_s * self.dt_s / self.dx_m**2


@dataclass(frozen=True)
class Solution:
    x_m: np.ndarray
    time_s: np.ndarray
    temperature_c: np.ndarray


def solve(p: Parameters, initial_c) -> Solution:
    """Euler explícito y segunda diferencia central, sin fuentes internas.

    Los nodos extremos son temperaturas prescritas. El último paso se acorta
    si hace falta para terminar exactamente en duration_s. Se guarda todo el
    historial: implementación inicial para mallas y corridas pequeñas.
    """
    initial = np.asarray(initial_c, dtype=float)
    if initial.shape != (p.nodes,) or not np.all(np.isfinite(initial)):
        raise ValueError("La temperatura inicial debe contener un valor finito por nodo")
    if not np.allclose(initial[[0, -1]], [p.bottom_c, p.top_c], rtol=0, atol=1e-10):
        raise ValueError("La condición inicial debe coincidir con los extremos prescritos")

    steps = math.ceil(p.duration_s / p.dt_s)
    times = np.minimum(np.arange(steps + 1, dtype=float) * p.dt_s, p.duration_s)
    temperatures = np.empty((steps + 1, p.nodes))
    temperatures[0] = initial
    for step, dt in enumerate(np.diff(times)):
        old = temperatures[step]
        new = temperatures[step + 1]
        fo = p.alpha_m2_s * dt / p.dx_m**2
        new[1:-1] = old[1:-1] + fo * (old[2:] - 2 * old[1:-1] + old[:-2])
        new[0], new[-1] = p.bottom_c, p.top_c
    return Solution(np.linspace(0, p.length_m, p.nodes), times, temperatures)


def sine_reference(p: Parameters, x_m, time_s, amplitude_c: float):
    """Solución exacta: perfil lineal estacionario + primer modo seno."""
    x = np.asarray(x_m)
    steady = p.bottom_c + (p.top_c - p.bottom_c) * x / p.length_m
    return steady + amplitude_c * np.sin(np.pi * x / p.length_m) * np.exp(
        -p.alpha_m2_s * (np.pi / p.length_m)**2 * np.asarray(time_s)
    )
