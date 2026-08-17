# Canary exhaustivo de creación de campañas Meta

El runner `scripts/exhaustive_campaign_canary.py` valida el contrato antes de
hacer llamadas de escritura y, cuando se autoriza explícitamente, ejecuta
escenarios reales siempre en `PAUSED`.

## Capas

- `--layer contracts`: 128 combinaciones deterministas sin Graph writes.
- `--layer negative`: bloqueos obligatorios sin mutar Meta.
- `--layer briefs`: 30 briefs en lenguaje natural; exige que el JSON conserve
  objetivo, presupuesto, audiencia, ubicaciones, placements, copy, CTA, media,
  destino y estado. Si el proveedor principal devuelve 429, hace un único
  intento con `--brief-fallback-model` y mantiene allí la corrección de JSON.
  También escala una sola vez si el proveedor principal sigue cambiando una
  decisión tras la corrección; no entra en bucles ni convierte un 429 o una
  respuesta incompleta en un aprobado.
- `--layer live --confirm-live-paused-canary`: 60 escenarios reales, resumibles
  y verificados mediante lectura posterior desde Meta.

El runner usa una matriz reproducible de 12 ventas web, 8 tráfico, 6 awareness,
8 interacción/video, 10 mensajes, 8 formularios, 4 posts existentes y 4
app/catálogo. Crea fixtures multimedia locales, registra requested-versus-
actual, conserva códigos/subcódigos/`fbtrace_id` redactados y elimina cada
campaña salvo un keeper por familia compatible.

## Seguridad operacional

- Nunca acepta tokens por argumentos ni los escribe en reportes.
- Rechaza intereses/localidades que no provengan del catálogo actual de Meta.
- Rechaza `INSTAGRAM_EXPLORE` manual, Advantage+ incompatible con edades y
  géneros no interpretables antes de crear objetos.
- Si Meta devuelve rate limit `80004/2446079`, detiene nuevas mutaciones y deja
  la limpieza pendiente para un reintento posterior seguro.
- La aceptación de las Condiciones de generación de clientes potenciales
  (`1815089`) y la ausencia de actores/catálogos se reportan como bloqueos de
  capacidad esperados, no como éxitos silenciosos.
- Una excepción o fallo parcial limpia los objetos pausados que sí llegaron a
  crearse; no deja IDs reutilizables obsoletos.

## Ejecución resumible

```text
python3 scripts/exhaustive_campaign_canary.py --layer contracts
python3 scripts/exhaustive_campaign_canary.py --layer negative
python3 scripts/exhaustive_campaign_canary.py --layer briefs --brief-delay-seconds 20 \
  --brief-fallback-model minimaxai/minimax-m3
# Para aislar calidad/latencia de un modelo concreto:
python3 scripts/exhaustive_campaign_canary.py --layer briefs \
  --brief-primary-model deepseek-ai/deepseek-v4-flash-0731 \
  --brief-fallback-model minimaxai/minimax-m3
python3 scripts/exhaustive_campaign_canary.py --layer live \
  --run-id YYYYMMDD-meta60 --start 1 --stop 60 \
  --confirm-live-paused-canary
```

Los artefactos (`manifest.json`, `contracts.json`, `negative-contracts.json`,
`briefs.json`, `live-report.json`, `assets.json` y `summary.md`) se guardan en
el directorio indicado por `--output-root`. No se publica una versión estable
hasta que el informe final y la suite completa sean revisados.
