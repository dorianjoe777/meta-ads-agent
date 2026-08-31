# Estado actual del dashboard de operador

Este documento es el punto de control conciso del **dashboard privado del
operador** que está desplegado en Contabo. No es un dashboard para compradores
y no convierte el panel en una URL pública. La fecha/hora de la última lectura
directa del VPS fue `2026-09-01T00:08:10Z`.

## Despliegue live verificado

| Elemento | Estado |
| --- | --- |
| Release activo del VPS | `d1bef249927c96e38cbd1ccd51bad1fe17f31b00` |
| Imagen inmutable del dashboard | `admira-ia-hosted:r91-canary-e6fa64f85138` |
| Contenedor del dashboard | En ejecución; `GET /` respondió `200` |
| Broker de runtimes | `admira-runtime-broker.service` activo |
| Provisioner de lifecycle | `admira-tenant-provisioner.service` activo |
| Broker central de imágenes | Activo mediante el perfil `central-images`; socket Unix presente |
| Readiness central | `ADMIRA_CENTRAL_IMAGE_READY=true`; workers recreados con la bandera nueva |
| API de licencias | Salud `ok`; backend Upstash y Blob configurados |
| Imagen de tenants existentes | `canary-one` y clientes: `admira-ia:r90`; `canary-two`/`canary-three`: r91 canary pinneado |
| Pool central ChatGPT/Codex | Dos slots privados (`primary`, `secondary`), ambos con autenticación presente |
| Migraciones del control plane | `001`–`013`, verificadas al promover el release |
| Backup recuperable | `/srv/admira/backups/operator-lifecycle-caeb723-20260831T201433Z/` |

El marcador `d1bef…` y la imagen `e6fa…` no indican dos dashboards distintos.
`d1bef…` contiene la corrección de Compose que permite montar la clave del
provisioner sin tocar el directorio de socket de sólo lectura; la interfaz y
backend del dashboard permanecen en la imagen inmutable `e6fa…`. Se comprobaron
los hashes de `operator_dashboard.html`, `operator_dashboard.js` y
`operator_dashboard.py` entre la imagen live y el código fuente: son iguales.

## Acceso práctico y persistente desde este Mac

El panel real vive sólo en el loopback del VPS (`127.0.0.1:8791`). No se publica
en Internet porque permite altas, expiraciones y licencias.

En el Mac configurado se instaló el LaunchAgent por usuario
`com.admira.operator-dashboard-tunnel`. Mantiene el túnel
`127.0.0.1:18793` → VPS `127.0.0.1:8791`, arranca al iniciar sesión y se
reconecta si SSH se cae o el Mac despierta. La URL fija
`http://127.0.0.1:18793/` es una vista segura del **panel live del VPS**, no una
aplicación local ni una URL pública.

El agente usa la llave existente sólo con autenticación de clave pública,
verificación estricta del host, `BatchMode`, `ExitOnForwardFailure`, keepalive y
sin agent forwarding. Su plist está en
`/Users/macminim1/Library/LaunchAgents/com.admira.operator-dashboard-tunnel.plist`
con modo `0600`; registra sólo errores SSH en una carpeta `0700` y enlaza sólo
el loopback, por lo que ni la LAN ni Internet pueden abrir el panel.

El servicio sólo puede estar activo cuando este Mac está encendido y el usuario
ha iniciado sesión; esa es la alternativa segura a instalar un daemon root. Para
verificarlo o reiniciarlo sin tocar el VPS:

```bash
launchctl print gui/$(id -u)/com.admira.operator-dashboard-tunnel
launchctl kickstart -k gui/$(id -u)/com.admira.operator-dashboard-tunnel
```

El launcher [open-operator-dashboard.command](open-operator-dashboard.command)
sigue disponible como respaldo manual; elige un puerto temporal distinto y no
debe ser necesario mientras el LaunchAgent esté sano.

Para el uso diario también existe el acceso directo
`/Users/macminim1/Desktop/Admira Operator Dashboard.app`. Al abrirlo, comprueba
que el LaunchAgent esté cargado, solicita su reconexión, espera hasta veinte
segundos por el loopback y abre la URL fija en el navegador. No crea un túnel
adicional ni publica ningún puerto. El antiguo `127.0.0.1:18792` era un puerto
temporal del launcher manual y no debe usarse como enlace permanente.

## Qué contiene el panel live

La interfaz tiene las pestañas separadas **Pruebas** y **Licenciadas**. Las
rutas y assets que se verificaron en el contenedor live permiten:

1. Crear la cuenta real de un cliente como prueba; los cinco días exactos se
   anclan a `tenant.created_at`.
2. Asignar una entrada sana del pool Gemini antes de emitir el claim.
3. Mostrar o reemitir el enlace temporal de Telegram sin mover el vencimiento.
4. Ampliar a una fecha exacta futura o caducar manualmente la prueba; caducar
   suspende el runtime de forma fail-closed.
