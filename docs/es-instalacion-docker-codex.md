# Instalacion con Docker + Codex CLI

Esta es la forma mas simple para entregar el producto como paquete instalable: Docker trae casi todo lo necesario dentro de una imagen.

Incluye:

- Python para correr el dashboard y el agente.
- Node/npm para herramientas creativas.
- Codex CLI instalado dentro del contenedor.
- Dashboard en `http://127.0.0.1:7871`.
- Volumen persistente para configuracion, datos, logs, outputs y guias de marca.

## Requisito del comprador

El comprador solo necesita instalar:

- Docker Desktop en PC/Mac, o
- Docker Engine + Docker Compose en VPS.

Luego abre la carpeta instalada y ejecuta:

```bash
./scripts/run-docker.sh
```

Tambien puedes usar los instaladores de doble clic incluidos en la entrega del producto:

- `Instalar en Windows.bat`
- `Instalar en Mac.command`
- `Instalar en Linux.desktop`

El script hace esto:

1. Crea `.env` desde `.env.example` si no existe.
2. Construye la imagen Docker.
3. Instala dependencias dentro de la imagen.
4. Instala Codex CLI dentro de la imagen.
5. Arranca el dashboard.

Abrir:

```text
http://127.0.0.1:7871
```

## Donde se guarda todo

Docker usa volumenes persistentes:

- `meta_ads_config`: `.env` y `ad-config.json`
- `meta_ads_data`: datos del dashboard
- `meta_ads_output`: reportes, creativos y exports
- `meta_ads_logs`: logs
- `meta_ads_brand_guides`: guias de marca y producto

Esto significa que si apagas y prendes el contenedor, la configuracion no se pierde.

## Codex CLI

La imagen instala Codex CLI con npm:

```bash
npm install -g @openai/codex
```

Dentro del producto, el agente lo llama usando:

```env
CODEX_CREATIVE_ENABLED=false
CODEX_CLI=codex
```

Codex viene instalado como la ruta principal para creativos. Cuando el comprador conecta ChatGPT/Codex, el agente puede pedirle a Codex que cree imagenes finales, guardarlas dentro del dashboard y enviarlas como vista previa protegida.

Para activar la funcion opcional, cambia `CODEX_CREATIVE_ENABLED=true` y configura la autenticacion de Codex segun la cuenta del comprador. Evita guardar credenciales de OpenAI en archivos de marca o prompts. Si se usa una variable en `.env`, pertenece solo a la instalacion local/VPS del comprador:

```env
OPENAI_API_KEY=sk-...
```

Importante: esa clave queda en la instalacion local/VPS del comprador. No se incluye en el paquete base.

## Guias creativas

## Conectar ChatGPT al agente

Despues de instalar, el onboarding inicial empieza por conectar Facebook/Meta, luego conecta ChatGPT/Codex y despues Telegram. Si el comprador salta un paso o necesita revisarlo despues, puede volver desde `Configuracion`.

La tarjeta te guia con palabras simples:

1. Tocar `Conectar ahora` en el dashboard.
2. Si estas en PC/Mac y se abre una terminal, seguir esa ventana.
3. Si estas en DigitalOcean/VPS, el dashboard muestra el login seguro dentro del navegador.
4. Abrir el enlace de ChatGPT que aparezca, iniciar sesion con la cuenta ChatGPT del comprador y volver al dashboard.
5. Si el agente pide elegir proveedor/modelo, responder en la caja del dashboard.
6. Tocar `Revisar conexion`.

En DigitalOcean no hace falta abrir un navegador dentro del servidor ni entrar por SSH para este paso. El dashboard corre la conexion del agente dentro del Droplet usando el modo sin navegador:

```bash
hermes model --no-browser
```

Ese comando queda como referencia tecnica para soporte. El comprador deberia poder hacerlo desde el boton `Conectar ahora`.

El contenedor crea las guias base si no existen:

```text
brand_guides/general_branding.md
brand_guides/products/
```

Desde el dashboard:

1. Ir a `Creativos`.
2. Tocar `Crear guias base`.
3. Escribir el producto principal.
4. Editar las guias si hace falta.

Luego el agente puede usar esas guias para pedirle a Codex:

- planes de marketing;
- conceptos visuales;
- prompts consistentes;
- ideas para imagenes 1:1, 4:5 y 9:16;
- copies cortos para anuncios.

## VPS

En VPS, abre el dashboard con tunel SSH:

```bash
ssh -L 7871:127.0.0.1:7871 usuario@ip-del-servidor
```

Luego abre en tu navegador:

```text
http://127.0.0.1:7871
```

No expongas el puerto del dashboard directamente a internet salvo que sepas configurar HTTPS, firewall y proxy.

Si el comprador usa DigitalOcean y quiere abrir el dashboard desde una IP autorizada, usa el modo de acceso estricto:

```bash
./scripts/install-digitalocean-strict-access.sh
```

Ese modo actualiza el firewall de DigitalOcean despues de un login SSH exitoso. La guia completa esta en `docs/es-digitalocean-acceso-estricto.md`.

## Cuando usar Docker vs instalacion normal

Usa Docker si quieres la experiencia mas limpia para compradores no tecnicos.

Usa `./scripts/install-local.sh` si el comprador ya tiene Python/Node instalados y prefiere correr todo directamente en su PC/VPS.
