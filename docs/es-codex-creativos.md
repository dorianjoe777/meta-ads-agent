# Usar Codex para estrategia creativa y prompts de imagen

Esta parte es opcional. Viene apagada por defecto para proteger mejor una instalacion de comprador.

El manager IA principal conversa contigo, lee Meta Ads y prepara decisiones. Codex puede funcionar como un segundo cerebro creativo: ayuda a crear planes de marketing, prompts de imagen y variaciones visuales consistentes para tus anuncios.

La idea no es que tengas que usar Codex manualmente todos los dias. La idea es que el sistema tenga una memoria creativa clara para que, cuando pidas nuevos anuncios, el agente pueda apoyarse en Codex con buenas instrucciones.

## Que se instala

El producto incluye la estructura de memoria. Cuando guardas tu marca, un producto o un brief publicitario desde `Creativos`, crea localmente los documentos:

```text
brand_guides/
  general_branding.md
  products/
    nombre-del-producto.md
  ad_briefs/
    promo-o-anuncio-especifico.md
```

Si Codex CLI ya esta instalado, el producto lo detecta. El agente, las guias y el proveedor creativo siguen funcionando aunque no actives Codex.

En una instalacion avanzada puedes pedir que el instalador intente instalar Codex CLI usando:

```bash
INSTALL_CODEX_CLI=true ./scripts/install-local.sh
```

En esta version, Codex prepara el plan y el prompt visual. La imagen se genera despues con el proveedor creativo configurado en el producto. La generacion directa de una imagen mediante Codex/OpenAI todavia no forma parte del flujo confirmado de v1.

## Seguridad antes de activarlo

Codex CLI es un agente que corre localmente, no una simple caja de texto. Por eso el producto no lo activa automaticamente. Si decides usarlo, configura:

```env
CODEX_CREATIVE_ENABLED=true
CODEX_CLI=codex
```

El producto lo ejecuta en una carpeta temporal, en modo de solo lectura, sin reglas locales ni conversacion persistente. Aun asi, mientras una herramienta local pueda inspeccionar el equipo, debes considerarla una funcion avanzada y activarla solo en una instalacion que controlas.

## Guia general de marca

`brand_guides/general_branding.md` describe la marca completa:

- Nombre de marca.
- Categoria.
- Que vende.
- Promesa principal.
- Cliente ideal.
- Colores.
- Tono.
- Estilo visual.
- Palabras que si usa.
- Palabras que evita.
- Reglas para imagenes.

Esta guia evita que cada creativo se vea como si fuera de una marca diferente.

En la licencia Agencia, estas guias quedan separadas por espacio de cliente. Cuando cambias de cliente, el agente usa las guias de esa marca, no las del cliente anterior.

## Guia por producto

Cada producto, servicio u oferta debe tener su propio archivo en:

```text
brand_guides/products/
```

Ejemplos:

```text
brand_guides/products/curso-de-fitness.md
brand_guides/products/mentoria-de-ventas.md
brand_guides/products/kit-de-skincare.md
```

Cada guia de producto debe incluir:

- Nombre del producto.
- Link.
- Precio o rango.
- Para quien es.
- Problema que resuelve.
- Objeciones frecuentes.
- Angulos de anuncios.
- Frases fuertes permitidas.
- Frases que se deben evitar.
- Prompt base del producto.

## Brief publicitario

La guia de marca y la ficha de producto explican el negocio. Pero los anuncios reales necesitan una capa mas concreta: el brief publicitario.

Un brief publicitario puede representar:

- Una promocion puntual.
- Una campana especifica.
- Un conjunto de anuncios especifico.
- Un anuncio ganador que quieres variar.
- Un test donde solo quieres cambiar colores, fondo, titular, encuadre, prueba social u otro elemento.

Cada brief debe dejar claro:

- Producto u oferta relacionada.
- Campana, conjunto de anuncios y anuncio base si existen.
- Promocion o idea puntual.
- Segmento de audiencia.
- Que ya funciona del anuncio.
- Que no debe cambiar.
- Ventana creativa: que si puede probar el agente.
- Cantidad de variaciones.
- Hipotesis que quieres validar.

Ejemplo de ventana creativa:

