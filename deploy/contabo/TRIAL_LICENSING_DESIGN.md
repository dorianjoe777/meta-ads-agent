# Diseño operativo de pruebas, licencias e identidad

Estado: **ciclo de prueba/licencia y panel privado desplegados; no implica que
el broker central de imágenes esté activado**.

Este documento define el plano de control mínimo para admitir tres clientes
nuevos por día con una prueba de cinco días. No describe un dashboard para el
comprador ni amplía Admira a API pública, CRM, ecommerce, webhooks o MCP.

## 1. Resultado esperado

- Cada cliente recibe un tenant privado y durable.
- El tenant no se reemplaza al terminar la prueba: cambia a `grace` y conserva
  memoria, sesiones, archivos, Meta, cronjobs y el binding recuperable de
  Telegram durante 30 días; después se eliminan el registro y su workspace si
  no fue licenciado.
- Durante `grace`, el tenant está suspendido y recibe un aviso de Telegram al
  entrar y cada tres días. Una ampliación explícita del operador cancela los
  avisos pendientes y devuelve el mismo tenant a `trial`.
- La prueba dura cinco días y usa capacidad de Gemini financiada por Admira.
- Al licenciar, Gemini cambia de forma atómica a una credencial del cliente.
- La generación de imágenes financiada por Admira dura los mismos cinco días
  iniciales de una prueba. Una cuenta licenciada usa su ruta personal por defecto;
  el operador puede incluirla explícitamente en el pool OAuth central mediante
  un switch auditable del panel privado.
- El cliente puede conectar su propia cuenta ChatGPT/Codex desde el primer día;
  esa conexión no cancela ni sustituye el patrocinio central vigente.
- Si cambia el teléfono, número o cuenta de Telegram, el cliente puede recuperar
  el mismo tenant mediante la identidad de licencia y una confirmación enviada
  al correo verificado.

Tres altas diarias durante cinco días producen 15 pruebas simultáneas en estado
estable. Esto significa 15 entitlements vigentes, no 15 contenedores encendidos:
los runtimes continúan usando suspensión y despertar bajo demanda.

## 2. Estados independientes

El estado comercial no debe confundirse con el origen de cada proveedor.

| Etapa | Tenant | Gemini | Imágenes |
| --- | --- | --- | --- |
| Preparado | `pending_claim` | sin consumo | sin consumo |
| Prueba activa | `trial` | pool de Admira | servicio central patrocinado |
| Periodo de gracia | `grace` | bloqueado | bloqueado |
| Licenciado, switch central activado | `licensed` | credencial del cliente | servicio central patrocinado |
| Licenciado, switch central desactivado | `licensed` | credencial del cliente | conexión del cliente mediante `/conectar_chatgpt`, add-on o bloqueado |
| Suspendido/cancelado | `suspended`/`cancelled` | bloqueado | bloqueado |

Las transiciones válidas son:

```text
pending_claim -> trial -> grace -> eliminado
                    \-> licensed -> suspended/cancelled
grace ------------------------> licensed
grace ------------------------> trial (ampliación explícita)
```

El flujo histórico de `pending_claim` activa la prueba al consumir el claim de
Telegram. Las altas comerciales creadas desde el panel privado usan el contrato
posterior de migration 013: los cinco días exactos comienzan al crear la cuenta
del cliente, no al emitir ni consumir el enlace. Reemitir un enlace nunca mueve
esa fecha; así el operador puede ver y caducar la prueba aun si el cliente aún
no abrió Telegram.

## 3. Datos del plano de control

El esquema actual ya reserva `tenant_entitlements`, `license_id`, `plan`,
`trial_started_at`, `trial_ends_at`, `paid_through` y `hosting_until`. La
implementación debe ampliar ese fundamento con tablas o campos equivalentes.

### Identidad comercial

- `tenant_license_contacts`: correo cifrado para entrega, hash/HMAC del correo
  normalizado para búsqueda, verificación y versión de identidad.
