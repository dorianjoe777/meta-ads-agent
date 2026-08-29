# Admira hosted runtime: estado y runbook operativo

Este documento describe exactamente dónde quedó la infraestructura de
alojamiento multiusuario y cómo operarla de forma segura. Es el complemento
operativo de [`README.md`](./README.md). Documenta el procedimiento de canary,
pero no lo da por aprobado ni autoriza tráfico real por sí solo.

El alcance comercial de esta fase es únicamente el bot central de Telegram con
un runtime Admira/Hermes privado por comprador. No se publica dashboard al
comprador y no se están construyendo API pública, webhooks, CRM, ecommerce,
CLI de cliente ni servidor MCP oficial. Las tablas auxiliares que ya existen no
convierten este despliegue en el futuro producto SaaS.

## 1. Punto de control actual

Último estado de código verificado antes de esta documentación:

| Elemento | Valor |
| --- | --- |
| Rama de trabajo | `feat/contabo-multitenant` |
| Último commit funcional desplegado | `3babd8b7989827512dea0ceeb8234cb99aa41312` |
| SHA exacto activo | `/srv/admira/control-plane/DEPLOYED_COMMIT` |
| Imagen de cada tenant | `admira-ia:r90` |
| Commit de la imagen tenant | `d03707465a5fedf7e5d1bb6b528365b299795540` |
| Manifiesto de la imagen tenant | `5df0e07e8b4a10e59a5b9c3659336f9b3a55ab556beaa67c2faba218dabc99db` |
| Servidor | Contabo Cloud VPS 4, Ubuntu 24.04, Docker 29.1.3 |
| Bot central canario | `@admiraia_bot` (`bot_id=8884068904`) |
| Estado de compradores | **Canary activo**: cuatro servicios singleton, un `runtime-worker`, un binding canario y un claim privado pendiente |

El 29 de agosto de 2026 se recuperó el acceso SSH autorizado y se desplegó el
commit funcional `a11ea43` desde un archive verificado por SHA-256. Se guardó
un dump validado de PostgreSQL y una copia recuperable del release anterior en
`/srv/admira/backups/deploy-a11ea43-20260829T152412Z/`; después se aplicaron las
cuatro migraciones, se reconstruyó la imagen compartida de workers y se
reinició el broker con el código nuevo.

`DEPLOYED_COMMIT` es la fuente autoritativa del SHA exacto activo y puede incluir
un commit posterior limitado a documentación.

El 29 de agosto de 2026 también se desplegó `d4766cb` desde un archive y
manifiesto verificados. Antes del cambio se creó y validó el backup
`/srv/admira/backups/deploy-d4766cb-20260829T163522Z/`. La migración 005, el
registro seguro de claims por stdin y la cadencia durable del bot compartido
quedaron activos; el perfil `buyers` se arrancó con exactamente una réplica de
cada worker después del gate de servidor. En ese corte inicial, los dos claims
canarios todavía estaban sin consumir. Después, `canary-one` se vinculó durante
la prueba real descrita abajo; `canary-two` continúa reservado y sin binding.

El token instalado sirve sólo para este canary. Como el valor original pasó
por una conversación de soporte, se debe revocar/rotar en BotFather e instalar
el reemplazo por un canal fuera del chat antes de admitir compradores reales.

El primer mensaje real descubrió que `ProtectHome=true` impedía a la CLI de
Docker localizar Compose cuando el broker intentaba despertar un tenant. El
commit `e607f04` conserva esa protección y configura un `DOCKER_CONFIG` vacío,
efímero y privado en `/run/admira-runtime-broker/docker-config` (directorio
0700, archivo 0600). También conserva códigos operativos seguros como
`runtime_start_failed`, sin devolver stderr de Docker. Después del despliegue
se suspendió `canary-one` y el broker lo despertó por sí mismo con cero
reinicios; luego se recuperó únicamente el update `Hola`. Los dos `/start`
fallidos quedaron `dead` deliberadamente para no duplicar la bienvenida.

El 29 de agosto de 2026 se desplegó después `3babd8b` desde un archive con 28
archivos verificados. Antes del cambio se guardaron y validaron el dump
PostgreSQL y el release anterior en
`/srv/admira/backups/deploy-3babd8b-20260829T225759Z/`; desde ese release se
reconstruyó además la imagen etiquetada de reversión. La migración 006 quedó
aplicada, el broker reinició con normal/hard `4/4` y los cuatro servicios del
control plane quedaron en la imagen nueva con cero reinicios. El perfil live
continúa deliberadamente con un solo `runtime-worker`; el perfil 6/8 sigue sin
activar hasta completar el soak.

## 2. Qué se construyó

