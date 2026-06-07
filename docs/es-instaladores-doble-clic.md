# Launchers de doble clic

Esta entrega usa launchers simples para compradores no tecnicos. Su trabajo no es instalar una app nativa compleja: su trabajo es levantar el producto dentro de Docker.

## Windows

Archivo:

```text
MetaAdsAgent-v1-windows.msi
```

Uso:

1. Instala Docker Desktop.
2. Abre Docker Desktop y espera que diga `Running`.
3. Abre el instalador `.msi` que recibiste.
4. Abre el acceso directo `Meta Ads Agent`.
5. Cuando termine de preparar todo, abre:

```text
http://127.0.0.1:7871
```

El archivo `Instalar en Windows.bat` queda dentro de la instalacion como motor tecnico, pero el comprador no deberia tener que buscarlo.

## Mac

Archivo:

```text
MetaAdsAgent-v1-mac.dmg
```

Uso:

1. Instala Docker Desktop.
2. Abre Docker Desktop y espera que diga `Running`.
3. Abre el `.dmg` que recibiste.
4. Abre `Meta Ads Agent.app`.
5. Cuando termine de preparar todo, abre:

```text
http://127.0.0.1:7871
```

Para venta publica, el `.dmg` debe llevar una app firmada y notarizada. Si estas probando un build interno sin firma, macOS puede pedir permiso extra en Privacidad y Seguridad. Eso no debe ser la experiencia normal del comprador.

El archivo `Instalar en Mac.command` queda dentro de la instalacion como motor tecnico, pero el comprador no deberia tener que buscarlo.

## Linux

Archivos:

```text
Instalar en Linux.sh
Instalar en Linux.desktop
```

Uso:

1. Instala Docker Engine y Docker Compose.
2. Abre la carpeta que dejó lista el instalador.
3. Haz doble clic en `Instalar en Linux.desktop` si tu entorno lo permite.
4. Si no, abre terminal en la carpeta y ejecuta:

```bash
./Instalar\ en\ Linux.sh
```

Luego abre:

```text
http://127.0.0.1:7871
```

## Que hacen estos instaladores

Los instaladores no guardan claves ni datos del comprador dentro del paquete base.

Ellos:

- crean `.env` desde `.env.example` si falta;
- levantan Docker Compose;
- construyen una imagen con Python, Node/npm y Codex CLI;
- crean volumenes persistentes para datos, logs, outputs y guias de marca;
- arrancan el dashboard local.

## Confianza del instalador

La confianza principal de la ruta recomendada viene de Docker, licencia, descarga temporal segura y checksums. La firma de Mac/Windows es una capa extra para que el launcher se vea mejor ante el sistema operativo, especialmente si se distribuye masivamente:

```text
docs/es-firma-instaladores.md
```

Si no hay firma todavia, la venta puede seguir empujando la ruta Docker. Los usuarios avanzados que pidan instalacion nativa entenderan mejor esos avisos.

## Importante

Si se cierra la ventana del instalador, el dashboard puede apagarse. Para uso continuo en VPS se recomienda correrlo con Docker en segundo plano o instalar el servicio systemd.
