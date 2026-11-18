"""Convergencia de S8 con celdas alineadas con los niveles de 1,1 m del BIM.

Usa el dominio completo para conservar las asimetrías de la voxelización.
Cada resultado conserva su malla, escenario, configuración y procedencia.
"""

import argparse
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import numpy as np
from thermal3d.voxel import load_ifc_meshes, voxelize, inside_mesh
from environment import SurfaceMap
from scripts import final_campaign as c, monte_carlo as io, weather_3d
from scripts.voxelize_foundation import case_ifc
from scripts.verify_s7 import inputs
from scripts.final_mc_refinement import richardson

OUT = c.ROOT / "results/final/s8_aligned"


def assess(values, tolerance_c=.2):
    """Objetivo exploratorio de cambio <1 % del límite de 20 °C, declarado aparte."""
    estimate=richardson(values)
    change=abs(values[-1]-values[-2])
    extrapolation_error=abs(estimate["extrapolated_c"]-values[-1]) if estimate["order"] is not None else None
    return {**estimate,"last_change_c":change,"target_c":tolerance_c,
            "richardson_error_c":extrapolation_error,
            "stable_sequence":extrapolation_error is not None and change<=tolerance_c and extrapolation_error<=tolerance_c}


@lru_cache(maxsize=3)
def geometry(n):
    """nx=ny=n, nz=n/4; las capas BIM y el suelo quedan alineados."""
    path, guids = case_ifc(c.ROOT/"config/case_g8.json")
    meshes, source = load_ifc_meshes(path, guids)
    lengths = np.max([m.vertices.max(axis=0) for m in meshes],axis=0)-np.min([m.vertices.min(axis=0) for m in meshes],axis=0)
    counts = np.array([n,n,n//4])
    grid = voxelize(meshes, lengths/counts*(1+1e-12), source)
    if not np.array_equal(grid.component.shape, counts):
        raise ValueError("La grilla no conserva los conteos declarados")
    return grid.component, grid.spacing_m, grid.origin_m, source["sha256"]


def fixed_protection(model):
    """Define la cubierta central por la sección IFC física a 2 m del origen."""
    path,guids=case_ifc(c.ROOT/"config/case_g8.json")
    meshes,_=load_ifc_meshes(path,guids)
    p=model["p"]
    origin=model["origin_m"]
    x=origin[0]+(np.arange(p.shape[0])+.5)*p.spacing_m[0]
    y=origin[1]+(np.arange(p.shape[1])+.5)*p.spacing_m[1]
    base=min(mesh.vertices[:,2].min() for mesh in meshes)
    section=np.zeros(p.shape[:2],dtype=bool)
    for mesh in meshes:
        section |= inside_mesh(x,y,np.array([base+2.0]),mesh)[:,:,0]
    concrete=model["grid"]["concrete"]
    core=concrete & section[:,:,None]
    regions=[]
    for region in p.exposed.regions:
        if region.name=="superior central":
            region=replace(region,cells=core)
        elif region.name=="superior periférica":
            region=replace(region,cells=concrete & ~section[:,:,None])
        regions.append(region)
    exposed=SurfaceMap(tuple(regions),p.exposed.default)
    boundaries={face:exposed if bc is p.exposed else bc for face,bc in p.boundaries.items()}
    return {**model,"p":replace(p,exposed=exposed,boundaries=boundaries)}


def run(n, dt, hours=None, fixed=False):
    manifest,reference=inputs()
    config=io.read_json(c.ROOT/"config/final_g8_s8.json")
    env=io.read_json(c.ROOT/"config/environment_s8.json")
    if hours is not None:
        config.update(hours=hours,max_hours=hours,report_21d=False)
    job={**manifest["jobs"][reference["base"]["index"]],"plan":config["plans"][0]["id"],"mesh":n,"dt":dt}
    suffix="fixed" if fixed else "full"
    path=OUT/f"n{n}_dt{dt:g}_{suffix}_{config['max_hours']:g}h.json"
    if path.exists():
        raise FileExistsError(path)
    original_geometry,original_builder=c.voxels,weather_3d.build_model
    def build(*args,**kwargs):
        return fixed_protection(original_builder(*args,**kwargs))
    try:
        c.voxels=geometry
        if fixed:
            weather_3d.build_model=build
        row=c.simulate(job,deepcopy(config),deepcopy(env))
    finally:
        c.voxels=original_geometry
        weather_3d.build_model=original_builder
    io.write_json(path,{"row":row,"config":config,"environment":env,"symmetry":suffix,
                        "grid_counts":[n,n,n//4],"source_sha256":io.digest(c.SOURCE),
                        "code_sha256":io.code_fingerprint()})
    print(path, row["tmax"]["value_c"],row["delta"]["value_c"],row["run_seconds"],flush=True)


def aggregate(fixed=False):
    """Compara tres mallas del dominio completo y verifica sensibilidad temporal."""
    suffix="fixed" if fixed else "full"
    records=[io.read_json(OUT/f"n{n}_dt600_{suffix}_3768h.json") for n in (24,48,96)]
    temporal=io.read_json(OUT/f"n48_dt300_{suffix}_3768h.json")
    for item in [*records,temporal]:
        for key in ("config","environment","source_sha256"):
            if item[key]!=records[0][key]:
                raise ValueError(f"Insumos distintos: {key}")
    rows=[item["row"] for item in records]
    for key in ("sample_id","curve","climate","heat_factor","placement_c","soil_c","hours","ifc_sha256","weather_sha256"):
        if any(item["row"][key]!=rows[0][key] for item in [*records,temporal]):
            raise ValueError(f"Escenario distinto: {key}")
    spacing=np.array([row["grid_spacing_m"] for row in rows])
    if not np.allclose(spacing[:-1],spacing[1:]*2):
        raise ValueError("Los pasos no se reducen exactamente a la mitad")
    estimates={key:assess([row[key]["value_c"] for row in rows]) for key in ("tmax","delta")}
    temporal_changes={key:abs(temporal["row"][key]["value_c"]-rows[1][key]["value_c"]) for key in estimates}
    result={"records":records,"temporal":temporal,"estimates":estimates,
            "protection_method":"ifc_section_2m" if fixed else "voxel_column_count",
            "temporal_changes_c":temporal_changes,
            "spatial_target_c":.2,"temporal_target_c":.02,
            "target_status":"Objetivos exploratorios elegidos para este estudio, sujetos a revisión del curso.",
            "meets_targets":all(e["stable_sequence"] for e in estimates.values()) and max(temporal_changes.values())<=.02,
            "scope":"Muestra 46 con clima original y horizonte 157 días. No representa convergencia de todo el Monte Carlo."}
    io.write_json(OUT/("summary.json" if fixed else "summary_legacy.json"),result)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for ax,key,label in zip(axes,("tmax","delta"),("T máxima [°C]","ΔT máximo [°C]")):
        values=[row[key]["value_c"] for row in rows]
        ax.plot(spacing[:,0]*1000,values,"o-")
        for x,y in zip(spacing[:,0]*1000,values):
            ax.annotate(f"{y:.4f}",(x,y),xytext=(0,8),textcoords="offset points",ha="center")
        ax.set(xlabel="Tamaño de celda x [mm]",ylabel=label)
        ax.margins(.15,.3);ax.grid(alpha=.2)
    fig.suptitle("S8 · mallas alineadas · dominio completo · Δt máximo 600 s")
    fig.tight_layout();fig.savefig(OUT/("convergence.png" if fixed else "convergence_legacy.png"),dpi=150);plt.close(fig)
    print(estimates,temporal_changes,result["meets_targets"],flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n",type=int,choices=(24,48,96,192))
    parser.add_argument("--dt",type=float,default=300)
    parser.add_argument("--hours",type=float)
    parser.add_argument("--aggregate",action="store_true")
    parser.add_argument("--fixed-protection",action="store_true")
    args=parser.parse_args()
    if args.aggregate:
        aggregate(args.fixed_protection)
    elif args.n:
        run(args.n,args.dt,args.hours,args.fixed_protection)
    else:
        parser.error("Falta --n o --aggregate")
