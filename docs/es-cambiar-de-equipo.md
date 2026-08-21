# Cambiar de equipo

Este producto permite mover una licencia Individual a otro equipo cuando el comprador cambia de PC, reinstala el sistema o decide pasar de instalacion local a VPS.

## Para el comprador

Usa la misma licencia y el mismo email de compra en el nuevo equipo.

Si la licencia ya estaba activa en otro equipo, el instalador o el dashboard mostrara un aviso:

```text
Esta licencia ya esta activa en otro equipo.
```

Al confirmar `Transferir a este equipo`, este equipo queda como el equipo activo para nuevas validaciones.

## Que pasa con el equipo anterior

El equipo anterior se desactiva cuando vuelva a validar online y el servidor confirme que la licencia fue transferida. Si permanece completamente offline, conserva la ultima comprobacion firmada para que una caida del servidor nunca convierta una compra de por vida en una licencia vencida.

Esto es intencional para que un comprador no se quede bloqueado si tu servidor de licencias falla, pero tambien significa que la transferencia no es un apagado instantaneo si el equipo anterior permanece offline.

## Recomendacion para soporte

Si el comprador cambio de PC:

1. Pedirle que instale el producto en el nuevo equipo.
2. Usar la misma licencia y email.
3. Confirmar `Transferir a este equipo`.
4. Pedirle que no use mas el equipo anterior.

Para situaciones de abuso, el servidor debe responder con revocacion o limite de equipo en la siguiente comprobacion online. `LICENSE_UNLOCK_HOURS` controla cada cuanto se renueva esa comprobacion; no es la duracion comercial de la licencia.

## Mover tambien la memoria local

Si el comprador quiere que el nuevo equipo se vea como el anterior, usa los botones dentro del dashboard:

```text
Configuracion > Cambiar de equipo sin perder memoria > Crear respaldo
Configuracion > Cambiar de equipo sin perder memoria > Restaurar respaldo
```

Ese respaldo mueve:

- historial del chat del dashboard;
- configuracion local;
- cuenta y pagina seleccionadas;
- memoria del negocio;
- acciones, aprobaciones y reportes;
- guias de marca y producto;
- archivos generados.

No mueve el desbloqueo cloud ni el `LICENSE_DEVICE_ID`. En el nuevo equipo la licencia debe validarse otra vez y, si es Individual, confirmar `Transferir a este equipo`.

Importante: el respaldo puede incluir tokens de Meta, Telegram y proveedores creativos. Debe tratarse como una contrasena.

## Si la instalacion esta en DigitalOcean

Si el comprador cambia de PC, probablemente tambien cambia la llave SSH.

Flujo recomendado:

1. Crear una nueva llave SSH en el nuevo PC.
2. Entrar al panel de DigitalOcean.
3. Agregar la nueva llave publica al Droplet o al usuario Linux.
4. Entrar por SSH desde el nuevo PC.
5. Ejecutar:

```bash
~/.local/bin/meta-ads-refresh-access
```

Despues de eso, el firewall de DigitalOcean permite la IP actual del nuevo PC.

Cuando el dashboard ya abra desde el nuevo PC, el comprador puede entrar a `Configuracion > Acceso cloud / DigitalOcean` y tocar `Actualizar acceso de esta red`. Ese boton no es una recuperacion si el dashboard no carga; solo guarda la red cuando ya hay acceso. Si todavia no puede abrir el dashboard, debe usar SSH o la consola web de DigitalOcean una sola vez para recuperar entrada.

Si no puede entrar por SSH, debe usar la consola web de DigitalOcean o agregar temporalmente su IP al firewall desde el panel.
