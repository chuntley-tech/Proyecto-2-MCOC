"""Difusión 2D/3D por balances centrados en celdas (G05 y difusión §§26–30).

Los ejes del array son (x, y[, z]); cada celda tiene volumen completo. En 2D
la profundidad es 1 m. Las interfaces activa/inactiva son adiabáticas salvo
que se declare explícitamente `exposed`, para representar una superficie.
G04 motiva la máscara; G08 exige separar estos cálculos de la lectura IFC.
"""

from dataclasses import dataclass, field
import math

import numpy as np

from thermal1d.solver import Dirichlet, Neumann, Robin, _check_boundary, _evaluate


@dataclass(frozen=True)
class Parameters:
    """Geometría SI, propiedades escalares o por celda y entradas trazables.

    shape contiene números de celdas, lengths_m las longitudes de la caja.
    source_w_m3 y Robin.ambient_c admiten constantes o funciones de t [s].
    Los bordes omitidos son adiabáticos; el flujo Neumann es positivo entrante.
    """

    shape: tuple
    lengths_m: tuple
    conductivity_w_mk: float
    density_kg_m3: float
    specific_heat_j_kgk: float
    dt_s: float
    duration_s: float
    boundaries: dict = field(default_factory=dict)
    active: np.ndarray | None = None
    source_w_m3: object = 0.0
    exposed: object = None

    def __post_init__(self):
        counts = np.asarray(self.shape)
        lengths = np.asarray(self.lengths_m, dtype=float)
        if (counts.ndim != 1 or counts.size not in (2, 3)
                or counts.dtype.kind not in "iu" or np.any(counts < 1)):
            raise ValueError("shape debe contener dos o tres enteros positivos")
        if lengths.shape != counts.shape or not np.all(np.isfinite(lengths)) or np.any(lengths <= 0):
            raise ValueError("lengths_m debe contener una longitud finita positiva por eje")
        _material(self.conductivity_w_mk, self.shape)
        _material(self.density_kg_m3, self.shape)
        _material(self.specific_heat_j_kgk, self.shape)
        values = np.asarray([self.dt_s, self.duration_s], dtype=float)
        if not np.all(np.isfinite(values)) or np.any(values <= 0):
            raise ValueError("k, rho, cp, dt y duración deben ser finitos positivos")
        if self.active is not None:
            mask = np.asarray(self.active)
            if mask.shape != tuple(self.shape) or mask.dtype != np.bool_ or not mask.any():
                raise ValueError("active debe ser booleana, tener el shape de la grilla y alguna celda activa")
        if not callable(self.source_w_m3):
            _evaluate(self.source_w_m3, 0.0)
        if self.exposed is not None:
            _check_boundary(self.exposed, "exposed")

    @property
    def spacing_m(self):
        """Δ por eje: longitud dividida por número de celdas."""
        return np.asarray(self.lengths_m, dtype=float) / np.asarray(self.shape)

    @property
    def alpha_m2_s(self):
        return _material(self.conductivity_w_mk, self.shape) / (_material(self.density_kg_m3, self.shape) * _material(self.specific_heat_j_kgk, self.shape))


@dataclass(frozen=True)
class Coefficients:
    """Conductancias [W/K] y capacidades [J/K] precalculadas una sola vez."""

    active: np.ndarray
    capacity_j_k: object
    volume_m3: float
    gx: np.ndarray
    gy: np.ndarray
    gz: np.ndarray | None
    faces: tuple
    general_dt_s: float
    local_dt_s: float
    fourier_sum: float


@dataclass(frozen=True)
class Solution:
    """Solo estados solicitados y energía activa ΣρcpVT relativa a 0 °C [J]."""

    time_s: np.ndarray
    temperature_c: np.ndarray
    energy_j: np.ndarray
    boundary_heat_in_j: np.ndarray
    source_heat_in_j: np.ndarray

    @property
    def energy_balance_error_j(self):
        """Residuo E−E₀−Q_borde−Q_fuente en los instantes guardados [J]."""
        return self.energy_j - self.energy_j[0] - self.boundary_heat_in_j - self.source_heat_in_j


def _material(value, shape):
    """Conserva el camino escalar y acepta campos finitos positivos compatibles."""
    array = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(array)) or np.any(array <= 0):
        raise ValueError("k, rho y cp deben ser finitos positivos")
    return float(array) if array.ndim == 0 else np.broadcast_to(array, shape)


