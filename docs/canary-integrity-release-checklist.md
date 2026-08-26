# Cierre íntegro de un canary

Esta es la checklist obligatoria para cerrar un canary y evitar que un
contenedor etiquetado `r64` ejecute archivos hot-patcheados de `r80` o de otra
versión. El incidente se produce cuando se reemplazan archivos dentro del
contenedor sin reconstruir una imagen desde un commit conocido: la etiqueta de
la imagen conserva el número viejo aunque el contenido ya sea una mezcla.

La corrección operativa es una sola cadena de procedencia:

```text
worktree limpio → commit SHA → tag rXX → build desde ese SHA
→ imagen con version/SHA/manifest → contenedor con los mismos tres valores
→ smoke tests → canary cerrado
```

No se debe declarar un canary final mientras uno de esos eslabones falte.
`verify-canary-integrity.sh` es un chequeo de lectura: no construye, no reinicia
ni despliega.

## Procedimiento

Desde el worktree que se va a publicar:

```bash
cd .codex-r75-work

# Debe mostrar un único valor canónico, y no debe haber cambios pendientes.
cat VERSION
git status --short --branch
git log -1 --oneline --decorate

# Comprueba limpieza, tag exacto, VERSION/.env.example y el hash de todos los
# archivos versionados. Sin argumento sólo valida el árbol local.
./scripts/verify-canary-integrity.sh

# Para cerrar el canary real, pasar el nombre exacto del contenedor activo.
./scripts/verify-canary-integrity.sh NOMBRE_DEL_CONTENEDOR
```

La salida debe incluir el mismo `version`, commit completo y
`source-manifest` para el árbol, la imagen y el contenedor. Un `r64` mezclado
con archivos posteriores falla explícitamente porque su versión, commit o
manifest no coincide.

## Qué debe existir antes de construir

- `git status --short` vacío, incluyendo índice y archivos no rastreados.
- `VERSION` contiene exactamente una versión canary, por ejemplo `r80`.
- `.env.example:META_ADS_AGENT_VERSION` coincide con `VERSION`.
- Existe el tag exacto (`r80`) y el commit que se va a construir está fijado.
- El cambio está commiteado y subido al remoto antes de empaquetar.
- No se permite hot-patch como cierre. Si hubo un parche de soporte, hay que
  pasarlo al source, commitearlo y reconstruir desde ese commit.

El empaquetado ya bloquea un worktree sucio:

```bash
./scripts/package-release.sh "$(cat VERSION)"
```

El ZIP y cualquier imagen deben salir después de ese commit; no se deben
copiar archivos nuevos dentro de la imagen o del contenedor posteriormente.

## Metadatos obligatorios de la imagen

El `Dockerfile` debe recibir la versión, el SHA y el digest producido por
`scripts/source_manifest.py`, y guardarlos como labels OCI:

```text
org.opencontainers.image.version         = r80
org.opencontainers.image.revision        = <git rev-parse HEAD>
org.opencontainers.image.source-manifest = <scripts/source_manifest.py>
```

Como la imagen excluye `.git`, el build también debe escribir el mismo digest
en `/app/source-manifest.sha256` y el SHA en `/app/build-commit.sha`. Esos archivos son sólo procedencia de build; no
es memoria ni configuración del comprador.

El nombre/tag de la imagen también debe contener `r80` (o la variable de
versión equivalente). `unknown`, `local` y una tag vieja no son válidos para
un canary cerrado. El checker exige estos labels; así un contenedor no puede
parecer correcto sólo porque `/app/VERSION` fue reemplazado.

## Verificaciones finales

1. Ejecutar `scripts/verify-canary-integrity.sh CONTENEDOR`.
2. Ejecutar `python3 scripts/release_canary.py` y el smoke test acotado de
   `scripts/run-canary-release.sh` según el runbook.
3. Comprobar que el smoke test no dejó procesos, cambios de estado ni acciones
   reales en Meta.
4. Guardar en la nota de cierre: versión, SHA, source-manifest, digest de la
   imagen, nombre del contenedor y resultados de los smoke tests.
5. Sólo después de todo lo anterior, empaquetar/publicar el release o mover el
   canal stable. El commit de cada cambio debe quedar visible en GitHub.

Si el checker falla por worktree sucio, no se debe ignorar con una variable ni
continuar el despliegue: revisar el cambio, añadirlo al commit correspondiente
o eliminar únicamente el artefacto generado que no pertenece al source.

## Diagnóstico rápido de una mezcla

```bash
docker inspect CONTENEDOR --format '{{.Config.Image}}'
docker image inspect IMAGEN --format '{{json .Config.Labels}}'
docker exec CONTENEDOR sh -lc 'cat /app/VERSION'
docker exec CONTENEDOR sh -lc 'cat /app/source-manifest.sha256'
```

Si la imagen dice `r64` pero el manifest del contenedor difiere del manifest
del commit actual, el canary no es reproducible. Detener la promoción, aplicar
el cambio en source, commitear, reconstruir desde el SHA y repetir la
checklist. Nunca se corrige copiando sólo dos módulos dentro del contenedor.
