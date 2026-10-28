"""Muestra la solución T(x,y,t) / T(x,y,z,t), no sus curvas de error.

Sin --show exporta PNG y datos numéricos. Con --show abre ventanas Matplotlib
giratorias. Los ensayos 2D/3D son sintéticos; --case fundacion visualiza el
campo guardado por foundation_3d_demo sin recalcular ni alterar ese resultado.
"""

import argparse
import json
import math
from pathlib import Path

import matplotlib
import numpy as np

from thermal1d.solver import Dirichlet
from thermal3d import Parameters, solve
from thermal3d.reference import sine_initial


def verification_solution(dim):
    """Ejemplo sintético: caja de 1 m, caras a 20 °C y seno inicial de 20 °C."""
    n, duration = (40 if dim == 2 else 24), 21600.0
    k, rho, cp = 2.2, 2400.0, 900.0
    alpha = k/(rho*cp)
    steps = math.ceil(duration/(0.05*(1/n)**2/alpha))
    p = Parameters((n,)*dim, (1.0,)*dim, k, rho, cp, duration/steps, duration,
                   {f: Dirichlet(20.0) for f in ("x-", "x+", "y-", "y+", "z-", "z+")[:2*dim]})
    initial = 20 + 20*sine_initial(p)
    result = solve(p, initial, save_every=10**9)
    return p, initial, result.temperature_c[-1]


def surface_cells(active):
    """Celdas superficiales de una máscara; solo se usa para dibujar el volumen."""
    inside = np.zeros_like(active)
    inside[1:-1, 1:-1, 1:-1] = (active[1:-1, 1:-1, 1:-1]
        & active[:-2, 1:-1, 1:-1] & active[2:, 1:-1, 1:-1]
        & active[1:-1, :-2, 1:-1] & active[1:-1, 2:, 1:-1]
        & active[1:-1, 1:-1, :-2] & active[1:-1, 1:-1, 2:])
    return active & ~inside


def plot_2d(initial, final, lengths, output):
    """Compara temperaturas iniciales y finales con una misma escala de colores."""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), layout="constrained")
    for ax, field, title in zip(axes, (initial, final), ("Inicio", "Después de 6 h")):
        im = ax.imshow(field.T, origin="lower", extent=[0, lengths[0], 0, lengths[1]],
                       vmin=20, vmax=40, cmap="inferno", aspect="equal")
        ax.set(xlabel="x [m]", ylabel="y [m]", title=title)
        ax.plot([0, lengths[0], lengths[0], 0, 0], [0, 0, lengths[1], lengths[1], 0],
                color="#00bcd4", linewidth=2, label="4 caras: Dirichlet 20 °C", clip_on=False)
        ax.legend(loc="upper right", fontsize=8)
    fig.colorbar(im, ax=axes, label="Temperatura [°C]")
    fig.suptitle("Solución del solver 2D — ensayo sintético, sin hidratación")
    fig.savefig(output/"solucion_2d.png", dpi=150)


