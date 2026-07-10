# Checklist de publicacion estable

Esta checklist existe para futuras sesiones de Codex. No basta con decir "ya esta en GitHub" si el comprador instala desde `https://admiraia.uboost.lat/access` o desde DigitalOcean. El comprador no descarga la rama directamente: descarga el asset estable registrado en el servidor de licencias.

## Regla principal

Antes de asegurar que una correccion ya esta disponible para compradores, verifica estas capas:

1. Rama GitHub actualizada.
2. ZIP buyer-safe reconstruido.
3. Asset estable de GitHub reemplazado.
4. Servidor de licencias apuntando al asset nuevo.
5. Descarga real verificada desde el asset publicado.
6. Si existen instalaciones anteriores, el dashboard debe poder ver una version `stable` mas nueva que su version instalada para mostrar la notificacion de actualizar.

Si falta una de esas capas, un VPS fresco puede seguir instalando codigo viejo aunque la rama este actualizada.

## Estado local sagrado: nunca se reemplaza con una release

En una actualizacion, el codigo puede cambiar, pero el estado local del comprador no. Para futuras sesiones de Codex, estos datos se consideran sagrados:

- contraseña/hash del dashboard;
- sesiones locales del dashboard;
- `.env` del comprador;
- `ad-config.json`;
- licencia, email de compra y device id;
- onboarding completado;
- perfil del negocio;
- cuenta publicitaria y Business Manager elegidos;
- Telegram, Meta token, Shopify y preferencias del agente;
- `dashboard/data`;
- `output`;
- `logs`;
- `runtime`;
- guias de marca y productos guardados.

Una release puede traer archivos nuevos, pero no debe reemplazar esos datos. Si una correccion requiere migrar alguno de esos datos, debe hacerse como migracion explicita, idempotente y con prueba dedicada. Nunca por copiar encima una carpeta del ZIP.

Regla de oro:

```text
Update = cambia codigo + conserva identidad/configuracion/memoria local.
Reset/onboarding nuevo = solo cuando el usuario lo pide explicitamente.
```

Antes de publicar, verificar que las pruebas de update cubren:

- una release que contiene `.env` no puede sobreescribir el `.env` real;
- una release que contiene `dashboard/data/onboarding_state.json` no puede borrar onboarding completado;
- una release que contiene `dashboard/data/dashboard_identity.json` no puede reemplazar la identidad local;
- una instalacion que pierde el hash de contraseña en `.env` puede recuperarlo desde `dashboard/data/dashboard_identity.json`;
- una instalacion que ya completo onboarding no queda atrapada si necesita crear una nueva contraseña porque no hay ninguna configurada.

### Regla anti-confusion para sesiones futuras de Codex

No decir simplemente "lo pushee a GitHub" como si eso significara que los compradores ya tienen actualizacion. Para este producto hay tres estados distintos:

- **GitHub pusheado:** el codigo esta en la rama, pero todavia no hay garantia de instalacion nueva ni notificacion en dashboard.
- **Release estable publicada:** `VERSION` fue subido, el ZIP estable fue reconstruido, GitHub Release tiene el asset correcto, y el registry del servidor de licencias apunta al asset nuevo. Esto permite instalaciones nuevas y notificaciones de update.
- **Servidor especifico hotpatcheado:** ese VPS puntual ya tiene el fix aplicado directamente. Si tambien se le sube la version actual, ese VPS no deberia mostrar una notificacion porque ya esta en la version nueva. Esto no contradice el sistema de updates; significa que ese servidor fue actualizado manualmente antes de usar el boton.

Para cualquier bug menor pedido por el usuario, el resultado por defecto debe ser **release estable publicada**, no solo commit/push. Solo saltar esto si el usuario pide explicitamente un hotfix local sin release.

Cuando se hotpatchee un servidor existente y tambien se publique release estable, explicarlo asi:

```text
Publique vX.Y.Z para que otros installs vean update. Este VPS puntual ya fue actualizado directamente a vX.Y.Z, por eso no vera la notificacion: ya no esta por debajo de la version estable.
```