5. Convertir la misma cuenta, aun vencida, a licenciada con la Gemini API key
   del cliente. El provisioner llama al bridge Vercel, que crea un registro
   idempotente en Upstash; el panel entrega el código una sola vez.
6. Conservar tenant, historial, binding Telegram y ChatGPT personal. La
   conversión no reinicia los cinco días de imágenes patrocinadas.

La pestaña **Licenciadas** muestra sólo metadatos seguros: cliente, referencia
de licencia redactada, fecha de licencia, fecha efectiva de patrocinio y estado.
Nunca muestra API keys, correo, autenticación ChatGPT ni el código completo otra
vez.

## Inventario observado en el snapshot

Estos números no incluyen secretos ni nombres de clientes:

| Inventario | Valor |
| --- | --- |
| Cuentas en **Pruebas** | 3 |
| Estados de esas pruebas | 3 `trial` (canarios reservados) |
| Cuentas en **Licenciadas** | 0 |
| Proyectos Gemini saludables registrados | 1 |
| Credenciales Gemini activas/saludables | 1 |
| Capacidad saludable declarada de prueba | 2 |
| Asignaciones Gemini de pool activas | 2 (canarios reservados; capacidad 2/2) |
| Slots centrales ChatGPT/Codex | 2 (`primary`, `secondary`) |

El mecanismo central está live para tenants que tengan el cliente r91 y una
entitlement patrocinada. La capacidad Gemini registrada actual está ocupada
2/2 por los canarios; hay que liberar o ampliar capacidad antes de crear una
prueba de cliente real. Todavía no representa el objetivo operativo de al menos
tres altas nuevas por día ni quince pruebas simultáneas. Antes de ofrecer ese
volumen hay que registrar y verificar más capacidad Gemini en el panel, sin
copiar claves a chat, Git o PostgreSQL.

## Canary central de imágenes verificado

`canary-two` es un tenant reservado sin binding de Telegram; se promovió de
r90 a `admira-ia-hosted:r91-canary-e6fa64f85138` sólo para esta comprobación.
Con su ruta `central_sponsored` se ejecutó una generación real y el cliente
recuperó un PNG válido de 810157 bytes. El mismo `update_id` se repitió después:
el ledger devolvió el trabajo ya `succeeded` sin otra llamada al proveedor y la
idempotencia quedó verificada. El archivo de entitlement temporal se eliminó al
finalizar.

`canary-three` se creó como segundo tenant reservado, recibió su Gemini del
pool y también quedó pinneado a r91. La función de claims de la migración 013
se corrigió para calificar `tenant_telegram_claims.tenant_id`; se verificó la
reemisión de ambos enlaces sin reiniciar el reloj de cinco días. Sus claims
siguen pendientes de consumo en Telegram.

El binding de Telegram de `canary-one` fue revocado a petición del operador el
`2026-09-01T00:07Z` para liberar el chat de prueba y permitir su reclamación por
`canary-two`. Se conservaron el tenant, el historial, las credenciales y los
archivos; sólo se eliminó el binding activo. No había mensajes pendientes en la
cola de salida y el evento quedó registrado como `telegram_binding_revoked`.
El poller se detuvo durante la transacción y volvió a quedar activo después.

La prueba sintética también verificó aislamiento HMAC entre tenants y el
fallback del selector de dos cuentas. No se provocó deliberadamente un límite
real de ChatGPT para probar fallback externo, porque eso consumiría créditos o
forzaría un fallo; ambas autenticaciones permanecen instaladas y privadas.

## Lo que está configurado y lo que sigue pendiente

Configurado: contraseña de operador (hash privado), panel, broker, provisioner,
base de datos/migraciones, el bridge de licencia, un proyecto Gemini saludable,
el broker central activo y el canary real de imágenes aprobado.

Pendiente deliberadamente:

- Ejecutar la entrevista y el flujo real de Facebook (Página, cuenta
  publicitaria y permisos) en Telegram para cada canario; requiere un
  `channel_id` distinto por tenant.
- Recuperación por correo/Telegram: `ADMIRA_TELEGRAM_RECOVERY_READY=false`.
- La prueba de capacidad/colas (soak) para el volumen comercial.
- Probar una caída real de una cuenta central no forma parte del smoke test;
  el fallback de dos slots ya está cubierto por la prueba sintética y la
  selección permanece limitada a dos intentos por solicitud.

El dashboard no recibe Docker, el árbol de tenants, el token del bot, las API
keys del pool ni la clave del bridge. Sus mutaciones cruzan únicamente un socket
Unix HMAC hacia el provisioner host-only.

## Alcance de la evidencia

Esta lectura verificó el contenedor, HTTP, servicios, flags, inventario
secret-free y presencia de las rutas/UI. La promoción del canary pasó el
preflight del servidor; el broker central pasó la prueba sintética, la
generación real y la repetición idempotente. No se creó ni licenció un cliente
real ni se expuso ninguna identidad Telegram; `canary-two` sigue reservado para
pruebas operativas.