def plot_3d(field, active, origin, spacing, output, prefix, title, surface=False,
            dirichlet_c=None, boundary_description=None):
    """Cortes ortogonales y nube 3D coloreada con la temperatura calculada."""
    import matplotlib.pyplot as plt

    lengths = np.asarray(field.shape)*spacing
    centers = [origin[a]+(np.arange(field.shape[a])+0.5)*spacing[a] for a in range(3)]
    i, j, k = np.asarray(field.shape)//2
    values = np.where(active, field, np.nan)
    low, high = float(field[active].min()), float(field[active].max())
    if dirichlet_c is not None:
        low, high = dirichlet_c, dirichlet_c+20.0
    # Un rango pequeño evita normalización degenerada si el campo es uniforme.
    if low == high:
        high = low+1.0
    frames = [(values[i].T, (1, 2), f"x = {centers[0][i]:.3f} m"),
              (values[:, j].T, (0, 2), f"y = {centers[1][j]:.3f} m"),
              (values[:, :, k].T, (0, 1), f"z = {centers[2][k]:.3f} m")]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5), layout="constrained")
    for ax, (image, (horizontal, vertical), caption) in zip(axes, frames):
        im = ax.imshow(image, origin="lower", cmap="inferno", vmin=low, vmax=high,
                       extent=[origin[horizontal], origin[horizontal]+lengths[horizontal],
                               origin[vertical], origin[vertical]+lengths[vertical]], aspect="auto")
        ax.set(xlabel="xyz"[horizontal]+" [m]", ylabel="xyz"[vertical]+" [m]", title=caption)
        if dirichlet_c is not None:
            x0, y0 = origin[horizontal], origin[vertical]
            x1, y1 = x0+lengths[horizontal], y0+lengths[vertical]
            ax.plot([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0], color="#00bcd4",
                    linewidth=2, label=f"Caras: Dirichlet {dirichlet_c:g} °C", clip_on=False)
            ax.legend(loc="upper right", fontsize=7)
    fig.colorbar(im, ax=axes, label="Temperatura final [°C]")
    fig.suptitle(title+" — cortes de la solución 3D"+("\n"+boundary_description if boundary_description else ""))
    fig.savefig(output/f"{prefix}_cortes.png", dpi=150)

    selected = surface_cells(active) if surface else np.zeros_like(active)
    if not surface:
        selected[i] = active[i]
        selected[:, j] |= active[:, j]
        selected[:, :, k] |= active[:, :, k]
    indices = np.nonzero(selected)
    fig = plt.figure(figsize=(9, 6), layout="constrained")
    ax = fig.add_subplot(projection="3d")
    points = ax.scatter(centers[0][indices[0]], centers[1][indices[1]], centers[2][indices[2]],
                        c=field[selected], s=9, marker="s", cmap="inferno", vmin=low, vmax=high,
                        linewidths=0, depthshade=False)
    ax.set(xlabel="x [m]", ylabel="y [m]", zlabel="z [m]",
           title=title+(" — superficie de celdas activas" if surface else " — cortes en el espacio"))
    ax.set_box_aspect(lengths)
    if dirichlet_c is not None:
        # Aristas de la caja física, no centros extremos ni nuevos nodos térmicos.
        for level in (0, 1):
            ax.plot(origin[0]+np.array([0, 1, 1, 0, 0])*lengths[0],
                    origin[1]+np.array([0, 0, 1, 1, 0])*lengths[1],
                    np.full(5, origin[2]+level*lengths[2]), color="#00bcd4", linewidth=1.5,
                    label=f"6 caras: Dirichlet {dirichlet_c:g} °C" if level == 0 else None)
        for a, b in ((0, 0), (0, 1), (1, 0), (1, 1)):
            ax.plot(np.full(2, origin[0]+a*lengths[0]), np.full(2, origin[1]+b*lengths[1]),
                    [origin[2], origin[2]+lengths[2]], color="#00bcd4", linewidth=1.5)
        ax.legend(loc="upper right", fontsize=8)
    if boundary_description:
        fig.suptitle(boundary_description, fontsize=10)
    fig.colorbar(points, ax=ax, label="Temperatura final [°C]", shrink=0.7)
    fig.savefig(output/f"{prefix}_vista_3d.png", dpi=150)


def plot_boundary_profiles(cases, output):
    """Separa las temperaturas conocidas en caras de los valores en centros.

    Los cuadrados en x=0 y x=L son datos Dirichlet. Las curvas usan solo
    centros calculados; no se modifica ni rellena artificialmente el campo.
    """
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), layout="constrained")
    report = {"data_status": "Ensayos sintéticos; las caras son datos impuestos y los centros son resultados calculados."}
    for ax, (p, initial, final) in zip(axes, cases):
        dim = len(p.shape)
        transverse = (p.shape[1]//2,) if dim == 2 else (p.shape[1]//2, p.shape[2]//2)
        line = (slice(None),)+transverse
        centers = (np.arange(p.shape[0])+0.5)*p.spacing_m[0]
        tb = p.boundaries["x-"].temperature_c
        ax.plot(centers, initial[line], "--", color="gray", label="Inicio: centros")
        ax.plot(centers, final[line], "o-", markersize=3, label="6 h: centros calculados")
        ax.scatter([0, p.lengths_m[0]], [tb, tb], marker="s", s=65, color="#00bcd4",
                   edgecolors="black", label=f"Caras físicas: {tb:g} °C", zorder=4)
        ax.axhline(tb, color="#00bcd4", linestyle=":")
        ax.set(xlabel="x [m]", ylabel="Temperatura [°C]", title=f"{dim}D: perfil interior; centros a Δx/2 de la cara")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)
        report[f"{dim}D"] = {"boundary_type": "Dirichlet", "faces": list(p.boundaries),
                             "boundary_temperature_c": tb, "spacing_m": p.spacing_m.tolist(),
                             "first_center_x_m": float(centers[0]), "last_center_x_m": float(centers[-1]),
                             "transverse_indices": list(transverse),
                             "first_center_final_c": float(final[line][0]),
                             "last_center_final_c": float(final[line][-1]),
                             "duration_s": p.duration_s}
    fig.suptitle("La cara está a 20 °C; la celda vecina puede estar más caliente")
    fig.savefig(output/"condiciones_borde_perfiles.png", dpi=150)
    (output/"condiciones_borde.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")