```text
Mantener el copy, la oferta y el testimonio. Probar 4 variaciones cambiando solo paleta de color, fondo y encuadre del producto.
```

Esto evita que el agente invente demasiado cuando lo que necesitas es mejorar un anuncio que ya funciona.

## Como usarlo dentro del dashboard

1. Abre `Creativos`.
2. En `Memoria creativa`, toca `Configurar memoria`.
3. Completa primero la esencia de tu marca: qué vendes, cliente ideal, estilo visual, voz y límites.
4. Toca `+ Producto` y crea una ficha por cada producto, servicio u oferta que anuncies.
5. Toca `Nuevo brief` para aterrizar una promocion, campana, conjunto de anuncios o anuncio ganador.
6. Define la `Ventana creativa para variantes`: que puede cambiar el agente y que debe permanecer igual.
7. Si no quieres llenar todo manualmente, conversa con el manager y pide que complete el brief contigo.
8. En un brief guardado, toca `Crear variaciones` para generar propuestas usando exactamente esa memoria.

No necesitas buscar ni editar archivos manualmente. La interfaz guarda por detrás `general_branding.md`, una ficha Markdown por producto y un Markdown por brief publicitario para que esa memoria sea local, respaldable y legible por el agente.

Cuando un lote creativo usa una ficha o un brief, la biblioteca lo etiqueta con el producto y el brief correspondiente. Así puedes distinguir ideas generales de producto vs variaciones de un anuncio real.

## Guardado de imagenes

Las imagenes generadas en `Creativos` quedan guardadas localmente en tu PC o VPS. Como un droplet pequeno suele traer espacio suficiente para empezar, el producto no borra tus creativos automaticamente.

Si quieres conservar una imagen fuera del producto, toca `Descargar` y guardala en tu carpeta de marca, Google Drive, Dropbox o donde organices tus archivos.

Si algun dia tu equipo o droplet se queda corto de espacio, entra a `Creativos` y usa `Limpiar borradores`. Esa limpieza borra solo imagenes generadas que todavia no elegiste para anuncios.

Hay una excepcion importante: cuando eliges una imagen y la preparas para crear un anuncio, esa imagen queda marcada como pieza de anuncio y no se borra con la limpieza de borradores. La idea es simple:

- Imagen exploratoria: queda guardada localmente mientras no limpies borradores.
- Imagen que te gustó: descargala.
- Imagen elegida para anuncio: queda protegida en la instalacion como pieza de anuncio.

Despues, cuando hables con el agente, puedes pedir:

```text
Prepara 3 conceptos visuales para mi producto principal usando mis guias de marca.
```

O:

```text
Necesito nuevos creativos para esta campana, manteniendo el mismo estilo visual de mi marca.
```

O:

```text
Este anuncio esta funcionando. Crea 5 variantes cambiando solo colores y fondo, manteniendo el copy y la oferta.
```

## Como debe pensar el agente

El agente debe usar Codex para tareas donde conviene pensar mas profundo:

- Planes de marketing.
- Sistemas de contenido.
- Prompts visuales consistentes.
- Variaciones de creativos por producto, campana, conjunto de anuncios o anuncio base.
- Adaptaciones por producto.
- Ideas para imagenes 1:1, 4:5 y 9:16.

El agente no debe improvisar una marca desde cero si ya existen guias. Primero debe leer la guia general, luego la guia del producto y finalmente el brief publicitario cuando el pedido sea de un anuncio o test especifico.

## Flujo recomendado

1. Completa el onboarding.
2. Deja lista la guia general de marca.
3. Crea una guia por cada producto importante.
4. Crea un brief por promocion, campana, conjunto o anuncio ganador.
5. Pide al agente que cree variaciones dentro de la ventana permitida.
6. Revisa las ideas.
7. Aprueba solo las que tienen sentido.
8. Usa esas piezas para preparar anuncios.

## Importante

Codex ayuda a pensar y crear, pero las acciones reales de Meta Ads siguen protegidas por las reglas del producto:

- Con supervision: el agente prepara y solo ejecuta la accion exacta que tu apruebas.
- Piloto automatico: el agente actua solo dentro de tus reglas.
- Campanas nuevas y creativos importantes pueden requerir aprobacion.

La creatividad puede ser rapida, pero el gasto real sigue protegido.
