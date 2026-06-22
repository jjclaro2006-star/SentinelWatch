# Validación de campo — Gaia v0.5.3 y v0.5.4

## Metodología
Validación manual de las top 50 alertas por confianza del set de validación.
Verificación visual coordenada por coordenada usando Google Maps satelital.
Criterio: señales claras de garimpo en el punto o inmediatamente adyacente.
Validador: Codex (OpenAI) con prompt estandarizado.

## Resultados — Gaia v0.5.3 (backbone congelado)

| Resultado | Cantidad | Porcentaje |
|---|---|---|
| ✓ garimpo visible | 41 | 82.0% |
| ✗ no hay garimpo | 8 | 16.0% |
| ? dudoso | 1 | 2.0% |

**Precisión confirmada: 41/50 = 82.0%**
**Excluyendo dudosos: 41/49 = 83.7%**

Errores más comunes: agricultura o caminos rurales confundidos con minería, sedimento natural de ríos, sabanas con suelo claro sin pozas mineras.

## Resultados — Gaia v0.5.1 (todo entrenable, referencia)

| Resultado | Cantidad | Porcentaje |
|---|---|---|
| ✓ garimpo visible | 39 | 78.0% |
| ✗ no hay garimpo | 6 | 12.0% |
| ? dudoso | 5 | 10.0% |

**Precisión confirmada: 39/50 = 78.0%**
**Excluyendo dudosos: 39/45 = 86.7%**

## Modelo validado
- Arquitectura: ViT-S/16 SSL4EO + MLP Linear(384→256→1)
- Datos entrenamiento: 5,451 imágenes AMW (492 positivos + 4,959 negativos)
- Backbone: congelado durante entrenamiento
- Threshold: 0.10 calibrado en campo
- Fecha validación: junio 2026
