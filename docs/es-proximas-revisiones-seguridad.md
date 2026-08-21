# Proximas revisiones de seguridad

Este documento deja anotados los puntos que deben revisarse en futuros debug/security passes del producto. La idea es que cada revision mantenga claro que protege Docker, que protege el navegador y que cosas no se deben prometer al comprador.

## Docker ayuda, pero no reemplaza CSP

Docker es una capa muy buena para el producto porque:

- Aisla el proceso del dashboard del resto del sistema del comprador.
- Reduce errores de instalacion entre Mac, Windows, Linux y VPS.
- Permite persistir solo lo necesario mediante volumenes controlados.
- Evita que el comprador tenga que instalar dependencias sueltas en su sistema.

Pero Docker no resuelve todo. Si el dashboard renderiza contenido inseguro en el navegador, ese codigo corre en el navegador del comprador, no dentro del contenedor. Por eso CSP sigue importando.

Ejemplo:

- Docker protege archivos/procesos del servidor local.
- CSP reduce el impacto de una posible inyeccion de JavaScript en el navegador.

Estado actual: el dashboard principal ya carga CSS y JavaScript desde archivos propios:

- `public/dashboard/dashboard.css`
- `public/dashboard/dashboard.js`
- `public/dashboard/local-disabled.css`
- `public/dashboard/login-wait.css`

La CSP del dashboard ya no permite bloques `<script>` ni `<style>` inline, ni atributos de evento como `onclick`, ni atributos de estilo HTML. La politica actual usa `script-src-attr 'none'` y `style-src-attr 'none'`.

Los botones dinamicos usan delegacion de eventos con `data-action-code` y una lista permitida de funciones conocidas. No se usa `eval` ni `new Function`. Las barras/posiciones dinamicas usan `data-style-code` y un aplicador controlado por JavaScript con propiedades permitidas.

## Proximo hardening recomendado

1. Auditar todos los usos de `innerHTML` y exigir `escapeHtml` o render por DOM seguro.
2. Revisar que todo link dinamico use `http/https` solamente.
3. Mantener `npm audit --omit=dev` en raiz y portal antes de cada release.
4. Mantener pruebas de path traversal para creativos, uploads, backups y updates.
5. Verificar que `dashboard/data`, `output`, `.env`, logs y seller no entren en releases compradores.
6. Si algun dia se agregan librerias externas, preferir Subresource Integrity, hashes o empaquetado local antes de permitir dominios externos en CSP.

## Exposicion publica del dashboard

Recomendacion de producto:

- Instalacion local: mantener el dashboard accesible solo desde la misma maquina.
- Acceso desde telefono: activar solo la opcion LAN desde Configuracion, y usarlo solo en la misma red Wi-Fi.
- No exponer el dashboard local a internet con port forwarding, ngrok, tuneles publicos o reglas de router caseras.
- Para acceso remoto, preferir DigitalOcean/cloud con el flujo oficial, firewall y HTTPS.

Copy recomendado para compradores:

> Para mayor seguridad, no expongas tu dashboard local a internet. Usalo en Docker desde tu equipo, o activa "ver desde mi telefono" solo para la misma red Wi-Fi. Si necesitas acceso remoto real, usa la instalacion cloud recomendada.

## Checklist de cada revision de seguridad

- Confirmar que el dashboard no guarda contrasenas reales en `localStorage`.
- Confirmar que las sesiones recordadas son tokens opacos y se guardan hasheadas.
- Confirmar permisos `0600` en `.env` cuando se escribe desde el dashboard.
- Confirmar que uploads y manifiestos solo leen dentro de `output/`.
- Confirmar que backups/updates validan paths, symlinks y tamano antes de extraer.
- Confirmar que el portal no renderiza links dinamicos no-http.
- Confirmar auditoria de dependencias sin vulnerabilidades conocidas.
- Confirmar suite principal pasando completo antes de publicar.
