# Checklist antes de dejar anuncios activos

No dejes anuncios activos por emocion. Hazlo cuando estas condiciones esten completas:

- Dashboard desbloqueado en el dispositivo del comprador.
- Licencia activa y validada.
- Token propio de Meta guardado localmente.
- Cuenta publicitaria real seleccionada.
- Pagina de Facebook y URL de destino guardadas.
- El dashboard muestra `Datos reales de Meta`.
- Hay al menos una lectura diaria con datos reales.
- La cola de aprobaciones se entiende.
- El comprador entiende que el chat no aprueba acciones.
- Nivel de control elegido: `Con supervision` o `Piloto automatico`.
- Si eliges `Piloto automatico`, el permiso para acciones automaticas esta activado.

## Prueba pequena

1. Prepara un cambio pequeno y reversible.
2. Confirma que cae en aprobaciones si es riesgoso.
3. Aprueba manualmente.
4. Revisa la tarjeta de resultado:
   - que se pidio
   - que se ejecuto
   - conector usado
   - respuesta de Meta Graph
   - estado final

Si algo no es claro, vuelve a `Con supervision`:

```env
META_ADS_AGENT_MODE=dry-run
LIVE_ACTIONS_ENABLED=false
```
