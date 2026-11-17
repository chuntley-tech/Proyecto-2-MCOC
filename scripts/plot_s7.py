"""Grafica evidencia guardada de S7 y audita la fuente, sin repetir simulaciones."""

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from scripts.final_mc import collect, write_csv
from thermal3d.hydration import load_curves

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "results/final/g8_20261119_mc"


def build(original=None):
    """Contrasta hashes y grafica máximos por escenario, no historias temporales."""
    source = ROOT / "data/hydration/source_terms.txt"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if original and hashlib.sha256(Path(original).read_bytes()).hexdigest() != digest:
        raise ValueError("El archivo entregado difiere del insumo versionado")
    out = BASE / "s7_figures"
    out.mkdir(exist_ok=True)
    batches = []
    samples = []
    for name in ("s7_base", "s7_confirm"):
        manifest, rows = collect(BASE / name)
        if manifest["source_sha256"] != digest:
            raise ValueError(f"{name}: la fuente difiere del manifiesto")
        comparison = json.loads((BASE / name / "comparison.json").read_text())
        if comparison["source_sha256"] != digest:
            raise ValueError(f"{name}: fuente distinta en comparación")
        batches.append((name, manifest, rows, comparison))
        samples.extend({"batch": name, "sample_id": r["sample_id"], "curve": r["curve"],
                        "heat_factor": r["heat_factor"], "tmax_c": r["tmax"]["value_c"],
                        "delta_c": r["delta"]["value_c"], "hours": r["hours"]} for r in rows)
    write_csv(out / "samples.csv", samples)
    config = batches[0][1]["config"]
    curves, audit = load_curves(source, offset_h=config["offset_h"], tail_h=config["tail_h"])
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(out / (name + ".png"), dpi=150)
        plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    for ax, suffix in zip(axes, ("SS", "22A")):
        for name, curve in curves.items():
            if name.endswith("_" + suffix):
                ax.plot(curve.age_s[1:] / 3600, curve.source_w_m3[1:], label=name)
        ax.set(xlabel="Edad modelada [h] (registro + 2 h)", ylabel="Q [W/m³]",
               title="SS · fuente principal" if suffix == "SS" else "22A · sensibilidad, menor confianza")
        ax.legend(); ax.grid(alpha=.2)
    fig.suptitle("Fuentes inferidas de probetas · source_terms.txt · sin factor Monte Carlo")
    save(fig, "hidratacion")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for name, manifest, rows, comparison in batches:
        for ax, field in zip(axes, ("tmax", "delta")):
            ax.scatter([r["sample_id"] for r in rows], [r[field]["value_c"] for r in rows],
                       s=16, alpha=.65, label=f'{name} · semilla {manifest["seed"]}')
    for ax, limit, label in zip(axes, (70, 20), ("Máxima T [°C]", "Máximo ΔT a 25 mm [°C]")):
        ax.axhline(limit, color="#c0392b", linestyle="--", label=f"Límite {limit} °C")
        ax.set(xlabel="Índice de simulación (no tiempo)", ylabel=label)
        ax.grid(alpha=.2); ax.legend(fontsize=8)
    fig.suptitle("S7 · máximos sobre todo el horizonte de 110 días · resultados simulados")
    save(fig, "maximos")

    fig, ax = plt.subplots(figsize=(9, 4))
    for i, (name, manifest, rows, comparison) in enumerate(batches):
        stats = comparison["plans"][0]["statistics"]["final"]["joint"]
        low, high = np.array(stats["ci95"]) * 100
        p = stats["p"] * 100
        ax.errorbar(p, i, xerr=[[p-low], [high-p]], fmt="o", capsize=6,
                    label=f'{name}: {stats["failures"]}/{stats["n"]}, cota {high:.2f} %')
    ax.axvline(5, color="#c0392b", linestyle="--", label="Criterio < 5 %")
    ax.set(yticks=[0, 1], yticklabels=["Base", "Confirmación"], ylim=(-.6, 1.6),
           xlabel="Probabilidad de falla conjunta [%]", title="S7 · IC bilateral exacto 95 % (Clopper–Pearson)")
    ax.legend(loc="upper center", fontsize=9); ax.grid(axis="x", alpha=.2)
    save(fig, "riesgo")
    evidence = {"source_sha256": digest, "original_matches": True if original else None,
                "source": "data/hydration/source_terms.txt", "hydration_audit": audit,
                "batches": [{"name": name, "seed": m["seed"], "n": len(rows),
                             "curves": sorted({r["curve"] for r in rows}),
                             "source_sha256": m["source_sha256"]} for name, m, rows, _ in batches]}
    (out / "source_audit.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"Fuente verificada: {digest}\n200 muestras auditadas. Figuras en {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path)
    build(parser.parse_args().original)
