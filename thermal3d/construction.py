"""Plan constructivo y activación por edad local, según G04 y difusión §23–25.

Los componentes BIM se conservan separados de las vertidas. No representa
cinética calibrada, transporte de hormigón ni duración del proceso de llenado.
"""

from dataclasses import dataclass, replace
import numpy as np

from thermal3d.solver import prepare, advance, _energy

GAS_CONSTANT_J_MOL_K = 8.31446261815324
REFERENCE_TEMPERATURE_K = 293.15


def arrhenius_factor(temperature_c, activation_energy_j_mol):
    """d(te)/dt a referencia 20 °C; Ea en J/mol y R en J/(mol·K).

    No se recortan factores: temperaturas no físicas o desbordamientos se
    rechazan para no ocultar errores ni introducir una cinética diferente.
    """
    if (not np.isfinite(activation_energy_j_mol) or activation_energy_j_mol < 0):
        raise ValueError("Ea debe ser finita no negativa [J/mol]")
    kelvin = np.asarray(temperature_c, dtype=float)+273.15
    if not np.all(np.isfinite(kelvin)) or np.any(kelvin <= 0):
        raise ValueError("Arrhenius requiere temperaturas finitas mayores que -273.15 °C")
    with np.errstate(over="ignore", invalid="ignore"):
        factor = np.exp(-activation_energy_j_mol/GAS_CONSTANT_J_MOL_K
                        *(1/kelvin-1/REFERENCE_TEMPERATURE_K))
    if not np.all(np.isfinite(factor)) or np.any(factor <= 0):
        raise ValueError("Factor de Arrhenius fuera del rango numérico")
    return factor


@dataclass(frozen=True)
class CosineHydration:
    """Pulso SINTÉTICO W/m³; integral total qmax*duration/2 J/m³.

    No es temperatura ni calor acumulado. No incluye dependencia con T.
    La conexión física es q = rho*cp*d(theta_ad)/dt (guía difusión §23).
    """

    qmax_w_m3: float = 1300.0
    duration_s: float = 172800.0

    def __post_init__(self):
        if not np.isfinite(self.qmax_w_m3) or self.qmax_w_m3 < 0:
            raise ValueError("Qmax debe ser finito no negativo")
        if not np.isfinite(self.duration_s) or self.duration_s <= 0:
            raise ValueError("Duración de hidratación positiva requerida")

    def rate(self, age_s):
        """Fuente nula antes de colocar y después del pulso; edad en segundos."""
        age = np.asarray(age_s, dtype=float)
        inside = (age >= 0) & (age < self.duration_s)
        safe = np.where(inside, age, 0.0)
        return np.where(inside, self.qmax_w_m3/2*(1-np.cos(2*np.pi*safe/self.duration_s)), 0.0)


@dataclass(frozen=True)
class ExponentialAdiabaticHydration:
    """Curva adiabática del curso: theta_ad(a)=theta_inf*(1-exp(-a/tau)).

    q(a)=rho*cp*(theta_inf/tau)*exp(-a/tau) [W/m³]. El límite de paso de edad
    se fija en 5*tau; la tasa exponencial no se trunca en ese instante (a 5*tau
    aún queda ~0,7 % de la elevación total).
    """

    theta_inf_c: float = 45.0
    tau_s: float = 30.0*3600.0
    density_kg_m3: float = 2400.0
    specific_heat_j_kgk: float = 900.0
    tau_h: float | None = None

    def __post_init__(self):
        if self.tau_h is not None:
            object.__setattr__(self, "tau_s", float(self.tau_h)*3600.0)
        values = (self.theta_inf_c, self.tau_s, self.density_kg_m3, self.specific_heat_j_kgk)
        if not all(np.isfinite(v) and v > 0 for v in values):
            raise ValueError("theta_inf, tau, rho y cp deben ser finitos positivos")

    @property
    def duration_s(self):
        """Límite de paso de edad equivalente (5 tau)."""
        return 5.0*self.tau_s

    def rate(self, age_s):
        """Fuente de hidratación por edad equivalente; nula antes de colocar."""
        age = np.asarray(age_s, dtype=float)
        with np.errstate(over="ignore"):
            return np.where(age >= 0, self.density_kg_m3*self.specific_heat_j_kgk
                            * (self.theta_inf_c/self.tau_s)*np.exp(-np.where(age >= 0, age, 0.0)/self.tau_s), 0.0)

    def theta_ad_c(self, age_s):
        """Elevación adiabática acumulada [°C] de la curva usada."""
        age = np.asarray(age_s, dtype=float)
        return np.where(age >= 0, self.theta_inf_c*(1-np.exp(-np.where(age >= 0, age, 0.0)/self.tau_s)), 0.0)


