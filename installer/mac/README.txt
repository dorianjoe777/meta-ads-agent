ADMIRA IA — INSTALADOR PARA macOS

El DMG contiene «Admira IA Installer.app», una interfaz gráfica normal de macOS.
No tienes que abrir Terminal ni ejecutar archivos .command.

La interfaz descarga e instala Docker Desktop oficial para Apple Silicon o Intel,
espera a que Docker esté listo, solicita el correo y licencia de compra, descarga
el paquete autorizado, construye el contenedor y abre el dashboard.

Al finalizar crea en el Escritorio:

  Admira IA Dashboard - correo@cliente.webloc

Ese acceso directo solo abre el dashboard en el navegador; Docker y Admira IA
quedan ejecutándose en segundo plano.

Puedes cerrar sesión o reiniciar el Mac. La continuación se registra con un
LaunchAgent de usuario y retoma la instalación al iniciar sesión otra vez.

Si macOS bloquea la app, haz clic derecho sobre «Admira IA Installer.app» → Abrir.
Este instalador aún no está firmado ni notarizado por Apple; para distribución
masiva debe firmarse con Developer ID y notarizarse.