- `tenant_entitlements`: estado comercial, identificador de licencia aleatorio,
  hash/HMAC de la prueba de licencia, `licensed_at`,
  `image_sponsorship_ends_at` y el opt-in booleano
  `licensed_central_image_pool_enabled`. El identificador de licencia sí se almacena en
  PostgreSQL porque forma parte de la identidad recuperable; nunca se almacenan
  aquí la clave Gemini ni credenciales de ChatGPT/Codex.

### Credenciales de proveedor

- `tenant_provider_credentials`: tenant, proveedor, propósito (`text` o
  `image`), origen (`operator_pool`, `customer`, `central_broker`), `secret_ref`,
  fingerprint no reversible, estado, activación, expiración y validación.
- `operator_provider_pool`: referencia de secreto, proyecto/cuenta lógica,
  estado, capacidad asignada y métricas de cuota sin registrar la clave.

Los valores reales permanecen en un almacén de secretos o en archivos privados
fuera del repositorio. PostgreSQL conserva referencias, estado y auditoría.

### Recuperación

- `tenant_recovery_challenges`: tenant, chat solicitante, hash del OTP o token,
  expiración corta, intentos máximos, cooldown y `consumed_at`.
- `tenant_telegram_bindings`: historial mediante `revoked_at`,
  `revoked_reason` y `replaced_by`; sólo un binding primario vigente por tenant
  y bot.

## 4. Alta diaria y expiración

El panel privado de operador debe ofrecer una operación `Crear prueba` que:

1. cree o valide el tenant durable;
2. asigne una entrada sana del pool Gemini sin exponer su valor;
3. cree un entitlement `trial` anclado a `tenant.created_at` y a su fecha
   exacta de vencimiento cinco días después;
4. emita el claim de Telegram de un solo uso sin reiniciar ni extender el
   vencimiento;
5. no arranque el contenedor;
6. registre un evento de auditoría.

En el flujo histórico, consumir el claim inicia `trial_started_at` y fija
`trial_ends_at = trial_started_at + 5 días`. Para una alta de panel, la misma
relación se fija en la transacción de creación con
`trial_started_at = tenant.created_at`; consumir el claim sólo vincula Telegram.
Un trabajo periódico vence pruebas, bloquea nuevos turns y cronjobs, suspende
el runtime, encola avisos idempotentes cada tres días y elimina el workspace y
el registro al terminar los 30 días. No debe depender solamente de ocultar
comandos en una interfaz; la regla debe estar aplicada en el plano de control.
Cada entrada a `grace` recibe un `grace_cycle_id` nuevo. El borrado usa un claim
con token de fencing: mientras exista, toda transición de salida de `grace`
queda bloqueada; sólo después de que el broker autenticado marque el workspace
como purgado puede borrarse el tenant con ese mismo token. Un scheduler caído
puede ser reemplazado tras vencer el lease sin abrir una carrera con una
ampliación o licencia.

Los comandos de consulta y reportes de la CLI deben mostrar como mínimo:

- altas de hoy frente al objetivo de tres;
- pruebas activas, por vencer, en `grace` y próximas a borrado;
- capacidad objetivo de 15 más el margen operativo configurado;
- salud/cuota de cada proyecto Gemini;
- cola y cuota del servicio de imágenes;
- tenants suspendidos o con credenciales inválidas.

## 5. Gemini: prueba y conversión a licencia

No se deben pegar claves en chat, tickets, argumentos de proceso o logs. La
entrada segura en esta fase es stdin sin eco o un archivo privado regular 0600
leído por la CLI. Después de guardarla, la salida sólo muestra proveedor,
fingerprint, origen y fecha de validación.

