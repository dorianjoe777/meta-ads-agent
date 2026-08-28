# Pipeline reproducible: anuncio con fotografía real y overlay generado

Este documento describe la prueba realizada el 27 de agosto de 2026 con una
fotografía real de `Downloads/images.jpeg` (Rodeo - Car Detailing). La foto se
considera material protegido (`pixel_locked`): no se entrega a Image 2 para
que la reinterprete ni se permite que el modelo reconstruya el vehículo, la
persona, el producto o el resultado real.

## Objetivo y separación de responsabilidades

El resultado se divide en dos capas:

1. **Foto base real.** Se conserva la imagen original; sólo se escala y se
   recorta proporcionalmente para ajustarla al lienzo final.
2. **Overlay gráfico.** Image 2 genera una composición de diseño (formas,
   marcos, bandas, textura, títulos, subtítulos, texto publicitario y CTA)
   sobre un color croma uniforme. Después se retira el croma de forma
   programática y se compone la capa sobre la foto.

El logo oficial no lo genera Image 2. Se aplica después, programáticamente,
desde el archivo de marca aprobado. Así se conserva su geometría, ortografía,
color y proporción exactos. Image 2 sí puede proponer y dibujar títulos,
subtítulos, texto y CTA del diseño; aun así, antes de publicar deben mostrarse
al cliente para revisión y el texto final del anuncio debe conservarse aparte
como dato estructurado.

## Procedimiento exacto de la prueba

1. Se cargó `Downloads/images.jpeg` como imagen de referencia local y se
   mantuvo como fuente inmutable. No se editó ni se pasó por el modelo.
2. Se llamó a Image 2 Medium mediante el proveedor `openai-codex`, desde el
   canary. La instrucción pedía un diseño cuadrado para Rodeo, con estética
   negra/grafito/naranja cobrizo y un anuncio de detailing de alta gama.
3. La instrucción pidió explícitamente: fondo verde croma plano y uniforme,
   sin degradados ni sombras verdes; overlay publicitario solamente; dejar el
   centro utilizable para colocar una fotografía real; **no incluir logo**.
   El texto, título y CTA sí podían formar parte del diseño generado.
4. Image 2 devolvió un lienzo de `1254 x 1254`. La primera variante de
   “transparencia” no era transparencia real: dibujó un checkerboard y devolvió
   un PNG RGB opaco. Por ello no se usó como máscara.
5. Se tomó la variante con fondo verde y se ejecutó
   `remove_green_screen_background` de `src/codex_brand_guides.py` con los
   parámetros usados en esta prueba: `tolerance=70` y `edge_softness=50`.
   La función convierte a RGBA, calcula la dominancia verde sobre cada píxel,
   vuelve transparentes los píxeles que superan el umbral y suaviza los bordes
   próximos al umbral. También reduce el derrame verde en bordes
   antialiasados.
6. Se verificó que el resultado fuera PNG RGBA, con el centro transparente y
   elementos gráficos visibles. La capa quedó con aproximadamente **70,9 % de
   transparencia** y se guardó como:
   `output/prototypes/real-photo-overlay-20260827/rodeo-overlay-canary-image2-chroma-transparent.png`.
7. Se colocó la fotografía real debajo de esa capa, ajustándola
   proporcionalmente al lienzo. No hubo una segunda llamada a Image 2 para la
   foto. El compuesto principal se guardó como:
   `output/prototypes/real-photo-overlay-20260827/rodeo-composite-canary-image2-chroma.png`.
8. Se generó además una variante que conserva la dimensión nativa útil de la
   foto (`678 x 678`) para comprobar que el flujo no exige ampliar siempre la
   fotografía: `rodeo-composite-native-pixel-locked-v2.png`.

### Instrucción reproducible del overlay

La llamada no recibió la fotografía real ni el logo. Recibió únicamente una
instrucción de diseño equivalente a esta, junto con el contexto de marca:

