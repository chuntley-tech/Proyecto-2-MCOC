"""Genera un IFC4 inicial en metros; no representa una geometría definitiva."""

import argparse
import json
from pathlib import Path
import uuid

import ifcopenshell
import ifcopenshell.api
import numpy as np


def create_model(config_path: Path, output: Path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    dimensions = config["geometry"]
    length, width, height = (float(dimensions[key]) for key in ("length_m", "width_m", "height_m"))
    if min(length, width, height) <= 0:
        raise ValueError("Dimensiones IFC deben ser positivas")
    model = ifcopenshell.file(schema="IFC4")

    def api(command, **kwargs):
        return ifcopenshell.api.run(command, model, **kwargs)

    project = api("root.create_entity", ifc_class="IfcProject", name="Proyecto 2 MCOC - G8")
    units = [api("unit.add_si_unit", unit_type=kind) for kind in ("LENGTHUNIT", "AREAUNIT", "VOLUMEUNIT")]
    api("unit.assign_unit", units=units)
    context = api("context.add_context", context_type="Model")
    body = api("context.add_context", context_type="Model", context_identifier="Body",
               target_view="MODEL_VIEW", parent=context)
    site = api("root.create_entity", ifc_class="IfcSite", name="Caso docente G8 - Cuatro Vientos")
    building = api("root.create_entity", ifc_class="IfcBuilding", name="Fundación de referencia")
    storey = api("root.create_entity", ifc_class="IfcBuildingStorey", name="Base")
    for parent, child in ((project, site), (site, building), (building, storey)):
        api("aggregate.assign_object", products=[child], relating_object=parent)
    material = api("material.add_material", name="Hormigón - propiedades pendientes de validación", category="concrete")
    # Subdivisión didáctica para identificar tres sólidos. No prescribe vertidas.
    layer_height = height / 3
    for index, label in enumerate(("inferior", "intermedia", "superior")):
        tag = f"G8-BASE-{index + 1:02d}"
        footing = api("root.create_entity", ifc_class="IfcFooting", predefined_type="PAD_FOOTING",
                      name=f"{tag} - Capa {label}")
        footing.Tag = tag
        api("spatial.assign_container", products=[footing], relating_structure=storey)
        placement = np.eye(4)
        placement[2, 3] = index * layer_height
        api("geometry.edit_object_placement", product=footing, matrix=placement)

        point2d = model.create_entity("IfcCartesianPoint", Coordinates=(length / 2, width / 2))
        profile = model.create_entity("IfcRectangleProfileDef", ProfileType="AREA",
                                      Position=model.create_entity("IfcAxis2Placement2D", Location=point2d),
                                      XDim=length, YDim=width)
        origin = model.create_entity("IfcCartesianPoint", Coordinates=(0., 0., 0.))
        solid = model.create_entity("IfcExtrudedAreaSolid", SweptArea=profile,
                                    Position=model.create_entity("IfcAxis2Placement3D", Location=origin),
                                    ExtrudedDirection=model.create_entity("IfcDirection", DirectionRatios=(0., 0., 1.)),
                                    Depth=layer_height)
        representation = model.create_entity("IfcShapeRepresentation", ContextOfItems=body,
                                              RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[solid])
        api("geometry.assign_representation", product=footing, representation=representation)
        api("material.assign_material", products=[footing], type="IfcMaterial", material=material)
        properties = api("pset.add_pset", product=footing, name="MCOC_InitialModel")
        api("pset.edit_pset", pset=properties, properties={
            "GeometryStatus": dimensions["status"], "Length_m": length,
            "Width_m": width, "Height_m": layer_height,
            "BaseElevation_m": index * layer_height, "ObjectID": tag,
            "SubdivisionStatus": "Tres capas iguales para E02; no es un plan de vertidas aprobado",
            "SolverAxis": "z vertical; solver independiente configurado en JSON",
            "ThermalDataStatus": "Valores sintéticos en config/case_g8.json; no material calibrado",
            "UpperCylinderStatus": "Omitido: altura y relación con espesor pendientes de validación"
        })
    location = api("pset.add_pset", product=site, name="MCOC_MeteorologicalPoint")
    api("pset.edit_pset", pset=location, properties={
        "Latitude": config["site"]["latitude"], "Longitude": config["site"]["longitude"],
        "CoordinateRole": config["site"]["coordinate_role"], "Group": "G8"
    })
    # Identidad estable al regenerar la misma estructura del ejemplo.
    for entity in model.by_type("IfcRoot"):
        key = f"Proyecto2MCOC/G8/{entity.is_a()}/{entity.Name}/{entity.id()}"
        if entity.is_a("IfcFooting"):
            key = f"Proyecto2MCOC/G8/IfcFooting/{entity.Tag}"
        entity.GlobalId = ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, key).hex)
    model.header.file_name.name = output.name
    model.header.file_name.time_stamp = "2026-10-19T00:00:00"
    model.header.file_name.author = ("G8",)
    model.header.file_name.organization = ("Proyecto docente MCOC",)
    model.header.file_name.preprocessor_version = "IfcOpenShell"
    model.header.file_name.originating_system = "Proyecto 2 MCOC - generador inicial"
    model.header.file_name.authorization = "Modelo docente provisional"
    output.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(output))
    print(f"IFC escrito: {output}; volumen geométrico esperado={length * width * height:.3f} m³")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/case_g8.json"))
    parser.add_argument("--output", type=Path, default=Path("models/g8_base.ifc"))
    args = parser.parse_args()
    create_model(args.config, args.output)
