"""Evidencias de sensibilidad, clima, hidratación y cortes de la campaña final."""

import numpy as np
import matplotlib.pyplot as plt

from scripts import final_campaign as campaign, monte_carlo as mc, view_3d, weather_3d
from thermal3d.hydration import load_curves
from thermal3d.vtk_export import write_vti


def save(fig, output):
    fig.savefig(output, dpi=140)
    plt.close(fig)


def check_case(chosen, manifest, capture=False):
    config = manifest["config"]
    env = manifest["environment"]
    job = manifest["jobs"][chosen["index"]]
    nominal = chosen
    model = monitor = fields = None
    if capture:
        nominal, model, monitor, fields = campaign.simulate(job, config, env, capture=True)
    variants = {"base": nominal}
    new_mesh, new_dt = job["mesh"]/2, job["dt"]/2
    variants["combined"] = campaign.simulate({**job, "mesh": new_mesh, "dt": new_dt}, config, env, capture=True)[0]
    if capture:
        variants["spatial"] = campaign.simulate({**job, "mesh": new_mesh}, config, env)
        variants["temporal"] = campaign.simulate({**job, "dt": new_dt}, config, env)
    metrics = {}
    for key,row in variants.items():
        metrics[key] = {k:row[k] for k in ("grid_spacing_m","dt","dt_mean_s","hours","energy_error_relative")}
        metrics[key].update({"delta_h": row["delta"]["time_h"], "delta_face": row["delta"]["surface"]["face"],
                             "profile_mm_c": row["delta"]["profile_mm_c"],
                             "protection_samples": row.get("protection_samples", []), "horizon_open": row["horizon_open"]})
        for name,limit in (("tmax",70),("delta",20)):
            value = row[name]["value_c"]
            metrics[key].update({name+"_c":value,name+"_exceeds":value>limit,
                                 name+"_change_c":abs(value-nominal[name]["value_c"])})
    details = {"candidate":job["plan"],"scenario":{"curve":job["curve"],"climate":job["climate"]["id"]},
               "metrics":metrics,"scenario_index":chosen["index"]}
    return details, nominal, model, monitor, fields