La arquitectura separa un plano de control central de los runtimes de cada
cliente. Hay una sola instancia de los servicios de coordinación y una imagen
inmutable compartida, pero cada cliente conserva su propio proceso, memoria,
sesión, credenciales y archivos.

```text
Telegram
   │
   ▼
telegram-poller ──(DB: inbox durable)──► runtime-worker
   │                                        │
   │                                        │ HMAC + Unix socket
   │                                        ▼
   │                              admira-runtime-broker (host)
   │                                        │
   │                         ┌─────────────┴─────────────┐
   │                         ▼                           ▼
   │                 runtime tenant A              runtime tenant B
   │                 (admira-ia:r90)               (admira-ia:r90)
   │                         │                           │
   └──── telegram-delivery ◄┴──── DB: outbox ordenado ───┘

scheduler-worker ──► broker ──► runtime tenant ──► cron de Hermes ──► outbox
```

Componentes de coordinación:

- **PostgreSQL 16**: fuente durable de tenants, bindings, entitlement/trial,
  inbox, outbox, leases, jobs, ejecuciones y auditoría.
- **Redis 7**: coordinación transitoria; nunca es la fuente de verdad.
- **`telegram-poller`**: único proceso que recibe el token de Telegram para
  leer mensajes y medios entrantes.
- **`runtime-worker`**: reclama turnos de la inbox y llama al broker; no tiene
  token de Telegram ni acceso al socket de Docker.
- **`telegram-delivery`**: único segundo proceso con token de Telegram; entrega
  texto y medios desde la outbox, en orden y con comprobación SHA-256.
- **`scheduler-worker`**: reclama jobs de Hermes, despierta el tenant y guarda
  la respuesta en la misma outbox; no tiene token de Telegram.
- **`admira-runtime-broker.service`**: servicio systemd en el host y único
  dueño del socket Docker. Expone sólo `turn`, `run_job`, `sync_jobs`,
  `suspend` y `status` mediante un socket Unix autenticado con HMAC.

## 3. Cómo se resuelve cada usuario

El bot central no copia su token a los tenants. La resolución es:

```text
(bot_id, chat_id, user_id)
        │
        ▼
tenant_telegram_bindings ──► tenant_id UUID ──► runtime_key privado
```

El primer vínculo se realiza con un claim de un solo uso:

1. El operador provisiona el directorio privado y emite un claim con TTL.
2. El operador entrega un deep-link de Telegram (`/start <claim>`).
3. El poller valida el DM, consume el claim en una transacción y crea el
   binding `(bot_id, chat_id, user_id)`.
4. Sólo se conserva el hash SHA-256 del claim; el valor original no entra en la
   inbox, en los archivos del tenant ni en el contexto del modelo.
5. Se encola un mensaje de bienvenida. La creación del claim no inicia el
   runtime ni activa compradores.

Ejemplo de operación host-only (no imprime ni requiere el token del bot):

```bash
cd /srv/admira/control-plane
./tenant_admin.py claim buyer-001 "Nombre del comprador" \
  --bot-username NombreDelBotCentral --ttl-seconds 1800
```

El resultado contiene un `telegram_url` de un solo uso. Se debe entregar al
comprador por un canal seguro y no pegarlo en logs públicos. El TTL permitido
es de 300 a 86.400 segundos (30 minutos es el valor predeterminado).

El comando de soporte `bind` existe cuando ya se conocen los IDs públicos:

```bash
./tenant_admin.py bind buyer-001 "Nombre del comprador" BOT_ID CHAT_ID USER_ID
```

La instalación está deliberadamente diseñada para un bot central y una
identidad de Telegram por tenant. No se debe intentar convertir esta fase en
un sistema multiempresa dentro del mismo tenant; para empezar desde cero se
crea otro tenant o se usa el flujo de reset del producto.

## 4. Recorrido de un mensaje y de un medio

### Entrada

1. `telegram-poller` llama `getUpdates`, valida que sea un mensaje privado y
   limita texto a 5.000 caracteres y cada archivo a 50 MiB.
2. El medio se descarga a un nombre aleatorio del spool de entrada; nunca se
   acepta una ruta enviada por el usuario.
3. `ingest_telegram_update` guarda una actualización sanitizada. La clave
   `(bot_id, update_id)` evita duplicados.
4. `runtime-worker` reclama la fila con lease y fencing token. Sólo se procesa
   un turno activo por tenant.
5. El worker adquiere el lease del runtime y envía al broker un sobre HMAC con
   nonce, timestamp, request ID y acción permitida.

### Runtime aislado

El broker provisiona/despierta el tenant con `tenantctl.py` y ejecuta
`tenant_turn.py` dentro del contenedor ya iniciado. La sesión de Hermes es
estable por chat y por generación de conversación:

```text
agent:main:telegram:dm:<chat_id>:g<N>
```

`/restart`, `/reset`, `/nuevo` y `/new` incrementan sólo esa generación: abren
una conversación fresca sin borrar Meta, memoria de negocio ni archivos. Los
comandos `/conectar_chatgpt`, `/reconectar_chatgpt` y la respuesta pendiente
`Listo`/`Done` se resuelven antes del modelo. `/resetear_completamente` exige la
frase exacta dentro del TTL, ligada a `chat_id`, `user_id` y `update_id`; el
broker detiene el runtime, ejecuta el borrado en un contenedor efímero con la
imagen `r90` fijada y vuelve a arrancarlo. Conserva licencia y conexión del
modelo, pero borra Meta, negocio, memoria, sesiones, archivos y cronjobs sólo
de ese tenant.

Después de un reset exitoso queda un recibo host-only ligado a la misma
identidad/update. Si el worker muere o pierde la respuesta del socket antes de
confirmar la inbox, el reintento devuelve el mismo éxito sin enviar la frase
destructiva al modelo. El recibo se escribe primero como `in_progress` y luego
como `completed`; una interrupción reanuda el reset idempotente. Si durante la
recuperación todos los slots ya están ocupados, termina el reset y deja el
tenant dormido hasta que haya capacidad. Repetir un `/restart` por lease o
socket perdido tampoco rota la sesión dos veces: `update_id` hace idempotente
esa generación.

El puente sólo permite materializaciones de medios bajo
`/app/output/telegram_uploads/`. Las líneas `MEDIA:` se extraen de la respuesta
y se devuelven al host para ser copiadas al spool de salida con referencia
opaca y SHA-256.

Las imágenes llegan como visión; los videos producen como máximo cuatro frames
representativos y los PDF siguen el contrato existente de documento/catálogo.
Los formatos no inspeccionables provocan una solicitud segura de reenvío. Las
copias temporales del medio dentro del tenant se eliminan al terminar el turno.
Si Telegram no permite descargar un archivo, el poller reintenta dos veces y
encola de forma durable un mensaje de reenvío sin IDs ni rutas internas. Un
fallo de PostgreSQL nunca avanza el cursor de Telegram.

### Salida

1. PostgreSQL divide el texto en partes de hasta 4.000 caracteres y encola
   primero texto y después medios, con `dispatch_order` global y orden por
   chat.
2. `telegram-delivery` reclama la outbox con lease. Verifica bot ID, referencia
   opaca, que el archivo sea regular/no symlink y su SHA-256 mientras lo lee en
   bloques de 1 MiB.
3. Sólo después de un ACK con fencing válido se elimina el medio de salida.
4. El texto puede tener hasta 262.144 bytes por respuesta y ocho medios por
   turno; los excesos se rechazan de forma segura.

## 5. Aislamiento de cada tenant

Cada cliente tiene exactamente este árbol en el host:

```text
/srv/admira/tenants/<tenant_id>/
├── runtime/       # HERMES_HOME, CODEX_HOME y .env privado
├── data/          # memoria, OAuth y estado del producto
├── output/        # creativos y materializaciones del tenant
├── brand_guides/  # logo y guías aprobadas
├── logs/          # logs de ese runtime
├── compose.yaml   # definición host-only de ese tenant
└── .hosted-reset-receipt.json  # opcional, host-only e idempotencia de reset
```

Los cinco directorios son los únicos mounts del contenedor. El recibo opcional
vive fuera de esos mounts, modo 0600, y contiene sólo estado/identidad de
idempotencia; nunca contiene tokens ni contenido del comprador.

`tenantctl.py` genera `/srv/admira/tenants/<tenant_id>/compose.yaml` con un
proyecto único `admira-tenant-<tenant_id>`, sin puertos publicados, sin token de
Telegram, sin socket Docker y sin mounts hacia otro tenant. El contenedor usa
`restart: "no"`: el host no despierta todos los tenants después de un reboot.

El entorno inicial queda así (las credenciales se agregan sólo durante el
onboarding del cliente):

```text
META_ADS_AGENT_MODE=dry-run
LIVE_ACTIONS_ENABLED=false
TELEGRAM_AGENT_ENABLED=false
AGENT_BRAIN_PROVIDER=gemini
AGENT_CHAT_MODEL=gemini-3.5-flash-lite
HERMES_HOME=/app/runtime/hermes
CODEX_HOME=/app/runtime/hermes/codex-auth
HERMES_MODEL=gpt-5.6-luna
HERMES_MODEL_USER_SELECTED=false
HERMES_RESPONSE_TIMEOUT_SECONDS=300
HERMES_TIMEOUT_SECONDS=300
```