@dataclass(frozen=True)
class Pour:
    """Capa horizontal: cotas relativas a la altura IFC, inicio [s], T [°C]."""

    id: int
    z_min_fraction: float
    z_max_fraction: float
    start_s: float
    placement_c: float


@dataclass(frozen=True)
class ConstructionPlan:
    """IDs por celda y campos de inicio/colocación independientes del BIM."""

    vertida_id: np.ndarray
    start_s: np.ndarray
    placement_c: np.ndarray
    rows: tuple


def build_plan(grid, pours):
    """Clasifica centros; exige cobertura, sin huecos ni capas vacías (G04)."""
    pours = sorted(pours, key=lambda p: p.z_min_fraction)
    if not pours or len({p.id for p in pours}) != len(pours):
        raise ValueError("Se requieren vertidas con IDs únicos")
    previous = 0.0
    ids = np.zeros(grid.component.shape, dtype=np.int32)
    starts = np.full(ids.shape, np.inf)
    temperatures = np.zeros(ids.shape)
    fractions = (np.arange(ids.shape[2])+0.5)/ids.shape[2]
    rows = []
    for p in pours:
        if (isinstance(p.id, bool) or not isinstance(p.id, int) or p.id < 1
                or p.id > np.iinfo(np.int32).max):
            raise ValueError("ID de vertida entero positivo requerido")
        if (not np.all(np.isfinite([p.z_min_fraction, p.z_max_fraction, p.start_s, p.placement_c]))
                or p.start_s < 0 or p.z_min_fraction != previous
                or not p.z_min_fraction < p.z_max_fraction <= 1):
            raise ValueError("Capas deben cubrir [0,1] sin huecos ni solapamientos; inicio >= 0")
        selected = grid.active & ((fractions >= p.z_min_fraction) & (fractions < p.z_max_fraction))[None, None, :]
        if not selected.any():
            raise ValueError("Vertida sin celdas; refinar malla o cambiar capas")
        ids[selected], starts[selected], temperatures[selected] = p.id, p.start_s, p.placement_c
        rows.append({"vertida_id": p.id, "start_s": p.start_s, "placement_c": p.placement_c,
                     "z_min_m": float(grid.origin_m[2]+grid.lengths_m[2]*p.z_min_fraction),
                     "z_max_m": float(grid.origin_m[2]+grid.lengths_m[2]*p.z_max_fraction),
                     "cells": int(selected.sum()),
                     "volume_m3": float(selected.sum()*np.prod(grid.spacing_m))})
        previous = p.z_max_fraction
    if previous != 1 or np.any(grid.active & (ids == 0)):
        raise ValueError("El plan debe cubrir todo el hormigón")
    return ConstructionPlan(ids, starts, temperatures, tuple(rows))


@dataclass(frozen=True)
class ConstructionSolution:
    """Estados posteriores a activación; energía de colocación relativa a 0 °C."""

    time_s: np.ndarray
    temperature_c: np.ndarray
    active: np.ndarray
    energy_j: np.ndarray
    boundary_heat_in_j: np.ndarray
    source_heat_in_j: np.ndarray
    placement_energy_j: np.ndarray
    equivalent_age_s: np.ndarray
    step_count: int = 0

    @property
    def energy_balance_error_j(self):
        return (self.energy_j-self.energy_j[0]-self.boundary_heat_in_j
                -self.source_heat_in_j-self.placement_energy_j)


