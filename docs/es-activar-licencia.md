# Activar licencia

## Que recibe el comprador

El comprador recibe una licencia por email. Esa es la unica clave comercial que necesita para activar el producto.

## Que hace la licencia

- Desbloquea configuracion real de comprador.
- Permite crear campanas y preparar acciones reales.
- Permite preparar campañas en pausa y aprobar activación/gasto cuando corresponda.
- Vincula la instalacion a este PC o VPS mediante un ID local.
- En licencia Individual, permite transferir la activacion a otro equipo cuando el comprador cambia de PC o reinstala.

## Estados posibles

- `Activa`: licencia confirmada.
- `No activada`: todavia no se ingreso licencia.
- `No se pudo validar con el servidor`: revisar internet o contactar soporte.
- `En periodo de gracia`: la licencia ya fue confirmada antes y puede seguir temporalmente aunque el servidor no responda.

## Mensaje para soporte

Si aparece problema de licencia, el comprador debe revisar internet y luego escribir a soporte con su email de compra y el codigo de licencia.

## Cambiar de equipo

Si el comprador ve que la licencia ya esta activa en otro equipo, puede elegir `Transferir a este equipo`.

Eso registra el nuevo equipo como activo para futuras validaciones. El equipo anterior deja de renovar la licencia cuando vuelva a validar online. Si el equipo anterior tenia un desbloqueo temporal guardado, puede seguir funcionando hasta que expire ese periodo.

Guia completa: `docs/es-cambiar-de-equipo.md`.