`GEMINI_API_KEY` empieza vacío. Si
`secrets/hosted_gemini_api_key.txt` contiene un archivo regular privado 0600,
el instalador lo coloca fuera del control plane y `tenantctl.py` lo copia sólo
al `.env` vacío de tenants nuevos; nunca reemplaza la elección del comprador ni
lo añade al Compose. Usar esa opción convierte el consumo y posible abuso de
esa clave compartida en responsabilidad del operador. La opción de menor
acoplamiento es dejarla vacía y hacer que cada comprador use
`/conectar_chatgpt` desde Telegram.

El entrypoint enlaza `/app/runtime/.env` a `/app/.env`, por lo que el runtime sí
consume ese archivo persistente sin `env_file:` (que expondría valores mediante
la inspección de Docker).

La imagen `r90` es código compartido de sólo lectura lógica. Lo mutable vive
en los cinco directorios del tenant. Suspender un tenant ejecuta `docker compose
down --remove-orphans` sin `--volumes`, por lo que no borra sesiones ni memoria.

## 6. Seguridad, roles y secretos

### PostgreSQL y RLS

Las migraciones son idempotentes y se aplican en orden:

```text
db/migrations/001_initial_multitenant.sql
db/migrations/002_telegram_ingress_control.sql
db/migrations/003_hosted_tenant_registration.sql
db/migrations/004_active_tenant_runtime_gate.sql
db/migrations/005_telegram_rate_limit_retry.sql
db/migrations/006_runtime_capacity_queue.sql
```

La migración 004 exige estado `active` para nuevas decisiones de claim y lease.
Una fila que quedó encolada no despierta deliberadamente un tenant que ya era
inactivo al reclamar/adquirir el runtime. Este gate no cancela trabajo que ya
estaba en vuelo durante el cambio exacto de estado; para una revocación
estricta, primero se drenan los workers del tenant y después se cambia su
estado.

La migración 005 trata `telegram_rate_limited` como backpressure del proveedor,
no como un fallo terminal: conserva la fila de outbox en `retry` aunque supere
el presupuesto normal de intentos. El delivery respeta el `retry_after`
acotado que entrega Telegram, pausa globalmente nuevos envíos y además limita
la cadencia global y por chat; errores distintos conservan su límite normal y
pueden terminar en `dead` para no reintentarse eternamente.

La migración 006 separa la espera por capacidad de un fallo real de ejecución.
`tenant_busy`, `runtime_capacity_exhausted` y
`runtime_capacity_headroom_low` devuelven el turno o cronjob a una cola durable,
incrementan `capacity_deferrals` y revierten el incremento del contador finito
de intentos. También implementa el claim LRU con fencing: sólo un worker puede
reclamar un runtime sin holder ni trabajo elegible, y un claim `stopping`
abandonado se recupera automáticamente al expirar.

Las tablas con `tenant_id` tienen RLS activado y forzado. El contexto
`admira.tenant_id` es fail-closed cuando no está definido. Los roles de servicio
son `NOLOGIN` y sólo exponen funciones necesarias; los logins son:

```text
admira_ingress_login
admira_runtime_login
admira_delivery_login
admira_scheduler_login
admira_provisioner_login
```

`admira_control_owner` es el dueño confiable de migraciones/funciones. No se
debe otorgar `BYPASSRLS` a ningún worker.

### Archivos sensibles

`deploy/contabo/secrets/` es privado, con modo 0600 y git-ignored. Contiene:

```text
postgres_password.txt
redis_users.acl
ingress_db_password.txt
runtime_db_password.txt
delivery_db_password.txt
scheduler_db_password.txt
provisioner_db_password.txt
runtime_broker_key.txt
telegram_bot_token.txt
hosted_gemini_api_key.txt       # opcional; vacío por defecto
```

El token central debe permanecer vacío hasta la activación explícita. El
init-container copia las contraseñas de servicio a un volumen privado de
PostgreSQL propiedad de UID 999; así no se relaja el modo de los secretos del
host. El bootstrap de roles se transmite por stdin para evitar el problema de
inodos obsoletos de mounts de un solo archivo durante una actualización.

### Red y privilegios

- La red `control_private` es interna y no publica puertos.
- Sólo poller y delivery se conectan a `telegram_egress`.
- Sólo runtime y scheduler reciben el grupo/socket del broker.
- Los workers usan UID/GID 1001, filesystem raíz de sólo lectura, tmpfs,
  `no-new-privileges`, todas las capabilities retiradas y límites de CPU/RAM.
- El broker systemd es el único proceso con acceso al socket Docker.
- `broker.lock` impide ejecutar dos brokers a la vez y saltarse el límite de
  admisión durante un despliegue o reinicio.

## 7. Rutas importantes en el servidor

