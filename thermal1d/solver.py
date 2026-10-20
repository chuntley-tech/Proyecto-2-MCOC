"""Balance térmico 1D con propiedades constantes.

Ecuación en la vertical z (0 ≤ z ≤ L):

    ρ cp ∂T/∂t = k ∂²T/∂z² + q̇

donde q̇ es una fuente volumétrica uniforme [W/m³] (por ejemplo, calor de
hidratación). Se discretiza con nodos equiespaciados, diferencias centrales en
el espacio y Euler explícito en el tiempo (FTCS).

Cada nodo interior representa una celda de alto Δz. Cada nodo de borde
representa media celda (Δz/2): por eso su balance usa 2·Fo para la conducción
y divide el flujo de borde por ρ·cp·Δz/2. Referencia:
docs/guias/DIFUSION_DE_CALOR_1D_2D_3D.md, secciones 10, 12 y 22;
G05_DIFUSION_TERMICA_FD.md, interpretación por balance y condiciones de borde.
La guía expresa el flujo positivo saliente; esta API usa el flujo entrante
(signo opuesto), sin cambiar la física. La sección 28 de difusión describe
otra disposición, por celdas centradas con resistencias, no la usada aquí.

Condiciones de borde disponibles en cada extremo:
    Dirichlet(T)            temperatura impuesta
    Neumann(q)              flujo que entra [W/m²]; q = 0 es adiabático
    Robin(h, T_amb)         convección: entra h (T_amb − T_borde) [W/m²]
"""

from dataclasses import dataclass
import math
from typing import Callable, Union

import numpy as np

# Un valor constante o una función del tiempo t [s].
TimeFunction = Union[float, Callable[[float], float]]


@dataclass(frozen=True)
class Dirichlet:
    """Temperatura impuesta en el borde: T = T_b [°C]."""

    temperature_c: float


@dataclass(frozen=True)
class Neumann:
    """Flujo de calor impuesto que ENTRA al dominio por el borde [W/m²].

    flux_in_w_m2 = 0 representa una cara adiabática o un plano de simetría.
    """

    flux_in_w_m2: float = 0.0


@dataclass(frozen=True)
class Robin:
    """Convección: el flujo que entra es h (T_amb − T_borde) [W/m²].

    ambient_c puede ser un número [°C] o una función del tiempo t [s] → °C.
    Si la superficie está más caliente que el aire, el flujo que entra es
    negativo: el borde pierde calor.
    """

    h_w_m2k: float
    ambient_c: TimeFunction

    def ambient_at(self, time_s: float) -> float:
        return _evaluate(self.ambient_c, time_s)


Boundary = Union[Dirichlet, Neumann, Robin]


def _evaluate(value: TimeFunction, time_s: float) -> float:
    result = float(value(time_s)) if callable(value) else float(value)
    if not math.isfinite(result):
        raise ValueError(f"Fuente o temperatura ambiente no finita en t={time_s:g} s")
    return result


def _require_finite(value, message):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(message)


def _check_boundary(boundary, name):
    if isinstance(boundary, Dirichlet):
        _require_finite(boundary.temperature_c, f"{name}: temperatura no finita")
    elif isinstance(boundary, Neumann):
        _require_finite(boundary.flux_in_w_m2, f"{name}: flujo no finito")
    elif isinstance(boundary, Robin):
        _require_finite(boundary.h_w_m2k, f"{name}: h no finito")
        if boundary.h_w_m2k < 0:
            raise ValueError(f"{name}: h debe ser ≥ 0")
        if not callable(boundary.ambient_c):
            _require_finite(boundary.ambient_c, f"{name}: temperatura ambiente no finita")
    else:
        raise TypeError(f"{name} debe ser Dirichlet, Neumann o Robin")


@dataclass(frozen=True)
class Parameters:
    length_m: float
    nodes: int
    conductivity_w_mk: float
    density_kg_m3: float
    specific_heat_j_kgk: float
    dt_s: float
    duration_s: float
    bottom: Boundary            # borde z = 0
    top: Boundary               # borde z = L
    source_w_m3: TimeFunction = 0.0
    check_stability: bool = True    # False solo para demostrar qué pasa con un paso inestable

    def __post_init__(self):
        positive = ("length_m", "conductivity_w_mk", "density_kg_m3",
                    "specific_heat_j_kgk", "dt_s", "duration_s")
        for name in positive:
            value = getattr(self, name)
            _require_finite(value, f"{name} debe ser finito y positivo")
            if value <= 0:
                raise ValueError(f"{name} debe ser finito y positivo")
        if isinstance(self.nodes, bool) or not isinstance(self.nodes, int) or self.nodes < 3:
            raise ValueError("nodes debe ser un entero >= 3")
        _check_boundary(self.bottom, "bottom")
        _check_boundary(self.top, "top")
        if not callable(self.source_w_m3):
            _require_finite(self.source_w_m3, "source_w_m3 no finito")
        if not isinstance(self.check_stability, bool):
            raise ValueError("check_stability debe ser true o false")
        if self.check_stability and self.fourier > self.max_fourier + 1e-12:
            raise ValueError(
                f"Paso inestable: Fo={self.fourier:.6g} > {self.max_fourier:.6g}. "
                f"Use dt_s ≤ {self.max_stable_dt_s:.6g} s"
            )

    @property
    def rho_cp(self):
        """Capacidad térmica volumétrica ρ·cp [J/(m³·K)]."""
        return self.density_kg_m3 * self.specific_heat_j_kgk

    @property
    def alpha_m2_s(self):
        """Difusividad térmica α = k / (ρ·cp) [m²/s]."""
        return self.conductivity_w_mk / self.rho_cp

    @property
    def dx_m(self):
        """Separación entre nodos Δz [m]."""
        return self.length_m / (self.nodes - 1)

    @property
    def fourier(self):
        """Número de Fourier de malla Fo = α·Δt / Δz²."""
        return self.alpha_m2_s * self.dt_s / self.dx_m**2

    @property
    def biot_numbers(self):
        """Bi = h·Δz / k de cada borde (0 si no es Robin): (inferior, superior)."""
        return tuple(b.h_w_m2k * self.dx_m / self.conductivity_w_mk if isinstance(b, Robin) else 0.0
                     for b in (self.bottom, self.top))

    @property
    def max_fourier(self):
        """Fo máximo estable: 1/2 en el interior y 1/(2(1+Bi)) en un borde Robin."""
        return 0.5 / (1.0 + max(self.biot_numbers))

    @property
    def max_stable_dt_s(self):
        return self.max_fourier * self.dx_m**2 / self.alpha_m2_s


