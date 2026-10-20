# E03 — Verificación del solver 1D · Grupo 8

**Repositorio:** https://github.com/chuntley-tech/Proyecto-2-MCOC
**Commit evaluado:** `<completar con el SHA declarado>`

Preparación contrastada con [G05](guias/G05_DIFUSION_TERMICA_FD.md) y
[Difusión de calor](guias/DIFUSION_DE_CALOR_1D_2D_3D.md), §§5–8, 21–22 y 32–33.
Los resultados se vuelven a generar localmente; este documento no acredita
una evaluación ni la lectura individual de cada integrante.

Todas las figuras y tablas se regeneran desde la raíz del repositorio con:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_case        # Figura 1 y results/example_1d
.\.venv\Scripts\python.exe -m scripts.convergence     # Figuras 2 y 3 y results/convergence
.\.venv\Scripts\python.exe -m pytest -q               # pruebas automáticas
```

## 1. Problema de verificación

El solver resuelve el balance de energía en una columna vertical con propiedades constantes:

ρ c<sub>p</sub> ∂T/∂t = k ∂²T/∂z²

Usamos datos **sintéticos**, elegidos solo para verificar el código. No son mediciones ni representan la fundación real ni el clima de Llanquihue:

| Dato | Valor |
|---|---|
| Largo L | 3,30 m, longitud del caso sintético principal; no se extrae automáticamente del IFC |
| k, ρ, c<sub>p</sub> | 2,2 W/(m·K), 2400 kg/m³, 900 J/(kg·K) → α = 1,0185·10⁻⁶ m²/s |
| Bordes | Dirichlet: T(0, t) = T(L, t) = 20 °C |
| Condición inicial | T(z, 0) = 20 + 20 sen(πz/L) °C |
| Duración | 14 días |

La solución exacta es T(z, t) = 20 + 20 sen(πz/L) exp(−t/τ), con τ = L²/(π²α) ≈ 12,5 días.

## 2. Método numérico

Usamos diferencias centrales en el espacio y Euler explícito en el tiempo:

T<sub>i</sub><sup>n+1</sup> = T<sub>i</sub><sup>n</sup> + Fo (T<sub>i+1</sub><sup>n</sup> − 2T<sub>i</sub><sup>n</sup> + T<sub>i−1</sub><sup>n</sup>), con Fo = αΔt/Δz²

- **Orden esperado:** 2 en Δz y 1 en Δt.
- **Estabilidad:** el esquema es estable si Fo ≤ 1/2. El solver rechaza pasos que no la cumplen. Con un borde convectivo (Robin) el límite es más estricto: Fo(1 + Bi) ≤ 1/2, con Bi = hΔz/k.

## 3. Solución numérica frente a la exacta

![Figura 1](../results/example_1d/profiles.png)

**Figura 1.** Perfiles cada 3,5 días. Línea continua: solver; discontinua: solución exacta.

Con 67 nodos (Δz = 0,05 m) y Δt = 600 s (Fo = 0,244):
- El error máximo al final es **6,4·10⁻⁴ °C** y el RMSE es 4,5·10⁻⁴ °C.
- En el centro, el solver da 26,547 °C y la solución exacta 26,548 °C.
- La forma sinusoidal se conserva y los bordes se mantienen en 20 °C.

## 4. Convergencia espacial

Refinamos Δz de 0,33 a 0,021 m (11 a 161 nodos) con **Fo = 0,02 fijo**. Así Δt baja junto con Δz² y el error temporal queda cerca de 8 veces menor que el espacial.

| Δz [m] | 0,330 | 0,165 | 0,0825 | 0,0413 | 0,0206 |
|---|---|---|---|---|---|
| Error máx. [°C] | 5,31·10⁻² | 1,32·10⁻² | 3,31·10⁻³ | 8,27·10⁻⁴ | 2,07·10⁻⁴ |

![Figura 2](../results/convergence/espacial.png)

**Figura 2.** El error baja cerca de 4 veces cada vez que Δz se divide por 2. La pendiente ajustada es **2,00**, igual al orden esperado de las diferencias centrales. Superpuesto aparece el error espacial puro, calculado analíticamente; casi coincide con el del solver.

## 5. Convergencia temporal

Fijamos 41 nodos (Δz = 0,0825 m) y bajamos Δt de 3332 a 209 s (Fo de 1/2 a 1/32).

Para aislar el error temporal no comparamos con la solución continua, sino con la **solución exacta del sistema semidiscreto**: el mismo Δz, integrado exactamente en el tiempo. El modo seno es un modo propio de la segunda diferencia central, con valor propio λ<sub>h</sub> = [2 sen(πΔz/2L)/Δz]². Por eso esa solución se puede escribir en forma cerrada, y la diferencia con el solver es solo error de Euler.

| Δt [s] | 3332 | 1668 | 835 | 418 | 209 |
|---|---|---|---|---|---|
| Error vs. semidiscreta [°C] | 1,13·10⁻² | 5,63·10⁻³ | 2,82·10⁻³ | 1,41·10⁻³ | 7,04·10⁻⁴ |

![Figura 3](../results/convergence/temporal.png)

**Figura 3.** El error se reduce a la mitad cada vez que Δt se divide por 2. La pendiente ajustada es **1,00**, igual al orden de Euler explícito.

La curva comparada con la solución continua muestra por qué hay que separar las dos fuentes de error:
- **No es monótona.** El error espacial tiende a frenar el enfriamiento y el de Euler a acelerarlo, así que se cancelan en parte; la cancelación es completa cerca de Fo = 1/6.
- **Se estanca.** Al achicar Δt, la curva tiende al error espacial de esa malla, 3,8·10⁻³ °C. Achicar Δt no mejora el resultado si no se refina también Δz.

## 6. Pruebas automáticas

`pytest` corre pruebas que comprueban, entre otras cosas:
- la solución seno exacta y el principio del máximo;
- los órdenes 2 (espacio) y 1 (tiempo);
- la serie de Fourier de una losa con cambio brusco en sus caras;
- la conservación exacta de energía en un dominio adiabático;
- la energía que entra por un flujo impuesto, igual a q·t;
- el estacionario lineal con bordes Robin;
- el aumento lineal con fuente uniforme y la parábola con caras frías;
- el rechazo de pasos inestables, también con Robin.

Además, los ejemplos de `config/ejemplos` se contrastan con los bucles de
referencia incluidos en el ZIP (Dirichlet, Neumann, Robin y fuente interna).
Se contrastaron con las guías entregadas: los casos 01, 03, 04 y 05 son
adaptaciones de los conceptos de bordes y fuentes, mientras que el caso 06
corresponde a la losa convectiva de la sección 12. Véase
[el detalle de referencias](REFERENCIAS_GUIAS.md).

## 7. Alcance

Esto es **verificación**: muestra que el código resuelve bien la ecuación que escribimos. No es **validación**, porque no compara con sensores ni con el paper.

Todavía faltan el calor de hidratación realista, la activación por vertidas, el clima de Llanquihue y el modelo en 2D y 3D. Por lo tanto, este resultado no dice nada sobre si la fundación cumple los límites de 70 °C y 20 °C.
