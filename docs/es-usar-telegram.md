# Hablar con el agente por Telegram

Telegram es opcional. Sirve para preguntarle al manager desde el celular, pedir un resumen, preparar una campana, enviar una imagen creativa y aprobar decisiones exactas con botones.

## Conectar el bot

1. Descarga Telegram en tu celular.
2. Recomendado: descarga Telegram tambien en tu PC para copiar y pegar la clave larga mas facil.
3. En Telegram, usa el buscador y escribe `BotFather`.
4. Entra al chat oficial de BotFather.
5. Escribe `/newbot`.
6. BotFather pedira un nombre. Puedes escribir cualquier nombre, por ejemplo `Manager de anuncios`.
7. BotFather pedira un usuario. Puede ser parecido al nombre, pero debe terminar en `bot`, por ejemplo `manageranuncios_bot`.
8. BotFather te enviara una clave larga.
9. En el dashboard, abre `Configuracion` y busca `Hablar por Telegram`.
10. Pega la clave larga y guarda.
11. Abre tu bot en Telegram y enviale un mensaje, por ejemplo `Hola`.
12. Vuelve al dashboard y toca `Detectar mi chat`.
13. Elige tu chat privado, activa la conversacion y toca `Enviar prueba`.

Esto se hace una sola vez. Despues, mientras el dashboard este encendido en tu PC/VPS, podras hablar con el agente desde Telegram.

## Que se puede automatizar

Telegram no permite que el dashboard cree el bot por ti: la clave solo la entrega BotFather dentro de Telegram. El dashboard si ayuda con lo siguiente:

- abrir Telegram/BotFather desde un boton;
- copiar el comando `/newbot`;
- guardar la clave larga;
- detectar tu chat privado despues de que le escribas al bot;
- enviar un mensaje de prueba;
- dejar el manager listo para responder y mostrar aprobaciones.

## Que puedes pedirle

```text
Que debo vigilar hoy?
Prepara una campana para mi producto.
Revisa el presupuesto de la campana de ventas.
Que falta para activar una campana con seguridad?
```

Tambien puedes mandar una foto al bot. El agente la guarda localmente en tu PC/VPS para usarla como creativo cuando prepares una campana.

## Comandos utiles

- `/nuevo`: empieza una conversacion sin contexto anterior.
- `/pendientes`: muestra decisiones que esperan aprobacion.
- `/ayuda`: recuerda ejemplos de uso.

## Aprobar desde Telegram

Cuando haya una decision pendiente, escribe:

```text
/pendientes
```

El bot mostrara cada accion con botones:

- `Aprobar`
- `No aprobar`

Si una campana quedara activa y podria gastar presupuesto real, el boton dira claramente:

```text
Si, activar
```

Para una decisión normal también puedes responder simplemente `aprobado`. Los identificadores técnicos se mantienen ocultos. Si quieres aprobar una decisión anterior y no está claro cuál, el agente te mostrará sus nombres sin códigos internos.

## Proteccion importante

- Solo el chat privado elegido puede hablar con el agente.
- El bot usa el mismo manager, memoria y reglas del dashboard.
- Telegram puede preparar acciones y aprobar cuando eliges la decisión mediante su botón o respondes `aprobado` a la propuesta presentada.
- Campanas activas y cambios que pueden gastar muestran una confirmacion especial antes de ejecutar.

## Mantenerlo encendido

Cuando el dashboard esta abierto, Telegram queda escuchando automaticamente despues de activarlo. En un VPS, el servicio del dashboard lo mantiene encendido.

Para correr solo Telegram sin abrir el dashboard, existe el comando avanzado:

```bash
./scripts/run-telegram-agent.sh
```
