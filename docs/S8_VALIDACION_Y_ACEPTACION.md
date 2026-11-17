# Evidencias para aceptar S8

Estado de revisión del 17 de noviembre de 2026. Las fichas disponibles permiten
formular una candidata térmica. La aceptación en obra requiere completar las
evidencias siguientes e identificar quién aprueba cada una. Un resultado
numérico calculado conserva su condición de predicción hasta contrastarlo
con registros independientes.

## Mezcla real y ensayo independiente

| Evidencia solicitada | Contenido verificable | Estado |
|---|---|---|
| Dosificación aprobada | Identificación y revisión, kg/m³ de cada componente, agua/aglomerante, cementos y aditivos | Pendiente del mandante/productor |
| Correspondencia con Arrieta M1–M4 | Receta y lote de cada probeta, fecha y temperatura de ensayo | Pendiente |
| k, ρ y cp | Método, humedad, edad, temperatura y resultados con incertidumbre | Valores de referencia y cabecera disponibles; ensayo de mezcla de obra pendiente |
| Fuente Q(t) | Datos originales, condiciones de borde, parámetros de inversión y residuo | Tabla inferida disponible; registros originales pendientes |
| Validación térmica | Historia de núcleo, superficie y ambiente de una muestra independiente | Pendiente de ensayo |

Propuesta de contraste experimental, sujeta al laboratorio y al profesor.
Registrar masa, geometría, temperatura de colocación, protección y ambiente.
Instrumentar al menos núcleo y profundidad superficial declarada. Guardar
tiempos, unidades, calibración e incertidumbre de sensores. Reservar un ensayo
independiente de los usados para ajustar los parámetros. Predeclarar métricas
de error sobre la historia completa y sobre máximos y sus instantes. Acordar
tolerancias a partir de la incertidumbre instrumental y del propósito del
modelo antes de observar los resultados. Una calibración de varios parámetros
debe revisar sus correlaciones e identificabilidad.

## Materiales y aprobación estructural

| Elemento | Evidencia solicitada | Responsable de aceptación |
|---|---|---|
| Mantas de 50/100 mm | Ficha vigente, lote, informe de conductividad/resistencia a temperaturas de servicio y montaje de capas | Constructor, proveedor y responsable térmico |
| Protección exterior | Solapes, cubierta impermeable, fijaciones, carga de viento y procedimiento de curado | Constructor y prevención |
| Subbase de 120 mm | Conductividad, espesor efectivo, contactos, rigidez, compresión, fluencia, humedad y capacidad térmica | Proveedor y especialistas estructural/geotécnico |
| Fundación con subbase | Cargas gravitatorias, cíclicas y sísmicas, cortante, giro, asentamientos y anclajes | Ingenieros responsables del diseño |
| Retiros | Plano de sectores y retiro de capas a días 35, 60, 80 y 150, monitoreo y contingencia | Constructor y responsable térmico |

La ficha S3 con resistencia a rotura de 900 kPa requiere calcular una tensión
admisible para las condiciones de servicio y sus factores de seguridad.
El caso térmico actual representa la subbase mediante una resistencia
interfacial. Se necesita revisar el efecto de su espesor y almacenamiento de
calor antes de homologarla físicamente a la solución construida.
[Investigación y fuentes originales](S7_INVESTIGACION_MATERIALES.md).

## Programación de bombeo y suministro

Texto preparado para una solicitud técnica, pendiente de envío por el equipo.

> Solicitamos evaluar el suministro continuo de aproximadamente 484,41 m³
> para una fundación, con inicio docente el 19 de noviembre de 2026 a las
> 08:00 de Santiago, caudal útil de 40 m³/h y duración prevista de 12,11 h.
> Agradecemos indicar mezcla propuesta, control de temperatura de entrega
> nominal 16 °C y tolerancia, trabajabilidad y tiempo abierto, planta de
> origen, capacidad efectiva, tiempos de transporte y flota disponible.
> Para bombeo, indicar equipo y operador, capacidad útil bajo el trazado de
> tubería y condiciones de acceso, estabilizadores y apoyo del terreno,
> horario continuo, personal y equipos de reserva. Informar restricciones,
> inspección de factibilidad, contingencias y confirmación escrita del servicio.

El programa de mantas termina al día 150. El cálculo térmico llega al día 157.
La duración de colocación D termina con la última descarga y se reporta
separada de la duración de protección y del horizonte térmico.

## Criterio numérico y probabilístico

El evento de falla conserva la unión T máxima > 70 °C o ΔT > 20 °C en
todo el hormigón colocado y todos los instantes evaluados. El Monte Carlo
de S8 usa la configuración y las mantas de S8, con el ensamble del 17 de
noviembre que cubre 14 días. Base y confirmación usan semillas distintas y
100 realizaciones cada una. Cada intervalo exacto y su horizonte deben
reportarse por lote. El cumplimiento del riesgo requiere cota superior
del IC conjunto inferior al 5 % bajo el modelo evaluado.

La secuencia espacial de ΔT de la muestra crítica anterior fue 15,6020,
15,6383 y 17,0489 °C. El incremento creciente impide deducir un orden
asintótico de esos máximos. La resolución vertical efectiva también cambia
la razón de refinamiento. Los máximos se buscan sobre caras escalonadas del
IFC voxelizado y su posición puede variar. Para cerrar la convergencia del
caso se requiere una secuencia con geometría y refinamiento controlados,
contraste de ubicaciones de máximos y error temporal subordinado al espacial.
Este punto se debe volver a evaluar sobre la realización crítica del propio
lote S8, que puede diferir de la muestra 46 de S7.

Hasta cerrar esos elementos, los intervalos de Monte Carlo se interpretan
condicionados a la discretización y a las distribuciones declaradas.
