# Antecedentes públicos para verificar S7

Investigación del 17 de noviembre de 2026. Se revisaron fuentes primarias de
fabricantes y proveedores, la página del titular y enlaces del expediente
ambiental. El alcance permite identificar materiales y evidencias a solicitar.
La selección efectiva para Cuatro Vientos y la disponibilidad para una fecha
de obra requieren confirmación documental del mandante y proveedores.

## Mezcla de hormigón

La página de Colbún identifica Cuatro Vientos en Loncotoro y Colegual,
Llanquihue. En las fuentes accesibles consultadas no se encontró una receta
aprobada, ensayos térmicos de su mezcla o una orden de suministro para la
fundación. El enlace SEA aportado originalmente produjo un error de lectura.
Se localizó el capítulo descriptivo del EIA, pero el servidor no entregó
contenido legible en la consulta. Este límite impide atribuir al expediente
una dosificación o proveedor concreto.
[Titular Colbún](https://www.colbun.cl/nuestras-energias/proyectos-de-energia-renovable/proyectos-eolicos/cuatro-vientos),
[capítulo 1 del EIA](https://seia.sea.gob.cl/archivos/2024/01/17/Capitulo_1_Descripcion_de_Proyecto_Rev1.pdf).

La ficha de Cemento Melón Especial contempla aplicaciones masivas y menor
generación de calor. Para elegirlo se necesita comprobar la resistencia y
durabilidad exigidas, y ensayar el hormigón con su dosificación completa.
Falta vincular la receta real con los valores de k, ρ, cp y las curvas M1–M4
SS del repositorio. La información comercial del cemento, por sí sola,
deja esa vinculación pendiente.
[Ficha de Melón Especial](https://www.melon.cl/productos/cementos/item/cemento-melon-especial/).

La documentación técnica del ICH sobre el trabajo de CTK describe maquetas
instrumentadas de 1 m³ y calibración de propiedades térmicas a partir de
temperaturas de núcleo y superficie. Es una vía para contratar o diseñar
la caracterización de la mezcla. Se requieren registros originales, condiciones
de borde, identificación de lote y un registro independiente para validar el
ajuste. Calibrar simultáneamente fuente, conductividad y pérdidas superficiales
requiere evaluar su identificabilidad.
[Descripción del procedimiento](https://hormigonaldia.ich.cl/recomendaciones-tecnicas/modelo-ctk-para-la-especificacion-de-hormigones-masivos-especiales/).

Solicitar al responsable de la mezcla la dosificación en kg/m³, cemento y
adiciones, relación agua/aglomerante, áridos y aditivos, resistencia y edad
especificadas, temperatura y trabajabilidad de entrega, densidad, método
experimental de k y cp, curva calorimétrica o historia instrumentada, y
correspondencia con las probetas Arrieta. Adjuntar incertidumbre y condiciones
de ensayo para cada propiedad.

## Mantas

Safe Energy publica una manta industrial de lana de roca con malla, en
50 y 100 mm de espesor y densidad 100 kg/m³. Su tabla declara conductividad
de prueba de 0,034 W/(m·K) a 24 °C y 0,042 a 93 °C, con referencias a ASTM
C592 y C177. La ficha identifica un producto térmico comercial. Para usarlo
como protección temporal del hormigón se necesita aprobar la envolvente,
resistencia a lluvia, fijaciones, juntas, compresión y compatibilidad con el
curado. La ficha del producto requiere complementarse con el informe de
ensayo y la confirmación del lote que se suministraría.
[Ficha Safe Energy, páginas 1–2](https://safe-energy.cl/pdf/safe/Manta_con_malla_Safe_Energy.pdf).

En S7, los espesores equivalentes iniciales de 175 y 45 mm con k = 0,04
representan R'' de 4,375 y 1,125 m²·K/W. Una propuesta con capas comerciales
de 50/100 mm exige recalcular esas resistencias y cada retiro. Los espesores
posteriores de 115, 9 o 6,25 mm también requieren convertir el programa
térmico en una solución material ejecutable.

Como referencia adicional, StrongCure es una manta destinada al curado de
hormigón que declara resistencia térmica ensayada bajo ASTM C518. Su tabla
indica R-values 2,2 y 3,3. Antes de introducirlos al solver deben confirmarse
las unidades con el fabricante. La información publicada consultada no
explicita esas unidades junto a los valores.
[Ficha de producto StrongCure](https://www.strongman.com/product/concrete-curing-blanket/).

## Subbase aislante

La guía TG03 de FOAMGLAS documenta aislantes para aplicaciones enterradas.
Su tabla incluye S3 con conductividad 0,045 W/(m·K) y resistencia a compresión
900 kPa. La propia guía identifica ese valor como resistencia de rotura y
exige un factor de seguridad para determinar cargas de trabajo. La elección
para la fundación debe incorporar fluencia, rigidez, cargas cíclicas,
asentamientos, cortante, agua y compatibilidad con anclajes.
[Guía oficial TG03, página 3](https://www.foamglas.com/-/media/project/foamglas/public/shared/files/tds/tg-03---below-ground-insulation.pdf).

Con λ = 0,045, alcanzar R'' = 2,5 exige e = R'' λ = 0,1125 m. Es una
estimación calculada para material homogéneo. Por ejemplo, 120 mm darían
2,667 m²·K/W antes de contactos y detalles. La especificación final debe
conservar o actualizar esa resistencia y representar la capacidad térmica
de la capa si afecta al resultado. Queda pendiente la disponibilidad en Chile
y la aprobación para las cargas de un aerogenerador.

## Bombeo y suministro

La ficha oficial Putzmeister BSF 36-4 publica capacidades de 108/160 m³/h
para la versión .16 H, según configuración de bombeo, y señala que los datos
son máximos teóricos. El objetivo de 40 m³/h es una fracción de esa capacidad,
pero requiere comprobar mezcla, trazado de tuberías, presión, alcance,
emplazamiento de estabilizadores y continuidad de alimentación.
[Ficha del fabricante, página 1](https://www.putzmeister.com/documents/20127/71252/M36-4%2BTypenblatt%2BDE.pdf/7c2c9d3a-1307-91a5-e516-80940691635c?t=1584101921708).

El reporte corporativo Melón de 2026 lista plantas de hormigón en Puerto Montt
y Osorno. Sus términos públicos de tienda exigen programación previa y
confirmación de disponibilidad, e indican horarios ordinarios limitados.
Para S7 se debe acordar específicamente la jornada continua de unas 12,11 h,
de 08:00 a aproximadamente 20:07. Las condiciones comerciales de un contrato
de obra pueden diferir de las de tienda.
[Presencia regional de Melón](https://www.melon.cl/wp-content/uploads/2026/04/260331_Melon_V4CMF.pdf),
[condiciones de programación, §20](https://tienda.melon.cl/terms-condictions).

Para un ejemplo sintético de camiones con carga útil 8 m³, 40 m³/h exige una
llegada cada 12 minutos. Un ciclo completo de 90 minutos demanda al menos
ceil(40 × 1,5 / 8) = 8 vehículos antes de reserva. El volumen de 484,41 m³
equivale a 61 cargas de hasta 8 m³. Estos valores ilustran la logística y
deben sustituirse por capacidades, recorridos y tiempos confirmados.

## Evidencias necesarias para cerrar la revisión

| Evidencia | Responsable esperado | Cierre que permite |
|---|---|---|
| Receta aprobada y ensayos identificados por lote | Mandante, productor y laboratorio | Propiedades reales y fuente de hidratación |
| Ficha vigente e informe térmico de mantas, capas y montaje | Proveedor y constructor | Resistencias y calendario de retiros ejecutables |
| Diseño de subbase y aprobación de cargas | Especialistas estructural y geotécnico | Compatibilidad del aislamiento con la fundación |
| Confirmación escrita de planta, bomba, jornada y contingencias | Productor, empresa de bombeo y constructor | Caudal útil y continuidad de S7 |

La muestra fina de S7 alcanzó 20,7783 °C de diferencial. La investigación de
productos permite formular alternativas documentadas. Cada selección requiere
una nueva simulación y revisión de convergencia antes de sostener cumplimiento.
[Revisión y resultados actuales](S7_VALIDACION.md).
