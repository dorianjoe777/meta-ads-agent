# Conectar mi cuenta de Facebook

## Idea simple

Admiro debe conectarse a tu propia cuenta de Meta para leer datos reales y preparar acciones. La conexión recomendada no es un token temporal de prueba: es una clave estable creada dentro de tu propio Meta Business.

Nosotros no recibimos esa clave. Queda guardada solo en tu PC o VPS, dentro de tu instalación.

## Ruta recomendada: conexión estable

Usa esta ruta si vas a trabajar con el agente todos los días.

1. Entra a Meta Business Settings.
2. Abre `Usuarios del sistema`.
3. Crea un Usuario del sistema para Admiro.
4. Dale acceso a tu cuenta publicitaria.
5. Dale acceso a tu página de Facebook.
6. Si usas Instagram conectado, asegúrate de que la página tenga ese Instagram vinculado.
7. Genera una clave/token para ese Usuario del sistema.
8. Marca permisos de anuncios y páginas según la guía visual incluida con tu compra.
9. Pega esa clave en el onboarding de Admiro, en `Conectar mi cuenta de Facebook`.
10. Toca `Buscar mis cuentas` y elige la cuenta publicitaria correcta.

Esta ruta es más larga que Graph API Explorer, pero es la ruta correcta para un producto real porque no depende de un token temporal pensado para pruebas.

## Ruta rápida: token temporal

Usa Graph API Explorer solo si quieres probar rápido.

Esta ruta puede funcionar para una demo, pero no es ideal para dejar el agente trabajando porque la clave puede vencer y tendrás que reconectar.

## Permisos sugeridos

- Leer cuentas publicitarias.
- Leer resultados e insights.
- Gestionar anuncios cuando apruebes acciones.
- Leer páginas para encontrar la página correcta.
- Leer Instagram conectado si tu página lo usa.

## Si la clave deja de funcionar

No significa que perdiste tu cuenta ni tus anuncios. Normalmente significa que Meta rechazó esa clave, fue revocada, perdió permisos o venció si usaste una clave temporal.

La solución es crear o pegar una clave nueva y volver a tocar `Buscar mis cuentas`.

## Por qué esto es más seguro

La conexión queda entre tu Meta Business y tu instalación local/VPS. Si algún día quieres cortar acceso, revocas la clave desde Meta.

Para compradores principiantes, la instalación guiada debe hacer este paso contigo.
