# Admira IA handoff — Meta live, branding, estrategia integrada y contenido

Fecha: 2026-09-09  
Checkout: `.contabo-multitenant-work`  
Branch: `feat/contabo-multitenant`  
Base revisada: `e37545c`  
Estado al cerrar la auditoría: implementación local validada; construcción y rollout se registrarán al final.

Este documento reemplaza el handoff anterior. Resume lo que ya estaba hecho, lo que fue corregido al auditarlo y las validaciones reales y los pasos de rollout. La auditoría de Astra ya se ejecutó; este documento conserva el estado verificable de la implementación. No contiene credenciales ni API keys.

## 1. Resultado de la auditoría de Sol

Se conservaron los arreglos válidos de Sol y se corrigieron inconsistencias que impedían cumplir el flujo solicitado:

- Se mantuvo el contexto Meta actual por turno, con `last_30d` como lectura viva prioritaria.
- Se mantuvo el orden de branding antes de la revisión final.
- Se corrigieron instrucciones antiguas que todavía decían confirmar el negocio antes del branding o que describían una propuesta solo publicitaria.
- Se añadió compatibilidad para dashboards de prueba que no exponen el lector de historial anual.
- Se ampliaron los grupos de herramientas del runtime para que las nuevas herramientas no queden bloqueadas por el filtro de superficie: historial anual, Ads Library, búsqueda de assets y registro de propuestas orgánicas.
- Se corrigió un comentario/contrato que todavía describía cinco secciones cuando el plan ahora tiene siete.

No se reemplazó la clasificación semántica por filtros rígidos de palabras. Las decisiones siguen basadas en estado backend, contexto, herramientas y confirmaciones naturales.

## 2. Imagen que usan las cuentas nuevas

La verificación remota del entorno activo mostró:

- `ADMIRA_TENANT_IMAGE=admira-ia-hosted:r99-canary-fb1fd7e329a4`
- Workers del control plane activos: `admira-control-plane:r99-canary-8d829b42fe7a`.
- Broker de propuestas: `admira-ia-hosted:proposal-pool-0dcae21ac47d`.
- Dashboard de operadores: `admira-operator:onboarding-9114afc34c96`.

Por tanto, las cuentas nuevas se están creando actualmente con `r99-canary-fb1fd7e329a4`. Este es el estado previo a la promoción descrita al final del documento.

## 3. Meta vivo por turno y caché anual

### Ya implementado

- `src/admira_hermes_runtime_patch.py`, `src/admira_tool_bridge.py` y `dashboard/monitoring-dashboard.py` usan `date_preset=last_30d` para grounding ordinario.
- El fetch por turno es read-only (`persist=False`) y no cambia el rango visual seleccionado en el dashboard.
- Telegram y Agent Chat reciben `live_meta_sync`; una lectura fallida/parcial no se presenta como “Meta vacío” ni como desconexión sin evidencia.
- `src/meta_history_cache.py` implementa caché por cuenta/Página, TTL de 6 horas, cooldown de reintento de 5 minutos y refresco en background.
- El refresco anual usa exactamente los días cerrados de los últimos 365 días y `level=campaign`, evitando depender del inventario actual filtrado; así puede incluir campañas archivadas históricas.
- El digest anual calcula spend, impressions, clicks, CTR, CPC, conversions, leads, purchases, CPL, CPA, revenue y ROAS cuando existen. No suma reach entre campañas.
- Se conservan `as_of`, ventana, estado `fresh|stale|pending`, error de refresco y las principales campañas. El detalle paginado queda bajo `mcp_admira_get_meta_history_context`.
- El contexto compacto adjunta `meta_history`, pero el live de 30 días gana siempre en estado actual y decisiones.
- Si el refresco anual falla, se conserva el último digest bueno como stale; nunca se etiqueta como actual.

### Verificación y correcciones adicionales

- Se encontró y corrigió que Hermes descartaba `meta_history` tanto al recibir la herramienta como al compactar el contexto antes de inferir.
- La ventana anual usa la zona horaria de la cuenta; un límite de paginación ahora se marca parcial y nunca reemplaza la última caché completa. La reserva del worker evita duplicar refreshes; errores al lanzarlo conservan el contexto previo.
- Caché y ledger orgánico escriben mediante reemplazo atómico para que otro turno no lea JSON incompleto.
- Lectura real read-only de Dorian en contenedor aislado, datos montados solo lectura: Meta respondió `ok=true`, `partial=false`, ventana 2025-09-09 a 2026-09-08, zona America/New_York, 0 campañas con actividad y digest de 433 caracteres. Esta cuenta no permite comprobar campañas archivadas reales; esa inclusión sí está cubierta por pruebas del contrato de Insights.
- La caché evita repetir la consulta anual a Meta. El digest adjunto sí consume algo de contexto/tokens; almacenar información no hace que un modelo pueda conocerla sin leerla. El detalle completo se recupera solo a petición mediante herramienta.

