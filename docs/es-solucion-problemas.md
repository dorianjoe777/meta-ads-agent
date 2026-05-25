# Solucion de problemas

## No veo datos reales

Toca `Actualizar datos reales`. Si sigue igual, revisa:

- Token vigente.
- Cuenta publicitaria correcta.
- Permisos de anuncios.
- Internet funcionando.

## No aparecen paginas de Facebook

Puede faltar permiso de paginas en el token. Genera uno nuevo con permisos de paginas y anuncios, pegalo otra vez y vuelve a buscar.

## La licencia no valida

Revisa internet. Si el problema sigue, contacta soporte con tu email de compra y licencia.

## El chat no responde

Revisa que `MINIMAX_API_KEY` este configurado. Si no hay clave, el dashboard puede responder con rutas internas, pero no sera la conversacion completa de MiniMax.

## Telegram no responde

- Revisa que activaste `Hablar por Telegram` desde Configuracion.
- Confirma que enviaste un mensaje a tu bot y elegiste tu chat privado.
- Confirma que el dashboard esta encendido; Telegram escucha junto con el dashboard.
- En VPS, revisa que el servicio del dashboard este activo.

## La campana no se crea

Revisa la tarjeta de resultado. Debe decir que falto: licencia, token, pagina, URL, imagen, presupuesto o confirmacion para dejar activo.