def solve_construction(p, plan, hydration, save_every=100, *, activation_energy_j_mol=0.0,
                       source_mask=None, initial_c=None):
    """Euler en t_n con reloj de edad por celda y eventos exactos de colocación.

    dt_s es un máximo: se reduce por estabilidad, pulso/100 y eventos.
    Conductancias se reconstruyen solo cuando cambia la máscara. Antes de
    colocar, T=0 es un marcador sin significado físico: consultar active.
    La fuente propia sustituye source_w_m3, que debe ser cero. Interfaces
    temporales expuestas usan p.exposed; sin él son adiabáticas.
    te parte en cero al colocar; q=hydration.rate(te_n)*factor(T_n) y
    te_{n+1}=te_n+dt*factor(T_n). Ea=0 conserva edad cronológica; no es
    una calibración. Se limita también el incremento de te a pulso/100.

    source_mask (opcional) separa las celdas que hidratan (hormigón) de las
    que solo conducen calor (por ejemplo, suelo). Si se entrega, debe tener el
    mismo shape y coincidir con las celdas marcadas por el plan; las celdas
    activas fuera de la máscara parten en initial_c (por defecto 0 °C) y no
    reciben fuente ni envejecen. Sin source_mask se conserva el comportamiento
    anterior: toda celda activa pertenece al plan y recibe hidratación.
    """
    if isinstance(save_every, bool) or not isinstance(save_every, int) or save_every < 1:
        raise ValueError("save_every debe ser entero positivo")
    if callable(p.source_w_m3) or np.any(np.asarray(p.source_w_m3) != 0):
        raise ValueError("Usar solo hidratación; source_w_m3 debe ser cero")
    arrhenius_factor(np.array([20.0]), activation_energy_j_mol)
    geometric = np.ones(p.shape, bool) if p.active is None else p.active
    poured = plan.vertida_id > 0
    if source_mask is None:
        reactive = geometric
    else:
        reactive = np.asarray(source_mask, dtype=bool)
        if reactive.shape != tuple(p.shape):
            raise ValueError("source_mask debe tener el shape de la grilla")
        if np.any(reactive & ~geometric):
            raise ValueError("source_mask debe ser subconjunto de la máscara activa")
        if not np.array_equal(poured, reactive):
            raise ValueError("Las celdas del plan deben coincidir con source_mask")
    if (plan.vertida_id.shape != tuple(p.shape) or plan.start_s.shape != tuple(p.shape)
            or plan.placement_c.shape != tuple(p.shape)
            or not np.array_equal(poured, reactive)):
        raise ValueError("Plan incompatible con la máscara geométrica")
    if initial_c is not None:
        initial_c = np.asarray(initial_c, dtype=float)
        if initial_c.shape != tuple(p.shape) or not np.all(np.isfinite(initial_c)):
            raise ValueError("initial_c debe tener un valor finito por celda")
    # Validar propiedades y obtener capacidades sin exigir dt del usuario.
    reference = prepare(replace(p, dt_s=1e-30))
    capacity = np.broadcast_to(reference.capacity_j_k, p.shape)
    active = geometric & ((poured & (plan.start_s <= 0)) | ~poured)
    initial = np.zeros(p.shape) if initial_c is None else initial_c
    temperature = np.where(active, np.where(poured, plan.placement_c, initial), 0.0)
    equivalent_age = np.zeros(p.shape, dtype=float)
    c = prepare(replace(p, active=active, dt_s=1e-30)) if active.any() else None
    events = np.unique(plan.start_s[poured]) if poured.any() else np.empty(0)
    times, fields, masks, energies = [], [], [], []
    boundary, sources, placements = [], [], []
    ages = []
    qb = qs = qp = time = 0.0

    def save():
        times.append(time); fields.append(temperature.copy()); masks.append(active.copy())
        energies.append(_energy(temperature, c) if c is not None else 0.0)
        boundary.append(qb); sources.append(qs); placements.append(qp)
        ages.append(equivalent_age.copy())

    save()
    step = 0
    while time < p.duration_s:
        future = events[events > time]
        event = float(future[0]) if future.size else p.duration_s
        limit = min(c.general_dt_s, c.local_dt_s)*0.8 if c is not None else np.inf
        reacting = active & reactive
        factor = arrhenius_factor(temperature[reacting], activation_energy_j_mol)
        age_limit = hydration.duration_s/(100*max(1.0, float(factor.max()) if factor.size else 1.0))
        end = min(time+p.dt_s, time+limit, time+age_limit, event, p.duration_s)
        if end <= time:
            raise ValueError("Paso temporal menor que la precisión del reloj")
        if c is not None:
            # Regla de la cadena: rate está definida por segundo equivalente.
            heat = np.zeros(p.shape)
            heat[reacting] = hydration.rate(equivalent_age[reacting])*factor
            b, s = advance(p, c, temperature, time, end-time, heat)
            qb += b; qs += s
            equivalent_age[reacting] += (end-time)*factor
        time = end
        new = poured & ~active & (plan.start_s <= time)
        changed = bool(new.any())
        if changed:
            temperature[new] = plan.placement_c[new]
            equivalent_age[new] = 0.0
            qp += float(np.sum(capacity[new]*temperature[new]))
            active = active | new
            c = prepare(replace(p, active=active, dt_s=1e-30))
        step += 1
        if changed or step % save_every == 0 or time == p.duration_s:
            save()
    return ConstructionSolution(*(np.asarray(values) for values in
                                  (times, fields, masks, energies, boundary, sources, placements, ages)), step_count=step)
