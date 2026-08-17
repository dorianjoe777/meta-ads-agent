# Memoria de rentabilidad

La memoria de rentabilidad es el cerebro operativo del manager IA. No existe para escribir reportes bonitos. Existe para que el agente recuerde que recomendo, que se aprobo, que se ejecuto y que paso despues.

## Para que sirve

El comprador no deberia tener que repetir cada semana:

- cual es su CPA objetivo
- que ROAS considera sano
- cuanto gasto minimo necesita antes de juzgar una campana
- cuando prefiere pausar
- cuando prefiere observar
- cuando conviene refrescar creatividad
- que decisiones anteriores funcionaron o salieron mal

La memoria guarda ese criterio y lo vuelve parte del siguiente analisis.

## Archivos locales

- `dashboard/data/profitability_rules.json`: reglas de rentabilidad del negocio.
- `dashboard/data/decision_memory.json`: recomendaciones, evidencia, aprobaciones, ejecuciones y revisiones futuras.
- `dashboard/data/creative_experiments.json`: pruebas creativas activas, umbrales de evidencia, líder provisional y próxima revisión adaptativa.
- `dashboard/data/optimization_state.json`: modo observación/desbloqueado, cooldown, retraso de atribución, tope de cuenta, reserva de tests y resultados maduros.
- `dashboard/data/performance_history.json`: historia diaria de Meta por campaña, conjunto, anuncio y desgloses disponibles.
- `dashboard/data/business_outcomes.json`: agregados diarios de Shopify, sin datos personales ni IDs crudos de pedido.
- `dashboard/data/optimization_research.json`: guía oficial e hipótesis expertas/comunitarias con credibilidad y vencimiento.
- `output/learning-log.md`: aprendizaje humano-legible de lo que mejoro, empeoro o quedo igual.
- `brand_guides/`: contexto de marca, productos, ofertas e ideas de anuncios.

Hermes recibe copias curadas dentro de su workspace local:

- `memory/profitability_rules.json`
- `memory/decision_memory.json`
- `memory/creative_experiments.json`
- `memory/optimization_state.json`
- `memory/business_outcomes.json`
- `memory/optimization_research.json`
- `memory/learning_log.md`
- `brand_guides/general_branding.md`
- `brand_guides/products/*.md`
- `brand_guides/ad_briefs/*.md`

Asi el agente puede empezar un chat nuevo sin perder lo importante del negocio.

## Formato de decision

Cada recomendacion importante debe guardar:

1. senal detectada
2. diagnostico
3. accion sugerida
4. riesgo
5. resultado esperado
6. revision posterior de 24h, 3 dias y 7 dias

La memoria no debe guardar solo "dijo subir presupuesto". Debe guardar por que, bajo que regla, y que hay que mirar despues.

## Como debe hablar el agente

El agente debe sonar como manager, no como asistente generico:

> Hice el analisis. La senal principal es que esta campana esta gastando por encima de tu CPA objetivo y no esta recuperando ROAS. Mi sugerencia es bajar presupuesto o preparar una variante creativa. El riesgo de pausar ya es cortar aprendizaje si todavia hay pocos datos. Lo puedo dejar preparado ahora para que lo apruebes.

Formato ideal:

1. **Que vi**
2. **Que significa**
3. **Que haria**
4. **Que riesgo tiene**
5. **Lo puedo preparar ahora**

## Lo que mejora ROAS en la practica

No prometemos magia. Construimos disciplina operativa:

- revisar todos los dias
- reducir gasto evidente sin esperar semanas
- escalar ganadores con limites
- evitar tocar campanas por ansiedad
- refrescar creativos cuando hay fatiga
- guardar aprendizajes para mejorar el criterio del agente

La historia de venta correcta:

> El agente te vuelve mas presente, mas rapido y menos impulsivo con tus anuncios. Eso aumenta las probabilidades de mejorar resultados porque cada decision sale con evidencia, seguimiento y memoria.

## Reglas nuevas de seguridad y medición

- Cero conversiones significa CPA desconocido, no CPA 9999.
- Ventas usan CPA, ROAS, margen y Shopify; leads usan CPL; mensajes usan costo por conversación.
- No se toca una campaña durante aprendizaje, datos incompletos, atribución inmadura, datos viejos o cooldown después de un cambio.
- Frecuencia alta sola no demuestra fatiga. Debe existir deterioro relativo de CPA, CTR o CPC y contexto de entrega.
- El optimizador empieza observando. Solo puede desbloquearse después de 14 días, 10 resultados maduros y confirmación expresa del comprador.
- Se reserva parte del presupuesto para tests creativos y se respeta el tope total de la cuenta.
- Una líder por CTR no se declara ganadora de ventas. Las decisiones creativas exigen suficiente entrega, confianza y mejora material.
- Shopify es la verdad del negocio cuando está conectado. Una diferencia con Meta se investiga como atribución, Pixel/CAPI, deduplicación o retraso.
- La investigación de foros y Reddit solo crea hipótesis; nunca ejecuta cambios de gasto.
