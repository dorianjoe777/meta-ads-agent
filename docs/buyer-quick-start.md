# Inicio rapido

Este producto instala un manager IA para Meta Ads en tu PC o VPS. La idea es simple: el agente lee datos reales, te explica que esta pasando y prepara acciones. Las acciones que pueden gastar dinero pasan por aprobacion y, si activas Piloto automatico, solo se ejecutan dentro de las reglas que tu defines.

## 1. Instalar

Opcion mas facil con Docker:

Haz doble clic en el archivo de tu sistema:

- `Instalar en Windows.bat`
- `Instalar en Mac.command`
- `Instalar en Linux.desktop`

O usa terminal:

```bash
./scripts/run-docker.sh
```

Opcion local directa:

```bash
./scripts/install-local.sh
./scripts/run-dashboard.sh
```

Abre el dashboard en el enlace que muestra la terminal.

Si quieres verlo desde tu telefono mientras esta instalado en tu PC/Mac, entra a `Configuracion` y activa `Ver desde mi telefono`. El dashboard te dara un enlace para abrirlo en el celular. El celular debe estar conectado al mismo Wi-Fi o red local, y se sigue protegiendo con tu contrasena del dashboard.

## 2. Agregar licencia

Pega la licencia que recibiste por email con tu compra. Esa es la unica clave que te damos nosotros.

Para crear campanas, activar anuncios o usar Piloto automatico, la licencia debe aparecer como activa.

La licencia Individual trabaja con una sola cuenta publicitaria y una sola pagina de Facebook activas. Si cambias de negocio despues, el historial anterior se elimina para iniciar limpio. La licencia Agencia crea espacios separados para varios clientes y puede usarse en hasta 4 dispositivos.

Al comienzo del onboarding pega la web de tu negocio y cuentale al agente en que etapa estas, que te preocupa y que quieres mejorar. Antes de abrir el dashboard completo, el agente prepara un primer plan simple con lo que entendio de tu web y tus respuestas.

Al final del onboarding crearas tu propia contrasena del dashboard para proteger este computador o VPS.

## 3. Crear tu conexion privada con Meta

Usa los screenshots incluidos con tu compra. La idea es que el acceso quede bajo tu control:

1. Abre Meta Developers.
2. Crea tu propia app de Meta.
3. Agrega Marketing API o abre Graph API Explorer para esa app.
4. Genera un token con permisos de anuncios.
5. Pega el token en el dashboard local. Se guarda automaticamente en esta instalacion.
6. Toca `Buscar cuentas` y elige la cuenta publicitaria.

Esto es mas seguro para el comprador: el token nace en su propia cuenta de Meta, se guarda localmente en su PC/VPS y puede revocarlo desde Meta cuando quiera.

## 4. Conectar el modelo del agente

Durante el onboarding veras `Conectar el modelo del agente`. Tienes dos rutas:

- `Hermes + ChatGPT/Codex`: recomendado para usar una suscripcion de ChatGPT/Codex sin pegar una clave de OpenAI en el dashboard.
- `MiniMax M3` u otra `API compatible OpenAI`: recomendado si prefieres pagar por tokens de un proveedor externo.

Para la ruta recomendada, toca `Conectar ahora`. El dashboard intentara abrir la terminal y guiar el login de ChatGPT/Codex. Si esta instalado en DigitalOcean o Docker y no puede abrir una terminal visual, veras un plan B claro para hacerlo en el servidor.

Para MiniMax M3, el preset usa:

```text
URL: https://api.minimax.io/v1
Modelo: MiniMax-M3
```

Si tu proveedor usa otro nombre de modelo, cambia ese campo por el nombre exacto que te muestre su panel. La clave API queda guardada localmente en esta instalacion y no se muestra de vuelta en el dashboard.

Importante: esta configuracion cambia el cerebro conversacional del manager. Las imagenes finales de anuncios siguen usando el proveedor creativo configurado en `Creativos`, porque cada proveedor maneja imagenes con una API distinta.

## 5. Preparar guias creativas

En `Creativos`, toca `Crear guias base`. Esto crea:

- `brand_guides/general_branding.md`
- Un archivo en `brand_guides/products/` para tu producto principal.

Estas guias ayudan al agente a pedirle a Codex planes creativos, prompts de imagen y conceptos visuales consistentes. Si Codex CLI esta instalado y configurado, el agente puede apoyarse en Codex para pensar mejor los creativos y preparar prompts para el proveedor de imagen configurado. Codex no genera por si mismo una imagen dentro de este flujo v1.

Ver: `docs/es-codex-creativos.md`.

Si usas Docker, Codex CLI ya viene instalado dentro del contenedor, pero el puente queda apagado por defecto porque Codex es un agente local. Activalo solo si quieres esa funcion avanzada, comprendes su acceso local y configuras tu propia autenticacion.

Ver tambien: `docs/es-instaladores-doble-clic.md`.

Si haces la configuracion por terminal durante una llamada guiada, puedes usar:

```bash
social setup
social auth login
social marketing accounts
social marketing set-default-account act_XXXX
```

## 6. Configurar destino de anuncios

El onboarding intentara traer automaticamente tus paginas de Facebook, Instagram conectado y web. Normalmente solo eliges la pagina correcta y sigues.

Si algo no aparece, puedes guardarlo manualmente:

- Pagina de Facebook
- Instagram conectado, si aplica
- URL de tu web o landing

Estos datos permiten crear creativos, anuncios y campanas completas sin pedirte informacion tecnica cada vez.

## 7. Confirmar datos reales

Corre:

```bash
python3 src/daily_agent.py status
./scripts/run-daily-agent.sh
```

El dashboard debe mostrar `Datos reales de Meta`. Si ves datos demo, toca `Actualizar datos reales` y revisa token, cuenta y permisos.

## 8. Crear tu primera campana

Dile al agente algo como:

```text
Crea una campana para vender mi curso de reposteria con $20 diarios, para mujeres en Bogota, enviando a https://miweb.com.
```

El agente te preguntara solo lo que falte. Cuando este lista, dejara una tarjeta de aprobacion con lo que se va a crear: campana, conjunto, creativo y anuncio.

Si quieres que el anuncio quede activo y pueda gastar, la tarjeta debe decirlo claro y debes confirmar: `Si, crear y dejar activo`.

## 9. Con supervision vs Piloto automatico

`Con supervision` significa: el agente lee datos reales, explica y prepara acciones para que tu apruebes. Si apruebas una accion exacta, puede ejecutarla sin que tengas que encender el piloto automatico.

`Piloto automatico` significa: el agente puede ejecutar cambios permitidos por tus reglas. Campanas nuevas, creativos nuevos, reactivaciones y cambios grandes siguen pidiendo aprobacion.

---

# English quick start

Install with `./scripts/install-local.sh`, start with `./scripts/run-dashboard.sh`, enter the license key received by email, create your private Meta connection with your own Meta app/token, select the ad account, confirm real Meta data, create your own dashboard password at the end of onboarding, then enable autopilot only after reviewing approvals.