def verify(out):
    manifest = mc.read_json(out/"manifest.json")
    result = mc.read_json(out/"comparison.json")
    config = manifest["config"]
    best = result["selected"] or min(result["plans"], key=lambda p:(p["prob_joint"],p["max_delta_c"],p["duration_h"]))["id"]
    plan_ids = {plan["id"] for plan in result["plans"]}
    candidate = "C" if "C" in plan_ids else best

    def worst(plan):
        return max((r for r in result["scenarios"] if r["plan"]==plan and r["weight"]>0),
                   key=lambda r:r["delta"]["value_c"])

    chosen = worst(candidate)
    job = manifest["jobs"][chosen["index"]]
    print(f"Refinamiento de {candidate}", flush=True)
    details, nominal, model, monitor, fields = check_case(chosen, manifest, capture=True)
    details["additional_cases"] = []
    for plan in dict.fromkeys(("D", best)):
        if plan in plan_ids and plan != candidate:
            print(f"Refinamiento de {plan}", flush=True)
            details["additional_cases"].append(check_case(worst(plan), manifest)[0])
    mc.write_json(out/"verification.json",details)
    result["verification"] = details
    result["example_history"] = list(monitor.hourly.values())
    result["curves"] = curves_for_view(config)
    result["weather_series"] = climate_for_view(config,[*manifest["weather"],*manifest.get("weather_sensitivity",[])])
    mc.write_json(out/"comparison.json",result)

    plots = out/"figures"
    plots.mkdir(exist_ok=True)
    fig,ax = plt.subplots(layout="constrained")
    for plan in result["plans"]:
        ax.scatter(plan["duration_h"],100*plan["prob_joint"],label=plan["id"])
        ax.annotate(plan["id"],(plan["duration_h"],100*plan["prob_joint"]),xytext=(5,5),textcoords="offset points")
    ax.axhline(5,color="tab:red",linestyle="--",label="Límite 5 %")
    ax.set(xlabel="Fin de la última vertida desde t₀ [h]",ylabel="Probabilidad conjunta [%]", ylim=(-3,110))
    ax.legend()
    save(fig,plots/"duracion_riesgo.png")

    fig,ax = plt.subplots(layout="constrained")
    for i,plan in enumerate(result["plans"]):
        for pour in plan["schedule"]:
            ax.barh(i,pour["duration_h"],left=pour["start_h"],edgecolor="white",color=f"C{pour['layer']-1}")
    ax.set(yticks=range(len(result["plans"])),yticklabels=[p["id"] for p in result["plans"]],xlabel="Horas desde t₀")
    save(fig,plots/"cronograma.png")

    fig,ax = plt.subplots(layout="constrained")
    for curve in result["curves"]:
        ax.plot(curve["time_h"],curve["source_w_m3"],label=curve["id"])
    ax.set(xlabel="Edad desde la colocación [h]",ylabel="Fuente [W/m³]")
    ax.legend(ncol=2)
    save(fig,plots/"hidratacion.png")

    fig,axes = plt.subplots(3,1,sharex=True,layout="constrained")
    for series in result["weather_series"]:
        for ax,name in zip(axes,("air_c","wind_m_s","solar_w_m2")):
            ax.plot(series["time_h"],series[name],label=series["id"])
            if series["tail_from_h"] is not None:
                ax.axvline(series["tail_from_h"],color="gray",ls=":",lw=.8)
    for ax, label in zip(axes,("Aire [°C]","Viento [m/s]","Radiación [W/m²]")):
        ax.set_ylabel(label)
    axes[0].legend()
    axes[-1].set_xlabel("Horas desde t₀ · línea punteada: comienzo del relleno")
    save(fig,plots/"clima.png")

    history = result["example_history"]
    fig,axes=plt.subplots(2,1,sharex=True,layout="constrained")
    for ax,keys in zip(axes,(("tmax_c","surface_c","core_c"),("delta_c",))):
        for key in keys:
            ax.plot([x["time_h"] for x in history],[x[key] for x in history],
                    label={"tmax_c":"Máxima del hormigón","surface_c":"Mínima a 25 mm",
                           "core_c":"Núcleo geométrico","delta_c":"Diferencial"}[key])
        ax.legend()
        ax.set_ylabel("Temperatura [°C]")
    for i in range(len(history[0]["pour_tmax_c"])):
        axes[0].plot([x["time_h"] for x in history], [x["pour_tmax_c"][i] for x in history],
                     linestyle=":", linewidth=1, label=f"Máxima V{i+1}")
    for ax in axes:
        ax.axvline(next(row["top_remove_h"] for row in result["plans"] if row["id"]==candidate),
                   color="gray", linestyle="--", label="Retiro superior")
        ax.legend(ncol=2, fontsize="small")
    axes[1].axhline(20,color="tab:red",linestyle="--")
    axes[1].set_xlabel(f"Horas desde t₀ · plan {candidate} · curva {job['curve']} · {job['climate']['id']}")
    save(fig,plots/"temperaturas_criticas.png")

    places = weather_3d.locate_core_and_surface(model)
    grid, p = model["grid"], model["p"]
    vtk = out/"vtk"
    for name,field in fields.items():
        record = nominal[name] if name=="tmax" else nominal[name]["hot"]
        active = np.isfinite(field)
        placed = active & grid["concrete"]
        zone = np.where(placed,1,0).astype(np.uint8)
        zone[weather_3d.touching(placed,~active)] = 2
        path = write_vti(vtk/f"{name}.vti",{"temperature":field, "material":np.where(
            active,np.where(grid["concrete"],1,2),0).astype(np.uint8), "zone":zone},
            p.spacing_m,model["origin_m"],{"TimeValue":record["time_h"]})
        summary = {"core":record,"surface_probes":{
            "superior":{"xyz_m":weather_3d.cell_centre(model,places["top"])},
            "lateral":{"xyz_m":weather_3d.cell_centre(model,places["side"])}},
            "weather":{"folder":config["weather_snapshot"]}}
        view_3d.matplotlib_slices(path,summary,plots/f"cortes_{name}.png")
    print("Verificación:",out/"verification.json",flush=True)


def curves_for_view(config):
    curves,_ = load_curves(campaign.SOURCE,offset_h=config["offset_h"],tail_h=config["tail_h"])
    hours = np.arange(337).tolist()
    return [{"id":name,"time_h":hours,"source_w_m3":curve.rate(np.array(hours)*3600).tolist()}
            for name,curve in curves.items()]


def climate_for_view(config, histories):
    rows = []
    for climate in histories:
        tail_method = climate.get("tail_method", "persistencia")
        series,start = campaign.make_weather(config,climate["member"],tail_method)
        t = (series.time_s-start)/3600
        select = (t>=0)&(t<=config["max_hours"])
        tail = t[select & (np.asarray(series.origin)==tail_method)]
        rows.append({"id":climate["id"],"time_h":t[select].tolist(),"air_c":series.air_c[select].tolist(),
                     "wind_m_s":series.wind_10m_m_s[select].tolist(),
                     "solar_w_m2":series.shortwave_w_m2[select].tolist(),
                     "origin":np.asarray(series.origin)[select].tolist(),
                     "tail_from_h":float(tail[0]) if len(tail) else None})
    return rows
