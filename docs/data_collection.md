# Datos para el piloto de extracción de áridos

## Regla de oro

Una imagen satelital permite detectar una **faena o cambio compatible con extracción**. No permite concluir, por sí sola, que esa faena sea ilegal. La clasificación final requiere permisos, fechas de vigencia y revisión humana.

## Fuentes para empezar

1. **Casos y fiscalización**: revisar SNIFA/SMA y registrar expedientes públicos con coordenadas o polígonos, fecha, estado del caso y enlace de evidencia. Etiqueta solo los casos confirmados como `confirmed_extraction`; una denuncia sin resultado debe quedar como `suspected_extraction`.
2. **Faenas autorizadas**: buscar proyectos de extracción de áridos y RCA en el SEA/SEIA. Son negativos críticos: visualmente parecen extracción, pero no deben producir una alerta de posible incumplimiento mientras el permiso sea válido.
3. **Permisos locales**: solicitar por Transparencia a municipios y organismos hídricos un listado estructurado, no PDFs sueltos. Campos mínimos: identificador, titular, geometría o coordenadas, cauce, acto administrativo, inicio, término, estado y volumen autorizado.
4. **Imágenes**: Sentinel-2 (óptico, 10 m) y Sentinel-1 (radar, 10 m) para series temporales gratuitas; Landsat para historia larga. Para faenas muy pequeñas o maquinaria se requerirá una fuente comercial correctamente licenciada.
5. **Capas auxiliares**: red hidrográfica, cuencas, cuerpos de agua, caminos, límites comunales y relieve. Ayudan a limitar el área de búsqueda y a construir negativos difíciles.

## Estructura mínima de cada etiqueta

- `id`: estable y único.
- `geometry`: punto o polígono GeoJSON.
- `label`: `confirmed_extraction`, `authorized_extraction`, `suspected_extraction` o `hard_negative`.
- `observed_at`: fecha de la observación.
- `source_url`: enlace al documento público o archivo interno autorizado.
- `precision`: `field_gps`, `polygon_documented`, `approximate_point` o `unknown`.
- `confidence`: número de 0 a 1.

No mezcles `confirmed` con ubicaciones aproximadas: ambas cosas deben quedar separadas en los campos de evidencia y precisión.

## Base pública SMA incluida

`build-sma-labels` toma las exportaciones públicas de Unidades Fiscalizables/Instrumentos y Sancionatorios de SNIFA. Conserva solo unidades cuyo nombre o descripción menciona áridos/arena y un contexto fluvial (río, cauce, estero o fluvial). Las etiqueta como `known_aggregate_site`, no como "legal" ni "ilegal": el catálogo público no asegura que la extracción estuviera activa o autorizada en una fecha determinada. Cada fila queda además en una cola de revisión antes de convertirla en etiqueta de píxel para entrenamiento.

`build-patches` busca para cada candidato una escena Sentinel-2 pública de baja nubosidad y guarda un PNG RGB de 256×256 píxeles, aproximadamente 2.56×2.56 km a 10 m. Es un recorte de entrenamiento **candidato**: la imagen y la fecha elegidas deben pasar una revisión visual antes de marcarla como positivo definitivo. En colecciones largas, ejecútalo por lotes usando `--offset` y `--limit`.

Para una colección grande de negativos, usa `--workers 8` y procesa por lotes. Mantén el registro de fallos: una imagen que no pudo descargarse no debe convertirse silenciosamente en una etiqueta.

## Ratio 1:10

Con 108 positivos, el objetivo es 1.080 negativos. `sample-river-negatives --ratio 10` genera esos 1.080 puntos desde la red hidrográfica oficial (ríos, esteros, arroyos y quebradas), a más de 10 km de cualquier sitio de áridos conocido de SMA. Son deliberadamente `background_river_candidate`, no negativos definitivos: la distancia a un catastro no demuestra ausencia de faena. Revisa visualmente las escenas y promueve a `hard_negative` solo los puntos donde no exista extracción, obra, acopio ni maquinaria.

`python -m sentinelwatch search-sentinel` guarda un catálogo STAC reproducible y `download-assets` descarga solo las bandas que indiques. En Earth Search, comienza con `blue,green,red,nir` (equivalentes a B02, B03, B04 y B08 de Sentinel-2); conserva el catálogo junto a las imágenes para saber de qué escena viene cada archivo.

## Solicitud de información sugerida

Solicita para el período 2018–actualidad: "base estructurada de autorizaciones, permisos, fiscalizaciones, denuncias y resoluciones relacionadas con extracción de áridos en cauces, incluyendo identificador, fecha, estado, comuna, cauce, coordenadas/polígono si existe, titular, vigencia y enlace al acto administrativo". Pide CSV, XLSX, GeoJSON o WFS; evita que el único resultado sean documentos escaneados.

## Control de calidad

- Incluye muchas escenas de bancos naturales de arena, crecidas, obras civiles, caminos y limpieza de cauces: son los falsos positivos importantes.
- Guarda imágenes antes/durante/después del caso, no una escena aislada.
- Divide entrenamiento y evaluación por cuenca y por fecha para evitar que el modelo memorice el paisaje.
- Conserva procedencia y licencia de cada archivo. No uses imágenes de Google Maps/Earth para entrenar salvo licencia explícita para ese uso.
