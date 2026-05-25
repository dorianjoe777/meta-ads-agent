# Usar Codex para estrategia creativa y prompts de imagen

Esta parte es opcional. Viene apagada por defecto para proteger mejor una instalacion de comprador.

El manager IA principal conversa contigo, lee Meta Ads y prepara decisiones. Codex puede funcionar como un segundo cerebro creativo: ayuda a crear planes de marketing, prompts de imagen y variaciones visuales consistentes para tus anuncios.

La idea no es que tengas que usar Codex manualmente todos los dias. La idea es que el sistema tenga una memoria creativa clara para que, cuando pidas nuevos anuncios, el agente pueda apoyarse en Codex con buenas instrucciones.

## Que se instala

El instalador prepara la carpeta:

```text
brand_guides/
  general_branding.md
  products/
    nombre-del-producto.md
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

## Como usarlo dentro del dashboard

1. Abre `Creatividades`.
2. Busca `Guias de marca para Codex`.
3. Toca `Crear guias base`.
4. Escribe el nombre de tu producto principal.
5. El sistema crea los archivos iniciales.
6. Puedes editarlos con calma como documentos de texto.

Despues, cuando hables con el agente, puedes pedir:

```text
Prepara 3 conceptos visuales para mi producto principal usando mis guias de marca.
```

O:

```text
Necesito nuevos creativos para esta campana, manteniendo el mismo estilo visual de mi marca.
```

## Como debe pensar el agente

El agente debe usar Codex para tareas donde conviene pensar mas profundo:

- Planes de marketing.
- Sistemas de contenido.
- Prompts visuales consistentes.
- Variaciones de creativos.
- Adaptaciones por producto.
- Ideas para imagenes 1:1, 4:5 y 9:16.

El agente no debe improvisar una marca desde cero si ya existen guias. Primero debe leer la guia general y la guia del producto.

## Flujo recomendado

1. Completa el onboarding.
2. Deja lista la guia general de marca.
3. Crea una guia por cada producto importante.
4. Pide al agente que cree conceptos visuales.
5. Revisa las ideas.
6. Aprueba solo las que tienen sentido.
7. Usa esas piezas para preparar anuncios.

## Importante

Codex ayuda a pensar y crear, pero las acciones reales de Meta Ads siguen protegidas por las reglas del producto:

- Con supervision: el agente prepara y solo ejecuta la accion exacta que tu apruebas.
- Piloto automatico: el agente actua solo dentro de tus reglas.
- Campanas nuevas y creativos importantes pueden requerir aprobacion.

La creatividad puede ser rapida, pero el gasto real sigue protegido.
