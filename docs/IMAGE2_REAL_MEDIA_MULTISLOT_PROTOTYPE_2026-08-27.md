# Image 2 con fotografías reales: prototipo multislots

Fecha: 2026-08-27

Estado: prototipo aislado verificado el 27 de agosto e incorporado después al MCP canary. La integración conserva sin cambios el proveedor, autenticación, modelo, timeout, fallback y runtime de Image 2.

Implementación canónica:

- esquema MCP: `src/admira_mcp_server.py`, herramienta existente `codex_image_generate`;
- orquestación: `dashboard/monitoring-dashboard.py`, rama activada únicamente cuando el modelo principal envía `real_media`;
- composición determinista: `src/hybrid_image_compositor.py`;
- skill del agente: `agent/skills/creative-production-codex-image/`;
- pruebas: `tests/test_codex_image_mcp_schema.py`, `tests/test_hybrid_image_compositor.py` y `tests/test_hybrid_image_dashboard_integration.py`.

No se creó un segundo MCP y no se alteró `call_codex_image_cli`: el mismo bridge que ya funcionaba genera sólo el overlay. La rama normal permanece intacta para creativos que no contienen `real_media`.

## Objetivo

Permitir que Image 2 diseñe libremente la pieza gráfica, incluyendo textos, jerarquía, CTA, formas, marcos y branding, sin alterar las fotografías reales del cliente. Las fotos y el logo se insertan después de forma programática.

La parte creativa sigue siendo dinámica. La parte determinista se limita a:

- vincular cada fotografía real con su espacio correcto;
- comprobar que todos los espacios existan y no se mezclen;
- reemplazar cromas por los archivos originales;
- colocar el logo original con fidelidad;
- rechazar un overlay técnicamente inválido antes de entregarlo.

No se añade un filtro determinista para interpretar la conversación ni una aprobación obligatoria del brief visual.

## Contrato mínimo recomendado

```json
{
  "schema_version": "image2-overlay.v1",
  "request_id": "uuid",
  "layout_intent": "before_after|services|collage|freeform",
  "visual_direction": "instrucciones naturales acordadas entre agente y cliente",
  "text_content": {
    "title": "...",
    "subtitle": "...",
    "cta": "...",
    "labels": ["ANTES", "DESPUÉS"]
  },
  "branding": {
    "colors": ["#0B5D3B", "#8BC34A", "#FFFFFF"],
    "logo_asset_id": "opcional"
  },
  "real_media": [
    {
      "slot_id": "before",
      "asset_id": "tenant-media-id",
      "role": "before",
      "label": "ANTES",
      "sha256": "opcional"
    }
  ],
  "style_reference": {
    "mode": "none|pool|explicit",
    "asset_id": "obligatorio sólo cuando mode=explicit"
  }
}
```

`real_media` es una lista ordenada y autoritativa. El compositor usa `slot_id`, `asset_id` y el hash del archivo; nunca adivina por semejanza visual ni por orden de nombres.

## Referencias de diseño: sólo bajo petición explícita

- El valor predeterminado y cuando se omite el campo es `style_reference.mode = none`.
- `pool` sólo se envía cuando el modelo principal entendió naturalmente que el usuario pidió usar sus referencias gráficas guardadas.
- `explicit` usa la referencia concreta solicitada por el usuario y prevalece sobre el pool.
- El pool usa una bolsa barajada: cada referencia elegible se usa una vez antes de volver a barajar y se evita la repetición inmediata.
- Fotografías reales y logos nunca son elegibles como referencias de estilo.
- No existe un detector oculto por palabras clave. El modelo principal interpreta la conversación y entrega el valor semántico al MCP.

Las cinco generaciones reales de esta prueba usaron `mode = none`: no se envió ninguna foto, logo ni referencia de estilo a Image 2.

## Flujo probado

