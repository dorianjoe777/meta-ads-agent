# Instaladores de doble clic

El ZIP incluye instaladores simples para compradores no tecnicos.

## Windows

Archivo:

```text
Instalar en Windows.bat
```

Uso:

1. Instala Docker Desktop.
2. Abre Docker Desktop y espera que diga `Running`.
3. Descomprime el ZIP del producto.
4. Haz doble clic en `Instalar en Windows.bat`.
5. Cuando termine de construir, abre:

```text
http://127.0.0.1:7871
```

## Mac

Archivo:

```text
Instalar en Mac.command
```

Uso:

1. Instala Docker Desktop.
2. Abre Docker Desktop y espera que diga `Running`.
3. Descomprime el ZIP del producto.
4. Haz doble clic en `Instalar en Mac.command`.
5. Cuando termine de construir, abre:

```text
http://127.0.0.1:7871
```

Si macOS muestra una advertencia de seguridad, haz clic derecho sobre el archivo, elige `Abrir` y confirma.

## Linux

Archivos:

```text
Instalar en Linux.sh
Instalar en Linux.desktop
```

Uso:

1. Instala Docker Engine y Docker Compose.
2. Descomprime el ZIP del producto.
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

Los instaladores no guardan claves ni datos del comprador dentro del ZIP.

Ellos:

- crean `.env` desde `.env.example` si falta;
- levantan Docker Compose;
- construyen una imagen con Python, Node/npm y Codex CLI;
- crean volumenes persistentes para datos, logs, outputs y guias de marca;
- arrancan el dashboard local.

## Importante

Si se cierra la ventana del instalador, el dashboard puede apagarse. Para uso continuo en VPS se recomienda correrlo con Docker en segundo plano o instalar el servicio systemd.