La validación automática de `gemini-set` y `gemini-license` (salvo dry-run) es
un health check acotado al endpoint oficial `GET
https://generativelanguage.googleapis.com/v1beta/models?pageSize=1`. La clave
se envía sólo mediante el header `x-goog-api-key`, con
`x-goog-api-client: admira-hosted/r91`, nunca en URL, argumentos, logs o errores.
`--allow-unverified` existe sólo como excepción explícita de operador y no debe
usarse para preparar cuentas listas para clientes; dry-run no contacta la red.
La política de preparación exige auth keys. Según la [documentación oficial de
claves de Gemini](https://ai.google.dev/gemini-api/docs/api-key), las nuevas
claves de AI Studio son auth keys, las standard sin restricción son rechazadas y
las standard serán rechazadas por completo en septiembre de 2026. Por eso una
respuesta exitosa del endpoint con una standard legacy no basta para admitirla
en el pool. No se afirma aquí que ya existan claves reales confirmadas ni que el
pool esté activo.

La conversión `trial -> licensed` debe ser una operación transaccional e
idempotente:

1. recibir correo y credencial Gemini del cliente por el canal seguro;
2. validar la credencial con una solicitud mínima y acotada;
3. escribir una nueva versión de secreto;
4. cambiar la referencia activa de Gemini;
5. reiniciar únicamente el proceso/tenant afectado cuando sea seguro;
6. comprobar un turno de salud;
7. marcar `licensed`, emitir la licencia y fijar el beneficio de imágenes a 30
   días;
8. retirar la asignación Gemini de Admira sólo después de comprobar la nueva;
9. registrar auditoría sin valores secretos.

El comando operativo actual es `gemini-license`; exige `--email-file` además de
la credencial Gemini. El archivo de correo debe ser regular y 0600, se consume
sólo en memoria y se normaliza antes de calcular el HMAC con la clave central
privada `secrets/recovery_hmac_key.txt` por defecto. La licencia, contacto HMAC,
referencia/fingerprint Gemini y auditoría se registran atómicamente; no se
almacena el correo ni ninguna clave del proveedor en PostgreSQL.

Si falla cualquier paso anterior al corte, la prueba conserva su credencial
anterior y no queda a medio migrar. Si la transición ya cambió el estado, el
rollback debe seguir el backup y runbook de `OPERATIONS.md`; no se revierte
editando SQL o archivos de tenant a mano.

La cuota de Gemini se aplica por proyecto, no por clave. Crear muchas claves
dentro del mismo proyecto no crea capacidad independiente. El pool debe conocer
el proyecto real y aplicar presupuesto por tenant antes de llegar al límite.

Migration `010_operator_gemini_pool.sql` convierte esa regla en estado durable:
`gemini_pool_projects` representa el límite por proyecto, mientras
`gemini_pool_credentials` conserva sólo fingerprint, tipo y referencia opaca
del secreto. `gemini_pool_assignments` permite una asignación activa por tenant
y sus funciones hosted reciben `runtime_key`, validan el tenant y dejan
auditoría de asignación/liberación. La capacidad no se libera manualmente si
el tenant sigue activo con una asignación finalizada; los cambios de lifecycle
son los que pueden liberar automáticamente. El validator es exclusivamente
para una PostgreSQL desechable. La CLI y el pool real no están declarados live
hasta crear y verificar proyectos y auth keys reales fuera del repositorio.

Toda rotación de Gemini sigue el fence `suspend -> write -> health -> metadata`.
El bypass `--runtime-already-stopped` sólo vale cuando el operador ya verificó
que el runtime está detenido y queda explícito en la operación. Un fallo al
suspender deja intacta la credencial anterior.

## 6. Generación central de imágenes

La integración central permanece desactivada hasta completar un canary del
broker y de su proveedor. `ADMIRA_CENTRAL_IMAGE_READY=false` es obligatorio
mientras tanto; la descripción siguiente define el destino del flujo, no un
servicio ya disponible.

No se debe copiar un mismo `auth.json` de ChatGPT/Codex a los tenants. Eso
multiplicaría una credencial de alto valor y haría difícil revocar, rotar,
atribuir consumo y garantizar aislamiento.

La ruta mínima segura es el servicio `central-image-broker`, actualmente
implementado pero dormido en el perfil Compose `central-images` y aún sin
activar. Requiere construir y verificar r91, dos conexiones centrales autorizadas y
un canary controlado. Migration `008_central_image_jobs.sql` es su ledger
durable; no se debe considerar disponible sólo porque el código y el esquema
existan. El flujo previsto es:

1. el tenant envía un trabajo autenticado con runtime key, prompt, referencias
   y un identificador idempotente;
2. el broker vuelve a resolver el tenant activo y valida entitlement y cuota;
3. la cuenta o proyecto financiado por Admira vive sólo en el broker;
4. cada trabajo usa un directorio temporal aislado y un intercambio HMAC/Unix
   socket por tenant;
5. la salida se copia al `output/` del tenant correcto tras validar hash y tipo;
6. el ledger registra unidades, estado y latencia, no credenciales, prompts ni
   respuestas del proveedor;
7. al terminar el patrocinio, rechaza el trabajo o usa una conexión del cliente
   según su entitlement.

Para producción comercial se prefiere un proyecto API de servidor con cuotas
por tenant. Si se utiliza temporalmente una suscripción ChatGPT, debe permanecer
centralizada y su uso multi-cliente debe confirmarse expresamente con el plan y
las condiciones aplicables antes de basar el servicio comercial en ella.

### Pool central mínimo para pruebas

Para trials y ampliaciones explícitas se prepara un mínimo de **dos cuentas
centrales autorizadas**, aisladas entre sí. No son cuentas de los tenants ni se
copian sus archivos de autenticación. El broker selecciona una cuenta sana por
trabajo y permite como máximo un intento de fallback por solicitud: si la cuenta
primaria falla, incluso por cuota o límite de imágenes, se prueba una sola vez
la otra cuenta elegible. El límite total es de dos intentos de proveedor por
solicitud. La cuenta que reportó cuota, autenticación o indisponibilidad entra
en cooldown; si ambas fallan, el trabajo queda en cola/error recuperable y no
se rota indefinidamente.

Cada cuenta tiene su propio directorio privado de autenticación, identidad,
fingerprint, estado y métricas. Un fallo de cuota, autenticación o timeout pone
esa cuenta en cooldown con backoff; el cooldown y la causa se auditan sin
guardar prompts, tokens, cookies ni respuestas crudas. Las cuotas y condiciones
del proveedor siguen siendo la autoridad: el pool no convierte varias cuentas
en una cuota garantizada.

El pool central permanece **dormant** (`ADMIRA_CENTRAL_IMAGE_READY=false`) hasta
que las dos autenticaciones hayan sido instaladas fuera de banda, verificadas
por separado y un canary real haya demostrado selección, fallback acotado,
cooldown, idempotencia y aislamiento. No se actualizan los tenants live de r90
como parte de esta preparación.

#### Instalación segura de las autenticaciones

El operador debe iniciar sesión manualmente en el host, usando el método de
autenticación autorizado por el proveedor, en terminal privada y sin pegar
credenciales en chat, tickets, comandos, argumentos, variables de entorno,
logs o capturas. Cada sesión debe escribir únicamente en su directorio propio,
por ejemplo `/srv/admira/shared/central-codex-auth/primary/` y
`/srv/admira/shared/central-codex-auth/secondary/`, con propietario del
servicio, modo de directorio 0700 y archivos de credenciales 0600. Compose
monta esa raíz en `/app/runtime/hermes/codex-auth-pool` sólo en el broker y de
forma escribible para permitir los archivos de estado/refresco de Codex. Nunca
se reutiliza o se copia un `auth.json` entre cuentas, tenants o releases.

Después de cada login, el operador verifica permisos y fingerprint. No hay un
health endpoint independiente que valide ChatGPT: la verificación funcional es
el canary real del broker, con salida redactada que sólo puede indicar la cuenta,
estado y timestamp, nunca el contenido secreto. El broker recibe ambos homes y
nunca expone su contenido al tenant. La activación del flag y el canary real
son pasos separados y requieren evidencia de ambas cuentas.

## 7. Recuperación desde otro Telegram

El núcleo preparado puede ofrecer a un chat no reconocido una respuesta
genérica con `/recuperar`, sin confirmar si una cuenta existe. En live sigue
apagado mientras `ADMIRA_TELEGRAM_RECOVERY_READY=false`; el correo sólo se
procesa mediante el perfil opt-in `recovery-email`. Cuando se canarie, el flujo
será:

1. solicitar correo de licencia y número de licencia;
2. comparar representaciones normalizadas mediante hash/HMAC;
3. responder de forma uniforme aunque los datos no existan;
4. entregar un OTP de un solo uso al correo ya verificado mediante el outbox
   SMTP; el usuario responde en el mismo Telegram con `/codigo REQUEST_ID OTP`;
5. limitar intentos por chat, correo hash y licencia hash;
6. al confirmar, bloquear el tenant en una transacción;
7. revocar el binding anterior y crear el nuevo binding primario;
8. invalidar otros desafíos y aumentar la versión de identidad;
9. registrar el resultado en el audit log;
10. continuar con el mismo tenant y todo su estado previo.

El núcleo SQL, el adaptador HMAC/cifrado y los workers de outbox SMTP/Telegram
están preparados, pero no hay una integración live hasta registrar proveedor
SMTP autorizado, remitente/dominio con SPF/DKIM/DMARC, secretos privados,
backup/migración revisados, segunda identidad Telegram y evidencia de canary.
No inventar credenciales ni activar la bandera como sustituto de esas pruebas.

Correo más licencia no es suficiente para cambiar el binding: ambos datos pueden
ser copiados o reenviados. La confirmación enviada al correo registrado es el
segundo factor que prueba control actual.

## 8. Herramientas privadas del operador

No existe ni se requiere un dashboard para compradores en esta fase. Sí existe
un dashboard **privado del operador**, desplegado en el loopback del VPS y
accesible sólo mediante SSH. Es la ruta normal para crear una prueba real,
consultar capacidad/estado, reemitir el deep-link, ampliar/caducar una prueba y
convertir el mismo tenant a licencia. No se publica como puerto de Internet ni
entrega Docker, roots de tenants, claves de pool ni secretos de licencias al
proceso web.

La CLI host-only sigue siendo una herramienta de reparación/operación legacy
revisada. Puede consultar auditoría o realizar tareas explícitas que no estén
en el panel, siempre sin revelar credenciales. No se debe sustituir la
conversión normal **Pruebas** → **Licenciadas** por la CLI ni prometer reenvío
de correo/recovery: ese flujo permanece apagado hasta su canary SMTP.

La lógica crítica vive en servicios comunes y el panel invoca sólo el
provisioner HMAC permitido. Esto permite la cadencia de tres altas diarias sin
crear una interfaz para compradores ni ampliar el producto al futuro SaaS.

## 9. Capacidad y aceptación antes de compradores

Live conserva por ahora el starter de cuatro runtimes y un worker. El candidato
de infraestructura prepara seis slots normales, burst condicionado hasta ocho y
ocho runtime-workers, pero debe activarse por etapas y sólo después del soak
descrito en `OPERATIONS.md`. Quince pruebas registradas son compatibles con
escala a cero, pero no prueban que quince usuarios simultáneos tendrán una
latencia aceptable. Antes de emitir claims comerciales se debe medir CPU, RAM,
tiempo de despertar/Gemini, edad de la inbox y cola del servicio de imágenes.

Un tenant canario nuevo debe pasar por el mismo camino que un comprador:

- claim, primer turno y expiración simulada;
- Gemini del operador y rotación a Gemini del cliente;
- generación/entrega de imagen por broker central;
- foto, video y PDF;
- OAuth Meta en dry-run;
- scheduler con suspensión y despertar;
- transición a licencia y fin del patrocinio de imágenes;
- recuperación desde una segunda identidad Telegram;
- ausencia de archivos, memoria, credenciales y respuestas cruzadas.

## 10. Orden de implementación

1. Completar el canary funcional actual, incluido el enlace de conexión de
   modelo, media, Meta y scheduler.
2. Mantener el lifecycle trial/licencia y la CLI segura como las operaciones
   actuales de control plane.
3. Construir y verificar r91, preparar el host con
   `prepare-central-image-broker.sh` e instalar la conexión central autorizada
   sólo en el broker.
4. Aplicar y validar migration 008 y ejecutar el canary de
   `central-image-broker`; mantener `ADMIRA_CENTRAL_IMAGE_READY=false` hasta
   que pase.
5. Integrar correo transaccional y recuperación/rebinding.
6. Ejecutar el canary de ciclo completo y sólo entonces admitir compradores.
