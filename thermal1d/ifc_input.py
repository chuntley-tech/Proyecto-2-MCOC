"""Adaptador IFC → entradas numéricas del caso; el solver no usa Blender."""

from copy import deepcopy
import hashlib
import math
from pathlib import Path

import numpy as np


THERMAL_PSET = "MCOC_Thermal1D"
THERMAL_PROPERTIES = {
    "conductivity_w_mk": "Conductivity_W_mK",
    "density_kg_m3": "Density_kg_m3",
    "specific_heat_j_kgk": "SpecificHeat_J_kgK",
}


def resolve_ifc_inputs(config, config_dir, ifc_path=None):
    """Lee altura real y, si está configurado, propiedades térmicas comunes.

    Rutas del JSON: relativas a su carpeta. --ifc: relativa al directorio actual.
    La altura es la envolvente vertical de los sólidos seleccionados, no una
    propiedad de texto. Se exige una pila vertical contigua con intersección XY.
    No se construye una malla térmica 3D ni una sección variable.
    """
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element
    import ifcopenshell.validate

    resolved = deepcopy(config)
    binding = dict(config.get("ifc", {}))
    if ifc_path is not None:
        path = Path(ifc_path).resolve()
    elif binding.get("path"):
        path = (Path(config_dir) / binding["path"]).resolve()
    else:
        raise ValueError("Debe indicar ifc.path en el caso o --ifc en el comando")
    if not path.is_file():
        raise ValueError(f"No se encontró el IFC: {path}")
    fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
    model = ifcopenshell.open(str(path))
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=True)
    if any(entry["level"] == "error" for entry in logger.statements):
        raise ValueError("El IFC tiene errores de validación; no se usarán sus datos")

    guids = binding.get("element_guids")
    if guids is not None:
        if not isinstance(guids, list) or not guids or len(set(guids)) != len(guids):
            raise ValueError("ifc.element_guids debe ser una lista no vacía sin duplicados")
        products = []
        for guid in guids:
            try:
                element = model.by_guid(guid)
            except RuntimeError as error:
                raise ValueError(f"No se encontró el objeto IFC con GUID {guid}") from error
            if not element.is_a("IfcFooting"):
                raise ValueError(f"El objeto {guid} no es IfcFooting")
            products.append(element)
    else:
        products = model.by_type("IfcFooting")
    if not products:
        raise ValueError("El IFC no contiene los sólidos necesarios para el dominio 1D")

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    settings.set(settings.CONVERT_BACK_UNITS, False)  # vértices en SI (metros)
    records = []
    for element in products:
        shape = ifcopenshell.geom.create_shape(settings, element)
        vertices = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
        if not vertices.size or not np.all(np.isfinite(vertices)):
            raise ValueError(f"Geometría vacía o no finita en {element.GlobalId}")
        low, high = vertices.min(axis=0), vertices.max(axis=0)
        if np.any(high <= low):
            raise ValueError(f"Sólido degenerado en {element.GlobalId}")
        records.append({"guid": element.GlobalId, "name": element.Name,
                        "bounds_min_m": low.tolist(), "bounds_max_m": high.tolist()})
    records.sort(key=lambda e: e["bounds_min_m"][2])
    for lower, upper in zip(records, records[1:]):
        if not math.isclose(lower["bounds_max_m"][2], upper["bounds_min_m"][2], abs_tol=1e-5, rel_tol=0):
            raise ValueError("Los sólidos tienen huecos o solapamientos verticales; revise el IFC antes de usar un dominio 1D")
    lows = np.asarray([r["bounds_min_m"] for r in records])
    highs = np.asarray([r["bounds_max_m"] for r in records])
    if np.any(np.max(lows[:, :2], axis=0) >= np.min(highs[:, :2], axis=0)):
        raise ValueError("Los sólidos no tienen una zona XY común para la aproximación vertical")
    low, high = lows.min(axis=0), highs.max(axis=0)
    thermal = resolved["thermal"]
    applied = {"length_m": {"configured": thermal.get("length_m"), "used": float(high[2] - low[2])}}
    thermal["length_m"] = applied["length_m"]["used"]

    source_guid = binding.get("thermal_property_guid")
    if source_guid:
        if source_guid not in {e.GlobalId for e in products}:
            raise ValueError("El objeto con propiedades térmicas debe pertenecer al dominio seleccionado")
        psets = ifcopenshell.util.element.get_psets(model.by_guid(source_guid))
        properties = psets.get(THERMAL_PSET, {})
        for field, property_name in THERMAL_PROPERTIES.items():
            value = properties.get(property_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"Falta o no es válida {THERMAL_PSET}.{property_name} en {source_guid}")
            applied[field] = {"configured": thermal.get(field), "used": float(value)}
            thermal[field] = float(value)
    if hashlib.sha256(path.read_bytes()).hexdigest() != fingerprint:
        raise ValueError("El IFC cambió durante la lectura; guarde el archivo y vuelva a ejecutar")
    metadata = {
        "file": path.name, "sha256": fingerprint, "elements": records,
        "bounds_min_m": low.tolist(), "bounds_max_m": high.tolist(),
        "applied_inputs": applied, "thermal_property_guid": source_guid,
        "thermal_property_set": THERMAL_PSET if source_guid else None,
        "scope": "Altura de envolvente vertical y propiedades homogéneas comunes; no representa sección variable ni flujos laterales",
    }
    return resolved, metadata
