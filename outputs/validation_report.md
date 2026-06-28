# SentinelWatch Public Case Validation

Generated: 2026-06-13

## Scope and Caveats

- Alert file used: `outputs/alerts_20260608.geojson`.
- Alerts loaded: `1642`.
- SentinelWatch alert footprint in this file is approximately lon `-75.495` to `-73.501`, lat `-4.999` to `-3.002`.
- Public reports often identify zones, communities, districts, or map hotspots rather than downloadable GPS points. Coordinates below are approximate centroids unless stated otherwise. INPE/BDQueimadas and NASA FIRMS were used as public fire-data reference systems, but this pass did not download per-detection fire pixels.
- A zero-match result for Colombia, Ucayali, Madre de Dios, or southern Peru should be read primarily as a coverage/footprint mismatch for this specific GeoJSON, not as evidence that SentinelWatch failed in those regions.

## Sources Used

- `maap222`: https://www.maapprogram.org/mennonites-deforestation-peru-amazon/
- `maap188`: https://www.maapprogram.org/tag/maap-188/
- `maap208`: https://www.maapprogram.org/category/countries/peru/
- `maap229`: https://www.maapprogram.org/amazon-deforestation-fire-hotspots-2024/
- `mongabay_fires`: https://es.mongabay.com/2025/07/incendios-forestales-afectaron-millones-hectareas-amazonia-2024/
- `fcds_nanay`: https://fcds.org.pe/noticias/loreto-detectan-primeros-casos-de-deforestacion-por-mineria-ilegal-en-el-rio-nanay/
- `mongabay_airstrips`: https://es.mongabay.com/specials/los-vuelos-de-la-muerte/
- `mongabay_atalaya`: https://es.mongabay.com/2024/11/droga-de-alto-vuelo-en-peru-comunidades-nativas-de-atalaya-viven-sitiadas-por-el-narcotrafico-y-mas-de-20-pistas-clandestinas/
- `devida2023`: https://www.gob.pe/institucion/devida/noticias/978259-peru-rompe-tendencia-creciente-de-cultivos-de-coca-en-2023
- `unodc_colombia2023`: https://www.unodc.org/unodc/press/releases/2024/October/colombia_-potential-cocaine-production-increased-by-53-per-cent-in-2023--according-to-new-unodc-survey.html
- `mongabay_ucayali_coca`: https://es.mongabay.com/2024/11/concesiones-de-alto-vuelo-pistas-de-aterrizaje-clandestinas-y-cultivos-de-coca-invaden-tierras-forestales-de-ucayali/
- `gfw_peru_fires`: https://www.globalforestwatch.org/dashboards/country/PER?category=fires
- `gfw_peru`: https://www.globalforestwatch.org/dashboards/country/PER
- `gfw_colombia`: https://www.globalforestwatch.org/dashboards/country/COL
- `nasa_firms`: https://firms.modaps.eosdis.nasa.gov/active_fire/
- `inpe_bdqueimadas`: https://terrabrasilis.dpi.inpe.br/queimadas/bdqueimadas/

## Deforestacion Ilegal

- Points evaluated: `8`
- Points with at least one SentinelWatch alert within 50 km: `1`
- Total point-alert matches within 50 km: `177`
- Overall minimum distance: `1.920 km`
- Median of point-level minimum distances: `465.328 km`
- Conclusion: Validaci?n parcial: hay coincidencias cerca de algunos puntos, pero muchos casos documentados est?n fuera del footprint o son zonas aproximadas.

| ID | Location | Date | Precision | Alerts <=50 km | Min km |
|---|---|---:|---|---:|---:|
| def_001 | Comunidad nativa Alvarenga / Alto Nanay, Loreto, Peru | 2024-04 | approx_named_place | 177 | 1.920 |
| def_002 | Tierra Blanca Mennonite colonies, Loreto, Peru | 2024-10 | approx_named_place_osm | 0 | 177.825 |
| def_003 | Chipiar / Padre Marquez, Loreto-Ucayali border, Peru | 2024-10 | approx_district_centroid_osm | 0 | 325.332 |
| def_004 | Masisea colony, Ucayali, Peru | 2024-10 | approx_district_centroid_osm | 0 | 446.617 |
| def_005 | San Jose de Karene native community, Madre de Dios, Peru | 2021-2024 | approx_named_place_osm | 0 | 929.160 |
| def_006 | Barranco Chico native community, Madre de Dios, Peru | 2021-2024 | approx_named_place_osm | 0 | 943.296 |
| def_007 | Chiribiquete / Yari-Yaguara II deforestation arc, Caqueta-Guaviare, Colombia | 2024 | approx_hotspot_centroid_from_report_map | 0 | 484.039 |
| def_008 | Tinigua National Park, Meta/Caqueta Amazon arc, Colombia | 2024 | approx_protected_area_centroid_osm | 0 | 617.866 |

## Incendios Provocados

