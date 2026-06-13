# Instaladores del producto

La entrega recomendada para compradores es **instalacion en contenedor Docker**. Los archivos de Mac, Windows y Linux son envoltorios faciles para descargar el producto, preparar Docker y abrir el dashboard; no son la promesa principal del producto.

Desde esta version, la forma recomendada de entrega es:

1. Mantener el codigo fuente en un repo privado.
2. Publicar un paquete fuente interno en GitHub Releases o en tu infraestructura privada.
3. Enviar al comprador email + clave de acceso despues de la compra.
4. El comprador entra a `https://admiroia.uboost.lat/access`.
5. Elige Mac, Windows o Linux y descarga el launcher de instalacion Docker desde una URL temporal segura.

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
LICENSE_SERVER_URL=https://admiroia.uboost.lat
LICENSE_RELEASE_ENDPOINT=/api/license/release
RELEASE_CHANNEL=stable
RELEASE_ASSET_NAME=MetaAdsAgent-source.zip
ALLOW_GITHUB_FALLBACK=false
```

Con eso, el portal y los instaladores primero hablan con tu servidor de licencias. Si la licencia es valida, el servidor devuelve una descarga firmada y temporal del paquete.

GitHub puede ser el origen tecnico del paquete, pero no es la experiencia que ve el comprador.

## Portal de descargas

URL recomendada para compradores:

```text
https://admiroia.uboost.lat/access
```

El comprador ve una landing simple:

- email de compra;
- clave de acceso recibida por email;
- botones para Mac, Windows y Linux orientados a Docker;
- version actual;
- mejoras incluidas.

La clave de acceso es la licencia, pero en la experiencia de comprador se presenta como una clave privada de descarga para que no suene tecnico.

## Mac con Docker

Archivo esperado:

```text
MetaAdsAgent-v1-mac.dmg
```

El comprador abre el DMG y luego abre:

```text
Admira IA.app
```

La app copia el producto a `~/Applications/Admira IA`, abre Docker Desktop si hace falta, crea la configuracion local si falta, levanta el contenedor en segundo plano y abre el dashboard en:

```text
http://127.0.0.1:7871
```

El `.pkg` sigue disponible como fallback tecnico. Para la venta principal, el punto importante no es `.dmg` vs `.pkg`: es que ambos deben llevar al comprador a correr el producto dentro de Docker.

## Windows con Docker

Archivo esperado:

```text
MetaAdsAgent-v1-windows.msi
```

El instalador copia el producto en la carpeta local del usuario y crea un acceso directo llamado `Meta Ads Agent`.

Al abrirlo por primera vez, intenta descargar la ultima version publicada desde tu servidor de licencias y luego levantar Docker. El comprador debe tener Docker Desktop instalado y abierto.

El `.exe` de NSIS y el `.msi` son envoltorios de instalacion. El comprador no deberia elegir "nativo vs Docker"; el producto debe empujarlo siempre a Docker, porque ahi vive la experiencia limpia, aislada y mas facil de soportar.

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

## Confianza del instalador

Para la ruta principal con Docker, la confianza viene de:

- contenedor aislado;
- servidor de licencias;
- descarga temporal segura;
- checksum de release;
- secretos guardados localmente;
- dashboard protegido por contrasena.

Firmar Mac/Windows es una capa extra para que el launcher se vea mas profesional, pero no debe bloquear el lanzamiento Docker-first. Si decides ofrecer instaladores nativos o wrappers publicos a gran escala:

- Mac puede usar `.dmg` con app firmada con `Developer ID Application` y notarizada por Apple.
- Windows puede usar `.msi` firmado con Authenticode.
- Linux debe incluir checksum `.sha256` y, si quieres una capa extra, firma GPG.

Ver:

```text
docs/es-firma-instaladores.md
```

## Para crear los launchers de instalacion

En Mac, launcher Docker:

```bash
MAC_APP_SIGN_IDENTITY="Developer ID Application: TU EMPRESA (TEAMID)" \
MAC_NOTARIZE=true \
APPLE_NOTARY_KEYCHAIN_PROFILE="meta-ads-agent-notary" \
META_ADS_LICENSE_SERVER_URL=https://admiroia.uboost.lat \
./scripts/build-mac-dmg.sh v1
```

Fallback PKG:

```bash
MAC_PKG_SIGN_IDENTITY="Developer ID Installer: TU EMPRESA (TEAMID)" \
MAC_NOTARIZE=true \
APPLE_NOTARY_KEYCHAIN_PROFILE="meta-ads-agent-notary" \
META_ADS_LICENSE_SERVER_URL=https://admiroia.uboost.lat \
./scripts/build-mac-pkg.sh v1
```

En Windows, launcher MSI/WiX:

```bash
WINDOWS_SIGN_MSI=true \
META_ADS_LICENSE_SERVER_URL=https://admiroia.uboost.lat \
./scripts/build-windows-msi.sh v1
```

Si WiX Toolset no esta instalado, el script deja listo un paquete fuente para compilar el `.msi` en una maquina Windows con WiX.

Launcher EXE con NSIS:

```bash
WINDOWS_SIGN_EXE=true \
META_ADS_LICENSE_SERVER_URL=https://admiroia.uboost.lat \
./scripts/build-windows-exe.sh v1
```

Si `makensis` no esta instalado, el script deja listo un paquete fuente para compilar el `.exe` en una maquina con NSIS.

En Linux:

```bash
META_ADS_LICENSE_SERVER_URL=https://admiroia.uboost.lat ./scripts/build-linux-bundle.sh v1
```

El script genera checksum. Si tienes llave GPG de publicacion:

```bash
LINUX_GPG_SIGN=true META_ADS_LICENSE_SERVER_URL=https://admiroia.uboost.lat ./scripts/build-linux-bundle.sh v1
```

Para generar el paquete fuente interno que descargan los instaladores:

```bash
META_ADS_LICENSE_SERVER_URL=https://admiroia.uboost.lat ./scripts/package-release.sh v1
```

## Asset tecnico recomendado para publicar

Publica siempre este asset estable:

```text
MetaAdsAgent-source.zip
```

El script de release tambien deja una copia versionada:

```text
MetaAdsAgent-v1.0.2-source.zip
```

## Flujo recomendado de publicacion

1. Generas el paquete fuente con `./scripts/package-release.sh v1.0.2`.
2. Subes `MetaAdsAgent-source.zip` como asset de una release privada en GitHub.
3. Registras en el servidor la URL API del asset privado, con formato `https://api.github.com/repos/OWNER/REPO/releases/assets/ASSET_ID`.
4. Registras esa release en tu servidor:

```bash
curl -X POST "https://admiroia.uboost.lat/api/admin/releases" \
  -H "Authorization: Bearer TU_CLAVE_ADMIN_PRIVADA" \
  -H "Content-Type: application/json" \
  -d '{
    "channel":"stable",
    "version":"v1.0.2",
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