No usar frases ambiguas como "no afecta servidores ya instalados" si el dashboard tiene updater. La frase correcta es:

```text
Los servidores instalados en versiones anteriores veran la actualizacion si su version local es menor que la version estable publicada. El servidor que hotpatchee manualmente no la vera porque ya quedo en esa version.
```

## Caso que origino esta nota

El cambio de Hermes para VPS se habia pusheado a GitHub, pero una instalacion fresca de DigitalOcean seguia mostrando:

- `hermes model`
- `Copiar paso`
- `ssh root@IP-DE-TU-SERVIDOR`

La causa fue que el instalador cloud descargaba `MetaAdsAgent-source.zip` del release estable `v1.0.4`, y ese asset todavia era viejo. La rama estaba bien, pero el asset estable no.

## 1. Verificar rama GitHub

```bash
git status --short --branch
git log -1 --oneline --decorate
git push
```

Debe quedar sin cambios pendientes y con `origin/<branch>` en el mismo commit.

## 2. Reconstruir ZIP buyer-safe

Usar el canal estable actual salvo que se decida publicar una version completa nueva con todos los instaladores.

```bash
META_ADS_LICENSE_SERVER_URL=https://admiraia.uboost.lat \
META_ADS_GITHUB_REPO=dorianjoe777/meta-ads-agent \
./scripts/package-release.sh "$(cat VERSION)"
```

Verificar que el ZIP contiene el cambio esperado y no contiene el texto viejo. Ejemplo para el fix de Hermes:

```bash
unzip -p release/MetaAdsAgent-source.zip dashboard/monitoring-dashboard.py \
  | rg -n "hermes model --no-browser|connect-status|connect-input"

if unzip -p release/MetaAdsAgent-source.zip dashboard/monitoring-dashboard.py \
  | rg -n "ssh root@IP-DE-TU-SERVIDOR|Copiar paso"; then
  echo "ERROR: texto viejo encontrado"
  exit 1
fi
```

El segundo comando no debe encontrar nada.

## 3. Reemplazar asset estable en GitHub

```bash
VERSION="$(cat VERSION)"
gh release upload "$VERSION" \
  release/MetaAdsAgent-source.zip \
  "release/MetaAdsAgent-$VERSION-source.zip" \
  release/SHA256SUMS.txt \
  --repo dorianjoe777/meta-ads-agent \
  --clobber
```

Luego obtener el nuevo `apiUrl`, `digest` y fecha:

```bash
gh release view "$(cat VERSION)" --repo dorianjoe777/meta-ads-agent --json assets \
  | python3 -c 'import json,sys; p=json.load(sys.stdin); [print(a["name"], a.get("apiUrl"), a.get("digest"), a.get("updatedAt")) for a in p["assets"] if a["name"]=="MetaAdsAgent-source.zip"]'
```

Importante: cuando se usa `--clobber`, el asset ID puede cambiar. Si cambia, el servidor de licencias debe apuntar al nuevo `apiUrl`.

## 4. Actualizar servidor de licencias

El canal `stable` vive en el registry privado del servidor de licencias. Debe apuntar al asset API nuevo:

```text
https://api.github.com/repos/dorianjoe777/meta-ads-agent/releases/assets/ASSET_ID_NUEVO
```

Se puede actualizar por API admin si `LICENSE_ADMIN_KEY` esta disponible, o directamente con `seller/vercel-license-api/lib/store.js` usando `BLOB_READ_WRITE_TOKEN` local de Vercel.

Nota: `vercel env pull` puede dejar algunas variables sensibles vacias en archivos locales aunque existan en Vercel como `Encrypted`. Si `POST /api/admin/releases` responde `401` y `LICENSE_ADMIN_KEY` local esta vacio o desactualizado, usar la ruta directa de Blob con `BLOB_READ_WRITE_TOKEN` y verificar el registry despues de esperar el cache de hasta 60 segundos.

Verificar despues:

```bash
node --input-type=module <<'NODE'
import fs from 'node:fs';
const envText = fs.readFileSync('./seller/vercel-license-api/.env.production.current', 'utf8');
for (const line of envText.split(/\r?\n/)) {
  if (!line || line.startsWith('#') || !line.includes('=')) continue;
  const [key, ...rest] = line.split('=');
  let value = rest.join('=').trim();
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
  if (value) process.env[key] = value;
}
const { readReleases } = await import('./seller/vercel-license-api/lib/store.js');
const releases = await readReleases();
console.log(JSON.stringify({
  version: releases.channels?.stable?.version,
  source_url: releases.channels?.stable?.assets?.['MetaAdsAgent-source.zip']?.source_url,
  improvements: releases.channels?.stable?.improvements?.map(i => i.title)
}, null, 2));
NODE
```

La salida debe mostrar el asset ID nuevo.

## 5. Verificar descarga real

Como minimo, descargar el asset publicado desde GitHub y revisar contenido:

```bash
rm -rf /tmp/admira-release-test
mkdir -p /tmp/admira-release-test
gh release download "$(cat VERSION)" \
  --repo dorianjoe777/meta-ads-agent \
  --pattern MetaAdsAgent-source.zip \
  --dir /tmp/admira-release-test \
  --clobber

unzip -p /tmp/admira-release-test/MetaAdsAgent-source.zip dashboard/monitoring-dashboard.py \
  | rg -n "CAMBIO_ESPERADO|TEXTO_QUE_NO_DEBE_APARECER"
```

Si hay una licencia cloud real disponible, tambien probar:

```bash
POST https://admiraia.uboost.lat/api/license/release
```

con `license_key`, `buyer_email`, `device_id`, `channel=stable` y `asset_name=MetaAdsAgent-source.zip`. No imprimir la licencia ni la URL firmada completa en logs.

## 6. Version nueva o mismo canal

Para que el dashboard muestre una notificacion simple de actualizar, la version publicada en el registry estable debe ser mayor que la version local del comprador. Por eso, ante cualquier fix buyer-visible, especialmente onboarding, conexion de agente, licencia, actualizador, Telegram, Meta o DigitalOcean:

1. Subir `VERSION` y `META_ADS_AGENT_VERSION` en `.env.example`.
2. Publicar el nuevo ZIP estable.
3. Actualizar `channels.stable.version` en el registry del servidor de licencias.
4. Verificar que `POST /api/license/release` devuelve esa version nueva.

No basta con reemplazar un asset manteniendo el mismo numero de version si se espera que instalaciones ya existentes vean una notificacion. Mantener el mismo numero solo sirve para instalaciones nuevas o para descargas manuales; no para avisar a dashboards que ya tienen esa version.

No crear una version nueva solo con `MetaAdsAgent-source.zip` si el portal necesita descubrir instaladores Mac/Windows/Linux por tag. Si se publica una version nueva, subir tambien los assets de plataforma:

- Mac `.dmg` o `.pkg`
- Windows `.msi` o `.exe`
- Linux `.tar.gz`
- `MetaAdsAgent-source.zip`
- `SHA256SUMS.txt`

Si solo se corrige lo que descarga DigitalOcean, es aceptable reemplazar el asset fuente del canal estable actual y actualizar el registry de licencias.

## 7. Que decir al usuario

Solo afirmar "ya esta disponible para instalaciones nuevas" cuando se haya verificado:

- `git log -1` muestra el commit correcto.
- `MetaAdsAgent-source.zip` reconstruido contiene el cambio.
- GitHub release asset tiene digest nuevo.
- El registry del servidor de licencias apunta al asset ID nuevo.
- Una descarga real del asset contiene el cambio.
- `POST /api/license/release` devuelve una version mayor que la version anterior instalada, si se espera que el dashboard muestre notificacion.

Si solo se hizo `git push`, decir claramente:

```text
Esta en GitHub, pero todavia falta reconstruir/publicar el asset estable que descarga DigitalOcean.
```

Si se publico release estable y ademas se actualizo manualmente el VPS del usuario, decir claramente:

```text
Otros installs antiguos deberian ver la notificacion de actualizar. Este VPS especifico no la vera porque ya lo subi manualmente a esa misma version.
```