- Points evaluated: `6`
- Points with at least one SentinelWatch alert within 50 km: `0`
- Total point-alert matches within 50 km: `0`
- Overall minimum distance: `177.825 km`
- Median of point-level minimum distances: `657.364 km`
- Conclusion: Sin coincidencias dentro de 50 km; la mayor?a de puntos cae fuera del footprint espacial del GeoJSON de SentinelWatch.

| ID | Location | Date | Precision | Alerts <=50 km | Min km |
|---|---|---:|---|---:|---:|
| fire_001 | Tierra Blanca Mennonite colonies, Loreto, Peru | 2023-2024 | approx_named_place_osm | 0 | 177.825 |
| fire_002 | Chipiar / Padre Marquez, Loreto-Ucayali border, Peru | 2023-2024 | approx_district_centroid_osm | 0 | 325.332 |
| fire_003 | Pucallpa/Calleria wildfire region, Ucayali, Peru | 2024-09 | approx_city_region_centroid | 0 | 382.632 |
| fire_004 | Guacamayo / mining corridor, Madre de Dios, Peru | 2024 | approx_named_place_osm | 0 | 932.095 |
| fire_005 | La Pampa, Madre de Dios, Peru | 2024 | approx_named_place_osm | 0 | 980.123 |
| fire_006 | San Ignacio de Velasco / northern soy frontier, Santa Cruz, Bolivia | 2024 | approx_regional_centroid | 0 | 1884.092 |

## Asentamientos Ilegales

- Points evaluated: `6`
- Points with at least one SentinelWatch alert within 50 km: `0`
- Total point-alert matches within 50 km: `0`
- Overall minimum distance: `177.825 km`
- Median of point-level minimum distances: `489.823 km`
- Conclusion: Sin coincidencias dentro de 50 km; la mayor?a de puntos cae fuera del footprint espacial del GeoJSON de SentinelWatch.

| ID | Location | Date | Precision | Alerts <=50 km | Min km |
|---|---|---:|---|---:|---:|
| settle_001 | Vanderland/Osterreich/Providencia Mennonite settlement complex near Tierra Blanca, Loreto, Peru | 2024 | approx_named_place_osm | 0 | 177.825 |
| settle_002 | Chipiar Mennonite colony, Loreto-Ucayali border, Peru | 2024 | approx_district_centroid_osm | 0 | 325.332 |
| settle_003 | Masisea Mennonite colony, Ucayali, Peru | 2024 | approx_district_centroid_osm | 0 | 446.617 |
| settle_004 | Raymondi district / Atalaya narco-airstrip cluster, Ucayali, Peru | 2024-11 | approx_district_area | 0 | 637.247 |
| settle_005 | Kakataibo indigenous reserve/concession zone, Ucayali-Huanuco, Peru | 2024-11 | approx_regional_centroid | 0 | 533.029 |
| settle_006 | Atalaya province, Ucayali, Peru | 2024 | approx_province_centroid_osm | 0 | 615.359 |

## Cultivos Coca

- Points evaluated: `8`
- Points with at least one SentinelWatch alert within 50 km: `0`
- Total point-alert matches within 50 km: `0`
- Overall minimum distance: `257.852 km`
- Median of point-level minimum distances: `431.870 km`
- Conclusion: Sin coincidencias dentro de 50 km; la mayor?a de puntos cae fuera del footprint espacial del GeoJSON de SentinelWatch.

| ID | Location | Date | Precision | Alerts <=50 km | Min km |
|---|---|---:|---|---:|---:|
| coca_001 | Bajo Amazonas / Mariscal Castilla, Loreto, Peru | 2023 | approx_zone_centroid | 0 | 335.446 |
| coca_002 | Yaguas production zone / Yaguas National Park landscape, Loreto, Peru | 2023 | approx_protected_area_centroid_osm | 0 | 257.852 |
| coca_003 | Calleria / Pucallpa, Ucayali, Peru | 2023 | approx_city_region_centroid | 0 | 382.632 |
| coca_004 | Aguaytia, Ucayali, Peru | 2023 | approx_zone_centroid | 0 | 454.773 |
| coca_005 | Tahuamanu, Madre de Dios, Peru | 2023 | approx_province_centroid_osm | 0 | 782.605 |
| coca_006 | Atalaya, Ucayali, Peru | 2024 | approx_province_centroid_osm | 0 | 615.359 |
| coca_007 | Puerto Asis / Putumayo coca zone, Colombia | 2023 | approx_municipality_centroid | 0 | 408.968 |
| coca_008 | Cartagena del Chaira / Caqueta coca-deforestation zone, Colombia | 2023 | approx_municipality_centroid | 0 | 484.886 |

## Overall Interpretation

The strongest spatial overlap in this alert file is for the northern Loreto/Nanay-side deforestation point near Alvarenga. Most other documented public cases are real and well-sourced, but fall outside the geographic extent of `alerts_20260608.geojson` (especially Ucayali, Madre de Dios, southern Peru, Bolivia, and Colombia). For a stronger multi-category validation, run SentinelWatch over AOIs covering each documented case cluster and repeat the same nearest-neighbor/50 km workflow.