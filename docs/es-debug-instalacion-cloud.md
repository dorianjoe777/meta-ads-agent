# Debug de instalacion cloud en DigitalOcean

Esta nota existe para futuras sesiones de Codex y para soporte tecnico. Resume que puede romperse cuando un comprador instala desde `https://admiroia.uboost.lat/access`, como diagnosticarlo rapido y que relacion tiene cada pieza con el flujo completo.

Para publicar cambios de producto, primero revisar la checklist especifica:

```text
docs/es-checklist-publicacion-release-estable.md
```

Esa checklist evita confundir "rama subida a GitHub" con "asset estable realmente descargado por DigitalOcean".

## Cadena de instalacion

La instalacion cloud funciona como una cadena:

```text
Access page -> licencia -> release privado GitHub -> DigitalOcean API -> cloud-init -> Docker -> dashboard -> access gate/firewall
```

Con HTTPS activado la cadena agrega:

```text
Access page -> DNS por instalacion -> Caddy/Let's Encrypt -> dashboard HTTPS
```

Si un enlace cambia, puede fallar esa parte aunque el resto este bien.

## Estado estable actual

- Canal estable: `v1.0.4`.
- Release privado: `MetaAdsAgent-source.zip`.
- Dominio de comprador: `https://admiroia.uboost.lat/access`.
- Dashboard cloud: puerto `7871`.
- Dashboard cloud HTTPS: puerto `443`, cuando DNS esta configurado.
- Certificados: Caddy + Let's Encrypt, sin servidor adicional.
- Access gate seguro: puerto `7870`.
- Helper del access gate: `/usr/local/bin/meta-ads-refresh-access`.
- Script real de firewall: `/opt/meta-ads-agent/scripts/digitalocean-refresh-firewall.sh`.

El fix validado en junio de 2026 corrigio dos problemas:

- Compatibilidad Python 3.11 en DigitalOcean.
- Boton seguro `Abrir mi dashboard`, que necesitaba un helper estable para actualizar firewall antes de redirigir.

## Que puede romperse en el futuro

### Release o paquete publicado

Si se publica un `stable` con archivos faltantes, version incorrecta, ZIP mal armado o dependencias rotas, DigitalOcean descargara ese paquete roto.

Sintoma comun:

- La instalacion llega a una etapa alta, pero el dashboard nunca abre.
- El contenedor aparece como `Restarting`.
- `docker_logs_tail` muestra errores de Python, imports o archivos faltantes.

Relacion con el fix anterior:

- El bug de Python 3.11 fue exactamente un paquete que funcionaba localmente pero fallaba dentro del droplet.

### Python y dependencias

El droplet puede correr Python 3.11 aunque la Mac local use una version mas nueva. Codigo valido en una version nueva puede fallar en 3.11.

Antes de publicar, verificar:

```bash
python3.11 -m py_compile src/codex_brand_guides.py dashboard/monitoring-dashboard.py src/*.py
python3 tests/test_integration.py
```

Sintomas comunes:

- `SyntaxError`.
- `ModuleNotFoundError`.
- `ImportError`.
- Contenedor reiniciando.

### Docker build

Cambios en `Dockerfile`, `requirements.txt`, Hermes, Codex CLI, Node o dependencias pueden romper el build o hacer que el contenedor arranque y se caiga.

Sintomas comunes:

- `docker_ps` vacio durante mucho tiempo.
- `docker_ps` con `Restarting`.
- `log_tail` detenido en `exporting layers` por mucho rato.
- `docker_logs_tail` con error de arranque.

### Cloud-init de DigitalOcean

Cloud-init es el script que corre una sola vez cuando se crea el droplet. Si este script queda mal, el droplet puede existir pero el producto no termina de instalar.

Sintomas comunes:

- DigitalOcean muestra el droplet activo.
- El access page se queda en `installing`.
- El status gate muestra etapas como `descargando_producto`, `preparando_archivos`, `instalando_dependencias` o `preparando_dashboard`.

Archivo clave:

```text
seller/vercel-license-api/lib/digitalocean-cloud.js
```

### Firewall y access gate

El boton seguro del portal depende de:

- Firewall ID.
- IP actual del comprador.
- Access gate en puerto `7870`.
- Dashboard en puerto `7871`.
- Helper `/usr/local/bin/meta-ads-refresh-access`.

Sintomas comunes:

- El dashboard abre directo en `http://IP:7871`.
- Pero `http://IP:7870/open/SECRET` devuelve `503`.
- El cuerpo del `503` menciona que no pudo preparar acceso.

Si aparece `No such file or directory: /usr/local/bin/meta-ads-refresh-access`, el cloud-init no creo el helper. Revisar `digitalocean-cloud.js`.

### DNS y HTTPS

El HTTPS cloud depende de estas variables en el servidor de licencias:

```text
DNS_PROVIDER=vercel
CLOUD_DASHBOARD_BASE_DOMAIN=cloud.admiroia.uboost.lat
VERCEL_DNS_DOMAIN=uboost.lat
VERCEL_DNS_TOKEN=...
VERCEL_DNS_TEAM_ID=...       # opcional
VERCEL_DNS_TEAM_SLUG=...     # opcional
```

Cloudflare queda disponible solo si el DNS se mueve a Cloudflare:

```text
DNS_PROVIDER=cloudflare
CLOUD_DASHBOARD_BASE_DOMAIN=cloud.admiroia.uboost.lat
CLOUDFLARE_ZONE_ID=...
CLOUDFLARE_API_TOKEN=...
CLOUDFLARE_DNS_PROXIED=false
```

Si faltan, la instalacion no debe romperse: vuelve al dashboard por IP en HTTP.

Si el dominio HTTPS no abre:

1. Revisar que el registro A exista en Vercel DNS y apunte al IPv4 del Droplet.
2. Revisar que el firewall mantenga `80` publico y `443` para la IP autorizada.
3. Revisar Caddy:

```bash
systemctl status caddy --no-pager
journalctl -u caddy -n 80 --no-pager
cat /etc/caddy/Caddyfile
```

4. Revisar que el access gate redirija al dominio HTTPS:

```bash
curl -I http://IP-DEL-DROPLET:7870/open/SECRETO
```

### DigitalOcean API

Puede romperse si DigitalOcean cambia permisos, nombres de imagen Ubuntu, comportamiento de SSH keys, tags, firewalls o droplets.

Sintomas comunes:

- No se crea droplet.
- No se adjunta firewall.
- La llave SSH es rechazada.
- No aparece IP publica.

Validar que el token tenga permisos para:

- Droplets create/read/delete.
- Firewalls create/read/update/delete.
- SSH Keys create/read.
- Tags create/read.

### License server y Vercel

El servidor de licencias entrega URLs firmadas y guarda estado de instalacion. Si fallan variables de entorno, Vercel Blob, GitHub token o release registry, la instalacion no podra descargar el paquete privado.

Sintomas comunes:

- `release_missing`.
- `github_token_missing`.
- `upstream_failed`.
- Access page abre, pero la descarga no empieza.

Archivos clave:

```text
seller/vercel-license-api/api/license/release.js
seller/vercel-license-api/api/download/release.js
seller/vercel-license-api/api/portal/cloud/digitalocean.js
seller/vercel-license-api/lib/store.js
```

### GitHub release assets

El droplet descarga `MetaAdsAgent-source.zip` desde GitHub privado a traves del servidor de licencias. Si el asset se borra, renombra o queda apuntando a otro ID, cloud-init falla al descargar.

Sintoma comun:

- El log se detiene cerca de `descargando_producto`.

Comprobar release:

```bash
gh release view v1.0.4 --repo dorianjoe777/meta-ads-agent --json tagName,assets,url
```

## Checklist rapido de diagnostico

1. Revisar estado en el access page.
2. Confirmar si dice `not_started`, `waiting_for_ip`, `installing`, `failed` o `ready`.
3. Obtener IP del droplet desde el portal o DigitalOcean.
4. Abrir status gate:

```text
http://IP:7870/status/SECRET
```

5. Leer estos campos:

```text
ready
stage
progress
docker_ps
log_tail
docker_logs_tail
```

6. Si `ready=true`, probar el boton seguro:

```text
http://IP:7870/open/SECRET
```

Debe responder `302` hacia:

```text
http://IP:7871/?cloud_access=ok
```

7. Probar dashboard directo despues del open:

```text
http://IP:7871/
```

Debe responder HTML con status `200`.

## Interpretacion de etapas

- `esperando_ip`: DigitalOcean creo el droplet pero aun no se guardo IP.
- `arrancando_servidor`: cloud-init empezo o el log no tiene una etapa mas nueva.
- `instalando_paquetes`: instalando paquetes base, Docker o dependencias.
- `descargando_producto`: descargando release privado.
- `preparando_archivos`: ZIP descargado y descomprimido.
- `instalando_dependencias`: corriendo instalador local o Docker build.
- `preparando_dashboard`: app instalada, preparando entorno.
- `iniciando_dashboard`: levantando Docker Compose.
- `verificando_dashboard`: dashboard responde o esta cerca de responder.
- `dashboard_ready`: dashboard listo.
- `instalacion_detenida`: hay logs de fallo.

## Comandos utiles

Consultar release estable desde el store local del servidor:

```bash
cd seller/vercel-license-api
node --input-type=module -e "import('./lib/store.js').then(async m=>console.log(JSON.stringify(await m.readReleases(), null, 2)))"
```

Recrear paquete buyer-safe:

```bash
./scripts/package-release.sh v1.0.4
```

Publicar assets en GitHub privado:

```bash
gh release view v1.0.4 --repo dorianjoe777/meta-ads-agent
```

Desplegar servidor de licencias:

```bash
cd seller/vercel-license-api
vercel --prod --yes
```

Verificar tests principales:

```bash
python3.11 -m py_compile src/codex_brand_guides.py dashboard/monitoring-dashboard.py src/*.py
python3 tests/test_integration.py
```

## Regla de oro para futuros fixes

No basta con que el droplet aparezca `active` en DigitalOcean. La instalacion solo esta bien cuando:

- El portal muestra `ready=true`.
- El status gate devuelve `ready=true`.
- `/open/SECRET` devuelve `302`.
- `http://IP:7871/` devuelve `200`.
- `docker_ps` muestra el contenedor `Up`.

## Seguridad

Si un token de DigitalOcean se pega en chat, documento o log, se debe rotar despues de la prueba. El portal no debe mostrar una opcion de guardar token para compradores; si se requiere reinstalar, el comprador pega un token valido de nuevo.