def foundation_boundary_description(path, field, time_s, fingerprint):
    """Muestra condiciones solo si el resumen coincide con el campo guardado."""
    summary = Path(path).with_name("demo_termica_fundacion.json")
    if not summary.is_file():
        return "Bordes no incluidos en el NPZ: consultar el caso que generó este campo."
    report = json.loads(summary.read_text(encoding="utf-8"))
    probe = tuple(report["probe_index"])
    if (report["voxel"]["ifc_input"]["sha256"] != fingerprint or report["final_time_s"] != time_s
            or not np.isclose(field[probe], report["final_center_temperature_c"], rtol=0, atol=1e-12)):
        raise ValueError("El resumen de bordes no coincide con el campo NPZ; regenere foundation_3d_demo")
    return (f"Robin en caras al aire: T_amb = {report['options']['air_c']:g} °C, "
            f"h efectivo = {report['effective_h_w_m2k']:g} W/(m²·K). Base: Neumann q_in = 0.")


def main(argv=None):
    """Exporta figuras y opcionalmente abre ventanas para rotar e inspeccionar."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("verificacion", "fundacion"), default="verificacion")
    parser.add_argument("--input", type=Path, default=Path("results/voxel/temperatura_final.npz"))
    parser.add_argument("--output", type=Path, default=Path("results/soluciones"))
    parser.add_argument("--show", action="store_true", help="abre ventanas; arrastrar con el ratón rota la vista 3D")
    args = parser.parse_args(argv)
    matplotlib.use("TkAgg" if args.show else "Agg")
    import matplotlib.pyplot as plt

    args.output.mkdir(parents=True, exist_ok=True)
    if args.case == "verificacion":
        p2, initial, final = verification_solution(2)
        case2 = (p2, initial, final)
        plot_2d(initial, final, p2.lengths_m, args.output)
        np.savez_compressed(args.output/"solucion_2d.npz", initial_c=initial, temperature_c=final,
                            spacing_m=p2.spacing_m, origin_m=np.zeros(2), time_s=p2.duration_s,
                            dirichlet_temperature_c=20.0)
        p3, initial, final = verification_solution(3)
        plot_boundary_profiles((case2, (p3, initial, final)), args.output)
        plot_3d(final, np.ones(p3.shape, dtype=bool), np.zeros(3), p3.spacing_m, args.output,
                "solucion_3d", "Ensayo sintético, después de 6 h", dirichlet_c=20.0,
                boundary_description="Dirichlet: 20 °C en las seis caras. Colores: temperaturas de centros, no de caras.")
        np.savez_compressed(args.output/"solucion_3d.npz", initial_c=initial, temperature_c=final,
                            spacing_m=p3.spacing_m, origin_m=np.zeros(3), time_s=p3.duration_s,
                            dirichlet_temperature_c=20.0)
        print("Solución 2D: solucion_2d.png; solución 3D: solucion_3d_cortes.png y solucion_3d_vista_3d.png")
        print("Ensayos sintéticos en cajas de 1 m; no representan la geometría de la fundación.")
        print("Bordes: Dirichlet 20 °C en 4 caras (2D) y 6 caras (3D). Ver condiciones_borde_perfiles.png.")
        print("El primer/último centro está a media celda de la cara: su temperatura no se fija a 20 °C.")
    else:
        with np.load(args.input, allow_pickle=False) as data:
            field = data["temperature_c"]
            active = data["component"] > 0
            origin, spacing = data["origin_m"], data["spacing_m"]
            time_s = float(data["time_s"])
            fingerprint = str(data["ifc_sha256"])
        if field.ndim != 3 or active.shape != field.shape or not active.any() or not np.all(np.isfinite(field[active])):
            raise ValueError("El NPZ debe contener un campo 3D finito y una máscara activa compatible")
        description = foundation_boundary_description(args.input, field, time_s, fingerprint)
        plot_3d(field, active, origin, spacing, args.output, "fundacion",
                f"Fundación: enfriamiento sintético, día {time_s/86400:g}", surface=True,
                boundary_description=description)
        print("Campo guardado de la fundación: fundacion_cortes.png y fundacion_vista_3d.png")
        print("Las superficies muestran las celdas exteriores; los cortes permiten ver el interior.")
        print(description)
    print(f"Figuras y datos en {args.output}")
    if args.show:
        print("Arrastra con el botón izquierdo del ratón para girar la vista 3D. Cierra las ventanas para terminar.")
        plt.show()
    else:
        plt.close("all")


if __name__ == "__main__":
    main()