```text
Crea solamente una capa gráfica cuadrada 1:1 para un anuncio premium de
Rodeo - Car Detailing. Usa negro, grafito y naranja cobrizo. Puedes crear el
título, subtítulo, texto breve y CTA. Mantén libre y visualmente útil la zona
central donde luego se colocará una fotografía real. El fondo debe ser verde
croma sólido #00FF00, completamente uniforme, sin degradados, sombras,
texturas ni reflejos verdes. No incluyas fotografía, vehículo, logo,
logotipo, isotipo ni imitación de marca. Devuelve solamente el overlay sobre
la placa croma.
```

El modelo fue `gpt-image-2-medium`, proveedor `openai-codex`, backend
`hermes-openai-codex`. Después de retirar el croma, la composición se hizo
localmente; la fotografía nunca volvió al modelo.

### Evidencia y huellas de la prueba

Los archivos de la prueba están bajo
`output/prototypes/real-photo-overlay-20260827/` (directorio local de
prototipos, no incluido en el producto):

- `rodeo-overlay-canary-image2-chroma-source.png`: salida RGB de Image 2 con
  placa verde.
- `rodeo-overlay-canary-image2-chroma-transparent.png`: overlay RGBA después
  de retirar el croma.
- `rodeo-composite-canary-image2-chroma.png`: fotografía real más overlay.

Huellas SHA-256 observadas:

```text
d5c30216ec849c07960755724a3a50b050a958b1a26550bc4ba50b76b93c21a6  images.jpeg
7810071ac83c0a3fa801e5d66ba53107efbfd9df6269678b117df692419445e7  rodeo-overlay-canary-image2-chroma-source.png
501506f9a2c0682b85314aa84a40c12e5f23efbfdc40443bea1498f190bddfd4  rodeo-overlay-canary-image2-chroma-transparent.png
4a81b75da08df94d6f03c8d9197e2e5d7b44061725991f58432a583330922ee7  rodeo-composite-canary-image2-chroma.png
```

## Verificaciones reproducibles

- El overlay debe reportar `RGBA` y no `RGB`; un archivo RGB no contiene alfa.
- El centro de la máscara debe tener alfa cero o casi cero; si el centro es
  opaco, la foto real quedará oculta.
- La foto base debe conservar su hash antes y después de la composición; sólo
  cambia el contenedor final, no el archivo fuente.
- El compuesto debe tener las dimensiones solicitadas y abrirse correctamente
  en un visor común.
- Debe comprobarse visualmente que no haya bordes verdes, recortes del sujeto,
  texto cortado ni deformación de la foto.
- Deben inspeccionarse por separado el overlay, la foto y el compuesto. Nunca
  se debe validar sólo la afirmación textual del modelo de que “la imagen está
  lista”.
- El logo colocado al final debe compararse con su archivo fuente: tamaño,
  relación de aspecto, colores, texto y transparencia.

## Por qué no se usa transparencia directa de Image 2

Aunque el modelo puede recibir instrucciones de fondo transparente, en esta
prueba interpretó la transparencia como un patrón visual de tablero y lo
codificó como píxeles normales en un PNG RGB. Ese checkerboard no es alfa y no
puede superponerse limpiamente. El croma uniforme permite medir y quitar el
fondo de forma verificable; no depende de que el modelo respete el canal alfa.

## Logo: referencia visual frente a aplicación exacta

Una imagen de `Downloads/logo.jpg` puede enviarse como referencia para que
Image 2 entienda el estilo, pero pedir “úsalo pixel por pixel” no garantiza una
copia exacta: el modelo puede volver a dibujar letras, cambiar proporciones,
alterar colores o inventar detalles. La prueba de fidelidad debe considerar
una salida de Image 2 como **inspiración**, no como activo oficial. El logo
oficial se debe insertar programáticamente después del overlay (idealmente
desde PNG/SVG con transparencia; si sólo existe JPG, debe prepararse una copia
de marca con fondo/transparencia controlados).

