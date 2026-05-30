# DigitalOcean con acceso estricto

Este modo es para compradores que quieren correr el dashboard en un VPS, pero sin dejarlo abierto a todo internet.

La idea es simple:

- El dashboard puede escuchar en el VPS.
- El firewall de DigitalOcean solo deja entrar a la IP actual del comprador.
- Cuando el comprador entra por SSH, el servidor detecta esa IP y actualiza el firewall.
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
DO_STRICT_ALLOW_SSH_FROM_ANYWHERE=false
```

`DIGITALOCEAN_TOKEN` debe tener permisos para leer/actualizar firewalls y leer droplets. Guardalo solo en el VPS, nunca dentro del instalador ni del paquete fuente interno.

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

Si SSH todavia entra, el sistema se realinea solo.

Para hacerlo sin tocar la terminal, abre el dashboard y entra a:

```text
Configuracion > Acceso cloud / DigitalOcean > Actualizar acceso de esta red
```

Ese boton autoriza la red desde la que estas viendo el dashboard en ese momento.

Tambien puedes correr manualmente en el VPS:

```bash
~/.local/bin/meta-ads-refresh-access
```

Si SSH ya no entra porque la IP cambio y el firewall quedo cerrado, entra al panel de DigitalOcean y agrega temporalmente tu IP actual al puerto `22`, o usa la consola de recuperacion de DigitalOcean. Despues de entrar por SSH, el script vuelve a dejar todo alineado.

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

## Opcion de recuperacion

Para compradores que cambian mucho de red, puedes dejar SSH mas flexible pero mantener el dashboard cerrado:

```env
DO_STRICT_ALLOW_SSH_FROM_ANYWHERE=true
```

Usa esto solo con SSH por llave y contrasena SSH desactivada. El dashboard sigue limitado a la IP detectada.
