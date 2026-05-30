# Hablar con el agente por Telegram

Telegram es opcional. Sirve para preguntarle al manager desde el celular, pedir un resumen, preparar una campana, enviar una imagen creativa y aprobar decisiones exactas con botones.

## Conectar el bot

1. En Telegram, busca `@BotFather`.
2. Crea un bot nuevo con `/newbot`.
3. Copia el token que te entrega BotFather.
4. En el dashboard, abre `Configuracion` y busca `Hablar por Telegram`.
5. Pega el token del bot y guarda.
6. Abre tu bot en Telegram y enviale un mensaje, por ejemplo `Hola`.
7. Vuelve al dashboard y toca `Detectar mi chat`.
8. Elige tu chat privado, activa la conversacion y toca `Enviar prueba`.

## Que puedes pedirle

```text
Que debo vigilar hoy?
Prepara una campana para mi producto.
Revisa el presupuesto de la campana de ventas.
Que falta para activar piloto automatico?
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
Si, crear y dejar activo
```

El agente no aprueba por texto libre. Si escribes "aprueba eso", te pedira usar el boton de la accion exacta.

## Proteccion importante

- Solo el chat privado elegido puede hablar con el agente.
- El bot usa Hermes y las mismas reglas del dashboard.
- Telegram puede preparar acciones y aprobar solo cuando eliges una decision exacta: boton, respuesta a la tarjeta, ID de aprobacion o una sola decision pendiente.
- Campanas activas y cambios que pueden gastar muestran una confirmacion especial antes de ejecutar.

## Mantenerlo encendido

Cuando el dashboard esta abierto, Telegram queda escuchando automaticamente despues de activarlo. En un VPS, el servicio del dashboard lo mantiene encendido.

Para correr solo Telegram sin abrir el dashboard, existe el comando avanzado:

```bash
./scripts/run-telegram-agent.sh
```
