# Diseño operativo de pruebas, licencias e identidad

Estado: **propuesto; todavía no desplegado**.

Este documento define el plano de control mínimo para admitir tres clientes
nuevos por día con una prueba de cinco días. No describe un dashboard para el
comprador ni amplía Admira a API pública, CRM, ecommerce, webhooks o MCP.

## 1. Resultado esperado

- Cada cliente recibe un tenant privado y durable.
- El tenant no se reemplaza al terminar la prueba: cambia de estado y conserva
  memoria, sesiones, archivos, Meta, cronjobs y el binding recuperable de
  Telegram.
- La prueba dura cinco días y usa capacidad de Gemini financiada por Admira.
- Al licenciar, Gemini cambia de forma atómica a una credencial del cliente.
- La generación de imágenes financiada por Admira puede continuar durante los
  primeros 30 días de licencia.
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
| Prueba vencida | `trial_expired` | bloqueado | bloqueado |
| Licenciado, primeros 30 días | `licensed` | credencial del cliente | servicio central patrocinado |
| Licenciado después del beneficio | `licensed` | credencial del cliente | conexión del cliente, add-on o bloqueado |
| Suspendido/cancelado | `suspended`/`cancelled` | bloqueado | bloqueado |

Las transiciones válidas son:

```text
pending_claim -> trial -> trial_expired
                    \-> licensed -> suspended/cancelled
trial_expired ---------------> licensed
```

La activación de la prueba debe ocurrir al consumir el claim de Telegram, no al
preparar el tenant. Así, los cinco días corresponden a uso real y no al tiempo
que el enlace estuvo esperando al comprador.

## 3. Datos del plano de control

El esquema actual ya reserva `tenant_entitlements`, `license_id`, `plan`,
`trial_started_at`, `trial_ends_at`, `paid_through` y `hosting_until`. La
implementación debe ampliar ese fundamento con tablas o campos equivalentes.

### Identidad comercial

- `tenant_license_contacts`: correo cifrado para entrega, hash/HMAC del correo
  normalizado para búsqueda, verificación y versión de identidad.
- `tenant_entitlements`: estado comercial, identificador de licencia aleatorio,
  hash/HMAC de la prueba de licencia, `licensed_at` e
  `image_sponsorship_ends_at`.

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

El panel/CLI de operador debe ofrecer una operación `Crear prueba` que:

1. cree o valide el tenant durable;
2. asigne una entrada sana del pool Gemini sin exponer su valor;
3. cree un entitlement pendiente;
4. emita el claim de Telegram de un solo uso;
5. no arranque el contenedor;
6. registre un evento de auditoría.

Al consumir el claim, una única transacción inicia `trial_started_at`, fija
`trial_ends_at = trial_started_at + 5 días` y activa el entitlement. Un trabajo
periódico vence pruebas, drena trabajo en curso y bloquea nuevos turns y cronjobs.
No debe depender solamente de esconder comandos en el dashboard.

El panel debe mostrar como mínimo:

- altas de hoy frente al objetivo de tres;
- pruebas activas, por vencer y vencidas;
- capacidad objetivo de 15 más el margen operativo configurado;
- salud/cuota de cada proyecto Gemini;
- cola y cuota del servicio de imágenes;
- tenants suspendidos o con credenciales inválidas.

## 5. Gemini: prueba y conversión a licencia

No se deben pegar claves en chat, tickets, argumentos de proceso o logs. La
entrada segura debe ser un campo de secreto HTTPS del panel privado o stdin sin
eco desde la CLI. Después de guardarla, la interfaz sólo muestra proveedor,
fingerprint, origen y fecha de validación.

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

Si falla cualquier paso anterior al corte, la prueba conserva su credencial
anterior y no queda a medio migrar.

La cuota de Gemini se aplica por proyecto, no por clave. Crear muchas claves
dentro del mismo proyecto no crea capacidad independiente. El pool debe conocer
el proyecto real y aplicar presupuesto por tenant antes de llegar al límite.

## 6. Generación central de imágenes

No se debe copiar un mismo `auth.json` de ChatGPT/Codex a los tenants. Eso
multiplicaría una credencial de alto valor y haría difícil revocar, rotar,
atribuir consumo y garantizar aislamiento.

La ruta mínima segura es un broker central de imágenes:

1. el tenant envía un trabajo autenticado con `tenant_id`, prompt, referencias y
   un identificador idempotente;
2. el broker valida entitlement y cuota antes de usar el proveedor;
3. la cuenta o proyecto financiado por Admira vive sólo en el broker;
4. cada trabajo usa un directorio temporal aislado;
5. la salida se copia al `output/` del tenant correcto tras validar hash y tipo;
6. el broker registra unidades, estado y latencia, no credenciales;
7. al terminar el patrocinio, rechaza el trabajo o usa una conexión del cliente
   según su entitlement.

Para producción comercial se prefiere un proyecto API de servidor con cuotas
por tenant. Si se utiliza temporalmente una suscripción ChatGPT, debe permanecer
centralizada y su uso multi-cliente debe confirmarse expresamente con el plan y
las condiciones aplicables antes de basar el servicio comercial en ella.

## 7. Recuperación desde otro Telegram

Un chat no reconocido puede recibir una respuesta genérica que ofrezca
`/recuperar`, sin confirmar si una cuenta existe. El flujo es:

1. solicitar correo de licencia y número de licencia;
2. comparar representaciones normalizadas mediante hash/HMAC;
3. responder de forma uniforme aunque los datos no existan;
4. enviar un OTP o enlace mágico de un solo uso al correo ya verificado;
5. limitar intentos por chat, correo hash y licencia hash;
6. al confirmar, bloquear el tenant en una transacción;
7. revocar el binding anterior y crear el nuevo binding primario;
8. invalidar otros desafíos y aumentar la versión de identidad;
9. registrar el resultado en el audit log;
10. continuar con el mismo tenant y todo su estado previo.

Correo más licencia no es suficiente para cambiar el binding: ambos datos pueden
ser copiados o reenviados. La confirmación enviada al correo registrado es el
segundo factor que prueba control actual.

## 8. Panel privado del operador

El panel no se publica como puerto abierto de Contabo. Debe quedar detrás de VPN,
túnel SSH o un proxy de acceso con MFA, sesiones cortas, CSRF, rate limiting y
auditoría. Sus operaciones mínimas son:

- crear una prueba y copiar el deep-link;
- ver capacidad, vencimientos y salud de proveedor;
- convertir una prueba a licencia;
- ingresar/reemplazar Gemini mediante un campo de secreto de una sola vista;
- reenviar el correo de licencia;
- suspender/reactivar un tenant;
- revisar y aprobar casos excepcionales de recuperación;
- consultar auditoría sin revelar credenciales.

La lógica debe vivir en un servicio común y ser usada primero por una CLI
administrativa. El panel sólo llama a esas mismas operaciones. Esto permite
iniciar la cadencia de tres altas diarias antes de terminar la interfaz sin crear
dos implementaciones distintas.

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

1. Corregir y completar el canary funcional actual, incluido el enlace de
   conexión de modelo, media, Meta y scheduler.
2. Añadir migración y servicio común para entitlements, contactos, referencias
   de secretos, auditoría y expiración.
3. Añadir CLI segura para crear pruebas, instalar/validar claves y licenciar.
4. Implementar el broker central de imágenes y sus cuotas.
5. Construir el panel privado sobre las mismas operaciones.
6. Integrar correo transaccional y recuperación/rebinding.
7. Ejecutar el canary de ciclo completo y sólo entonces admitir compradores.
