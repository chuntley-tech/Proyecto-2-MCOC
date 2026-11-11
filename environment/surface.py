"""Superficie expuesta al ambiente: convección con viento, sol, moldaje y aislación.

Balance en la cara exterior de las capas (moldaje o aislación sin masa):

    a·f·G + h (T_aire − T_ext) = (T_ext − T_s) / R_capas

Despejando T_ext, el calor que entra al hormigón por m² es

    q = (T_sa − T_s) / (1/h + R_capas),     T_sa = T_aire + a·f·G / h

T_sa es la temperatura «sol-aire». El sol (onda corta, G) se absorbe en la
cara exterior y pasa por la misma película de aire y las mismas capas que la
convección: así se suma UNA vez. h es convectivo (más, si se decide, la parte
lineal de onda larga); G nunca es una radiación «neta» que ya incluya pérdidas
por convección o onda larga, porque eso las contaría dos veces.

En el solver, entre el centro del voxel y la cara hay además media celda de
hormigón, Δ/(2k). La resistencia total es Δ/(2k) + 1/h(t) + R_capas(t).
Al desmoldar, R_capas cambia en el instante indicado: la condición de borde
cambia en el tiempo (guía de difusión, §29).

Valores por defecto: correlaciones y propiedades típicas de libro, no
mediciones del proyecto. Deben citarse como supuestos.
"""

from dataclasses import dataclass, field
import math
from typing import Callable, Optional, Union

import numpy as np

TimeFunction = Union[float, Callable[[float], float]]


def _value(item, time_s):
    result = float(item(time_s)) if callable(item) else float(item)
    if not math.isfinite(result):
        raise ValueError(f"Dato ambiental no finito en t = {time_s:g} s")
    return result


def convection_h(wind_m_s: float, a: float = 5.7, b: float = 3.8) -> float:
    """h convectivo [W/(m²·K)] con la correlación lineal de Jürges/McAdams: a + b·v.

    v es el viento sobre la superficie [m/s]. Es una correlación de ingeniería
    para superficies planas (v < ~5 m/s); fuera de ese rango es una extrapolación.
    Con v = 0 queda a, que representa la convección natural.
    """
    if not math.isfinite(wind_m_s) or wind_m_s < 0:
        raise ValueError("La velocidad del viento debe ser finita y no negativa")
    return a + b * wind_m_s


def wind_at_height(wind_10m_m_s: float, height_m: float = 2.0, exponent: float = 0.14) -> float:
    """Traslada el viento de 10 m (dato meteorológico) a la altura de la cara: ley potencial."""
    if height_m <= 0:
        raise ValueError("La altura debe ser positiva")
    return wind_10m_m_s * (height_m / 10.0) ** exponent


@dataclass(frozen=True)
class Layer:
    """Capa delgada sin capacidad térmica: R'' = espesor / k [m²K/W]."""

    name: str
    thickness_m: float
    conductivity_w_mk: float
    source: str = "valor típico de referencia; no medido en el proyecto"

    def __post_init__(self):
        if not (self.thickness_m > 0 and self.conductivity_w_mk > 0):
            raise ValueError("Espesor y conductividad de la capa deben ser positivos")

    @property
    def resistance_m2k_w(self) -> float:
        return self.thickness_m / self.conductivity_w_mk


FORMWORK_PLYWOOD_18MM = Layer("moldaje de contrachapado 18 mm", 0.018, 0.13)
INSULATION_BLANKET_25MM = Layer("manta aislante 25 mm", 0.025, 0.04)


