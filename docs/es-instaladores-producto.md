# Instaladores del producto

Este producto puede entregarse como ZIP simple o como instaladores por sistema operativo.

Desde esta version conviene publicarlo en GitHub Releases para que los instaladores descarguen siempre la version publicada mas reciente del producto.

Configuracion recomendada antes de publicar:

```text
installer/release-bootstrap.env
```

Valores clave:

```text
BOOTSTRAP_FROM_GITHUB=true
GITHUB_RELEASE_REPO=tu-org/tu-repo
GITHUB_SOURCE_ASSET=MetaAdsAgent-source.zip
GITHUB_RELEASE_CHANNEL=latest
```

Con eso, los instaladores intentan bajar el asset publicado en GitHub. Si ese repo no esta configurado, usan la copia incluida como respaldo.

## Mac

Archivo esperado:

```text
MetaAdsAgent-v1-mac.pkg
```

El comprador hace doble clic, instala el producto y luego abre:

```text
/Applications/Meta Ads Agent/Instalar en Mac.command
```

Ese archivo primero puede descargar la ultima version publicada desde GitHub y despues levanta Docker, crea la configuracion local si falta y abre el dashboard en:

```text
http://127.0.0.1:7871
```

## Windows

Archivo esperado:

```text
MetaAdsAgent-v1-windows.exe
```

El instalador copia el producto en la carpeta local del usuario y crea un acceso directo llamado `Meta Ads Agent`.

Al abrirlo por primera vez, intenta descargar la ultima version publicada desde GitHub y luego levantar Docker. El comprador debe tener Docker Desktop instalado y abierto.

## Linux

Archivo esperado:

```text
MetaAdsAgent-v1-linux.tar.gz
```

El comprador descomprime el archivo y ejecuta:

```bash
./Instalar\ en\ Linux.sh
```

Ese script puede descargar la ultima version publicada desde GitHub antes de correr el dashboard local.

## Requisitos

- Docker Desktop en Windows/Mac.
- Docker Engine y Docker Compose en Linux.
- Internet para validar licencia, conectar Meta, descargar la imagen inicial y, si activas bootstrap, bajar la ultima version publicada desde GitHub.
- Licencia enviada por email al comprador.

## Para crear los instaladores

En Mac:

```bash
META_ADS_GITHUB_REPO=tu-org/tu-repo ./scripts/build-mac-pkg.sh v1
```

En Windows, usando NSIS:

```bash
META_ADS_GITHUB_REPO=tu-org/tu-repo ./scripts/build-windows-exe.sh v1
```

Si `makensis` no esta instalado, el script deja listo un ZIP fuente para compilar el `.exe` en una maquina con NSIS.

En Linux:

```bash
META_ADS_GITHUB_REPO=tu-org/tu-repo ./scripts/build-linux-bundle.sh v1
```

Para el ZIP fuente que vas a subir a GitHub Releases:

```bash
META_ADS_GITHUB_REPO=tu-org/tu-repo ./scripts/package-release.sh v1
```

## Asset recomendado para GitHub Releases

Publica siempre este asset estable:

```text
MetaAdsAgent-source.zip
```

El script de release tambien deja una copia versionada:

```text
MetaAdsAgent-v1-source.zip
```

## Nota importante

Los instaladores y el ZIP de release no incluyen claves, tokens, datos del comprador, logs ni resultados generados. Todo eso se crea o se conserva localmente despues de la instalacion.
