# DigitalOcean con acceso estricto

Este modo es para compradores que quieren correr el dashboard en un VPS, pero sin dejarlo abierto a todo internet.

La idea es simple:

- El dashboard puede escuchar en el VPS.
- El firewall de DigitalOcean solo deja abrir el dashboard desde la IP actual del comprador.
- El portal entrega un boton `Abrir mi dashboard` que autoriza la IP actual antes de cargar el dashboard.
- SSH queda disponible con llave, sin contrasena, para recuperar acceso si cambia la IP.
- Cuando el comprador entra por SSH, el servidor detecta esa IP y actualiza el firewall del dashboard.
- Telegram sigue siendo la forma mas comoda de hablar con el agente desde cualquier lugar.

## Cuando usarlo

Usalo si el comprador quiere tener el agente siempre encendido en DigitalOcean y acepta que el dashboard solo abra desde una red autorizada.

No es ideal para alguien que viaja todo el dia y cambia de red cada rato. Para ese caso, Telegram debe ser el canal principal y el dashboard queda para configuracion.

## Seguridad realista

Este modo reduce mucho la exposicion: si una persona no esta en la IP permitida, ni siquiera llega al login del dashboard.

Sigue siendo importante mantener:

- SSH con llave, no contrasena.
- licencia activa;
- contrasena del dashboard;
- aprobaciones para cambios riesgosos;
- token de Meta guardado solo en el VPS.

## Variables necesarias

En el VPS, el instalador puede leer estas variables desde `.env` o pedirlas en pantalla:

```env
DIGITALOCEAN_TOKEN=
DIGITALOCEAN_FIREWALL_ID=
DIGITALOCEAN_DROPLET_ID=
DASHBOARD_PORT=7871
DO_STRICT_EXTRA_TCP_PORTS=
DO_STRICT_ALLOW_SSH_FROM_ANYWHERE=true
DO_STRICT_ACCESS_GATE_PORT=7870
CLOUD_ACCESS_SECRET=
```

`DIGITALOCEAN_TOKEN` debe tener permisos para leer/actualizar firewalls y leer droplets. Guardalo solo en el VPS, nunca dentro del instalador ni del paquete fuente interno.

Para instalaciones de comprador, el token debe ser sin vencimiento si DigitalOcean ofrece esa opcion, o de duracion larga. Si el token vence, el agente puede seguir funcionando, pero el servidor no podra actualizar automaticamente el firewall cuando cambie la IP.

## Configuracion recomendada

1. Crear el Droplet en DigitalOcean.
2. Crear un firewall dedicado solo para este producto.
3. Asignar ese firewall al Droplet.
4. Instalar el producto en el VPS.
5. Ejecutar:

```bash
./scripts/install-digitalocean-strict-access.sh
```

Ese script crea un comando local:

```bash
~/.local/bin/meta-ads-refresh-access
```

Tambien agrega una pequena regla a `~/.profile` para que, despues de entrar por SSH, se actualice automaticamente la IP permitida.

## Acceso al dashboard

Para abrirlo directamente desde la IP autorizada:

```text
http://IP-DEL-VPS:7871
```

Si prefieres no exponer el dashboard ni siquiera a la IP autorizada, usa tunel SSH:

```bash
ssh -L 7871:127.0.0.1:7871 usuario@IP-DEL-VPS
```

Luego abre:

```text
http://127.0.0.1:7871
```

## Si cambia la IP

El camino normal para el comprador es volver al portal y usar:

```text
Abrir mi dashboard
```

Ese boton llama una puerta segura del Droplet en el puerto `7870`. Esa puerta:

- exige una clave larga generada durante la instalacion;
- detecta la IP publica actual;
- actualiza el firewall del dashboard;
- redirige al dashboard en el puerto `7871`.

No es una puerta para operar el agente, cambiar anuncios o ver datos. Solo autoriza la red actual para cargar el dashboard.

Si el dashboard todavia abre desde la red actual, usa el boton preventivo:

```text
Configuracion > Acceso cloud / DigitalOcean > Actualizar acceso de esta red
```

Ese boton autoriza la red desde la que ya estas viendo el dashboard. No sirve si el firewall ya bloqueo la nueva IP, porque en ese caso el comprador no puede cargar el dashboard.

La recuperacion tecnica es por SSH. Al entrar con tu llave:

```bash
ssh root@IP-DEL-VPS
```

el servidor detecta tu IP y actualiza el firewall automaticamente. Tambien puedes correr manualmente en el VPS:

```bash
~/.local/bin/meta-ads-refresh-access
```

Si SSH no entra, normalmente no es por cambio de IP sino por llave equivocada, usuario equivocado o regla SSH alterada. En ese caso:

1. Entrar al panel de DigitalOcean.
2. Abrir la consola web del Droplet, o revisar que tu llave publica este autorizada.
3. Entrar al VPS y correr:

```bash
~/.local/bin/meta-ads-refresh-access
```

Despues de eso, el firewall vuelve a permitir la IP actual.

## Protector automatico en el computador

El helper local por hora queda como respaldo avanzado. No debe ser el camino principal del comprador, porque el boton `Abrir mi dashboard` ya hace la recuperacion al momento de entrar.

Ese helper corre cada hora:

- revisa la IP publica actual del computador;
- si cambio, entra al VPS por SSH con la llave del comprador;
- ejecuta `~/.local/bin/meta-ads-refresh-access`;
- actualiza el firewall del dashboard sin guardar el token de DigitalOcean en el computador.

Esto es la forma mas amigable para compradores no tecnicos. Si el computador esta apagado, no puede correr; en ese caso Telegram sigue funcionando y el comprador puede recuperar acceso entrando por SSH cuando vuelva a usar su equipo.

## Si cambia de PC

Cuando el comprador cambia de PC, tambien puede cambiar su llave SSH.

Flujo de soporte recomendado:

1. Crear una nueva llave SSH en el nuevo PC.
2. Agregar la llave publica al Droplet desde la consola de DigitalOcean o al archivo `~/.ssh/authorized_keys` del usuario.
3. Entrar por SSH desde el nuevo PC.
4. Ejecutar:

```bash
~/.local/bin/meta-ads-refresh-access
```

Ese comando actualiza el firewall para la IP del nuevo PC.

Cuando el dashboard ya abra desde el nuevo PC, usa `Configuracion > Acceso cloud / DigitalOcean > Actualizar acceso de esta red` para dejar esa red autorizada. Si todavia no abre, usa SSH o la consola de DigitalOcean una sola vez para recuperar entrada.

## Modelo recomendado

```env
DO_STRICT_ALLOW_SSH_FROM_ANYWHERE=true
```

Esto deja SSH como puerta de recuperacion, pero solo con llave y con contrasena SSH desactivada. El dashboard sigue limitado a la IP detectada.
