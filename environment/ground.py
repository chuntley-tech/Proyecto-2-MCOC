"""Tratamiento del suelo bajo la fundación (G04: suelo explícito o condición efectiva).

Tres opciones, de la más simple a la más completa:

1. Base adiabática, Neumann(0): el suelo no intercambia calor. Simple, pero
   sobreestima la temperatura cerca de la base.
2. Base a temperatura fija, Dirichlet(T_suelo): supone que el suelo es un
   sumidero infinito pegado al hormigón. Exagera el enfriamiento de la base.
3. Suelo explícito (esta función): voxeles de suelo con su k, ρ y cp bajo el
   hormigón, hasta una profundidad donde se impone la temperatura profunda.
   El suelo almacena y conduce calor; la superficie del terreno alrededor de la
   fundación queda expuesta al aire.

Propiedades por defecto del suelo: Ju y Lei (2019), citadas en la guía de
difusión §31 (k = 1,39 W/(m·K), ρ = 1800 kg/m³, cp = 1273 J/(kg·K)). La
temperatura profunda es un SUPUESTO (del orden de la media anual del aire del
lugar); debe reemplazarse por un dato o justificarse.
"""

from dataclasses import dataclass
import math

import numpy as np


@dataclass(frozen=True)
class SoilModel:
    depth_m: float = 2.2
    margin_m: float = 0.0
    conductivity_w_mk: float = 1.39
    density_kg_m3: float = 1800.0
    specific_heat_j_kgk: float = 1273.0
    deep_temperature_c: float = 10.0
    source: str = ("k, ρ y cp: Ju y Lei (2019), guía de difusión §31. "
                   "Temperatura profunda: supuesto, no medido.")

    def __post_init__(self):
        values = (self.depth_m, self.conductivity_w_mk, self.density_kg_m3, self.specific_heat_j_kgk)
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError("Profundidad y propiedades del suelo deben ser positivas")
        if not (math.isfinite(self.margin_m) and self.margin_m >= 0 and math.isfinite(self.deep_temperature_c)):
            raise ValueError("Margen no negativo y temperatura profunda finita")


def _cells(length, spacing, name):
    count = round(length / spacing)
    if not math.isclose(count * spacing, length, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError(f"{name} ({length:g} m) debe ser múltiplo del espaciamiento ({spacing:g} m)")
    return int(count)


def add_soil_layer(active, spacing_m, lengths_m, concrete, soil: SoilModel):
    """Agrega suelo bajo el hormigón (último eje = vertical) y un margen lateral.

    active: máscara del hormigón; concrete: k, ρ, cp del hormigón (dict de
    escalares o campos). Devuelve un dict con la grilla ampliada: shape,
    lengths_m, active (hormigón ∪ suelo), campos de material, máscaras
    'concrete' y 'soil', el desplazamiento del origen y la condición de la
    base (Dirichlet a la temperatura profunda).
    """
    from thermal1d.solver import Dirichlet

    active = np.asarray(active, dtype=bool)
    spacing = np.asarray(spacing_m, dtype=float)
    lengths = np.asarray(lengths_m, dtype=float)
    vertical = active.ndim - 1
    depth = _cells(soil.depth_m, spacing[vertical], "La profundidad del suelo")
    pads = [(0, 0)] * active.ndim
    for axis in range(vertical):
        margin = _cells(soil.margin_m, spacing[axis], "El margen") if soil.margin_m else 0
        pads[axis] = (margin, margin)
    pads[vertical] = (depth, 0)
    concrete_mask = np.pad(active, pads, constant_values=False)
    soil_mask = np.zeros_like(concrete_mask)
    index = [slice(None)] * active.ndim
    index[vertical] = slice(0, depth)
    soil_mask[tuple(index)] = True

    fields = {}
    for key, soil_value in (("conductivity_w_mk", soil.conductivity_w_mk), ("density_kg_m3", soil.density_kg_m3),
                            ("specific_heat_j_kgk", soil.specific_heat_j_kgk)):
        value = np.broadcast_to(np.asarray(concrete[key], dtype=float), active.shape)
        field = np.pad(value, pads, mode="edge")
        field = np.where(soil_mask, soil_value, field)
        fields[key] = field
    shape = concrete_mask.shape
    new_lengths = tuple(float(n * d) for n, d in zip(shape, spacing))
    shift = [-pads[axis][0] * spacing[axis] for axis in range(active.ndim)]
    return {"shape": shape, "lengths_m": new_lengths, "active": concrete_mask | soil_mask,
            "concrete": concrete_mask, "soil": soil_mask, **fields, "origin_shift_m": shift,
            "base": Dirichlet(soil.deep_temperature_c), "soil_model": soil}
