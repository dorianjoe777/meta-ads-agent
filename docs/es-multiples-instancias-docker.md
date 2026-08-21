# Varias instancias de Admira IA en el mismo equipo

Cuando el instalador detecta una instalación existente, muestra dos opciones:

1. Actualizar la instancia existente y conservar sus datos.
2. Crear una instancia nueva y aislada para otra licencia.

La segunda opción crea automáticamente una carpeta, proyecto Docker, contenedor,
puerto y volúmenes independientes. También genera una identidad de dispositivo
distinta para que la nueva licencia no se confunda con la instalación anterior.

Cada instancia debe usar:

- una licencia diferente;
- un bot de Telegram diferente (un bot no puede ser atendido por dos gateways);
- sus propias credenciales de Meta/Codex y sus propios datos.

El puerto de la nueva instancia se elige automáticamente a partir de `7871`.
La URL se muestra al terminar, por ejemplo `http://127.0.0.1:7872/`.

Para instalaciones automatizadas se puede seleccionar la opción sin preguntas:

```text
META_ADS_INSTANCE_MODE=new
META_ADS_NEW_INSTANCE_DIR=C:\ruta\Admira IA Cliente 2
```

En una actualización se debe conservar `META_ADS_INSTANCE_MODE=existing` o no
definirlo; así el instalador mantiene la configuración y los volúmenes actuales.
