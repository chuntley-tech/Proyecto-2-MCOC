# IFC, vertidas y activación térmica

Implementación inicial basada en G04, G05 y las secciones 23–25 de la guía
de difusión. El IFC sigue siendo la fuente de geometría; las propiedades y
el cronograma del ejemplo son **supuestos sintéticos**, no datos medidos.

## Ejecutar y modificar

Desde la raíz del repositorio, en CMD:

```cmd
.venv\Scripts\python.exe -m scripts.construction_demo
.venv\Scripts\python.exe -m pytest -q tests/test_construction.py
```

La configuración está en [`config/construction_g8.json`](../config/construction_g8.json).
`case_config` resuelve el archivo del caso relativo al JSON de construcción;
de él se obtiene la ruta del IFC y sus GUID. No se reconstruyen sólidos desde
las dimensiones del JSON. El IFC de referencia es
[`models/g8_base.ifc`](../models/g8_base.ifc), reconstrucción docente de 3,30 m.

Cada entrada de `pours` contiene:

| Campo | Significado |
|---|---|
| `id` | Identificador entero positivo y único |
| `z_min_fraction`, `z_max_fraction` | Intervalo relativo a la altura total del IFC, entre 0 y 1 |
| `start_s` | Instante de colocación, en segundos desde el inicio del cálculo |
| `placement_c` | Temperatura del hormigón al colocarlo, en °C |

Las capas deben cubrir toda la altura sin huecos ni solapamientos y contener
celdas. Los centros determinan su pertenencia: refinar la malla si una capa
no se captura. El cronograma es independiente del identificador de componente
IFC. No se presupone que los tres objetos BIM sean tres vertidas.

El ejemplo utiliza tres capas de igual altura, colocadas a los 0, 1 y 2 días,
a 20 °C, y una simulación de 4 días. Estos valores son supuestos de ensayo.
Se supone colocación instantánea de cada capa completa.

## Hidratación inicial

Se conserva el pulso sintético del visor, ahora en función de la **edad local**
de cada vertida: `a = t − start_s`.

\[
\dot q_h(a)=\frac{Q_{\max}}2[1-\cos(2\pi a/\tau)],\quad 0\le a<\tau;
\qquad \dot q_h=0\text{ fuera del intervalo}.
\]

`Qmax = 1300 W/m³` y `τ = 172800 s` en el ejemplo. Su integral completa es
`Qmax·τ/2 = 112320000 J/m³`. La conexión física con una curva adiabática es
`q_h = ρ cp dθ_ad/dt`. No representa cinética calibrada, grado de hidratación
ni dependencia de la velocidad con la temperatura. La fuente se evalúa en
`t_n`, al inicio de cada paso, por lo que su integral numérica es una suma
izquierda; la conservación se comprueba contra esa misma energía discreta.

## Activación y balance

`vertida_id` identifica todo el hormigón futuro. `active(t)` incluye únicamente
las celdas ya colocadas. Las futuras no generan calor ni intercambian energía.
Su temperatura almacenada en cero es un marcador: **no debe graficarse como
temperatura física**, sino ocultarse usando la máscara de cada instante.

Al llegar a un inicio de vertida, se asigna `placement_c` y se reconstruyen
conductancias y superficies expuestas. Hasta la colocación de la capa vecina,
su interfaz recibe `exposed`; después es una interfaz conductiva interna.
En el ejemplo, Robin con aire a 20 °C y h=10 W/(m²·K) en superficies expuestas;
base adiabática. No hay suelo ni moldaje explícitos.

`dt_s` es un máximo solicitado: el solver limita cada paso a 0,8 del menor
límite de estabilidad general/local, a τ/100 y al siguiente evento o final.
Solo reconstruye coeficientes al activar celdas. Guarda el estado inicial,
cada `save_every` pasos, los eventos y siempre el final, posteriores a colocar.

\[
E(t)-E(0)=Q_{borde}+Q_{fuente}+E_{colocación}.
\]

`E_colocación = Σ ρ cp V T_colocación` cuenta únicamente las activaciones
posteriores a cero, con referencia térmica a 0 °C; las iniciales ya están en
`E(0)`. No es una generación de calor adicional.

## Salidas y verificación

[`results/construction/resumen.json`](../results/construction/resumen.json)
registra configuración, SHA-256 IFC, cotas, volúmenes por vertida, temperaturas,
estados activos y balance. `construction.npz` conserva componentes, grilla,
`vertida_id`, campos de inicio/colocación y estados térmicos con sus máscaras.

En la ejecución inicial: 7120 celdas geométricas, volumen IFC 487,350199 m³,
volumen voxelizado 489,500004 m³, residuo relativo máximo de energía
1,183684 × 10⁻¹⁵. Son resultados calculados guardados en ese JSON, con la
resolución solicitada 0,5 × 0,5 × 0,275 m.

Las pruebas verifican cobertura y volumen, planes inválidos, eventos exactos,
ausencia de intercambio con hormigón futuro, energía de colocación, dominio
inicialmente vacío, activación final, enfriamiento de superficies temporales,
edad local y equivalencia con el solver fijo cuando todo se coloca al inicio.

Verificación del 3 de noviembre de 2026: 12 pruebas específicas aprobadas;
batería completa, 211 aprobadas en 82,52 s. Se comprobó también que el NPZ
conserva cobertura de etiquetas, suma de volúmenes y marcadores inactivos.

![Evolución sintética y activación](../results/construction/evolucion.png)

Esta funcionalidad se ejecuta en **Python**. El HTML conserva su división
geométrica simultánea y no ejecuta este cronograma. Quedan para etapas
posteriores la calibración experimental, clima real, cinética térmica avanzada,
duración de llenado, suelo y validación de una decisión constructiva.
