# Catastro de Depósitos de Relaves de Chile — octubre de 2025

## Fuente y descarga

La URL histórica indicada para el catálogo (`https://www.sernageomin.cl/datos-publicos-deposito-de-relaves/`) devolvía HTTP 404 al verificarse el 24 de junio de 2026. Se utilizó la publicación geoespacial oficial vigente de SERNAGEOMIN, cuyo metadato declara actualización a octubre de 2025:

- Puntual: `https://services1.arcgis.com/OyjvVdFTl5hfSdX3/arcgis/rest/services/CDR_CHILE_PUNTUAL_2025/FeatureServer/0`
- Areal: `https://services1.arcgis.com/OyjvVdFTl5hfSdX3/arcgis/rest/services/CDR_CHILE_AREAL_2025/FeatureServer/0`

Los GeoJSON son extracciones directas de esos servicios, en WGS 84 (EPSG:4326). El servicio contiene 839 registros en ambas capas.

## Archivos

- `CDR_CHILE_PUNTUAL_2025.geojson`: descarga puntual directa del servicio oficial.
- `CDR_CHILE_AREAL_2025.geojson`: descarga poligonal directa del servicio oficial.
- `CDR_CHILE_PUNTUAL_2025.csv`: versión tabular derivada de la capa puntual.
- `CDR_CHILE_PUNTUAL_2025.{shp,shx,dbf,prj}`: exportación shapefile WGS 84 de la capa puntual.
- `CDR_CHILE_PUNTUAL_2025.kml`: exportación KML compatible con Google Earth de la capa puntual.
- `CDR_CHILE_PUNTUAL_2025_field_mapping.json`: mapea los nombres originales a los nombres DBF, que se limitan a diez caracteres.
- `relaves_proximity_screening_hydrorivers_worldpop2020.csv`: cribado de proximidad, no una evaluación de riesgo.
- `relaves_satellite_spotcheck_5.csv`: revisión visual de cinco muestras aleatorias en Google Maps satelital.

## Cribado de proximidad

Las distancias a ríos usan HydroRIVERS v10 (South America). Las zonas habitadas son celdas de WorldPop 2020 de 1 km con al menos 50 personas. Se trata de una pantalla espacial: no representa conectividad hidrológica, población expuesta, dirección de flujo ni riesgo de falla.