def effective_h(h_w_m2k, *resistances_m2k_w):
    """Coeficiente equivalente: película y capas de resistencia R'' en serie."""
    values = np.asarray((h_w_m2k,) + resistances_m2k_w, dtype=float)
    if not np.all(np.isfinite(values)) or np.any(values < 0):
        raise ValueError("h y resistencias deben ser finitos no negativos")
    return 0.0 if h_w_m2k == 0 else 1 / (1/h_w_m2k + sum(resistances_m2k_w))


def _interface(active, lower, upper, k, geometric_factor, diagonal):
    """Una cara interna intercambia la misma potencia con signos opuestos."""
    # Dos medias celdas: media armónica; con material escalar no se altera la API.
    conductivity = k if np.isscalar(k) else 2 * k[lower] * k[upper] / (k[lower] + k[upper])
    g = conductivity * geometric_factor * (active[lower] & active[upper])
    diagonal[lower] += g
    diagonal[upper] += g
    return g


def _add_face(faces, diagonal, indices, mask, boundary, k, area, delta):
    """Ensamble común de una cara exterior o expuesta, una sola vez."""
    local_k = k if np.isscalar(k) else k[indices]
    if isinstance(boundary, Dirichlet):
        g = 2 * local_k * area / delta * mask
    elif isinstance(boundary, Robin) and boundary.h_w_m2k > 0:
        g = area / (1/boundary.h_w_m2k + delta/(2*local_k)) * mask
    else:
        g = np.zeros_like(mask, dtype=float)
    diagonal[indices] += g
    faces.append((indices, boundary, g, area * mask))


def prepare(p):
    """Precalcula caras y rechaza ambos límites explícitos de G05 y §30.

    Dirichlet usa media celda conductiva; Robin suma esa resistencia y la
    película convectiva. h=0 equivale a cara adiabática sin dividir por cero.
    """
    active = np.ones(p.shape, dtype=bool) if p.active is None else np.array(p.active, copy=True)
    spacing = p.spacing_m
    volume = float(np.prod(spacing))  # profundidad unitaria en 2D
    capacity = _material(p.density_kg_m3, p.shape) * _material(p.specific_heat_j_kgk, p.shape) * volume
    diagonal = np.zeros(p.shape)
    k = _material(p.conductivity_w_mk, p.shape)
    gx = _interface(active, np.s_[:-1, ...], np.s_[1:, ...], k, volume / spacing[0]**2, diagonal)
    gy = _interface(active, np.s_[:, :-1, ...], np.s_[:, 1:, ...], k, volume / spacing[1]**2, diagonal)
    gz = None
    if len(p.shape) == 3:
        gz = _interface(active, np.s_[:, :, :-1], np.s_[:, :, 1:], k, volume / spacing[2]**2, diagonal)
    faces = []
    valid = {"x-", "x+", "y-", "y+"}
    if len(p.shape) == 3:
        valid |= {"z-", "z+"}
    for face, boundary in p.boundaries.items():
        if face not in valid:
            raise ValueError(f"Cara desconocida para esta grilla: {face}")
        _check_boundary(boundary, face)
        axis = "xyz".index(face[0])
        indices = [slice(None)] * len(p.shape)
        indices[axis] = 0 if face[1] == "-" else -1
        indices = tuple(indices)
        area = volume / spacing[axis]
        _add_face(faces, diagonal, indices, active[indices], boundary, k, area, spacing[axis])
    if p.exposed is not None:
        # Lista corta de caras orientadas, sin iterar por celdas.
        oriented = [(0, np.s_[:-1, ...], np.s_[1:, ...]), (0, np.s_[1:, ...], np.s_[:-1, ...]),
                    (1, np.s_[:, :-1, ...], np.s_[:, 1:, ...]), (1, np.s_[:, 1:, ...], np.s_[:, :-1, ...])]
        if len(p.shape) == 3:
            oriented += [(2, np.s_[:, :, :-1], np.s_[:, :, 1:]), (2, np.s_[:, :, 1:], np.s_[:, :, :-1])]
        for axis, indices, neighbor in oriented:
            mask = active[indices] & ~active[neighbor]
            if mask.any():
                _add_face(faces, diagonal, indices, mask, p.exposed, k, volume/spacing[axis], spacing[axis])
    alpha = k * volume / capacity
    max_alpha = float(alpha) if np.isscalar(alpha) else float(np.max(alpha[active]))
    general_dt = 0.5 / (max_alpha * float(np.sum(1 / spacing**2)))
    with np.errstate(divide="ignore", invalid="ignore"):
        limits = np.where(diagonal > 0, capacity / diagonal, np.inf)
    local_dt = float(np.min(limits[active]))
    fourier = max_alpha * p.dt_s * float(np.sum(1 / spacing**2))
    if p.dt_s > general_dt:
        raise ValueError(f"Estabilidad general: suma Fo={fourier:.12g} > 0.5; dt={p.dt_s:.12g} s, límite={general_dt:.12g} s")
    if p.dt_s > local_dt:
        raise ValueError(f"Estabilidad local: dt={p.dt_s:.12g} s > C/suma(G)={local_dt:.12g} s")
    return Coefficients(active, capacity, volume, gx, gy, gz, tuple(faces), general_dt, local_dt, fourier)


