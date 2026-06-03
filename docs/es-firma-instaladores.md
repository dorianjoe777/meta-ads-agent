# Firma de instaladores

Esta guia existe para evitar que el comprador vea avisos raros como `desarrollador no verificado`, `Unknown Publisher` o bloqueos de seguridad.

La solucion real no es esconder el aviso. La solucion profesional es firmar los instaladores con certificados oficiales.

## Que pasa si no firmamos

En Mac, un `.pkg`, `.dmg`, `.app` o `.command` sin firma y sin notarizacion puede pedir al comprador ir a Privacidad y Seguridad para permitir la instalacion.

En Windows, un `.exe` o `.msi` sin firma puede aparecer como editor desconocido y activar SmartScreen.

En Linux, normalmente no aparece el mismo aviso visual, pero el comprador tecnico puede querer checksum o firma GPG para confirmar que el archivo no fue cambiado.

## Mac recomendado: DMG con app launcher

Para venta publica, la experiencia recomendada es:

```text
MetaAdsAgent-v1.0.2-mac.dmg
```

Ese DMG contiene `Meta Ads Agent.app`. Al abrirla, copia el producto a:

```text
~/Applications/Meta Ads Agent
```

Despues abre Terminal con el instalador local. Asi el comprador no tiene que buscar archivos raros dentro de una carpeta.

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

## Windows recomendado: MSI

Para venta publica, la experiencia recomendada es:

```text
MetaAdsAgent-v1.0.2-windows.msi
```

El `.msi` se siente mas normal para instalacion empresarial y crea accesos directos sin presentar el producto como un ejecutable suelto.

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

Para una entrega profesional:

- Mac: `.dmg` con app firmada, notarizada y stapled.
- Windows: `.msi` firmado con Authenticode.
- Linux: `.tar.gz` con `.sha256` y, si aplica, `.asc`.

Mantener `.pkg` y `.exe` como fallback esta bien, pero no deberian ser la primera experiencia para compradores no tecnicos.

No prometas `sin ningun aviso` en Windows al principio. Lo honesto es: `instalador firmado por el editor`, y luego construir reputacion de descarga.

## Checklist antes de publicar

1. Crear build limpio.
2. Firmar instalador.
3. Notarizar Mac.
4. Generar checksum.
5. Probar en una maquina limpia.
6. Subir solo los instaladores finales al release.
7. Registrar la version estable en el servidor de licencias.
