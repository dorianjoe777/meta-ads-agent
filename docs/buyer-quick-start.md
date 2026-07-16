# Inicio rapido

Este producto instala un manager IA para Meta Ads en tu PC o VPS. La idea es simple: el agente lee datos reales, te explica que esta pasando y prepara acciones. Las acciones que pueden gastar dinero pasan por aprobacion y, si activas Piloto automatico, solo se ejecutan dentro de las reglas que tu defines.

## 1. Instalar

Opcion mas facil con Docker:

Descarga el instalador de tu sistema desde la pagina de acceso:

- Mac: abre el `.dmg` y luego `Admira IA.app`.
- Windows: abre el instalador de Windows y luego el acceso directo `Meta Ads Agent`.
- Linux: abre el bundle de Linux o usa `Instalar en Linux.desktop`.

En Mac no abras `Instalar en Mac.command` como paso principal. Ese archivo queda dentro del producto como motor tecnico; la experiencia normal debe ser abrir la app del `.dmg`, que prepara Docker por ti.

Si macOS muestra un aviso de seguridad al abrir `Admira IA.app`, haz esto:

1. Abre `Configuracion del Sistema`.
2. Entra a `Privacidad y seguridad`.
3. Baja hasta la parte de `Seguridad`.
4. Toca `Abrir de todos modos` para `Admira IA`.
5. Vuelve a abrir `Admira IA.app`.

Ese aviso puede aparecer en esta version porque el launcher de Mac todavia no esta firmado por Apple. El producto sigue corriendo dentro de Docker en tu propio equipo.

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

Usa los screenshots incluidos con tu compra. La idea es que el acceso quede bajo tu control. Tienes dos opciones:

**Opcion recomendada: conexion estable**

1. Abre Meta Business Settings.
2. Crea un `Usuario del sistema` para Admira.
3. Dale acceso a tu cuenta publicitaria y a tu pagina de Facebook.
4. Genera una clave estable para ese Usuario del sistema con permisos de anuncios y paginas.
5. Pega la clave en el dashboard local. Se guarda automaticamente en esta instalacion.
6. Toca `Buscar mis cuentas` y elige la cuenta publicitaria.

Esto es mas seguro para el comprador: la clave nace en su propio Meta Business, se guarda localmente en su PC/VPS y puede revocarla desde Meta cuando quiera.

**Opcion rapida: empezar hoy**

Tambien puedes usar Graph API Explorer si quieres avanzar mas rapido o si todavia no tienes acceso al dueño del Business Portfolio. Esta clave puede vencer, por eso Admira te avisara para renovarla aproximadamente cada 60 dias. Mas adelante puedes ir a `Configuracion` y cambiarla por una clave estable.

## 4. Conectar el modelo del agente

Durante el onboarding veras `Conectar el modelo del agente`. Tienes varias formas de darle cerebro al manager, pero la infraestructura del agente siempre es la misma: memoria, herramientas y aprobaciones.

- `ChatGPT/Codex`: recomendado para usar una suscripcion de ChatGPT/Codex sin pegar una clave de OpenAI en el dashboard.
- `NVIDIA NIM`: usa una API key de build.nvidia.com y carga automaticamente los modelos disponibles en esa cuenta mediante el catalogo oficial.
- `MiniMax M3` u otra `API compatible OpenAI`: recomendado si prefieres pagar por tokens de un proveedor externo.

Para la ruta recomendada, toca `Conectar ahora`. El dashboard intentara abrir la terminal y guiar el login de ChatGPT/Codex. Si esta instalado en DigitalOcean o Docker y no puede abrir una terminal visual, veras un plan B claro para hacerlo en el servidor.

Para MiniMax M3, el preset usa:

```text
URL: https://api.minimax.io/v1
Modelo: MiniMax-M3
```

Para NVIDIA NIM, el endpoint queda fijo en `https://integrate.api.nvidia.com/v1`. Toca `Cargar modelos de NVIDIA` despues de pegar la clave para consultar el catalogo vivo; la clave no se guarda dentro del cache del catalogo. El acceso alojado gratuito o promocional depende de las cuotas vigentes de NVIDIA y puede devolver limites 429.

Si tu proveedor usa otro nombre de modelo, cambia ese campo por el nombre exacto que te muestre su panel. La clave API queda guardada localmente en esta instalacion y no se muestra de vuelta en el dashboard.

Importante: esta configuracion cambia el cerebro conversacional del manager, no sus reglas. Las imagenes finales de anuncios se crean con Codex/Image usando tu conexion ChatGPT/Codex.

## 5. Preparar guias creativas

En `Creativos`, toca `Crear guias base`. Esto crea:

- `brand_guides/general_branding.md`
- Un archivo en `brand_guides/products/` para tu producto principal.

Estas guias ayudan al agente a preparar conceptos visuales consistentes. Cuando pides una imagen final, el agente usa la misma conexion ChatGPT/Codex que configuraste para hablar con el manager; no necesitas contratar otra API de imagenes.

Ver: `docs/es-codex-creativos.md`.

Si usas Docker, la conexion ChatGPT/Codex queda dentro del contenedor y se mantiene para chat e imagenes. Si cambias de equipo o reinstalas, vuelve a conectar ChatGPT/Codex desde el onboarding o desde `Configuracion`.

Ver tambien: `docs/es-instaladores-doble-clic.md`.

Durante la configuración guiada, pega la clave de Meta en el dashboard y elige la cuenta publicitaria desde la lista que trae Meta Graph.

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
