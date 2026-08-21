# Canary de protección NVIDIA/Hermes

> Documento histórico para instalaciones antiguas que seleccionaron NVIDIA como proveedor principal. NVIDIA/NIM ya no forma parte del catálogo ni de la cadena de fallback del canary Gemini actual. El fallback vigente es exclusivamente `openai-codex` con `gpt-5.6-terra`, usando la suscripción ChatGPT/Codex conectada. No usar este procedimiento para validar el canary actual.

La protección se valida en dos capas:

1. `scripts/nvidia_protection_canary.py` construye solicitudes representativas
   de métricas, campañas, creativos, contenido orgánico, catálogo y contexto
   sobredimensionado. No llama a NVIDIA, Meta ni a un Gateway de comprador.
2. `scripts/run-remote-nvidia-protection-canary.sh` ejecuta una sola llamada
   Hermes, con un `HERMES_HOME` temporal, sin herramientas ni acciones de Meta.
   Copia solamente la configuración necesaria, registra conteos/tamaños y
   elimina el directorio temporal al terminar.

El gate comprueba:

- perfiles de herramientas: las herramientas Admira se reducen al flujo actual;
  memoria, archivos, web y visión nativos permanecen disponibles;
- `max_tokens` de hasta 8.192 en conversación normal y 12.288 en creativo/
  orgánico;
- presupuesto de entrada de 48.000 tokens después de ventana deslizante y
  recorte de último recurso;
- MiniMax M3 como principal, DeepSeek V4 Flash como primer pool alterno para
  timeout específico, y cero reintentos del mismo NIM tras 429/cuota/auth;
- diagnósticos sin mensajes, tokens, API keys ni secretos.

Ejemplo local:

```bash
python3 scripts/nvidia_protection_canary.py --output /tmp/nvidia-protection-report.json
```

Canary remoto (requiere que la clave SSH ya esté autorizada en el droplet):

```bash
./scripts/run-remote-nvidia-protection-canary.sh root@HOST ~/.ssh/admiro_ai admira-ia
```

El canary remoto no se considera aprobado si no puede autenticarse por SSH,
si el proveedor no devuelve diagnóstico, si Hermes tarda más del timeout o si
la solicitud supera cualquiera de los límites. No se debe convertir un bloqueo
de acceso en un “PASS” manual.
