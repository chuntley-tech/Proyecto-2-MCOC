# E04: preparación oral del solver general

Contenido conceptual aprovechado del segundo ZIP y adaptado a nuestra API.
Las evidencias reproducibles están en [E04_solver_3d](E04_solver_3d.md) y
[E06](E06_dossier_verificacion.md); los valores de ensayo son sintéticos.

## Balance, stencil y signos

Explicar `C_i dT_i/dt = ΣG_ij(T_j−T_i) + q̇V_i + Q_borde,i`.
`C=ρcpV` tiene unidades J/K; `G=kA/d`, W/K; `q̇`, W/m³; y el flujo de
Neumann, W/m². El flujo positivo entra al dominio. Cada cara interna suma una
potencia a una celda y resta la misma a su vecina: esa simetría conserva energía.

Los centros se ubican en `(i+0.5)Δ`, con `Δ=L/n`. El stencil cartesiano tiene
cuatro o seis vecinos en 2D o 3D. Las diferencias se calculan por slicing,
sin conectar caras opuestas. La fuente y el ambiente variable se evalúan al
inicio del paso; el último paso se acorta. `save_every` conserva inicial y final.

## Bordes y materiales

- Dirichlet: temperatura de la cara, conectada al centro por media celda.
- Neumann: potencia entrante `q_in A`; cero es adiabático.
- Robin: película de aire y media celda conductiva en serie. No equivale a
  fijar la temperatura de la superficie igual al aire.
- Materiales diferentes: las dos medias celdas están en serie, por eso se usa
  la media armónica de k. Cada celda tiene su propio ρcp.
- Aislación: `effective_h` suma resistencias superficiales en serie. Los valores
  de demostración no representan un moldaje real validado.

Las caras de la caja se asignan en `boundaries`. Las superficies escalonadas
entre activo e inactivo usan `exposed` solo si se declara; en caso contrario son
adiabáticas. Las celdas inactivas no almacenan energía del dominio térmico.

## Estabilidad y verificación

Se exigen tanto `α Δt Σ(1/Δ²) ≤ 1/2` como `Δt ≤ C_i/ΣG_i`, incluyendo los
bordes. Con material variable, el primero usa la máxima difusividad activa,
de forma conservadora. Una esquina con varias caras impuestas puede imponer
un límite local más estricto que el del interior.

El error espacial se compara contra el seno continuo. El orden temporal se
compara contra la solución semidiscreta para evitar compensaciones entre
errores de espacio y tiempo. Conservar energía no demuestra por sí solo que
la distribución de temperaturas sea correcta: hacen falta ambos tipos de pruebas.

## BIM y método de Schmidt

Blender/Bonsai edita el IFC; IfcOpenShell lo triangula en coordenadas SI.
El voxelizador clasifica centros y conserva GUID y componente. El solver
solo recibe grilla, máscara y material: no depende de Blender.

G05 resume el método de Schmidt como diferencias finitas simplificadas para
hormigón masivo. Nuestro balance comparte esa filosofía, pero utiliza celdas
centradas y resistencias por cara. **La lectura individual del Anexo 4 original
del ICH sigue pendiente de acreditar**: el ZIP no contiene ese documento.

Para demostrar el flujo, guardar una copia editada en Bonsai y usar `--ifc`
en los comandos de [E05](E05_guia_laboratorio.md). No regenerar el IFC después
de editarlo, pues `scripts.create_ifc` sustituiría la geometría nominal.