## 4. Onboarding: branding antes de revisar y confirmar

El flujo implementado es:

`Facebook → Página/cuenta → descubrimiento de negocio → colores/estilo/tono/logo/referencias → revisión combinada de negocio + branding → confirmación natural → estrategia integrada`.

La revisión combinada incluye:

- negocio, oferta, clientes, diferenciadores, mercados, capacidad, precios, costos, objetivos y experiencia publicitaria;
- nombre de marca, colores, estilo, tono, logo/logo no disponible, activos reales, restricciones;
- cada referencia y los elementos exactos que el comprador quiere conservar.

El backend guarda un `brand_foundation_hash` junto a la presentación de revisión. Si el branding cambia, la confirmación anterior deja de coincidir; el compare-and-swap no permite confirmar una revisión vieja. `record_strategic_review_presented` y la transición de lifecycle rechazan una fundación desactualizada.

La confirmación sigue siendo semántica y natural; no depende de una frase mágica. El servidor sí exige que exista una presentación canónica actual para proteger la identidad de lo que se confirma.

## 5. Plan estratégico integrado de siete secciones

`src/strategic_plan_compiler.py` y el dashboard ahora usan:

1. Oportunidad publicitaria.
2. Audiencia y mensaje.
3. Campaña y conceptos creativos.
4. Presupuesto y medición.
5. Estrategia de contenido orgánico.
6. Plan diario y rotación orgánica.
7. Próximos pasos y preguntas.

El prompt exige una estrategia adaptada al nicho, sin imponer una mezcla universal de “tres posts”. Incluye pilares, cadencia, formatos, memoria de novedad de 15 días, uso de fotos reales frente a IA, baúles/vaults y una idea adicional inspirada en Ads Library.

La prioridad de proveedores para compilar es Gemini 3.7 Flash, luego Gemini 3.6 Flash, luego Gemini 3.5 Flash y después el pool conectado de ChatGPT/Codex. Gemini Lite no se usa para este compilador.

Los planes nuevos llevan `schema_version=2`. El pool central acepta la nueva operación firmada `admira_prepare_integrated_strategic_plan`; la operación antigua conserva su esquema de cinco campos para otros tenants durante el rollout. Los planes antiguos sin secciones orgánicas siguen siendo válidos y no se reabren silenciosamente; solo una revisión explícita del comprador puede crear un plan nuevo.

## 6. Assets, logo y vaults

- `extract_logo_background_to_transparency` elimina solo el fondo claro conectado al borde y conserva blancos internos del logo. Si la confianza es baja, mantiene el original.
- `save_content_asset` persiste `vault_name`, `content_group`, roles visuales, producto/servicio, aprobación y procedencia.
- Antes/después conserva ambos archivos con el mismo `vault_name` y `content_group`, usando `visual_role=before|after`.
- Para orgánico, el agente busca primero assets reales clasificados y aprobados en el vault pertinente. Si no existe uno apto, usa una imagen IA y nunca la presenta como foto real, testimonio real, cliente real o resultado real.
- `search_content_assets` permite recuperar por asset ID, vault, categoría, producto, procedencia, texto y aprobación de paid/daily.

Gemini 3.7 Flash produjo una propuesta real válida de siete campos en 2,59 segundos usando la conexión instalada de Dorian y un negocio ficticio de validación. No se escribieron datos del comprador ni se enviaron mensajes Telegram.

## 7. Historial semántico orgánico de 15 días

`src/organic_content_memory.py` registra cada propuesta antes de publicar, incluso si queda pendiente. Guarda draft ID, fecha, pilar, tema, oferta, hook, CTA, concepto visual, formato, vaults/asset IDs, caption y estado de publicación.

`src/hermes_bridge.py` inyecta una proyección acotada de los últimos 15 días. El prompt diario pide comparar semánticamente pilar, tema, oferta, hook, CTA, visual y formato; cerca de los días 12–15 permite reciclar solo con un cambio material. El historial no autoriza publicar: publicar sigue requiriendo aprobación separada.

Se corrigieron además: la pérdida de ruta de medios en actualizaciones de publicación con payload reducido; la identidad del draft al pasar por aprobación; la repetición deliberada de una pieza en otro día ahora crea nueva evidencia temporal. El cron pasa el draft ID original al staging. El prompt se reconcilia por hash aun si la hora no cambia, y se corrigieron llaves JSON sin escapar que impedían construirlo. La aceptación de la estrategia integrada permite guardar la cadencia orgánica sin pedir aprobar otra vez la misma dirección; una decisión posterior de declinar/pausar se respeta.

## 8. Idea diaria basada en Meta Ads Library

Se añadió `src/competitor_research.py` y la herramienta `mcp_admira_capture_ad_library_reference`:

