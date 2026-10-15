"""Lee el IFC, valida su estructura y comprueba la geometría triangulada."""

import argparse
import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
import ifcopenshell.util.unit
import ifcopenshell.validate
import numpy as np


def inspect_model(path: Path):
    model = ifcopenshell.open(str(path))
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=True)
    errors = [entry for entry in logger.statements if entry["level"] == "error"]
    if errors:
        raise ValueError(f"Validación IFC: {len(errors)} errores: {errors}")
    elements = []
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    for element in model.by_type("IfcFooting"):
        shape = ifcopenshell.geom.create_shape(settings, element)
        vertices = np.asarray(shape.geometry.verts).reshape(-1, 3)
        material = ifcopenshell.util.element.get_material(element)
        elements.append({
            "guid": element.GlobalId, "class": element.is_a(), "name": element.Name,
            "material": material.Name if material else None,
            "dimensions_m": (vertices.max(axis=0) - vertices.min(axis=0)).tolist(),
            "volume_m3": ifcopenshell.util.shape.get_volume(shape.geometry),
            "properties": ifcopenshell.util.element.get_psets(element)
        })
    return {"schema": model.schema, "length_unit_scale_to_m": ifcopenshell.util.unit.calculate_unit_scale(model),
            "validation_errors": len(errors), "footings": elements}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=Path("models/g8_base.ifc"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(inspect_model(args.path), indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result + "\n", encoding="utf-8")
    print(result)
