# Espia Creativo

Espia Creativo es el modulo para convertir anuncios fuertes del mercado en ideas originales para la marca del comprador.

No debe venderse como "inspiracion" tibia. Tampoco debe venderse como copiar o plagiar anuncios. El punto fuerte es mas claro:

> Roba la estrategia, no el anuncio.

## Promesa

El agente analiza anuncios de otros negocios para detectar la estructura que los hace fuertes:

- gancho
- emocion
- oferta
- colores
- prueba social
- ritmo visual
- CTA
- posible audiencia

Luego crea una version original para la marca del comprador, respetando sus productos, estilo y reglas.

## Nombres y copy

Nombre recomendado:

**Espia Creativo**

Tagline:

**Roba la estrategia, no el anuncio.**

Botones posibles:

- **Analizar anuncio ganador**
- **Espiar y remezclar**
- **Crear mi version**
- **Guardar como referencia fuerte**

Frase comercial:

> Si un anuncio ya esta llamando la atencion en tu mercado, no empieces desde cero. El agente detecta la jugada creativa y la convierte en una pieza original para tu producto.

## Implementacion segura para v1

No construir scraper propio todavia. Para v1:

1. El comprador pega un link publico de Meta Ad Library o sube una captura.
2. Hermes analiza visualmente la referencia.
3. El agente extrae patron creativo, no copia exacta.
4. Codex/imagen genera variantes originales usando `brand_guides/` y `ad_briefs/`.
5. El resultado queda como borrador y, si se quiere usar en Meta, pasa por aprobacion.

## Que debe evitar

- No copiar imagenes exactas.
- No copiar textos exactos.
- No prometer que un anuncio funcionara solo porque se parece a otro.
- No mezclar el analisis creativo con la memoria de rentabilidad. La memoria puede decir "necesitamos refrescar creatividad"; Espia Creativo resuelve "que tipo de creatividad probamos".

## Como se conecta con la memoria

La memoria de rentabilidad detecta problemas:

- fatiga
- CPA subiendo
- CTR cayendo
- ganador que necesita variantes

Espia Creativo responde con ideas:

- nuevos angulos
- variaciones visuales
- referencias transformadas
- prompts para imagen
- briefs listos para aprobar