- acepta únicamente una URL pública exacta de Facebook Ads Library con ID numérico;
- usa `agent-browser` para abrir, verificar URL, revisar snapshot y tomar screenshot;
- falla de forma cerrada ante login, challenge, redirección o creativo no visible;
- no inventa anuncios ni métricas privadas.

El cron diario debe producir una pieza competitiva extra solo si puede verificar el anuncio y su URL. La captura se guarda como `style_reference`, `reference_scope=task`, `reference_role=competitor_structure`, `preservation_mode=style_only`, sin aprobación de ads/daily. Image 2 recibe esa referencia únicamente para ángulo y estructura; las referencias de branding del comprador y su guía escrita siguen mandando. No se copian logo, nombre, colores propietarios, personas, claims, precio ni texto del competidor.

El creativo generado se guarda como `competitor_inspired_creative` con `creative_candidate_status=proposed`, `approved_for_ads=false` y la URL exacta. Solo una instrucción posterior del comprador puede promover el mismo candidato a `saved_for_paid` con `approved_for_ads=true`. La búsqueda posterior conserva la fuente de Ads Library junto a cada candidato.

El Dockerfile fija `agent-browser@0.20.0` y reutiliza el Chrome incluido por Remotion. Se descartó la instalación duplicada de Chrome: intentaba ejecutar sudo y usaba una ruta incorrecta. La capa corregida se construyó y ejecutó en Node 22.

La captura real del anuncio público 1044608904871305 se verificó visualmente. Se espera la carga del medio y se captura el elemento imagen/video dentro del modal que contiene el ID exacto; el archivo de referencia ya no incluye navegación de Facebook. Un video aporta solo un frame, no evidencia de su secuencia. El navegador recibe un entorno sin claves de los proveedores. Hermes dispone del mismo browser local para descubrir anuncios; no necesita un servicio de browser externo para esta ruta.

La captura/referencia y separación de branding están probadas. La calidad de una tanda autónoma completa y el éxito de Image 2 dependen además de disponibilidad del pool real.

## 9. Herramientas y superficie runtime

Se añadieron al catálogo, puente y registro de skills:

- `record_organic_content_proposal`
- `get_meta_history_context`
- `capture_ad_library_reference`
- `search_content_assets`

También se añadieron a los grupos runtime `organic`, `creative` e `insights` donde corresponde. El catálogo valida que definiciones y skill registry coincidan al importar.

## 10. Validación ejecutada

- Suite Linux con Hermes instalado: **1149 tests**, OK, 7 omitidos por sus condiciones de entorno. Se excluyó únicamente el método host-only que exige Docker Compose y `.env` del servidor desde dentro del contenedor; ese test pasa en el entorno local.
- Tras añadir compatibilidad del pool para tenants antiguos, encuadre del creativo, conservación de rechazos y repetición temporal: 46 tests focalizados de historial/branding y pool, OK. La suite completa se repetirá sobre el commit final.
- 26 assertions de integración del runner propio: branding antes de revisión, cron con 15 días/vaults, persistencia real de archivos, preparación/publicación orgánica con aprobación.
- `git diff --check` y compilación de módulos correctos.
- Meta anual real, Gemini 3.7 real de siete campos y captura visual pública reales verificados en contenedores aislados. No se publicaron anuncios/posts ni se enviaron mensajes Telegram.

La importación `agent.prompt_builder` que fallaba en el checkout local queda resuelta al ejecutar los tests en la imagen Linux con Hermes. Otra prueba de compositor requería crear `/app/output/creatives` en el contenedor de tests; el mismo supuesto falla en la imagen base sin cambios. El runner prepara ese directorio, sin modificar el producto para esconder la diferencia de entorno.

## 11. Promoción y comprobaciones finales

1. Crear commit inmutable, construir la imagen hosted, verificar etiquetas/manifiesto y repetir pruebas del artefacto.
2. Actualizar primero el pool central con compatibilidad simultánea de estrategias viejas y nuevas.
3. Actualizar el selector del provisioner y el compose de Dorian cuando no haya turno activo; conservar imágenes y configuración anteriores para reversión.
4. Verificar imagen efectiva del provisioner, arranque y herramientas del tenant, conservación del negocio/conexión/sesión y funcionamiento del browser.

No se ha simulado una conversación del comprador enviando mensajes en su nombre. Tampoco se ha publicado contenido en Meta para verificarlo. El cron completo con generación/entrega debe observarse en uso autorizado. El fallo histórico del pool (429/revocación) está documentado en `deploy/contabo/CONVERSATION_RECOVERY_20260909.md`; no atribuir una lectura Gemini vacía a cuota sin evidencia del proveedor.

El resultado exacto del rollout y sus referencias de reversión se añadirá aquí después de ejecutarlo.