def _exchange(power, temperature, lower, upper, g):
    """Slicing sin periodicidad: flujo interno conservativo entre vecinos."""
    flux = g * (temperature[upper] - temperature[lower])
    power[lower] += flux
    power[upper] -= flux


def _energy(temperature, c):
    """Suma ponderada sin incluir energía de celdas inactivas."""
    if np.isscalar(c.capacity_j_k):
        return float(np.sum(temperature[c.active]) * c.capacity_j_k)
    return float(np.sum((temperature * c.capacity_j_k)[c.active]))


def solve(p, initial_c, save_every=100):
    """Euler explícito: fuente y ambiente se evalúan en t_n, nunca al final.

    Se acorta el último paso y se guarda inicial, cada save_every y final.
    No se construye un historial de pasos no solicitados. Las celdas inactivas
    conservan su temperatura inicial y no participan en energía ni interfaces.
    """
    if isinstance(save_every, bool) or not isinstance(save_every, int) or save_every < 1:
        raise ValueError("save_every debe ser un entero positivo")
    temperature = np.array(initial_c, dtype=float)
    if temperature.shape != tuple(p.shape) or not np.all(np.isfinite(temperature)):
        raise ValueError("Temperatura inicial: un valor finito por celda")
    c = prepare(p)
    saved_times, saved = [0.0], [temperature.copy()]
    energies = [_energy(temperature, c)]
    boundary_heat, source_heat = [0.0], [0.0]
    accumulated_boundary = accumulated_source = 0.0
    steps = math.ceil(p.duration_s / p.dt_s)
    time = 0.0
    for step in range(steps):
        end = min((step + 1) * p.dt_s, p.duration_s)
        dt = end - time
        power = np.zeros_like(temperature)
        _exchange(power, temperature, np.s_[:-1, ...], np.s_[1:, ...], c.gx)
        _exchange(power, temperature, np.s_[:, :-1, ...], np.s_[:, 1:, ...], c.gy)
        if c.gz is not None:
            _exchange(power, temperature, np.s_[:, :, :-1], np.s_[:, :, 1:], c.gz)
        for indices, boundary, g, area in c.faces:
            if isinstance(boundary, Neumann):
                face_power = boundary.flux_in_w_m2 * area
            else:
                ambient = boundary.temperature_c if isinstance(boundary, Dirichlet) else boundary.ambient_at(time)
                face_power = g * (ambient - temperature[indices])
            power[indices] += face_power
            accumulated_boundary += float(np.sum(face_power)) * dt
        source_power = _evaluate(p.source_w_m3, time) * c.volume_m3 * c.active
        power += source_power
        accumulated_source += float(np.sum(source_power)) * dt
        temperature += dt / c.capacity_j_k * power
        time = end
        if (step + 1) % save_every == 0 or step + 1 == steps:
            saved_times.append(time)
            saved.append(temperature.copy())
            energies.append(_energy(temperature, c))
            boundary_heat.append(accumulated_boundary)
            source_heat.append(accumulated_source)
    return Solution(np.asarray(saved_times), np.asarray(saved), np.asarray(energies),
                    np.asarray(boundary_heat), np.asarray(source_heat))