@dataclass(frozen=True)
class LayerSchedule:
    """Capas vigentes por tramos: [(desde_s, (capas...)), ...], ordenado por tiempo.

    Ejemplo: moldaje desde 0 y desmolde a las 72 h →
    LayerSchedule(((0, (FORMWORK_PLYWOOD_18MM,)), (72*3600, ()))).
    """

    stages: tuple = ((0.0, ()),)

    def __post_init__(self):
        starts = [float(start) for start, _ in self.stages]
        if not starts or starts[0] != 0 or any(b <= a for a, b in zip(starts, starts[1:])):
            raise ValueError("Los tramos deben partir en t = 0 y estar en orden creciente")
        for _, layers in self.stages:
            for layer in layers:
                if not isinstance(layer, Layer):
                    raise ValueError("Cada tramo debe contener objetos Layer")

    @classmethod
    def formwork_removed_at(cls, strip_s: float, formwork: Layer = FORMWORK_PLYWOOD_18MM, after=()):
        """Moldaje desde t = 0 y desmolde en strip_s (opcionalmente se agregan otras capas)."""
        if not strip_s > 0:
            raise ValueError("El desmolde debe ocurrir después de t = 0")
        return cls(((0.0, (formwork,)), (float(strip_s), tuple(after))))

    def layers_at(self, time_s: float) -> tuple:
        current = self.stages[0][1]
        for start, layers in self.stages:
            if time_s >= start:
                current = layers
        return tuple(current)

    def resistance_at(self, time_s: float) -> float:
        return sum(layer.resistance_m2k_w for layer in self.layers_at(time_s))

    @property
    def min_resistance_m2k_w(self) -> float:
        return min(sum(layer.resistance_m2k_w for layer in layers) for _, layers in self.stages)

    @property
    def change_times_s(self) -> tuple:
        return tuple(float(start) for start, _ in self.stages[1:])


