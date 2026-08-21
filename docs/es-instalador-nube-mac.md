# Instalador de Admira IA en DigitalOcean para macOS

El DMG `AdmiraIA-CloudInstaller-mac` ofrece una instalación cloud con interfaz gráfica nativa de macOS. No requiere abrir Terminal ni instalar Docker Desktop en el Mac: Docker se instala dentro del Droplet remoto.

El asistente solicita:

- correo utilizado para comprar Admira IA;
- licencia de Admira IA;
- token personal de DigitalOcean;
- tamaño y región del Droplet.

Después valida la licencia, genera una clave SSH Ed25519 en el Llavero/almacenamiento local del usuario, crea el Droplet y el firewall, sube el paquete autorizado, instala Docker y arranca Admira IA con Compose. Para el Droplet de 1 GB configura temporalmente un swap de 2 GB para que la primera construcción tenga memoria suficiente.

Al finalizar:

- abre el onboarding remoto en el navegador;
- crea `Admira IA Dashboard.webloc` en el Escritorio;
- guarda la clave privada SSH en `~/Library/Application Support/Admira IA/Cloud Installer/keys/`;
- elimina del Llavero el token de DigitalOcean y la licencia temporal.

Si el Mac se reinicia mientras la instalación está en curso, el estado del trabajo se conserva por licencia y un LaunchAgent vuelve a abrir la interfaz para continuar sin crear un Droplet duplicado. Los diagnósticos quedan en `~/Library/Application Support/Admira IA/Cloud Installer/install.log`.

## Instalador interno por Terminal

Para pruebas personales existe `AdmiraIA-Cloud-Installer-v*.command`. Al hacer doble clic abre Terminal, solicita correo, licencia, token de DigitalOcean, tamaño y región, y ejecuta el mismo motor cloud sin abrir la interfaz gráfica. También conserva la reanudación automática con `--resume`; no es un archivo destinado a compradores.

El DMG de distribución debe firmarse con Developer ID y notarizarse antes de entregarlo a compradores. Sin firma, macOS puede requerir clic derecho → Abrir la primera vez.
