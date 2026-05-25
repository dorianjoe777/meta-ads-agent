# Servidor de licencias para vender v1

Este producto ya valida licencia desde el dashboard del comprador. Para vender rápido necesitas un endpoint propio en tu dominio.

## Qué resuelve

- El comprador recibe una sola licencia por email.
- El dashboard consulta tu dominio para confirmar que la licencia existe.
- Si tu dominio falla por unas horas, el comprador conserva un desbloqueo guardado en su equipo.
- Si la licencia no existe, está inactiva o supera el límite de equipos, se bloquean acciones reales y creación de campañas.

## Crear una licencia

```bash
curl -X POST "https://licencias-miro-ai.uboost.lat/api/admin/licenses" \
  -H "Authorization: Bearer TU_CLAVE_ADMIN_PRIVADA" \
  -H "Content-Type: application/json" \
  -d '{"buyer_email":"comprador@email.com","buyer_name":"Nombre del comprador","plan":"individual"}'
```

Para licencia Agencia, que permite hasta 4 dispositivos y espacios separados para varios clientes:

```bash
curl -X POST "https://licencias-miro-ai.uboost.lat/api/admin/licenses" \
  -H "Authorization: Bearer TU_CLAVE_ADMIN_PRIVADA" \
  -H "Content-Type: application/json" \
  -d '{"buyer_email":"agencia@email.com","buyer_name":"Nombre Agencia","plan":"agency"}'
```

El servidor mantiene un archivo privado por licencia para que una licencia nueva pueda activarse inmediatamente y registra cada dispositivo en un archivo privado separado para contar instalaciones sin depender de un JSON cacheado. Por el cache minimo de Vercel Blob, revocar o cambiar el plan de una licencia existente puede tardar hasta 60 segundos en reflejarse en nuevas activaciones.

## Configuración en el producto del comprador

En el `.env` de release debes definir:

```text
LICENSE_SERVER_URL=https://licencias-miro-ai.uboost.lat
LICENSE_PUBLIC_KEY=clave-publica-incluida-en-el-release
LICENSE_REQUIRED_FOR_LIVE=true
```

El dashboard llamará:

```text
POST https://licencias-miro-ai.uboost.lat/api/license/activate
```

## API ya desplegada en Vercel

La implementación de producción está en `seller/vercel-license-api` y usa un Blob privado de Vercel. Variables privadas del proyecto Vercel:

```text
LICENSE_PRIVATE_KEY_B64=clave-privada-solo-en-vercel
LICENSE_ADMIN_KEY=clave-de-administracion-solo-del-vendedor
LICENSE_UNLOCK_HOURS=168
BLOB_READ_WRITE_TOKEN=agregado-por-vercel-blob
```

Endpoint publicado:

```text
https://licencias-miro-ai.uboost.lat
```

## Operación diaria

Cuando Hotmart confirma una compra:

1. Tomas el email del comprador.
2. Creas la licencia contra el endpoint administrativo protegido usando tu clave admin.
3. Envías esa licencia en el email de bienvenida.
4. El comprador pega licencia + email en onboarding.
5. El dashboard confirma licencia contra tu dominio.

## Importante

Este servidor es deliberadamente simple para v1. Usa almacenamiento privado persistente y firmas asimétricas: el comprador recibe solo la clave pública; la clave privada nunca sale de Vercel. Para una etapa SaaS futura conviene añadir panel de administración y webhooks de Hotmart.