```text
/srv/admira/control-plane/                  # copia desplegada del plano de control
/srv/admira/tenants/<tenant_id>/             # estado persistente por tenant
/srv/admira/shared/telegram-spool/inbound/  # medios entrantes (GID 19092)
/srv/admira/shared/telegram-spool/outbound/ # medios salientes (GID 19092)
/run/admira-runtime-broker/broker.sock      # socket HMAC (GID 19091, modo 660)
/run/admira-runtime-broker/broker.lock      # exclusión de instancia, modo 600
/run/admira-runtime-broker/docker-config/   # config CLI privada; permite Compose con ProtectHome
/etc/admira/runtime-broker.key              # clave del servicio systemd (modo 600)
/etc/admira/hosted-gemini-api-key           # proveedor opcional para tenants nuevos
/srv/admira/backups/                         # dumps y copias de recuperación
```

La carpeta `control-plane` debe contener una marca `DEPLOYED_COMMIT` después de
cada despliegue. Las carpetas de release intermedias se mueven a backups con
modo restrictivo; no se copian archivos sueltos desde una versión anterior.

## 8. Último estado verificado de la instalación Contabo

La siguiente verificación se hizo sobre el servidor Contabo
(`169.58.246.232`) después de desplegar `3babd8b`:

- Host `vmi3537882`; Docker responde correctamente.
- PostgreSQL y Redis están activos y saludables.
- `admira-runtime-broker.service` está activo y escucha en el socket indicado.
- Los spools existen con el grupo de servicio correcto.
- El token de `@admiraia_bot` está instalado con modo 0600, no se imprime en
  los gates y no existe dentro de ningún tenant.
- Hay exactamente una réplica en ejecución y cero reinicios de
  `telegram-poller`, `runtime-worker`, `telegram-delivery` y
  `scheduler-worker`; sus logs de arranque no muestran conflicto, excepción ni
  error de autorización.
- PostgreSQL contiene dos tenants: `canary-one` tiene un binding, su `Hola`
  está `processed` y todos sus envíos tienen ACK de Telegram; `canary-two`
  conserva un claim sin usar y cero bindings. No hay inbox/outbox pendientes.
- Los dos updates `/start` que agotaron intentos durante el fallo inicial
  permanecen `dead`; no se reencolaron porque la bienvenida ya había sido
  entregada. La recuperación transaccional seleccionó exactamente un `Hola`
  sin outbox previo y conservó su contador de intentos.
- Las migraciones 004, 005 y 006 están aplicadas. El gate activo del tenant, la
  rama durable de `telegram_rate_limited`, los contadores separados de espera
  por capacidad y los claims LRU con fencing son visibles en las funciones
  reales. Live conserva un `runtime-worker` y normal/hard `4/4`; el perfil 6/8
  descrito más abajo sigue siendo candidato y no está activado.
- La imagen compartida `admira-control-plane:r1` fue reconstruida y
  `admira-ia:r90` sigue presente y fijada para los tenants.
- Los 28 archivos versionados coinciden con el manifiesto del release; ambos
  marcadores remotos quedaron reconciliados con `3babd8b`.
- El dump PostgreSQL previo se validó con `pg_restore --list`; el código y las
  dos copias recuperables del control plane previo están en
  `/srv/admira/backups/deploy-3babd8b-20260829T225759Z/`. Las raíces tenant no
  se modificaron durante este despliegue; los secretos y `.env` del release
  activo conservaron permisos privados.

Esto significa que la infraestructura y el bot ya completaron un turno real
con la identidad canaria vinculada a `canary-one`. `canary-two` continúa sin
identidad y no hay compradores reales; esa reserva es intencional hasta poder
probar el aislamiento con una segunda cuenta de Telegram.

## 9. Procedimiento de instalación inicial

Ejecutar en una copia revisada del repositorio, como el usuario del servicio;
usar `sudo` sólo para instalar el broker:

```bash
cd /srv/admira/control-plane
./bootstrap-control-plane.sh
./apply-control-plane.sh
sudo ./install-runtime-broker.sh
docker compose --profile buyers config --quiet
./release-preflight.sh --local
```

El comando `docker compose ... config` valida el perfil sin arrancarlo; el
preflight local valida el candidato sin exigir todavía un token real ni
tenants canarios. Antes de una activación se debe comprobar:

```bash
test ! -s secrets/telegram_bot_token.txt
systemctl is-active --quiet admira-runtime-broker.service
docker compose ps
```

## 10. Activación controlada de compradores

La activación es un cambio deliberado y separado de la instalación:

1. Instalar el token real en `secrets/telegram_bot_token.txt` usando un método
   que no lo deje en el historial ni en la salida de shell.
2. Provisionar dos tenants canarios controlados por el operador, emitir un
   claim distinto para cada uno, pero no compartir todavía los deep-links.
