"""Explora protecciones comerciales de S8 sobre el escenario crítico archivado."""

import argparse
from copy import deepcopy
from scripts import final_campaign as campaign, monte_carlo as io
from scripts.verify_s7 import inputs

OUT = campaign.ROOT / "results/final/s8_candidates"


def configurations():
    """Espesores en múltiplos de 50 mm; propiedades de servicio son hipótesis."""
    manifest, _ = inputs()
    candidates = {}
    for thickness in (.05, .10, .15, .20):
        for removal in (2520, 3600):
            name = f"S8-{int(thickness*1000)}mm-{removal}h"
            config = deepcopy(manifest["config"])
            plan = config["plans"][0]
            plan.update(id=name, label=name, top_remove_h=removal,
                        subbase_r_m2k_w=.12/.045,
                        blanket_stages=[[0, thickness], [removal, 0]],
                        blanket_core_stages=[[0, .05], [removal, 0]])
            if thickness > .05:
                plan["blanket_stages"] = [[0, thickness], [840, .05], [removal, 0]]
            config["max_hours"] = removal+168
            config["mix"]["conductivity_w_mk"] = 2.2
            candidates[name] = config
    for removal in (2520, 3600):
        name = f"S8-staged-{removal}h"
        config = deepcopy(manifest["config"])
        plan = config["plans"][0]
        plan.update(id=name, label=name, top_remove_h=removal, subbase_r_m2k_w=.12/.045,
                    blanket_stages=[[0,.20],[840,.15],[1440,.10],[1920,.05],[removal,0]],
                    blanket_core_stages=[[0,.05],[1920,.05],[removal,0]])
        config["max_hours"] = removal+168
        candidates[name] = config
    return candidates


def run(name, mesh):
    manifest, reference = inputs()
    if io.digest(campaign.SOURCE) != manifest["source_sha256"]:
        raise ValueError("La fuente difiere del lote de referencia")
    config = configurations()[name]
    env = deepcopy(manifest["environment"])
    # Ficha Safe Energy: 0,034 a 24 °C y 0,042 a 93 °C.
    # El valor constante 0,042 es una hipótesis de servicio a examinar.
    env["insulation"]["conductivity_w_mk"] = .042
    config = campaign.resolve_campaign(config)
    job = {**manifest["jobs"][reference["base"]["index"]], "plan": name, "mesh": mesh, "dt":600}
    path = OUT / f"{name}_mesh{mesh:g}.json"
    if path.exists():
        raise FileExistsError(path)
    row = campaign.simulate(job, config, env)
    if row["ifc_sha256"] != manifest["ifc_sha256"] or row["weather_sha256"] != manifest["weather_sha256"]:
        raise ValueError("La geometría o el clima difieren del lote de referencia")
    io.write_json(path, {"row":row, "config":config, "environment":env,
                        "reference_manifest_sha256":reference["manifest_sha256"],
                        "source_sha256":io.digest(campaign.SOURCE), "code_sha256":io.code_fingerprint()})
    print(name, mesh, row["tmax"]["value_c"], row["delta"]["value_c"], row["horizon_open"], flush=True)


def aggregate():
    """Publica métricas de las alternativas realmente calculadas y las mallas disponibles."""
    records = [io.read_json(path) for path in sorted(OUT.glob("*_mesh*.json"))]
    metrics = [{"plan":item["row"]["plan"], "mesh":item["row"]["mesh"],
                "spacing_m":item["row"]["grid_spacing_m"],
                "tmax_c":item["row"]["tmax"]["value_c"],
                "delta_c":item["row"]["delta"]["value_c"],
                "delta_time_h":item["row"]["delta"]["time_h"],
                "closed":not item["row"]["horizon_open"],
                "hours":item["row"]["hours"],
                "energy_error_relative":item["row"]["energy_error_relative"]} for item in records]
    name = "S8-staged-3600h"
    studies = sorted([row for row in metrics if row["plan"]==name],key=lambda row: -row["mesh"])
    selected = next(item for item in records if item["row"]["plan"]==name)
    io.write_json(OUT / "summary.json", {"plan":name, "sample_id":46,
                  "config":selected["config"], "environment":selected["environment"],
                  "screen":metrics, "refinements":studies,
                  "scope":"Escenario crítico de S7, con clima original y persistencia. Los lotes Monte Carlo propios se presentan por separado.",
                  "properties_status":"Selección propuesta a partir de fichas, pendiente de validación de obra."})
    io.write_json(campaign.ROOT / "config/final_g8_s8.json", selected["config"])
    io.write_json(campaign.ROOT / "config/environment_s8.json", selected["environment"])
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1,2,figsize=(10,4))
    for ax,key,limit,label in zip(axes,("tmax_c","delta_c"),(70,20),("T máxima [°C]","ΔT máximo [°C]")):
        ax.plot([r["spacing_m"][0]*1000 for r in studies],[r[key] for r in studies],"o-")
        ax.axhline(limit,color="#b45309",linestyle="--",label="Límite docente")
        ax.set(xlabel="Tamaño de celda x [mm]",ylabel=label)
        ax.grid(alpha=.2); ax.legend()
    fig.suptitle("S8 · escenario 46 · retiro completo al día 150 · horizonte 157 días")
    fig.tight_layout(); fig.savefig(OUT / "refinement.png",dpi=150); plt.close(fig)
    print(studies, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", choices=list(configurations()))
    parser.add_argument("--mesh", type=float, choices=(2,1,.5), default=2)
    parser.add_argument("--aggregate", action="store_true")
    args = parser.parse_args()
    if args.aggregate:
        aggregate()
    else:
        for name in [args.plan] if args.plan else configurations():
            run(name, args.mesh)