@dataclass(frozen=True)
class SurfaceExposure:
    """Cara expuesta al ambiente. Objeto de borde que entiende thermal3d.solver.

    air_c, wind_10m_m_s y shortwave_w_m2: número o función de t [s] (serie
    meteorológica interpolada). h: si es None, h = convection_h(viento a
    wind_height_m); si es un número, se usa fijo (sin viento en el modelo).
    solar_absorptance a y solar_factor f: fracción de G que llega y se absorbe
    en esta cara (f = 1 en una cara horizontal superior; 0 en la base). Para
    no subestimar el viento máximo en el criterio de estabilidad se entrega
    max_wind_m_s (el máximo de la serie).
    """

    air_c: TimeFunction
    wind_10m_m_s: TimeFunction = 0.0
    shortwave_w_m2: TimeFunction = 0.0
    layers: LayerSchedule = field(default_factory=LayerSchedule)
    h_w_m2k: Optional[float] = None
    solar_absorptance: float = 0.0
    solar_factor: float = 1.0
    wind_height_m: float = 2.0
    max_wind_m_s: float = 0.0
    name: str = "superficie"
    h_a_w_m2k: float = 5.7
    h_b_w_m2k_per_m_s: float = 3.8
    wind_exponent: float = 0.14

    def __post_init__(self):
        if self.h_w_m2k is not None and not (math.isfinite(self.h_w_m2k) and self.h_w_m2k > 0):
            raise ValueError(f"{self.name}: h fijo debe ser positivo")
        if not (0 <= self.solar_absorptance <= 1 and 0 <= self.solar_factor <= 1):
            raise ValueError(f"{self.name}: absortancia y factor solar entre 0 y 1")
        if not (math.isfinite(self.max_wind_m_s) and self.max_wind_m_s >= 0):
            raise ValueError(f"{self.name}: viento máximo no válido")
        if not (math.isfinite(self.h_a_w_m2k) and self.h_a_w_m2k > 0
                and math.isfinite(self.h_b_w_m2k_per_m_s) and self.h_b_w_m2k_per_m_s >= 0
                and math.isfinite(self.wind_exponent)):
            raise ValueError(f"{self.name}: coeficientes de convección no válidos")

    def validate(self, name: str = ""):
        """Comprueba los datos en t = 0 (el solver la llama al preparar)."""
        self.film_h_w_m2k(0.0)
        self.equivalent_ambient_c(0.0)

    def film_h_w_m2k(self, time_s: float) -> float:
        if self.h_w_m2k is not None:
            return self.h_w_m2k
        wind = _value(self.wind_10m_m_s, time_s)
        if callable(self.wind_10m_m_s) and wind > self.max_wind_m_s:
            raise ValueError(f"{self.name}: viento supera el máximo declarado para la estabilidad")
        return self._h_from_wind(wind)

    def _h_from_wind(self, wind_10m):
        wind = wind_at_height(wind_10m, self.wind_height_m, self.wind_exponent)
        return convection_h(wind, self.h_a_w_m2k, self.h_b_w_m2k_per_m_s)

    def outer_resistance_m2k_w(self, time_s: float) -> float:
        """1/h(t) + R_capas(t): todo lo que hay entre la cara del hormigón y el aire."""
        return 1.0 / self.film_h_w_m2k(time_s) + self.layers.resistance_at(time_s)

    @property
    def min_outer_resistance_m2k_w(self) -> float:
        """Cota inferior en todo el cálculo (viento máximo, sin capas): fija el Δt estable."""
        if self.h_w_m2k is not None:
            h_max = self.h_w_m2k
        else:
            wind_max = self.max_wind_m_s
            if not callable(self.wind_10m_m_s):
                wind_max = max(wind_max, self.wind_10m_m_s)
            h_max = self._h_from_wind(wind_max)
        return 1.0 / h_max + self.layers.min_resistance_m2k_w

    def sol_air_c(self, time_s: float) -> float:
        """T_sa = T_aire + a·f·G/h [°C]: el sol entra una sola vez, por la misma película."""
        absorbed = self.solar_absorptance * self.solar_factor * _value(self.shortwave_w_m2, time_s)
        return _value(self.air_c, time_s) + absorbed / self.film_h_w_m2k(time_s)

    def equivalent_ambient_c(self, time_s: float) -> float:
        return self.sol_air_c(time_s)

    def flux_in_w_m2(self, time_s: float, surface_c: float) -> float:
        """Calor que entra por m² a una cara del hormigón a surface_c (diagnóstico)."""
        return (self.sol_air_c(time_s) - surface_c) / self.outer_resistance_m2k_w(time_s)

    def describe(self, time_s: float) -> dict:
        layers = self.layers.layers_at(time_s)
        return {"cara": self.name, "t_s": time_s, "aire_c": _value(self.air_c, time_s),
                "h_w_m2k": self.film_h_w_m2k(time_s),
                "capas": [layer.name for layer in layers],
                "r_capas_m2k_w": self.layers.resistance_at(time_s),
                "t_sol_aire_c": self.sol_air_c(time_s)}


@dataclass(frozen=True)
class Region:
    """Qué caras toma una condición: direcciones ('z+', 'x-', …) y celdas (máscara)."""

    boundary: object
    directions: Optional[frozenset] = None
    cells: Optional[np.ndarray] = None
    name: str = ""


@dataclass(frozen=True)
class SurfaceMap:
    """Asigna condiciones distintas a caras distintas del mismo dominio.

    Recorre las regiones en orden; la primera que calza con la dirección y la
    celda se queda con la cara. Las caras que no calzan reciben `default`
    (por defecto adiabática). Ejemplo: la cara superior del hormigón con manta
    y sol, los costados con moldaje que se retira, el suelo descubierto al aire.
    """

    regions: tuple
    default: object = None

    def children(self):
        from thermal1d.solver import Neumann
        return [region.boundary for region in self.regions] + [self.default or Neumann(0.0)]

    def split(self, indices, mask, direction):
        from thermal1d.solver import Neumann
        remaining = np.array(mask, dtype=bool, copy=True)
        parts = []
        for region in self.regions:
            if region.directions is not None and direction not in region.directions:
                continue
            selected = remaining if region.cells is None else remaining & np.asarray(region.cells)[indices]
            if np.any(selected):
                parts.append((selected, region.boundary))
                remaining = remaining & ~selected
        parts.append((remaining, self.default or Neumann(0.0)))
        return parts
