"""Genera la fundación octagonal con transición y cilindro superior, en IFC4."""

import argparse
import json
from pathlib import Path
import uuid

import ifcopenshell
import ifcopenshell.api
import numpy as np

from scripts.foundation_geometry import geometry_parts
from thermal1d.ifc_input import THERMAL_PROPERTIES, THERMAL_PSET


def create_model(config_path: Path, output: Path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    dimensions = config["geometry"]
    length, width, height = (float(dimensions[key]) for key in ("length_m", "width_m", "height_m"))
    parts = geometry_parts(dimensions)
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
    # Tres componentes geométricos identificables. No prescribe vertidas.
    for part in parts:
        tag = part["tag"]
        footing = api("root.create_entity", ifc_class="IfcFooting", predefined_type="PAD_FOOTING",
                      name=f"{tag} - {part['name']}")
        footing.Tag = tag
        api("spatial.assign_container", products=[footing], relating_structure=storey)
        placement = np.eye(4)
        placement[:3, 3] = [length / 2, width / 2, part["z"]]
        api("geometry.edit_object_placement", product=footing, matrix=placement)

        if part["kind"] == "mesh":
            representation = api("geometry.add_mesh_representation", context=body,
                                 vertices=[part["vertices"].tolist()], faces=[part["faces"]],
                                 force_faceted_brep=True)
        else:
            if part["kind"] == "circle":
                profile = model.create_entity("IfcCircleProfileDef", ProfileType="AREA", Radius=part["radius"])
            else:
                points = [model.create_entity("IfcCartesianPoint", Coordinates=tuple(p))
                          for p in part["polygon"].tolist()]
                curve = model.create_entity("IfcPolyline", Points=points + [points[0]])
                profile = model.create_entity("IfcArbitraryClosedProfileDef", ProfileType="AREA", OuterCurve=curve)
            origin = model.create_entity("IfcCartesianPoint", Coordinates=(0., 0., 0.))
            solid = model.create_entity("IfcExtrudedAreaSolid", SweptArea=profile,
                                        Position=model.create_entity("IfcAxis2Placement3D", Location=origin),
                                        ExtrudedDirection=model.create_entity("IfcDirection", DirectionRatios=(0., 0., 1.)),
                                        Depth=part["height"])
            representation = model.create_entity("IfcShapeRepresentation", ContextOfItems=body,
                                                  RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[solid])
        api("geometry.assign_representation", product=footing, representation=representation)
        api("material.assign_material", products=[footing], type="IfcMaterial", material=material)
        properties = api("pset.add_pset", product=footing, name="MCOC_InitialModel")
        api("pset.edit_pset", pset=properties, properties={
            "GeometryStatus": dimensions["status"], "Height_m": part["height"],
            "BaseElevation_m": part["z"], "ObjectID": tag,
            "Component": part["name"],
            "SubdivisionStatus": "Tres componentes geométricos para E02; no es un plan de vertidas aprobado",
            "TransitionAssumption": dimensions["transition_assumption"],
            "SolverAxis": "z vertical; solver independiente configurado en JSON",
            "ThermalDataStatus": "Valores sintéticos en config/case_g8.json; no material calibrado",
            "UpperCylinderStatus": "Incluido: diámetro 7 m y altura 1.10 m; altura total 3.30 m"
        })
        if part["kind"] == "circle":
            api("pset.edit_pset", pset=properties, properties={"Diameter_m": 2 * part["radius"]})
    location = api("pset.add_pset", product=site, name="MCOC_MeteorologicalPoint")
    api("pset.edit_pset", pset=location, properties={
        "Latitude": config["site"]["latitude"], "Longitude": config["site"]["longitude"],
        "CoordinateRole": config["site"]["coordinate_role"], "Group": "G8"
    })
    controller = next(e for e in model.by_type("IfcFooting") if e.Tag == "G8-BASE-03")
    thermal_pset = api("pset.add_pset", product=controller, name=THERMAL_PSET)
    thermal_properties = {name: float(config["thermal"][field]) for field, name in THERMAL_PROPERTIES.items()}
    thermal_properties["DataStatus"] = "Valores sintéticos de verificación; propiedades homogéneas para todo el dominio 1D, no mediciones G8"
    api("pset.edit_pset", pset=thermal_pset, properties=thermal_properties)
    # Identidad estable al regenerar la misma estructura del ejemplo.
    for entity in model.by_type("IfcRoot"):
        key = f"Proyecto2MCOC/G8/{entity.is_a()}/{entity.Name}/{entity.id()}"
        if entity.is_a("IfcFooting"):
            key = f"Proyecto2MCOC/G8/IfcFooting/{entity.Tag}"
        entity.GlobalId = ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, key).hex)
    model.header.file_name.name = output.name
    model.header.file_name.time_stamp = "2026-10-20T00:00:00"
    model.header.file_name.author = ("G8",)
    model.header.file_name.organization = ("Proyecto docente MCOC",)
    model.header.file_name.preprocessor_version = "IfcOpenShell"
    model.header.file_name.originating_system = "Proyecto 2 MCOC - generador inicial"
    model.header.file_name.authorization = "Modelo docente provisional"
    output.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(output))
    print(f"IFC escrito: {output}; tres componentes, envolvente={length:g} x {width:g} x {height:g} m")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/case_g8.json"))
    parser.add_argument("--output", type=Path, default=Path("models/g8_base.ifc"))
    args = parser.parse_args()
    create_model(args.config, args.output)
