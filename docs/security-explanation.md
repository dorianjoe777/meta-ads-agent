# Seguridad para compradores

Este producto esta pensado para dar tranquilidad sin volver la instalacion complicada.

## Lo importante

- Corre localmente en tu PC o en tu VPS.
- El comprador crea su propia contrasena del dashboard al final del onboarding.
- El nivel inicial es `Con supervision`: lee datos reales, explica y prepara acciones sin ejecutar cambios peligrosos por sorpresa.
- Las acciones reales requieren licencia activa y una autorizacion clara: tu aprobacion exacta, o Piloto automatico activo dentro de tus reglas.
- Cambios riesgosos pasan por cola de aprobacion.
- El chat puede ayudarte a preparar acciones. En Telegram solo se puede aprobar una decision exacta: boton, respuesta a la tarjeta, ID de aprobacion o una sola decision pendiente.
- En licencia Individual, las claves quedan en `.env`.
- En licencia Agencia, cada espacio guarda su conexión Meta/Telegram local en archivos privados del backend, con acceso restringido al usuario del PC/VPS. No se envían al vendedor.

## Que protege la contrasena del dashboard

La contrasena protege chat con acciones, aprobaciones, cambios de presupuesto, exportes, generacion creativa, subidas y acciones reales.

## Que protege Piloto automatico

Si Piloto automatico esta apagado, el agente no ejecuta cambios por su cuenta. Aun puedes ejecutar una decision concreta tocando `Aprobar` en el dashboard o el boton exacto de Telegram.

## Que protege la cola de aprobaciones

Reactivar campanas, cambios grandes de presupuesto, subida de creativos y creacion de anuncios no deben ejecutarse por sorpresa. Primero quedan preparados para que el comprador revise y apruebe.

## Licencia cloud

La version de comprador valida la licencia con el servidor del vendedor. Si no puede confirmar la licencia y el periodo de gracia vencio, el producto permite ver dashboard/demo, pero bloquea campanas nuevas, acciones reales y Piloto automatico.

## Que no promete v1

No es un sistema corporativo con SSO o multiusuario. v1 es local-first, simple y self-serve: suficiente para compradores que quieren instalar en su PC/VPS y operar sus anuncios con mas claridad.