3. Ejecutar el gate de servidor antes de arrancar `buyers`:

   ```bash
   ./release-preflight.sh --server --tenant-a canary-one --tenant-b canary-two
   ```

   El preflight es sólo lectura: comprueba archivos, sintaxis, Compose,
   permisos sin imprimir tokens, broker/socket, imagen fijada, migración
   visible y las dos raíces canarias. No crea tenants ni habilita tráfico.
4. Arrancar los workers en modo controlado:

   ```bash
   docker compose --profile buyers build
   docker compose --profile buyers up -d \
     --scale telegram-poller=1 --scale telegram-delivery=1
   ```

   Se mantiene exactamente una réplica de `telegram-poller` y una de
   `telegram-delivery`. La concurrencia de usuarios vive en PostgreSQL y en
   runtimes aislados; no se escalan los dos procesos que poseen el token porque
   el poller tiene un único cursor de long polling y delivery posee el estado
   global de cadencia/backpressure. `scheduler-worker` también permanece
   singleton. Sólo `runtime-worker` usa `RUNTIME_WORKER_REPLICAS`, validado en el
   rango 1–8.

5. Abrir ambos deep-links desde dos identidades privadas de Telegram. Confirmar
   en PostgreSQL que existen dos bindings distintos y que cada claim fue
   consumido una sola vez.
6. En el primer tenant, probar texto, foto, video corto y PDF; confirmar inbox,
   respuesta, outbox, entrega y limpieza de la materialización temporal.
7. Probar `/restart`, `/reset`, `/conectar_chatgpt` y el flujo exacto de
   `/resetear_completamente` sólo en el canario desechable. Confirmar que reset
   de conversación conserva el estado durable y que reset completo no afecta
   las campañas que ya existen en Meta.
8. Crear un job programado corto, suspender el runtime y confirmar que el
   scheduler lo despierta, entrega el resultado y vuelve a permitir idle.
9. Intercalar mensajes y un archivo distinto en ambos tenants; comprobar que
   sesiones, rutas, hashes, memoria, credenciales, cronjobs y respuestas nunca
   aparecen en el otro.
10. Detener una vez `runtime-worker` después de reclamar trabajo y reiniciarlo;
   verificar lease/fencing, reintento sin doble entrega y recuperación del
   cursor. Luego repetir con un fallo temporal de descarga de medio.
11. Mantener sólo los dos canarios y ejecutar la rampa de capacidad, sin saltar
    etapas:

    - starter: 1 worker, normal/hard 4;
    - concurrencia base: 4 workers, normal/hard 4;
    - normal ampliado: 6 workers, normal/hard 6;
    - candidato final: 8 workers, normal 6, hard 8 y headroom 2048 MiB.

    En cada etapa registrar RSS por tenant, `MemAvailable`, swap usado, p95 de
    despertar/respuesta, edad máxima de inbox y ausencia de OOM/reinicios. Emitir
    claims reales únicamente después de aprobar esas evidencias.

No se debe activar el perfil sólo porque el contenedor base esté saludable. La
ausencia del token y del perfil `buyers` es el guardarraíl de lanzamiento.

## 11. Actualización segura y control de versiones

Cada cambio futuro debe seguir este orden para no regresar accidentalmente a
una versión antigua:

1. Hacer el cambio en la rama de trabajo y ejecutar la suite completa.
2. Comprobar `git diff --check`, sintaxis Bash/Python y ambos perfiles de
   `docker compose config --quiet`.
3. Confirmar que todos los archivos desplegables pertenecen al mismo commit;
   no mezclar un `runtime_broker.py` de un release con un `compose.yaml` de otro.
4. Crear un commit descriptivo y subirlo a GitHub.
5. Guardar un backup recuperable del control plane y de la base antes de copiar
   o activar el release. No modificar todavía `DEPLOYED_COMMIT`.
6. Copiar el release completo a una carpeta nueva y validar allí sus hashes,
   permisos, sintaxis y configuraciones Compose. Actualizar la ruta activa
   desde esa única carpeta, sin mezclar archivos de releases distintos, y
   ejecutar:

   ```bash
   ./apply-control-plane.sh
   sudo ./install-runtime-broker.sh
   ```

   El instalador usa `systemctl restart` para garantizar que el broker no quede
   ejecutando Python de la versión anterior en memoria.
7. Si se cambia `Control.Dockerfile` o código de los workers, construir una vez
   como `telegram-poller`; los otros servicios reutilizan el mismo tag. No se
   deben lanzar builds paralelos del mismo tag.
