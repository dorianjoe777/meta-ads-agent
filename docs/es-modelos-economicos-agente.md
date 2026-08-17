# Modelos económicos para el cerebro de Admira IA

Actualizado: 15 de julio de 2026.

## Decisión de producto

ChatGPT Go no debe recomendarse como cerebro principal de Admira IA. Su acceso a Codex puede agotarse con una cuota de larga duración y no permite comprar créditos adicionales. Puede mantenerse como conexión opcional para imágenes cuando esa capacidad esté disponible, pero no como la ruta recomendada para conversación, herramientas y cronjobs.

Para un comprador con presupuesto de USD 20/mes, ChatGPT Plus debe ser la recomendación general: incluye Codex y generación de imágenes dentro de la misma suscripción, aunque con límites separados. MiniMax M3 queda como alternativa para uso intensivo de texto/agente o para quien prefiera una cuota muy amplia y predecible. Admira debe priorizar conexiones oficiales del propio comprador. No se debe depender de OpenRouter ni revender o compartir credenciales entre compradores.

## Consumo real usado para comparar

El caso diagnosticado en una instalación real registró aproximadamente:

- 499,054 tokens de entrada nuevos;
- 1,715,712 tokens de entrada cacheados;
- 2,148 tokens de salida;
- 15 llamadas internas durante una sesión corta;
- cerca de 83,540 tokens de contexto en un mensaje simple.

Estas cifras no deben considerarse normales ni aceptables. La reducción del prompt y la carga de skills bajo demanda siguen siendo obligatorias, independientemente del proveedor elegido.

## Opciones recomendadas

### 1. ChatGPT Plus — recomendación general para la mayoría

- Precio oficial: USD 20/mes.
- Incluye ChatGPT, Codex y generación de imágenes.
- Las cuotas de imagen son independientes de la cuota Codex; agotar una no implica necesariamente agotar la otra.
- Algunos usuarios Plus pueden comprar créditos Codex adicionales cuando consumen la cuota incluida.
- Ventaja: una sola suscripción cubre conversación, herramientas de Admira y generación con Image 2.
- Riesgo: Codex continúa teniendo límites variables y el prompt excesivo de Admira puede consumirlos rápidamente; reducir el contexto sigue siendo obligatorio.
- Uso recomendado: opción predeterminada para autónomos y pequeñas empresas.