### Prueba estricta con `Downloads/logo.jpg`

Se hizo una llamada aislada real a `gpt-image-2-medium` por la misma ruta del
canary. El archivo `logo.jpg` se pasó como única referencia y se ordenó:
devolver una copia idéntica de `1254 x 1254`, conservar cada píxel, texto,
geometría, color, espaciado y fondo, y no redibujar ni reinterpretar nada.

La llamada terminó correctamente, pero el resultado fue **otro logo**: cambió
el isotipo central por un automóvil y un escudo grande, reemplazó la tipografía
y alteró composición, escala y colores. La salida quedó en
`output/prototypes/real-photo-overlay-20260827/logo-image2-reference-copy.png`.

Comparación decodificada contra el original:

- dimensiones: ambas `1254 x 1254`;
- píxeles RGB exactamente iguales dentro de la unión del contenido: **0,0069 %**;
- MAE dentro de esa región: **159,44/255**;
- IoU de las máscaras de contenido en el lienzo: **0,1030**;
- IoU aun normalizando ambos recortes a la misma escala: **0,1659**;
- PSNR del lienzo completo: **8,81 dB**.

El fondo blanco compartido infla cualquier porcentaje calculado sobre todo el
lienzo; por eso la decisión se toma sobre la región de contenido. Esta prueba
descarta la reproducción pixel por pixel mediante una referencia generativa.
Una referencia puede ayudar a aproximar el estilo, pero no constituye una
garantía de identidad de marca.

La garantía real es una operación de composición: Image 2 produce el diseño,
incluidos título, textos y CTA, con la instrucción explícita de omitir el logo;
el compositor inserta después el archivo oficial. Si se exige identidad literal
de cada píxel, el logo debe colocarse a escala 1:1. Si se redimensiona, deja de
ser identidad binaria de píxeles por el remuestreo, aunque sigue siendo una
transformación determinista del activo oficial y no un redibujo generativo.

## Puntos de dolor y fallbacks

- **Croma contaminado:** si la marca usa verde o la escena contiene mucho
  verde, cambiar el color de placa por un croma que no aparezca en la foto ni
  en el branding. El algoritmo actual es específicamente de fondo verde; no se
  debe aplicarlo ciegamente a otra placa.
- **Checkerboard/RGB:** rechazarlo y regenerar solicitando una placa croma
  plana; no intentar “arreglar” el tablero como si fuera alfa.
- **Texto ilegible o incorrecto:** pedir otra variante o corregir el texto
  posteriormente con un compositor tipográfico; el texto final debe aprobarlo
  el cliente.
- **Logo alterado:** descartar el logo generado y aplicar el archivo oficial
  por código.
- **Sujeto cortado o overlay opaco:** conservar la foto original y regenerar
  sólo el overlay; nunca regenerar la foto para arreglar una capa.
- **Fallo de Image 2:** informar el fallo real y conservar la foto; no afirmar
  que el creativo fue creado. Si existe una plantilla aprobada, usarla como
  fallback y componerla de forma local.

## Metadatos recomendados

Cada creativo compuesto debería registrar, separado del texto conversacional:

```json
{
  "pipeline": "real_photo_overlay",
  "photo_path": ".../images.jpeg",
  "photo_pixel_locked": true,
  "overlay_path": "...-transparent.png",
  "overlay_generator": "gpt-image-2-medium",
  "overlay_provider": "openai-codex",
  "overlay_background": "chroma_green",
  "remove_background": {
    "method": "deterministic_green_screen",
    "tolerance": 70,
    "edge_softness": 50
  },
  "logo_mode": "programmatic_official_asset",
  "copy_source": "model_proposal_pending_client_approval",
  "client_approved": false,
  "created_at": "2026-08-27"
}
```

Al aprobar el cliente, se actualizan únicamente los campos de aprobación y
las versiones exactas de título, texto, CTA y logo; no se sustituye la foto
real ni se marca como aprobado un archivo de una campaña anterior.
