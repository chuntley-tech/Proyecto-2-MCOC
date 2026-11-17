"""Reúne resultados reales de S8, incluidos horizontes abiertos y extensiones."""

from pathlib import Path
from scripts import final_mc, monte_carlo as io

ROOT = io.ROOT
OUT = ROOT / "results/final/s8_mc"


def build():
    """Conserva por separado los dos IC y el alcance de cada verificación."""
    lots, samples = [], []
    for name in ("base", "confirm"):
        manifest, rows = final_mc.collect(OUT/name)
        comparison = io.read_json(OUT/name/"comparison.json")
        plan = comparison["plans"][0]
        lots.append({"name":name, "seed":manifest["seed"], "statistics":plan["statistics"],
                     "max_tmax_c":max(row["tmax"]["value_c"] for row in rows),
                     "max_delta_c":max(row["delta"]["value_c"] for row in rows),
                     "feasible":plan["feasible"], "manifest_sha256":io.digest(OUT/name/"manifest.json"),
                     "source_sha256":manifest["source_sha256"], "weather_sha256":manifest["weather_sha256"]})
        samples.extend({"lot":name,"sample_id":row["sample_id"],"curve":row["curve"],
                        "member":row["climate"]["member"], "tmax_c":row["tmax"]["value_c"],
                        "delta_c":row["delta"]["value_c"],"hours":row["hours"],
                        "fails":row["fails"],"horizon_open":row["horizon_open"]} for row in rows)
    extensions = [io.read_json(path) for path in sorted(OUT.glob("horizon_pilot_*.json"))]
    refined = io.read_json(OUT/"refined_30_240d.json")
    summary = {"lots":lots,"extensions":extensions,"refined":refined,
               "scope":"Resultados de 157 días en malla base. Horizontes abiertos impiden aceptar cumplimiento integral de S8.",
               "validation":"Propiedades y operación pendientes de certificación y aprobación de obra."}
    io.write_json(OUT/"summary.json", summary)
    final_mc.write_csv(OUT/"samples.csv", samples)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1,2,figsize=(11,4))
    for name in ("base","confirm"):
        chosen=[row for row in samples if row["lot"]==name]
        for ax,key,threshold in zip(axes,("tmax_c","delta_c"),(70,20)):
            ax.scatter([r["sample_id"] for r in chosen],[r[key] for r in chosen],s=15,alpha=.65,label=name)
    for ax,limit,label in zip(axes,(70,20),("T máxima [°C]","ΔT máximo [°C]")):
        ax.axhline(limit,color="#b45309",linestyle="--")
        ax.set(xlabel="Índice de simulación",ylabel=label)
        ax.grid(alpha=.2); ax.legend()
    fig.suptitle("S8 · 200 simulaciones de 157 días · 167 horizontes abiertos")
    fig.tight_layout(); fig.savefig(OUT/"monte_carlo.png",dpi=150); plt.close(fig)
    print([(lot["name"],lot["statistics"]["final"]["joint"],lot["statistics"]["final"]["open_horizons"]) for lot in lots])


if __name__ == "__main__":
    build()
