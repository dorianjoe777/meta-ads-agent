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

Revisa primero el paso `Conectar el modelo del agente` en Configuracion. Ahí puedes usar una de dos rutas:

- `Hermes + ChatGPT/Codex`: recomendado si quieres usar tu suscripcion de ChatGPT/Codex.
- `MiniMax M3` u otra `API compatible OpenAI`: recomendado si quieres pagar por tokens de un proveedor externo.

Si ya terminaste el onboarding, puedes volver al mismo flujo desde el dashboard:

```text
Configuracion > Conectar el modelo del agente
```

Si eliges Hermes, esa tarjeta te dira si falta Hermes o si falta iniciar sesion. Si necesitas hacerlo manualmente, abre Terminal en el mismo equipo donde corre Admiro AI y ejecuta:

```bash
hermes model
```

Elige `OpenAI Codex`, inicia sesion con la cuenta ChatGPT del comprador y vuelve al dashboard. Despues toca `Ya lo hice, revisar conexion`.

Si Admiro AI esta instalado en DigitalOcean, este comando se ejecuta dentro del servidor, no en el computador personal. Entra por SSH o por la consola web de DigitalOcean y corre `hermes model` ahi.

Si eliges MiniMax M3 u otro proveedor, guarda:

- URL compatible OpenAI, por ejemplo `https://api.minimax.io/v1`.
- Nombre del modelo, por ejemplo `MiniMax-M3`.
- Clave API del proveedor.

La clave queda guardada localmente en `.env` y no vuelve a aparecer en el dashboard. Para proveedores remotos usa siempre `https://`; `http://` solo se acepta para modelos locales como `127.0.0.1`.

## Telegram no responde

- Revisa que activaste `Hablar por Telegram` desde Configuracion.
- Confirma que enviaste un mensaje a tu bot y elegiste tu chat privado.
- Confirma que el dashboard esta encendido; Telegram escucha junto con el dashboard.
- En VPS, revisa que el servicio del dashboard este activo.

## La campana no se crea

Revisa la tarjeta de resultado. Debe decir que falto: licencia, token, pagina, URL, imagen, presupuesto o confirmacion para dejar activo.
