# Iniciativa futura: canales de Telegram por cliente para agencias

Esta nota documenta una idea para una versión futura de Admira orientada a agencias que manejan varios clientes. No describe una funcionalidad actual; debe tratarse como dirección de producto para una fase posterior.

## Idea principal

En la versión de agencias, cada espacio o cliente podría tener su propio canal de Telegram conectado a una versión del agente preparada para comunicación con ese cliente.

La agencia seguiría usando Admira como manager operativo de Meta Ads para todos sus clientes, pero podría habilitar, por cliente, un canal de comunicación separado donde el cliente recibe información útil sin entrar al dashboard principal de la agencia.

Ejemplo:

- Agencia: maneja varios clientes desde Admira.
- Cliente A: tiene su propio canal de Telegram conectado a su cuenta/campañas.
- Cliente B: tiene otro canal independiente.
- El agente sabe qué cliente, cuenta, campañas, reglas y memoria corresponden a cada canal.

## Qué recibiría el cliente

El canal del cliente podría recibir:

- resumen diario programado de resultados;
- alertas importantes cuando algo necesite atención;
- avisos cada ciertos días clave del ciclo de optimización;
- explicación simple de qué está pasando con sus campañas;
- respuestas a preguntas generales del cliente sobre resultados, gasto, leads, mensajes, ventas o próximos pasos.

La idea es que el cliente tenga visibilidad y tranquilidad sin necesitar aprender el dashboard ni pedir reportes manuales a la agencia.

## Qué recibiría la agencia

La agencia también debería recibir las alertas importantes, especialmente cuando:

- una campaña se desvíe del objetivo;
- un creativo muestre fatiga;
- haya cambios fuertes de costo por resultado;
- se acerque una fecha de decisión de un test;
- el cliente pregunte algo importante;
- el cliente deje feedback que pueda afectar estrategia, oferta o creatividad.

En eventos críticos, ambos lados deberían recibir notificación:

- cliente: explicación simple y clara;
- agencia: contexto operativo y sugerencia de acción.

## Cronjobs por cliente

Cada cliente podría tener cronjobs propios, por ejemplo:

- resumen diario en la hora local del cliente;
- revisión de tests creativos cada X días;
- revisión semanal de aprendizaje y presupuesto;
- alertas inmediatas cuando se cumplan reglas importantes;
- recordatorios para confirmar eventos, leads o feedback relevante.

Estos cronjobs deben estar ligados al espacio del cliente, no a toda la agencia.

## Feedback del cliente como memoria útil

Una extensión futura de esta idea sería permitir que el agente recoja feedback del cliente desde su canal de Telegram y lo muestre a la agencia.

Ejemplos de feedback:

- “No quiero que usemos ese tono.”
- “Ese producto ya no está disponible.”
- “Ese tipo de cliente no nos interesa.”
- “Los leads de esa campaña preguntan mucho pero no compran.”
- “Prefiero que destaquemos calidad, no descuento.”
- “Ese estilo visual sí representa mi marca.”

Ese feedback debería guardarse como memoria del cliente, no como memoria global de la agencia.

## Uso del feedback en futuras decisiones

Cuando la agencia esté creando o manejando anuncios para ese cliente, Admira debería traer a colación el feedback guardado si existe una intersección relevante.

Ejemplos:

- Si se va a crear un anuncio parecido a uno que el cliente rechazó antes, el agente debería advertirlo.
- Si se propone una oferta con descuento y el cliente dijo que prefiere posicionamiento premium, el agente debería recordarlo.
- Si un estilo visual funcionó o fue aprobado por el cliente, el agente debería sugerir reutilizarlo o adaptarlo.
- Si el cliente marcó cierto tipo de lead como mala calidad, el agente debería tenerlo en cuenta para futuras campañas.

La meta es que Admira no solo reporte resultados, sino que aprenda las preferencias operativas y comerciales de cada cliente.

## Diferencia entre canal de agencia y canal de cliente

El canal de la agencia debería poder ver y decidir acciones operativas:

- aprobar cambios;
- pausar, escalar o crear campañas;
- revisar diagnósticos completos;
- recibir recomendaciones técnicas;
- coordinar entre varios clientes.

El canal del cliente debería ser más limitado:

- recibir reportes;
- hacer preguntas generales;
- dejar feedback;
- confirmar información de negocio;
- entender qué está pasando sin tener control directo de acciones sensibles.

Por defecto, el cliente no debería poder aprobar cambios reales en Meta Ads salvo que la agencia configure explícitamente esa capacidad.

## Consideraciones de seguridad y permisos

Antes de implementar esto, habría que definir:

- qué puede ver el cliente;
- qué puede preguntar;
- qué datos no se deben mostrar;
- si el cliente puede aprobar acciones o solo opinar;
- cómo se separan las memorias de cada cliente;
- cómo se auditan mensajes y decisiones;
- cómo se evita mezclar datos entre clientes;
- cómo se revoca un canal si termina la relación con el cliente.

## Posicionamiento de producto

Esta capacidad podría convertir a Admira en una herramienta fuerte para agencias porque no solo ayuda a operar anuncios, sino también a dar una experiencia profesional al cliente.

Posible promesa:

> “Cada cliente tiene su propio manager de reportes por Telegram, mientras tu agencia mantiene el control estratégico y operativo.”

Esto ayudaría a diferenciar Admira como una solución para agencias que quieren:

- reducir reportes manuales;
- mejorar comunicación con clientes;
- centralizar feedback;
- guardar preferencias por cliente;
- usar memoria operativa para crear mejores campañas futuras.