@dataclass(frozen=True)
class Solution:
    x_m: np.ndarray
    time_s: np.ndarray
    temperature_c: np.ndarray   # una fila por instante guardado


def _boundary_node(boundary, t_edge, t_inner, time_s, dt, fo, source_heat, rho_cp, dz):
    """Nueva temperatura de un nodo de borde (balance sobre media celda)."""
    if isinstance(boundary, Dirichlet):
        return boundary.temperature_c
    if isinstance(boundary, Neumann):
        flux_in = boundary.flux_in_w_m2
    else:
        flux_in = boundary.h_w_m2k * (boundary.ambient_at(time_s) - t_edge)
    return (t_edge + 2 * fo * (t_inner - t_edge)
            + 2 * dt * flux_in / (rho_cp * dz) + source_heat)


def solve(p: Parameters, initial_c, save_every: int = 1) -> Solution:
    """Integra en el tiempo con Euler explícito y diferencias centrales.

    initial_c: temperatura inicial de cada nodo [°C]. En los bordes Dirichlet
    se reemplaza por la temperatura impuesta. El interior no se modifica.
    save_every: guarda uno de cada `save_every` pasos; siempre guarda el
    instante inicial y el final. El último paso se acorta si hace falta para
    terminar exactamente en duration_s.
    """
    temperature = np.array(initial_c, dtype=float)
    if temperature.shape != (p.nodes,) or not np.all(np.isfinite(temperature)):
        raise ValueError("La temperatura inicial debe contener un valor finito por nodo")
    if isinstance(save_every, bool) or not isinstance(save_every, int) or save_every < 1:
        raise ValueError("save_every debe ser un entero >= 1")
    if isinstance(p.bottom, Dirichlet):
        temperature[0] = p.bottom.temperature_c
    if isinstance(p.top, Dirichlet):
        temperature[-1] = p.top.temperature_c

    steps = math.ceil(p.duration_s / p.dt_s)
    times = np.minimum(np.arange(steps + 1, dtype=float) * p.dt_s, p.duration_s)
    times[-1] = p.duration_s
    dz, rho_cp, alpha = p.dx_m, p.rho_cp, p.alpha_m2_s

    saved_times, saved = [times[0]], [temperature.copy()]
    new = np.empty_like(temperature)
    for step in range(steps):
        time_s, dt = times[step], times[step + 1] - times[step]
        fo = alpha * dt / dz**2
        source_heat = dt * _evaluate(p.source_w_m3, time_s) / rho_cp   # °C aportados en el paso
        new[1:-1] = (temperature[1:-1]
                     + fo * (temperature[2:] - 2 * temperature[1:-1] + temperature[:-2])
                     + source_heat)
        new[0] = _boundary_node(p.bottom, temperature[0], temperature[1],
                                time_s, dt, fo, source_heat, rho_cp, dz)
        new[-1] = _boundary_node(p.top, temperature[-1], temperature[-2],
                                 time_s, dt, fo, source_heat, rho_cp, dz)
        temperature, new = new, temperature
        if (step + 1) % save_every == 0 or step + 1 == steps:
            saved_times.append(times[step + 1])
            saved.append(temperature.copy())
    return Solution(np.linspace(0, p.length_m, p.nodes), np.array(saved_times), np.array(saved))


def energy_per_area_j_m2(p: Parameters, temperature_c):
    """Energía térmica por m² de planta, medida desde 0 °C [J/m²].

    Usa los mismos volúmenes de control del solver: Δz en el interior y Δz/2
    en los bordes. Acepta un perfil o un historial (una fila por instante).
    """
    weights = np.full(p.nodes, p.dx_m)
    weights[[0, -1]] = p.dx_m / 2
    return p.rho_cp * (np.asarray(temperature_c, dtype=float) @ weights)
