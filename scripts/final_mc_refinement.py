"""Verifica tres mallas del caso de mayor diferencial de C3 y del finalista."""
import argparse
from functools import lru_cache
from pathlib import Path

import numpy as np

from scripts import final_campaign as campaign, final_mc, monte_carlo as io
from scripts.voxelize_foundation import case_ifc
from thermal3d.voxel import load_ifc_meshes

MESHES = (2.,1.,.5)


def richardson(values):
    coarse, medium, fine = values
    first, second = coarse-medium, medium-fine
    if second == 0 or first*second <= 0 or abs(first) <= abs(second):
        return {"order":None,"extrapolated_c":None,"reason":"Sin convergencia monótona decreciente"}
    order = float(np.log2(first/second))
    return {"order":order,"extrapolated_c":float(fine+(fine-medium)/np.expm1(order*np.log(2)))}


@lru_cache(maxsize=1)
def geometry_features():
    path, guids = case_ifc(campaign.ROOT/"config/case_g8.json")
    meshes, _ = load_ifc_meshes(path,guids)
    result = []
    for mesh in meshes:
        triangles = mesh.vertices[mesh.faces]
        normals = np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        normals /= np.linalg.norm(normals,axis=1)[:,None]
        adjacency = {}
        for i,face in enumerate(mesh.faces):
            for j,k in ((0,1),(1,2),(2,0)):
                adjacency.setdefault(tuple(sorted((face[j],face[k]))),[]).append(i)
        edges = [key for key,(a,b) in adjacency.items() if normals[a]@normals[b] < np.cos(np.deg2rad(12))]
        result.append((mesh.name,triangles,normals,mesh.vertices[np.asarray(edges,dtype=int).reshape(-1,2)]))
    return result


def _edge_distances(point, starts, ends):
    delta = ends-starts
    weight = np.clip(np.sum((point-starts)*delta,axis=-1)/np.sum(delta**2,axis=-1),0,1)
    return np.linalg.norm(point-starts-weight[...,None]*delta,axis=-1)


def contact(surface):
    point = np.array(surface["xyz_m"])
    axis = "xyz".index(surface["face"][0])
    point[axis] += .025 if surface["face"][1]=="+" else -.025
    closest = None
    edge_distance = float("inf")
    for name, tri, normal, edges in geometry_features():
        offset = np.sum((point-tri[:,0])*normal,axis=-1)
        projected = point-offset[:,None]*normal
        sided = [np.sum(np.cross(tri[:,b]-tri[:,a],projected-tri[:,a])*normal,axis=-1)
                 for a,b in ((0,1),(1,2),(2,0))]
        boundary = np.min(_edge_distances(point,tri,tri[:,[1,2,0]]),axis=1)
        distances = np.where(np.min(sided,axis=0)>=-1e-10,abs(offset),boundary)
        i = int(distances.argmin())
        if closest is None or distances[i]<closest[0]:
            closest = (distances[i],name,normal[i])
        if len(edges):
            edge_distance = min(edge_distance,float(_edge_distances(point,edges[:,0],edges[:,1]).min()))
    distance, name, normal = closest
    oblique = abs(normal[axis])<.95
    classification = ("próximo a arista IFC" if edge_distance<=.025 else
                      "escalón voxelizado junto a cara oblicua" if oblique else "próximo a cara IFC")
    return {"voxel_face_xyz_m":point.tolist(),"nearest_component":name,"surface_distance_m":float(distance),
            "edge_distance_m":edge_distance,"ifc_normal":normal.tolist(),"classification":classification}


def cases(lot):
    manifest, rows = final_mc.collect(lot)
    comparison = io.read_json(lot/"comparison.json")
    nominee = comparison["selected"] or comparison["best_relative"]
    if nominee in {"C","C3"}:
        nominees = [plan for plan in comparison["plans"] if plan["id"] not in {"C","C3"}]
        nominee = nominees[0]["id"]
    ids = ["C3",nominee]
    return manifest,{plan:max((r for r in rows if r["plan"]==plan),key=lambda r:r["delta"]["value_c"])
                     for plan in ids}


def run(lot, plan, mesh):
    manifest, selected = cases(lot)
    sample = selected[plan]
    job = {**manifest["jobs"][sample["index"]],"mesh":mesh,"dt":600}
    row = campaign.simulate(job,manifest["config"],manifest["environment"])
    row["ifc_contact"] = contact(row["delta"]["surface"])
    out = lot/"refinement"/f"{plan}_{mesh:g}.json"
    io.write_json(out,row)
    return row


def aggregate(lot):
    _, selected = cases(lot)
    studies = {}
    for plan in selected:
        rows = [io.read_json(lot/"refinement"/f"{plan}_{mesh:g}.json") for mesh in MESHES]
        estimates = {key:richardson([row[key]["value_c"] for row in rows]) for key in ("tmax","delta")}
        estimates["delta"]["same_face_direction"] = len({r["delta"]["surface"]["face"] for r in rows})==1
        studies[plan] = {"sample_id":selected[plan]["sample_id"],"rows":rows,"richardson":estimates}
    io.write_json(lot/"refinement.json",studies)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lot",type=Path)
    parser.add_argument("--plan")
    parser.add_argument("--mesh",type=float,choices=MESHES)
    args = parser.parse_args()
    if args.plan and args.mesh:
        row = run(args.lot,args.plan,args.mesh)
        print(args.plan,args.mesh,row["tmax"]["value_c"],row["delta"]["value_c"])
    elif not args.plan and not args.mesh:
        aggregate(args.lot)
    else:
        parser.error("Debes indicar tanto --plan como --mesh")


if __name__=="__main__":
    main()
