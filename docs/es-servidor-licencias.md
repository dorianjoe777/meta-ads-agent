# Servidor de licencias para vender v1

Este producto ya valida licencia desde el dashboard del comprador. Para vender rápido necesitas un endpoint propio en tu dominio.

## Qué resuelve

- El comprador recibe una sola licencia por email.
- El dashboard consulta tu dominio para confirmar que la licencia existe.
- Si tu dominio falla por unas horas, el comprador conserva un desbloqueo guardado en su equipo.
- Si la licencia no existe, está inactiva o supera el límite de equipos, se bloquean acciones reales y creación de campañas.
- El mismo servidor puede entregar descargas firmadas de la ultima version publicada sin exponer tu repo privado.

## Crear una licencia

```bash
curl -X POST "https://admiroia.uboost.lat/api/admin/licenses" \
  -H "Authorization: Bearer TU_CLAVE_ADMIN_PRIVADA" \
  -H "Content-Type: application/json" \
  -d '{"buyer_email":"comprador@email.com","buyer_name":"Nombre del comprador","plan":"individual"}'
```

Para licencia Agencia, que permite hasta 4 dispositivos y espacios separados para varios clientes:

```bash
curl -X POST "https://admiroia.uboost.lat/api/admin/licenses" \
  -H "Authorization: Bearer TU_CLAVE_ADMIN_PRIVADA" \
  -H "Content-Type: application/json" \
  -d '{"buyer_email":"agencia@email.com","buyer_name":"Nombre Agencia","plan":"agency"}'
```

El servidor mantiene un archivo privado por licencia para que una licencia nueva pueda activarse inmediatamente y registra cada dispositivo en un archivo privado separado para contar instalaciones sin depender de un JSON cacheado. Por el cache minimo de Vercel Blob, revocar o cambiar el plan de una licencia existente puede tardar hasta 60 segundos en reflejarse en nuevas activaciones.

## Configuración en el producto del comprador

En el `.env` de release debes definir:

```text
LICENSE_SERVER_URL=https://admiroia.uboost.lat
LICENSE_PUBLIC_KEY=clave-publica-incluida-en-el-release
LICENSE_REQUIRED_FOR_LIVE=true
```

El dashboard llamará:

```text
POST https://admiroia.uboost.lat/api/license/activate
```

Y los instaladores del comprador llamarán:

```text
POST https://admiroia.uboost.lat/api/license/release
```

## API ya desplegada en Vercel

La implementación de producción está en `seller/vercel-license-api` y usa un Blob privado de Vercel. Variables privadas del proyecto Vercel:

```text
LICENSE_PRIVATE_KEY_B64=clave-privada-solo-en-vercel
LICENSE_ADMIN_KEY=clave-de-administracion-solo-del-vendedor
LICENSE_UNLOCK_HOURS=168
RELEASE_DOWNLOAD_SECRET=secreto-solo-servidor-para-firmar-descargas
RELEASE_TOKEN_MINUTES=15
RELEASE_SOURCE_ALLOWLIST=tu-storage.com,downloads.tudominio.com
BLOB_READ_WRITE_TOKEN=agregado-por-vercel-blob
```

Endpoint publicado:

```text
https://admiroia.uboost.lat
```

## Publicar una release protegida

Primero generas el ZIP buyer-safe:

```bash
./scripts/package-release.sh v1
```

Luego subes `MetaAdsAgent-source.zip` a tu storage privado o a tu dominio.

Despues registras esa version en el servidor:

```bash
curl -X POST "https://admiroia.uboost.lat/api/admin/releases" \
  -H "Authorization: Bearer TU_CLAVE_ADMIN_PRIVADA" \
  -H "Content-Type: application/json" \
  -d '{
    "channel":"stable",
    "version":"v1",
    "asset_name":"MetaAdsAgent-source.zip",
    "filename":"MetaAdsAgent-source.zip",
    "content_type":"application/zip",
    "source_url":"https://downloads.tudominio.com/MetaAdsAgent-source.zip",
    "improvements":[
      {
        "title":"Manager mas claro para principiantes",
        "body":"La actualizacion mejora textos, guias y tarjetas dentro del dashboard.",
        "impact":"Usabilidad"
      },
      {
        "title":"Mas seguridad en acciones reales",
        "body":"Refuerza aprobaciones y protecciones antes de tocar presupuesto real.",
        "impact":"Confianza"
      }
    ]
  }'
```

Esas `improvements` son las tarjetas que el comprador ve antes de confirmar la actualizacion desde su dashboard.

Consulta administrativa:

```bash
curl "https://admiroia.uboost.lat/api/admin/releases" \
  -H "Authorization: Bearer TU_CLAVE_ADMIN_PRIVADA"
```

## Flujo de instalacion del comprador

1. El comprador abre el instalador.
2. El instalador pide licencia + email de compra.
3. El instalador llama `POST /api/license/release`.
4. Si la licencia es valida, el servidor responde con:
   - version
   - asset_name
   - expires_at
   - download_url
5. El instalador descarga desde `GET /api/download/release?token=...`.
6. El token expira rapido y no revela tu repo privado.

## Rutas del servidor

- `GET /health`
- `POST /api/license/activate`
- `POST /api/license/release`
- `GET /api/download/release?token=...`
- `GET /api/admin/licenses`
- `POST /api/admin/licenses`
- `GET /api/admin/releases`
- `POST /api/admin/releases`
- `POST /api/webhooks/hotmart`

## Operación diaria

Pega esta URL en Hotmart como `URL para envio de datos`:

```text
https://admiroia.uboost.lat/api/webhooks/hotmart
```

Configura en Vercel:

- `HOTMART_HOTTOK`: el token que Hotmart manda en el header `X-HOTMART-HOTTOK`.
- `BUYER_EMAIL_PROVIDER=resend`: envia el correo de acceso con Resend.
- `RESEND_API_KEY`: API key de Resend.
- `BUYER_EMAIL_FROM`: remitente con dominio/sender verificado en Resend, por ejemplo `Admira IA <licenses@admiroia.uboost.lat>`.
- `BUYER_ACCESS_URL=https://admiroia.uboost.lat/access`.

Cuando Hotmart confirma una compra con `PURCHASE_APPROVED` / `APPROVED`:

1. El webhook valida `X-HOTMART-HOTTOK`.
2. Toma el email, nombre y transaccion de Hotmart.
3. Crea o reutiliza una licencia por `purchase.transaction`.
4. Envia el correo de bienvenida con licencia y link a `/access`.
5. El comprador entra con email + licencia en el portal.
6. El dashboard confirma licencia contra tu dominio.

Si Hotmart reintenta el mismo evento, no se duplica la licencia. Si llega reembolso, chargeback, cancelacion o bloqueo, el servidor revoca la licencia asociada a esa transaccion.

## Importante

Este servidor es deliberadamente simple para v1. Usa almacenamiento privado persistente, firmas asimétricas para licencias y tokens HMAC de corta duracion para descargas. El comprador recibe solo la clave pública; la clave privada y el secreto de descargas nunca salen de Vercel. Para una etapa SaaS futura conviene añadir panel de administración completo y rotación de secretos.