8. Verificar hashes remotos, logs, socket, permisos y `docker compose ps`.
9. Sólo cuando todas las verificaciones anteriores hayan pasado, escribir el
   SHA nuevo en `DEPLOYED_COMMIT` mediante reemplazo atómico y conservar el
   marcador anterior dentro del backup. Un despliegue fallido nunca debe
   anunciar el candidato como activo.
10. Sólo después habilitar o reiniciar `buyers` si la prueba controlada pasó.

El runtime de un tenant nunca debe hacer `pull` o `build` al despertar:
`tenantctl.py` usa `--no-build --pull never` y mantiene la imagen r90 fijada.

## 12. Rollback y recuperación

Ante una regresión, no editar un archivo dentro de un contenedor ni usar
`docker system prune`. Detener la activación de compradores, conservar logs y:

1. Identificar el SHA bueno anterior y la marca `DEPLOYED_COMMIT`.
2. Restaurar la carpeta completa de ese release (no archivos individuales).
3. Restaurar el dump de PostgreSQL sólo si hubo una migración incompatible; las
   migraciones actuales son idempotentes y normalmente no requieren rollback de
   datos.
4. Ejecutar `apply-control-plane.sh` y
   `sudo install-runtime-broker.sh` para recargar el código del broker.
5. Verificar primero el broker y un tenant canario; dejar `buyers` apagado hasta
   que el flujo completo esté sano.

Los backups actuales están bajo `/srv/admira/backups/`; son recuperables y no
forman parte de la ruta activa. No deben confundirse con el release activo.

## 13. Operación diaria y diagnóstico

Comandos de observación sin mutar estado:

```bash
docker compose ps
docker compose logs --tail=100 postgres redis
systemctl status admira-runtime-broker.service --no-pager
journalctl -u admira-runtime-broker.service -n 100 --no-pager
ss -ltn                         # no debería mostrar puertos del control plane
stat /run/admira-runtime-broker/broker.sock
find /srv/admira/shared/telegram-spool -maxdepth 2 -type f -printf '%p %s bytes\n'
```

Síntomas y primer lugar donde mirar:

| Síntoma | Revisar primero |
| --- | --- |
| No entra ningún mensaje | token, `telegram-poller`, `telegram_ingress` y cursor en DB |
| Entra pero no responde | estado/lease de `tenant_telegram_updates`, `runtime-worker`, broker |
| Responde texto pero falta imagen | spool outbound, SHA, `telegram-delivery`, ACK de outbox |
| Cron no corre | `scheduler-worker`, `tenant_scheduled_jobs`, hora/lease y broker |
| Tenant no despierta | `tenantctl plan/status`, imagen `admira-ia:r90`, permisos del directorio |
| Broker rechazado | socket/GID 19091, clave `/etc/admira/runtime-broker.key`, nonce/replay |
| Datos cruzados entre clientes | detener workers, revisar RLS y `tenant_id`; no continuar hasta aislarlo |
| Código parece antiguo | `DEPLOYED_COMMIT`, hash de archivos y proceso systemd en memoria |

El script `db/validate_control_plane.sql` es destructivo y sólo debe ejecutarse
contra una base PostgreSQL desechable. La prueba E2E desechable cubre claim,
binding, inbox, lease, outbox y scheduler; no sustituye una prueba real de
Telegram.

## 14. Retención y capacidad

- Entrada: 7 días; salida: 14 días; medios entregados correctamente: se borran
  inmediatamente después del ACK.
- Temporales incompletos: 1 hora.
- Máximo por medio: 50 MiB; limpieza acotada para no bloquear al worker.
- Idle por defecto: 900 segundos. Suspender libera CPU/RAM, no memoria ni
  sesiones persistentes.

Los perfiles de concurrencia son deliberadamente distintos del número total de
clientes registrados:

| Perfil | `RUNTIME_WORKER_REPLICAS` | Normal | Hard | Admisión de burst |
| --- | ---: | ---: | ---: | --- |
| Starter desplegado | 1 | 4 | 4 | no |
| Candidato final | 8 | 6 | 8 | slots 7–8 sólo con `MemAvailable` ≥ 2048 MiB |

`ADMIRA_MAX_ACTIVE_TENANTS=4` se conserva como alias legacy seguro para el
starter. El perfil nuevo usa `ADMIRA_NORMAL_ACTIVE_TENANTS`,
`ADMIRA_HARD_MAX_ACTIVE_TENANTS` y `ADMIRA_BURST_MIN_AVAILABLE_MB`; el instalador
exige `1 <= normal <= hard <= 8`. El techo de runtimes y las réplicas de worker
son controles distintos: un runtime caliente conserva un workspace en RAM,
mientras una réplica procesa como máximo un turno durable a la vez.

Ante contención:

1. Si el mismo tenant ya tiene un turno/job en curso, se difiere como
   `tenant_busy`; no se desaloja a ningún otro cliente.
