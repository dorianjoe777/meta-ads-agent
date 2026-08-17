# Activar licencia

## Que recibe el comprador

El comprador recibe una licencia por email. Esa es la unica clave comercial que necesita para activar el producto.

## Que hace la licencia

- Es una licencia comercial de por vida; no tiene fecha de vencimiento.
- Desbloquea configuracion real de comprador.
- Permite crear campanas y preparar acciones reales.
- Permite preparar campañas en pausa y aprobar activación/gasto cuando corresponda.
- Vincula la instalacion a este PC o VPS mediante un ID local.
- En licencia Individual, permite transferir la activacion a otro equipo cuando el comprador cambia de PC o reinstala.

## Estados posibles

- `Activa de por vida`: licencia confirmada. La comprobacion firmada se renueva automaticamente en segundo plano.
- `No activada`: todavia no se ingreso licencia.
- `No se pudo validar con el servidor`: revisar internet o contactar soporte.

Una fecha interna de renovacion nunca debe mostrarse ni tratarse como vencimiento de la compra. Si el servidor o internet fallan, una licencia ya validada sigue activa; cuando vuelve la conexion, el producto renueva la comprobacion automaticamente. Una revocacion real comunicada por el servidor (por ejemplo, reembolso o transferencia de equipo) si se respeta.

## Mensaje para soporte

Si aparece problema de licencia, el comprador debe revisar internet y luego escribir a soporte con su email de compra y el codigo de licencia.

## Cambiar de equipo

Si el comprador ve que la licencia ya esta activa en otro equipo, puede elegir `Transferir a este equipo`.

Eso registra el nuevo equipo como activo para futuras validaciones. El equipo anterior se desactiva cuando vuelva a validar online. Si permanece completamente offline, conserva la ultima comprobacion firmada para evitar que una caida del servicio bloquee al comprador.

Guia completa: `docs/es-cambiar-de-equipo.md`.
