# Conectar mi cuenta de Facebook

## Idea simple

Admiro debe conectarse a tu propia cuenta de Meta para leer datos reales y preparar acciones. Tienes dos caminos: una conexión estable recomendada, o una clave rápida para empezar antes.

Nosotros no recibimos esa clave. Queda guardada solo en tu PC o VPS, dentro de tu instalación.

## Opción 1: conexión estable recomendada

Usa esta ruta si vas a trabajar con el agente todos los días.

1. Entra a Meta Business Settings.
2. Abre `Usuarios del sistema`.
3. Crea un Usuario del sistema para Admiro.
4. Dale acceso a tu cuenta publicitaria.
5. Dale acceso a tu página de Facebook.
6. Si usas Instagram conectado, asegúrate de que la página tenga ese Instagram vinculado.
7. Genera una clave para ese Usuario del sistema.
8. Marca permisos de anuncios y páginas según la guía visual incluida con tu compra.
9. Pega esa clave en el onboarding de Admiro, en `Conectar mi cuenta de Facebook`.
10. Toca `Buscar mis cuentas` y elige la cuenta publicitaria correcta.

Esta ruta es más larga que Graph API Explorer, pero es la más cómoda para uso diario porque no depende de una clave rápida pensada para empezar o probar.

## Opción 2: empezar más rápido

Usa Graph API Explorer si quieres empezar más rápido o si todavía no tienes acceso completo al Meta Business de la página.

Esta ruta puede funcionar bien para comenzar. La diferencia es que la clave puede vencer, así que Admiro te avisará para renovarla aproximadamente cada 60 días. También podrás cambiar a la conexión estable más adelante desde `Configuración`.

## Permisos sugeridos

- Leer cuentas publicitarias.
- Leer resultados e insights.
- Gestionar anuncios cuando apruebes acciones.
- Leer páginas para encontrar la página correcta.
- Leer Instagram conectado si tu página lo usa.

## Si la clave deja de funcionar

No significa que perdiste tu cuenta ni tus anuncios. Normalmente significa que Meta rechazó esa clave, fue revocada, perdió permisos o venció si usaste una clave rápida.

La solución es crear o pegar una clave nueva y volver a tocar `Buscar mis cuentas`. Si estás usando la ruta rápida, esto puede pasar cada cierto tiempo y es normal.

## Por qué esto es más seguro

La conexión queda entre tu Meta Business y tu instalación local/VPS. Si algún día quieres cortar acceso, revocas la clave desde Meta.

Para compradores principiantes, la instalación guiada debe hacer este paso contigo.
