# Instaladores del producto

La entrega recomendada para compradores es por instaladores segun sistema operativo.

Desde esta version, la forma recomendada de entrega es:

1. Mantener el codigo fuente en un repo privado.
2. Publicar un paquete fuente interno en GitHub Releases o en tu infraestructura privada.
3. Entregar al comprador un instalador que pide licencia + email y descarga una URL firmada desde tu dominio.

Asi separas dos cosas:

- tu repo privado para desarrollo
- tu servidor de licencias como puerta de acceso para compradores

Configuracion principal:

```text
installer/release-bootstrap.env
```

Valores clave:

```text
BOOTSTRAP_PROVIDER=license_server
LICENSE_SERVER_URL=https://licencias-miro-ai.uboost.lat
LICENSE_RELEASE_ENDPOINT=/api/license/release
RELEASE_CHANNEL=stable
RELEASE_ASSET_NAME=MetaAdsAgent-source.zip
ALLOW_GITHUB_FALLBACK=false
```

Con eso, los instaladores primero hablan con tu servidor de licencias. Si la licencia es valida, el servidor devuelve una descarga firmada y temporal del paquete.

GitHub puede ser el origen tecnico del paquete, pero no es la experiencia que ve el comprador.

## Mac

Archivo esperado:

```text
MetaAdsAgent-v1-mac.pkg
```

El comprador hace doble clic, instala el producto y luego abre:

```text
/Applications/Meta Ads Agent/Instalar en Mac.command
```

Ese archivo primero puede descargar la ultima version publicada desde tu servidor de licencias y despues levanta Docker, crea la configuracion local si falta y abre el dashboard en:

```text
http://127.0.0.1:7871
```

## Windows

Archivo esperado:

```text
MetaAdsAgent-v1-windows.exe
```

El instalador copia el producto en la carpeta local del usuario y crea un acceso directo llamado `Meta Ads Agent`.

Al abrirlo por primera vez, intenta descargar la ultima version publicada desde tu servidor de licencias y luego levantar Docker. El comprador debe tener Docker Desktop instalado y abierto.

## Linux

Archivo esperado:

```text
MetaAdsAgent-v1-linux.tar.gz
```

El comprador descomprime el archivo y ejecuta:

```bash
./Instalar\ en\ Linux.sh
```

Ese script puede descargar la ultima version publicada desde tu servidor de licencias antes de correr el dashboard local.

## Requisitos

- Docker Desktop en Windows/Mac.
- Docker Engine y Docker Compose en Linux.
- Internet para validar licencia, conectar Meta, descargar la imagen inicial y bajar la ultima version publicada desde tu servidor.
- Licencia enviada por email al comprador.

## Para crear los instaladores

En Mac:

```bash
META_ADS_LICENSE_SERVER_URL=https://licencias-miro-ai.uboost.lat ./scripts/build-mac-pkg.sh v1
```

En Windows, usando NSIS:

```bash
META_ADS_LICENSE_SERVER_URL=https://licencias-miro-ai.uboost.lat ./scripts/build-windows-exe.sh v1
```

Si `makensis` no esta instalado, el script deja listo un paquete fuente para compilar el `.exe` en una maquina con NSIS.

En Linux:

```bash
META_ADS_LICENSE_SERVER_URL=https://licencias-miro-ai.uboost.lat ./scripts/build-linux-bundle.sh v1
```

Para generar el paquete fuente interno que descargan los instaladores:

```bash
META_ADS_LICENSE_SERVER_URL=https://licencias-miro-ai.uboost.lat ./scripts/package-release.sh v1
```

## Asset tecnico recomendado para publicar

Publica siempre este asset estable:

```text
MetaAdsAgent-source.zip
```

El script de release tambien deja una copia versionada:

```text
MetaAdsAgent-v1.0.1-source.zip
```

## Flujo recomendado de publicacion

1. Generas el paquete fuente con `./scripts/package-release.sh v1.0.1`.
2. Subes `MetaAdsAgent-source.zip` como asset de una release privada en GitHub.
3. Registras en el servidor la URL API del asset privado, con formato `https://api.github.com/repos/OWNER/REPO/releases/assets/ASSET_ID`.
4. Registras esa release en tu servidor:

```bash
curl -X POST "https://licencias-miro-ai.uboost.lat/api/admin/releases" \
  -H "Authorization: Bearer TU_CLAVE_ADMIN_PRIVADA" \
  -H "Content-Type: application/json" \
  -d '{
    "channel":"stable",
    "version":"v1.0.1",
    "asset_name":"MetaAdsAgent-source.zip",
    "filename":"MetaAdsAgent-source.zip",
    "source_url":"https://api.github.com/repos/OWNER/REPO/releases/assets/ASSET_ID",
    "improvements":[
      {
        "title":"Mejor onboarding para compradores nuevos",
        "body":"Menos lenguaje tecnico y pasos mas claros para conectar Meta.",
        "impact":"Instalacion"
      },
      {
        "title":"Manager mas confiable",
        "body":"Mejoras en aprobaciones, chat y protecciones antes de acciones reales.",
        "impact":"Operaciones"
      }
    ]
  }'
```

5. El comprador ejecuta el instalador.
6. El instalador pide licencia + email.
7. Tu servidor entrega una URL firmada de corta duracion.
8. El servidor descarga el asset privado desde GitHub con token server-side y entrega el paquete sin exponer el repo privado.
9. El instalador actualiza la instalacion y conserva `.env`, `ad-config.json` y datos locales del comprador.

## Nota importante

Los instaladores y el paquete fuente interno no incluyen claves, tokens, datos del comprador, logs ni resultados generados. Todo eso se crea o se conserva localmente despues de la instalacion.
