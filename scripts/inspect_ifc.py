"""Lee un IFC de la fundación, lo valida y resume cada vertida.

Uso (desde la raíz):
    python -m scripts.inspect_ifc
    python -m scripts.inspect_ifc models/foundation.ifc --output results/ifc_validation.json
    python -m scripts.inspect_ifc models/foundation.ifc --compare results/ifc_validation.json

Con --compare se listan las diferencias respecto de una inspección guardada
antes. Sirve para la prueba de ida y vuelta: modificar una vertida en Bonsai,
guardar el IFC y comprobar desde Python qué cambió.
"""

import argparse
import json
from pathlib import Path

import numpy as np


def _clean_psets(psets):
    """Property sets sin el 'id' interno, que cambia cada vez que se guarda el archivo."""
    return {name: {key: value for key, value in sorted(props.items()) if key != "id"}
            for name, props in sorted(psets.items())}


def inspect_model(path) -> dict:
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element
    import ifcopenshell.util.shape
    import ifcopenshell.util.unit
    import ifcopenshell.validate

    model = ifcopenshell.open(str(path))
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=True)
    errors = [entry for entry in logger.statements if entry["level"] == "error"]

    products = list(model.by_type("IfcFooting"))
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    elements = []
    for element in sorted(products, key=lambda e: e.Name or ""):
        shape = ifcopenshell.geom.create_shape(settings, element)
        vertices = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
        material = ifcopenshell.util.element.get_material(element)
        container = ifcopenshell.util.element.get_container(element)
        elements.append({
            "name": element.Name,
            "guid": element.GlobalId,
            "class": element.is_a(),
            "tag": element.Tag,
            "predefined_type": getattr(element, "PredefinedType", None),
            "container": container.Name if container else None,
            "material": material.Name if material else None,
            "bounds_min_m": vertices.min(axis=0).tolist(),
            "bounds_max_m": vertices.max(axis=0).tolist(),
            "dimensions_m": (vertices.max(axis=0) - vertices.min(axis=0)).tolist(),
            "volume_m3": float(ifcopenshell.util.shape.get_volume(shape.geometry)),
            "properties": _clean_psets(ifcopenshell.util.element.get_psets(element)),
        })

    report = {
        "file": Path(path).name,
        "schema": model.schema,
        "length_unit_scale_to_m": ifcopenshell.util.unit.calculate_unit_scale(model),
        "validation_errors": len(errors),
        "validation_messages": [str(entry.get("message", entry)) for entry in errors[:10]],
        "element_count": len(elements),
        "total_volume_m3": float(sum(e["volume_m3"] for e in elements)),
        "elements": elements,
        "footings": elements,  # compatibilidad con los consumidores anteriores
    }
    if elements:
        low = np.min([e["bounds_min_m"] for e in elements], axis=0)
        high = np.max([e["bounds_max_m"] for e in elements], axis=0)
        report.update(bounds_min_m=low.tolist(), bounds_max_m=high.tolist(),
                      dimensions_m=(high - low).tolist())
    return report


def _different(a, b, tol):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) > tol * max(1.0, abs(a))
    return a != b


def _vector(values):
    return "(" + ", ".join(f"{v:.3f}" for v in values) + ")"


def compare_reports(old: dict, new: dict, tol: float = 1e-6) -> list:
    """Lista legible de diferencias entre dos inspecciones."""
    changes = []
    # El GUID identifica al objeto aunque se cambie su nombre en Bonsai.
    before = {e["guid"]: e for e in old.get("elements", old.get("footings", []))}
    after = {e["guid"]: e for e in new.get("elements", new.get("footings", []))}
    changes += [f"{before[key]['name']}: eliminado" for key in sorted(set(before) - set(after))]
    changes += [f"{after[key]['name']}: elemento nuevo" for key in sorted(set(after) - set(before))]
    for guid in sorted(set(before) & set(after)):
        a, b = before[guid], after[guid]
        name = b["name"]
        for key in ("name", "class", "tag", "predefined_type", "container", "material"):
            if a.get(key) != b.get(key):
                changes.append(f"{name}: {key} {a.get(key)!r} -> {b.get(key)!r}")
        for key in ("bounds_min_m", "bounds_max_m"):
            if not np.allclose(a[key], b[key], rtol=0, atol=1e-4):
                changes.append(f"{name}: {key} {_vector(a[key])} -> {_vector(b[key])}")
        if _different(a["volume_m3"], b["volume_m3"], 1e-4):
            changes.append(f"{name}: volumen {a['volume_m3']:.3f} -> {b['volume_m3']:.3f} m³")
        for pset in sorted(set(a["properties"]) | set(b["properties"])):
            props_a, props_b = a["properties"].get(pset), b["properties"].get(pset)
            if props_a is None or props_b is None:
                changes.append(f"{name}: property set {pset} {'agregado' if props_a is None else 'eliminado'}")
                continue
            for prop in sorted(set(props_a) | set(props_b)):
                if _different(props_a.get(prop), props_b.get(prop), tol):
                    changes.append(f"{name}: {pset}.{prop} {props_a.get(prop)!r} -> {props_b.get(prop)!r}")
    return changes


def format_report(report: dict) -> str:
    lines = [f"Archivo: {report['file']} · esquema {report['schema']} · "
             f"unidad de largo = {report['length_unit_scale_to_m']:g} m · "
             f"errores de validación: {report['validation_errors']}"]
    lines.append(f"{'Objeto':<11} {'Clase':<10} {'GUID':<23} {'Inicio_h':>8} {'Tcol_C':>7} "
                 f"{'z [m]':>13} {'Volumen [m³]':>13}")
    for e in report["elements"]:
        plan = e["properties"].get("UANDES_HormigonMasivo", {})
        z_range = f"{e['bounds_min_m'][2]:.2f}–{e['bounds_max_m'][2]:.2f}"
        start, placement = plan.get("Inicio_h", "–"), plan.get("TemperaturaColocacion_C", "–")
        lines.append(f"{e['name']:<11} {e['class']:<10} {e['guid']:<23} {start!s:>8} {placement!s:>7} "
                     f"{z_range:>13} {e['volume_m3']:>13.2f}")
    if report["elements"]:
        lines.append(f"Total: {report['element_count']} objetos · volumen {report['total_volume_m3']:.2f} m³ · "
                     f"dimensiones globales {_vector(report['dimensions_m'])} m")
    for message in report["validation_messages"]:
        lines.append(f"  Error: {message}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", type=Path, default=Path("models/g8_base.ifc"))
    parser.add_argument("--output", type=Path, help="guarda la inspección en JSON")
    parser.add_argument("--compare", type=Path, help="inspección JSON anterior para detectar cambios")
    args = parser.parse_args(argv)

    report = inspect_model(args.path)
    print(format_report(report))
    if report["validation_errors"]:
        raise ValueError("El IFC contiene errores de validación; no se guardará como referencia válida")
    if args.compare:
        previous = json.loads(args.compare.read_text(encoding="utf-8"))
        changes = compare_reports(previous, report)
        print(f"\nCambios respecto de {args.compare}:" if changes else f"\nSin cambios respecto de {args.compare}.")
        for change in changes:
            print(f"  - {change}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    main()