2. Si el broker cuenta el techo real de contenedores o rechaza burst por
   headroom, el worker reclama con fencing el LRU realmente idle y lo suspende.
   No son elegibles runtimes con holder, update procesándose, update listo para
   ejecutar ni cronjob due/leased.
3. El turno se vuelve a intentar después de liberar el slot. Si todos los
   runtimes continúan ocupados, vuelve a la inbox durable con dos segundos de
   espera. PostgreSQL conserva orden por disponibilidad/recepción y serializa
   cada tenant; no termina en `dead` por esperar capacidad.
4. Los cronjobs usan la misma separación de contador, pero no desalojan
   interactivos: esperan durablemente y el scheduler sigue aplicando la
   suspensión idle ordinaria.

La suspensión ejecuta Compose `down` sin `--volumes`. Cuando el cliente vuelve,
se despierta exactamente su misma raíz persistente y continúa con su historial,
memoria, archivos y conexiones. El tiempo visible será despertar frío más
latencia del proveedor; todavía debe medirse p50/p95 con tenants reales antes de
publicar un SLA.

Snapshot de sólo lectura del VPS el 2026-08-29, sin tenant activo durante la
medición: 4 CPU, 7.8 GiB RAM total, aproximadamente 7.0 GiB `MemAvailable`, 4
GiB swap SSD existente (0 usado), `vm.swappiness=60`, 85 GiB de disco libre y
aproximadamente 194 MiB RSS sumados en los servicios Docker base. Esto justifica
probar el perfil 6+2, no activarlo sin soak. Swap es sólo colchón de emergencia:
el broker decide burst con `MemAvailable` y nunca cuenta swap como RAM normal.

Ejecutar antes y después de cada etapa, sin mutar el host ni leer secretos:

```bash
./capacity-preflight.sh
docker compose --profile buyers ps
```

No arrancar todos los tenants en un reinicio ni aumentar simultáneamente hard y
workers sin registrar RAM, CPU, OOM/reinicios, edad de cola, despertar y latencia
del proveedor.

## 15. Evidencia local y pendientes antes de vender/activar

El candidato tiene 135 pruebas automatizadas para resolución de identidad, dos raíces
tenant distintas, sesiones separadas, comandos nativos, autorización de reset,
medios, cursor durable, fencing/reintentos, scheduler, límite de capacidad,
bloqueo de instancia y gate de tenants activos. También pasan la compilación
Python/Bash, `git diff --check` y ambos perfiles de
`docker compose config --quiet`. Las seis migraciones se aplicaron desde cero y
se reaplicaron idempotentemente
en PostgreSQL 16 desechable; el fixture completo confirmó claim, binding,
inbox, lease, outbox, scheduler, roles restringidos y el gate de tenant
inactivo. Pruebas dinámicas adicionales confirmaron que Telegram y cron
conservan el presupuesto de fallos durante contención, que dos workers obtienen
claims LRU distintos y que un claim `stopping` expirado se recupera. Una prueba
separada confirmó que un 429 agotado continúa en `retry` mientras un error
genérico agotado termina en `dead`.

En Contabo se verificaron además hashes del release, backup, migraciones
004/005/006, imagen de workers, imagen tenant r90, broker/socket, normal/hard
`4/4`, salud de PostgreSQL/Redis, despertar en frío controlado por el broker,
un turno Telegram completo y una réplica de cada uno de los cuatro servicios
`buyers` sin reinicios ni errores.

Eso no sustituye estas evidencias externas todavía pendientes:

1. Abrir el claim todavía pendiente de `canary-two` desde una segunda identidad
   privada de Telegram y comprobar dos bindings distintos. Una misma identidad
   no se reutiliza para fingir esta evidencia de aislamiento.
2. Continuar el canary dirigido de la sección 10: comandos,
   conexión del modelo, OAuth de Meta en dry-run, foto/video/PDF, generación y
   entrega de creativos, scheduler, suspensión/despertar y recuperación de un
   worker interrumpido.
3. Conservar evidencia de que ningún archivo, sesión, memoria, credencial,
   cronjob o respuesta cruzó de un canario al otro y observar recursos/colas
   antes de emitir claims a compradores reales.
4. Revocar el token canario que pasó por la conversación de soporte, instalar
   el token reemplazado sin pegarlo en chat y repetir el gate de identidad del
   bot antes de la primera admisión comercial.

Hasta cerrar esos puntos, el control plane debe considerarse **infraestructura
desplegada con workers canarios activos, pero bloqueada para compradores por
las evidencias canarias y la rotación final del token**, no un servicio
comercial aprobado. Ninguno de estos pendientes requiere construir dashboard
o el futuro producto SaaS.
