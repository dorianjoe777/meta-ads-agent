# Firma de launchers e instaladores avanzados

Esta guia no cambia la decision principal del producto: **la ruta vendible recomendada es Docker/contenedor**. Mac, Windows y Linux reciben launchers que preparan Docker y abren el dashboard. La firma es una capa de presentacion para esos launchers o para instalaciones nativas avanzadas, no el nucleo del producto.

Esta guia existe para entender avisos como `desarrollador no verificado`, `Unknown Publisher` o SmartScreen cuando distribuyes launchers de escritorio. La solucion profesional para eliminar o reducir esos avisos es firmar con certificados oficiales, pero para v1 no debe bloquear la venta si el comprador usa Docker como camino principal.

## Que pasa si no firmamos

En Mac, un `.pkg`, `.dmg`, `.app` o `.command` sin firma y sin notarizacion puede pedir al comprador ir a Privacidad y Seguridad para permitir la instalacion.

Fallback temporal para compradores Mac mientras no haya firma/notarizacion:

1. Abrir `Configuracion del Sistema`.
2. Entrar a `Privacidad y seguridad`.
3. Bajar hasta la seccion `Seguridad`.
4. Hacer clic en `Abrir de todos modos` para `Admira IA`.
5. Confirmar y abrir `Admira IA.app` otra vez.

No presentar esto como la experiencia ideal. Es solo el camino temporal para builds sin firma. La solucion profesional sigue siendo firmar el `.app`, crear el `.dmg`, notarizarlo con Apple y hacer `staple` del ticket.

En Windows, un `.exe` o `.msi` sin firma puede aparecer como editor desconocido y activar SmartScreen.

En Linux, normalmente no aparece el mismo aviso visual, pero el comprador tecnico puede querer checksum o firma GPG para confirmar que el archivo no fue cambiado.

## Mac launcher: DMG con app

Para la ruta Docker-first, el DMG es solo una forma comoda de abrir el instalador:

```text
MetaAdsAgent-v1.0.2-mac.dmg
```

Ese DMG contiene `Admira IA.app`. Al abrirla, copia el producto a:

```text
~/Applications/Admira IA
```

Despues levanta Docker directamente en segundo plano y abre el dashboard local en el navegador. Asi el comprador no tiene que buscar archivos raros dentro de una carpeta ni mirar una terminal.

Necesitas:

- cuenta Apple Developer Program;
- certificado `Developer ID Application`;
- Xcode Command Line Tools;
- credenciales de notarizacion de Apple.

Ejemplo:

```bash
MAC_APP_SIGN_IDENTITY="Developer ID Application: TU EMPRESA (TEAMID)" \
MAC_NOTARIZE=true \
APPLE_NOTARY_KEYCHAIN_PROFILE="meta-ads-agent-notary" \
./scripts/build-mac-dmg.sh v1.0.2
```

El script firma la app, crea el `.dmg`, lo envia a notarizacion con `notarytool`, le pega el ticket con `stapler` y genera un `.sha256`.

## Mac fallback: PKG

Necesitas:

- cuenta Apple Developer Program;
- certificado `Developer ID Installer`;
- Xcode Command Line Tools;
- credenciales de notarizacion de Apple.

Ejemplo:

```bash
MAC_PKG_SIGN_IDENTITY="Developer ID Installer: TU EMPRESA (TEAMID)" \
MAC_NOTARIZE=true \
APPLE_ID="tu-email@empresa.com" \
APPLE_TEAM_ID="TEAMID" \
APPLE_APP_SPECIFIC_PASSWORD="xxxx-xxxx-xxxx-xxxx" \
./scripts/build-mac-pkg.sh v1.0.2
```

Alternativa recomendada para CI:

```bash
MAC_PKG_SIGN_IDENTITY="Developer ID Installer: TU EMPRESA (TEAMID)" \
MAC_NOTARIZE=true \
APPLE_NOTARY_KEYCHAIN_PROFILE="meta-ads-agent-notary" \
./scripts/build-mac-pkg.sh v1.0.2
```

El script firma el `.pkg`, lo envia a notarizacion con `notarytool`, le pega el ticket con `stapler` y genera un `.sha256`.

Usa `.pkg` si quieres una instalacion clasica en `/Applications`. Usa `.dmg` si quieres una experiencia mas familiar para compradores no tecnicos.

## Windows launcher: MSI

Para la ruta Docker-first, el MSI es solo una forma comoda de copiar archivos y crear acceso directo:

```text
MetaAdsAgent-v1.0.2-windows.msi
```

El `.msi` se siente mas normal para instalacion empresarial y crea accesos directos sin presentar el producto como un ejecutable suelto. Despues, el producto sigue corriendo en Docker.

Necesitas una de estas opciones:

- Azure Trusted Signing / Azure Artifact Signing;
- certificado OV o EV de firma de codigo;
- Windows SDK con `signtool.exe`;
- WiX Toolset para compilar el `.msi`.

Ejemplo MSI:

```bash
WINDOWS_SIGN_MSI=true \
WINDOWS_SIGNING_CERT_PATH="C:/certs/meta-ads-agent.pfx" \
WINDOWS_SIGNING_CERT_PASSWORD="password-del-certificado" \
./scripts/build-windows-msi.sh v1.0.2
```

## Windows fallback: EXE

Ejemplo con certificado `.pfx`:

```bash
WINDOWS_SIGN_EXE=true \
WINDOWS_SIGNING_CERT_PATH="C:/certs/meta-ads-agent.pfx" \
WINDOWS_SIGNING_CERT_PASSWORD="password-del-certificado" \
WINDOWS_TIMESTAMP_URL="http://timestamp.digicert.com" \
./scripts/build-windows-exe.sh v1.0.2
```

Ejemplo si el certificado ya esta instalado en Windows:

```bash
WINDOWS_SIGN_EXE=true \
./scripts/build-windows-exe.sh v1.0.2
```

Importante: aun con firma, SmartScreen puede mostrar aviso en las primeras descargas porque Windows tambien mira reputacion del archivo y del editor. La firma cambia el mensaje de `editor desconocido` a un editor verificable, y la reputacion mejora con uso real.

## Linux

El script genera checksum automaticamente:

```bash
./scripts/build-linux-bundle.sh v1.0.2
```

Para agregar firma GPG:

```bash
LINUX_GPG_SIGN=true ./scripts/build-linux-bundle.sh v1.0.2
```

## Que entregar al comprador

Para la venta principal:

- Mac: launcher que lleva a Docker.
- Windows: launcher que lleva a Docker.
- Linux/VPS: bundle que levanta Docker Compose.
- Checksums visibles para confirmar integridad.

Para una entrega avanzada o mas corporativa:

- Mac: `.dmg` con app firmada, notarizada y stapled.
- Windows: `.msi` firmado con Authenticode.
- Linux: `.tar.gz` con `.sha256` y, si aplica, `.asc`.

Mantener `.pkg`, `.exe` o instalacion nativa como fallback esta bien, pero no deberian ser la primera experiencia para compradores no tecnicos.

No prometas `sin ningun aviso` en Windows al principio. Lo honesto es: `instalador firmado por el editor`, y luego construir reputacion de descarga.

## Checklist antes de publicar

1. Crear build limpio.
2. Confirmar que el launcher empuja a Docker.
3. Firmar/notarizar solo si vas a publicar wrappers de escritorio como experiencia masiva.
4. Generar checksum.
5. Probar en una maquina limpia.
6. Subir solo los instaladores finales al release.
7. Registrar la version estable en el servidor de licencias.