1. El modelo principal convierte la conversación natural en el contrato anterior.
2. El MCP elige un croma saturado distinto para cada `slot_id`.
3. Los cromas se seleccionan fuera de las familias de matiz usadas por el branding y suficientemente separados entre sí.
4. Image 2 recibe el brief visual, los textos y la asignación exacta `croma → slot`, pero no recibe las fotos reales ni el logo.
5. El overlay generado se valida con tolerancia de color porque Image 2 puede aproximar el RGB solicitado.
6. Se exige un componente conectado válido por slot, área suficiente, cero solapamiento y ausencia de componentes extra relevantes.
7. Una limpieza espacial estrecha recupera el antialias del borde sin tocar elementos gráficos alejados.
8. Cada foto original se recorta en modo `cover` y se inserta únicamente en el componente de su slot.
9. El logo original se añade programáticamente en la variante de color elegida.
10. Se guarda evidencia con hashes del overlay, fuentes y salida, más el mapa de slots.

## Pruebas reales con el proveedor activo

Proveedor y modelo observados en las cinco llamadas: `hermes-openai-codex`, `gpt-image-2-medium`. Se usó el bridge actual sin modificarlo.

| Caso | Fotos | Resultado | Evidencia técnica |
|---|---:|---|---|
| Antes/después | 2 | PASS | un componente por slot, 0 solapamientos, 0 residuos RGB fuera de máscara |
| Dos servicios diferentes | 2 | PASS | faros y pulido conservaron su asociación correcta |
| Collage de servicios | 4 | PASS | pintura, motor, faros e interior conservaron orden, etiqueta y archivo |
| Branding verde | 2 | PASS | se usaron magenta y naranja; el verde de marca permaneció intacto |
| Variación del mismo antes/después | 2 | PASS | composición materialmente distinta, mismas fotos y semántica correctas |

Las cuatro composiciones corregidas usan limpieza de borde espacial y registran:

- `mask_overlap_pixels = 0`;
- `remaining_key_pixels_outside_masks = 0`;
- `component_count = 1` para cada slot;
- `meaningful_extra_component_count = 0`;
- todos los slots y casos con `pass = true`.

La segunda variación del antes/después difiere en 99,75 % de sus píxeles respecto de la primera. La primera usa dos paneles inclinados de tamaño semejante; la segunda usa una ventana protagonista grande y otra compacta. Esto demuestra que no hay una plantilla visual fija.

## Selección de cromas con branding verde

El selector por matiz se probó con 2, 4 y 6 slots:

| Slots | Separación mínima frente al verde de marca | Separación mínima entre cromas | Resultado |
|---:|---:|---:|---|
| 2 | 111,03° | 76,47° | PASS |
| 4 | 72,21° | 38,82° | PASS |
| 6 | 60,74° | 29,41° | PASS |

Esto evita usar verde, lima o un cian cercano cuando esas familias forman parte del branding. Los colores de las fotografías fuente no producen conflicto porque la detección se ejecuta sobre el overlay antes de insertar las fotos.

## Evidencias y artefactos

- Prompts reales: `output/prototypes/multislot-chroma-real-20260827/prompts.json`
- Overlays de Image 2: `output/prototypes/multislot-chroma-real-20260827/overlays/`
- Especificaciones de slots: `output/prototypes/multislot-chroma-real-20260827/spec-*.json`
- Composiciones con borde corregido: `output/prototypes/multislot-chroma-real-20260827-v2/composites/`
- Evidencia por composición: `output/prototypes/multislot-chroma-real-20260827-v2/evidence/`
- Prueba del selector de cromas: `output/prototypes/multislot-chroma-20260827/key-color-self-test.json`
- Harness aislado: `scripts/prototypes/multislot_chroma_harness.py`

## Límites observados

- Image 2 no siempre devuelve exactamente el RGB solicitado; hace falta detección tolerante y por matiz.
- Tesseract no leyó de forma confiable toda la tipografía estilizada. OCR tradicional no debe bloquear una pieza que visualmente está bien. Puede generar una advertencia y dejar la revisión estética/textual al usuario.
- Un verificador visual con Luna puede añadirse como QA opcional, pero no es necesario para vincular fotos, validar máscaras o componer la pieza.
- Si falta un slot, hay máscaras solapadas, aparece contaminación relevante o no se puede resolver un `asset_id`, el overlay debe descartarse y regenerarse. Esto es aceptación técnica de salida, no una restricción conversacional.

## Conclusión

El enfoque es viable como un MCP normal invocado por Hermes, incluso cuando el cerebro principal sea Gemini Flash Lite. No hace falta iniciar un runtime completo de Codex para coordinar la composición. Se conserva la llamada existente a Image 2 para generar el overlay; el MCP realiza el mapeo y la composición determinista después.
