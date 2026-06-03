# Cierre rápido para vender v1

Este es el camino más corto para lanzar sin convertir el producto en un proyecto infinito.

## Estado actual

El producto ya tiene:

- Dashboard local/VPS en español.
- Onboarding dedicado antes del dashboard.
- Conexión Meta con app/token propio del comprador.
- Lectura de datos reales de Meta.
- Chat principal con manager IA.
- Telegram opcional para hablar y aprobar desde el teléfono.
- Creación de campañas completas con aprobación.
- Modo `Con supervisión` y `Piloto automático`.
- Reglas de guardrails configurables.
- Instaladores: Mac `.pkg`, Windows vía NSIS, Linux `.tar.gz`.
- Docker con Python, Node y Codex CLI.
- Guías de marca para pedir planes/creativos a Codex.
- Servidor simple de licencias para vender v1.
- Plan Individual limitado a un negocio activo.
- Plan Agencia para varios clientes, hasta 4 dispositivos y espacios separados.

## Lo que falta antes de vender al público

### 1. Dominio de licencias: completado

La API está desplegada en Vercel y publicada como:

```text
https://admiroia.uboost.lat
```

El release debe mantener:

```text
LICENSE_SERVER_URL=https://admiroia.uboost.lat
LICENSE_PUBLIC_KEY=clave-publica-de-verificacion
LICENSE_REQUIRED_FOR_LIVE=true
```

### 2. Generar licencia del comprador

```bash
curl -X POST "https://admiroia.uboost.lat/api/admin/licenses" \
  -H "Authorization: Bearer TU_CLAVE_ADMIN_PRIVADA" \
  -H "Content-Type: application/json" \
  -d '{"buyer_email":"cliente@email.com","buyer_name":"Cliente","plan":"individual"}'
```

La primera licencia de prueba y su validación real ya fueron comprobadas. Antes de publicar, prueba además una instalación limpia como comprador.

### 3. Compilar `.exe` en Windows

En esta Mac quedó listo el instalador fuente. Para el `.exe` final necesitas NSIS:

```bash
./scripts/build-windows-exe.sh 1.0.0
```

Si se compila en Windows, entregar:

```text
MetaAdsAgent-1.0.0-windows.exe
```

### 4. Probar compra como comprador real

En una máquina limpia:

1. Instalar Docker.
2. Instalar producto.
3. Abrir dashboard.
4. Pegar licencia + email.
5. Pegar token Meta.
6. Seleccionar cuenta.
7. Seleccionar página.
8. Confirmar `Datos reales de Meta`.
9. Crear contraseña.
10. Pedir al agente una campaña.
11. Ver aprobación.
12. No dejar activo todavía salvo smoke test controlado.

### 5. Preparar email de entrega

El comprador debe recibir:

- Licencia.
- Link de descarga para su sistema.
- Video corto de instalación.
- Screenshots para crear app/token en Meta.
- Aviso claro: necesita Docker Desktop.
- Link a soporte.

## No bloquear el lanzamiento por esto

No esperes a tener:

- Panel SaaS de licencias.
- Instalador perfecto sin Docker.
- App Meta aprobada por Meta.
- Portal de curso completo.
- Creativos 100% automáticos.
- Integración Hotmart automatizada.

Para v1, eso puede ser manual. La promesa principal es: instalar un manager IA local para entender, preparar y ejecutar Meta Ads con más control.

## Oferta recomendada para vender rápido

Vender como:

```text
Manager IA local para Meta Ads
Instalado en tu PC o VPS.
Lee tus datos reales, te explica qué está pasando,
prepara campañas y puede ejecutar acciones con aprobación.
```

No vender como:

```text
Bot mágico que siempre sube ROAS automáticamente.
```

Sí puedes decir:

```text
Te ayuda a tomar mejores decisiones, detectar gasto débil,
renovar creativos y operar tu cuenta con menos estrés.
En piloto automático puede ejecutar acciones permitidas bajo tus reglas.
```

## Orden de cierre

1. Compilar `.exe`.
2. Probar instalación limpia del paquete comprador.
3. Grabar video instalación Windows.
4. Grabar video conexión Meta.
5. Crear email de bienvenida.
6. Publicar Hotmart.
7. Vender primeros 5 con soporte cercano.
8. Ajustar fricciones reales.
9. Recién después automatizar más.
