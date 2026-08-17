# Instalador de Admira IA en la nube para Windows

El archivo `Instalar Admira IA en la nube.bat` abre un asistente gráfico que:

1. valida el token de DigitalOcean sin enviarlo a otro servidor;
2. genera una clave SSH Ed25519 en `%LOCALAPPDATA%\Admira IA\cloud-installer`;
3. crea el Droplet, el firewall y el acceso SSH;
4. instala Docker, Admira IA y un swap de 2 GB cuando se elige el Droplet de 1 GB;
5. guarda la información mínima de conexión localmente;
6. crea `Admira IA - Cliente.url` en el escritorio y abre el onboarding.

La clave privada SSH permanece en el equipo del cliente. El token de DigitalOcean se usa durante el aprovisionamiento y no se incluye dentro de la aplicación instalada en el Droplet.

## Requisitos

- Windows 10/11 con PowerShell y OpenSSH Client (`ssh-keygen`, `ssh`, `scp`).
- Conexión a Internet.
- Un token de DigitalOcean con permisos para crear Droplets, claves SSH y firewalls.

La limpieza automática de multimedia no forma parte todavía de este instalador; se implementará como una fase independiente para proteger creativos usados y retirar únicamente borradores antiguos cuando el disco alcance un umbral.