Fuentes: [ChatGPT Plus](https://help.openai.com/en/articles/6950777-what), [Codex con planes ChatGPT](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan), [créditos adicionales](https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-plus-pro).

### 2. MiniMax M3 — alternativa para uso intensivo del agente

- Integración actual: ya funciona en Admira mediante la API oficial compatible con OpenAI.
- Contexto: hasta 1M en el plan M3.
- Tool calling: disponible.
- Plan oficial Plus: USD 20/mes y aproximadamente 1.7B tokens M3 al mes.
- Pago por uso M3, contexto menor o igual a 512K: USD 0.30/M entrada, USD 1.20/M salida y USD 0.06/M cache leído.
- Ventaja: cuota grande, costo predecible y compatibilidad explícita con herramientas como OpenClaw.
- Desventaja frente a Plus: cuesta lo mismo y no proporciona la generación Image 2 de ChatGPT que ya utiliza Admira.
- Uso recomendado: comprador con mucho volumen de conversación, cronjobs o gestión de múltiples cuentas que agotaría Plus; puede mantener una conexión ChatGPT separada únicamente para imágenes.

Fuentes: [Token Plan de MiniMax](https://platform.minimax.io/subscribe), [API y modelos](https://platform.minimax.io/docs/api-reference/api-overview), [precios](https://platform.minimax.io/docs/pricing/overview).

### 3. DeepSeek V4 Flash — recomendación principal de pago por consumo

- API oficial compatible con OpenAI: `https://api.deepseek.com`.
- Modelo recomendado: `deepseek-v4-flash`.
- Contexto: 1M.
- Tool calling y JSON: disponibles.
- Precio oficial: USD 0.14/M entrada sin cache, USD 0.0028/M entrada con cache y USD 0.28/M salida.
- Estimación sobre la sesión real medida: aproximadamente USD 0.08.
- Ventaja: el costo más bajo encontrado para el volumen de contexto actual y cache automático muy económico.
- Riesgo a validar: calidad consistente de decisiones de marketing en español y fidelidad del tool calling durante flujos largos.

Fuente: [modelos y precios de DeepSeek](https://api-docs.deepseek.com/quick_start/pricing).

Para una recomendación centrada en calidad, también se debe probar `deepseek-v4-pro`. Mantiene contexto de 1M y tool calling; cuesta USD 0.435/M de entrada sin cache, USD 0.003625/M con cache y USD 0.87/M de salida. Sobre la sesión real medida costaría aproximadamente USD 0.23, todavía muy poco para un comprador individual.

Precaución técnica: el modo thinking de DeepSeek exige reenviar `reasoning_content` después de tool calls. No debe ofrecerse como preset hasta comprobar que la versión de Hermes instalada conserva correctamente ese campo. La primera prueba debe comparar Flash y Pro en modo no-thinking y luego validar thinking en un ciclo real de herramientas.

### 4. Gemini 3.1 Flash-Lite — alternativa económica y multimodal

- API oficial compatible con OpenAI: `https://generativelanguage.googleapis.com/v1beta/openai/`.
- Modelo recomendado: `gemini-3.1-flash-lite`.
- Function calling y entradas multimodales: disponibles.
- Precio oficial: USD 0.25/M entrada, USD 1.50/M salida y USD 0.025/M de cache.
- Tiene nivel gratuito, pero Google indica que los datos del nivel gratuito pueden usarse para mejorar sus productos. Para información real de clientes debe recomendarse el nivel pagado.
- Ventaja: costo bajo, buena ventana de contexto y capacidad multimodal.
- Riesgo a validar: diferencias de compatibilidad del wrapper OpenAI y comportamiento con todos los schemas de herramientas de Hermes.

Fuentes: [precios de Gemini](https://ai.google.dev/gemini-api/docs/pricing), [compatibilidad OpenAI](https://ai.google.dev/gemini-api/docs/openai).

### 5. OpenAI API GPT-5.4 mini — alternativa de mayor continuidad con OpenAI

- API oficial por consumo, separada de la cuota ChatGPT/Codex.
- Contexto: 400K.
- Function calling y herramientas: disponibles.
- Precio: USD 0.75/M entrada, USD 0.075/M entrada cacheada y USD 4.50/M salida.
- Estimación sobre la sesión real medida: aproximadamente USD 0.51.
- Ventaja: comportamiento cercano al que ya esperamos de la familia GPT y límites API explícitos.
- Desventaja: más costoso que DeepSeek, MiniMax y Gemini para el contexto actual.

Fuente: [GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini).

### 6. Groq con GPT OSS 120B — alternativa experimental después de adelgazar el contexto

- API compatible con OpenAI, tool calling y JSON disponibles.
- Precio: USD 0.15/M entrada y USD 0.60/M salida.
- Contexto: 131,072 tokens.
- Ventaja: muy rápido y económico.
- Bloqueo actual: el prompt observado de Admira ya usa unos 83.5K tokens antes de crecer la conversación. La ventana queda demasiado estrecha para operación confiable.
- Solo debe evaluarse después de reducir drásticamente el contexto base.

Fuentes: [precios de Groq](https://groq.com/pricing), [modelos](https://console.groq.com/docs/models), [tool use](https://console.groq.com/docs/tool-use/overview).

### 7. NVIDIA Build con GLM-5.2 — opción gratuita solo para pruebas

- Es la ruta que ya se utilizó en el laboratorio de demos de Admira.
- Base URL: `https://integrate.api.nvidia.com/v1`.
- Modelo: `z-ai/glm-5.2`.
- API compatible con OpenAI, contexto de 1M y capacidades de tool use.
- NVIDIA ofrece el endpoint alojado sin costo a miembros de su Developer Program para prototipado, desarrollo y pruebas.
- Los límites dependen del modelo y de la carga; el servicio gratuito puede tener esperas y no ofrece una garantía de producción.
- No debe venderse como proveedor gratuito permanente para manejar campañas reales. Sí puede servir para demos, evaluación del comprador y recuperación temporal.
- Autoalojar el NIM no es económico: la configuración oficial de GLM-5.2 requiere alrededor de 900 GB de memoria GPU agregada en hardware compatible.

Fuentes: [endpoint GLM-5.2](https://build.nvidia.com/z-ai/glm-5.2), [NIM para desarrolladores](https://developer.nvidia.com/nim), [condiciones de prototipado y producción](https://docs.api.nvidia.com/nim/docs/run-anywhere), [requisitos de GLM-5.2](https://catalog.ngc.nvidia.com/orgs/nim/zai-org/containers/glm-5.2/-).

Prueba directa del 15 de julio de 2026:

- autenticación y respuesta del endpoint: correctas;
- asesoría en español para una cafetería con USD 10/día: correcta, clara y proactiva;
- primera respuesta: 24.81 segundos;
- solicitud estructurada de herramienta `get_live_meta_campaigns`: correcta en 4.07 segundos;
- continuación después del resultado de herramienta: correcta en 19.45 segundos;
- interpretó una campaña activa, USD 8.40 de gasto, 7 mensajes y 3 leads calificados;
- calculó correctamente USD 2.80 por lead calificado y no inventó otras campañas;
- detalles a controlar con el prompt de Admira: usó una tabla Markdown, terminó con una pregunta opcional innecesaria y empleó un regionalismo mexicano. La infraestructura de Telegram ya normaliza tablas, pero el modelo necesita las reglas completas de tono y cierre ejecutivo.

## Opciones que no deben recomendarse como backend del producto

### ChatGPT Go

- Su acceso Codex es limitado y la duración exacta depende de la cuota del plan.
- Free y Go no pueden comprar créditos Codex adicionales; al agotarse deben esperar o actualizar el plan.
- No es suficiente para el prompt y los ciclos de herramientas actuales de Admira.

Fuentes: [Codex incluido en planes ChatGPT](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan), [créditos](https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-plus-pro).

### Z.AI GLM Coding Plan

- El plan Lite cuesta USD 18/mes y funciona con herramientas de coding.
- Sus términos prohíben utilizar la cuota en bots, aplicaciones, SaaS o backends propios sin acuerdo separado.
- Puede evaluarse la API general de pago por consumo, pero no debe ofrecerse la suscripción Coding Plan como conexión de Admira.

Fuentes: [planes GLM](https://z.ai/subscribe), [términos de suscripción](https://docs.z.ai/legal-agreement/subscription-terms).

### Alibaba/Qwen Coding Plan

- Está orientado a herramientas interactivas de programación.
- La documentación advierte que no debe usarse en scripts automatizados, backends personalizados o escenarios no interactivos.
- La API general de Model Studio sí puede evaluarse por consumo, pero el Coding Plan no debe presentarse como opción segura para Admira.

Fuentes: [Coding Plan](https://help.aliyun.com/en/model-studio/coding-plan), [FAQ y restricciones](https://help.aliyun.com/en/model-studio/coding-plan-faq).

## Orden recomendado para pruebas

1. Recomendar ChatGPT Plus como opción general cuando el comprador dispone de USD 20/mes.
2. Mantener MiniMax M3 como alternativa ya soportada para texto intensivo y agencias.
3. Añadir un preset oficial de DeepSeek V4 Flash y ejecutar la suite conversacional completa.
4. Añadir un preset oficial de Gemini 3.1 Flash-Lite pagado y ejecutar la misma suite.
5. Conservar OpenAI API GPT-5.4 mini como opción premium por consumo.
6. Mantener NVIDIA Build + GLM-5.2 como preset interno de prueba, claramente marcado como no apto para producción garantizada.
7. Evaluar Groq solamente después de bajar el contexto inicial muy por debajo de 50K tokens.

## Prueba obligatoria antes de ofrecer un proveedor

Cada modelo debe superar, usando Hermes real:

- conversación en español con un dueño sin experiencia en marketing;
- lectura live de campañas e insights de Meta;
- tool calling de varios pasos sin inventar ejecuciones;
- creación pausada y aprobación exclusiva para activar gasto;
- continuidad después de reset;
- cronjob con modelo fijado;
- recepción y análisis de imágenes/documentos;
- respuesta sin rutas internas ni mensajes técnicos innecesarios;
- 30 turnos continuos sin perder producto, oferta ni objetivo;
- medición real de tokens, costo, latencia, errores 429 y éxito de herramientas.

## Cambios de producto derivados

- Detectar `plan_type=go` y explicar que no es apropiado como cerebro principal.
- Recomendar ChatGPT Plus primero para uso general; ofrecer MiniMax para volumen intensivo y, tras validación, presets de DeepSeek y Gemini.
- Mantener ChatGPT separado para Image 2 cuando el cerebro principal sea otro proveedor.
- Mostrar gasto acumulado y una alerta configurable para las APIs de pago por consumo.
- Reducir AGENTS, schemas y skills cargadas inicialmente; cargar instrucciones especializadas solo cuando la tarea las requiera.
- No presentar ningún modelo como compatible solo porque acepta el protocolo OpenAI: debe superar la suite real de herramientas de Admira.
