# Conectar Meta con tu propia app

## Por que usamos tu propia app de Meta

El comprador conecta su propia app/token de Meta. Esto es mas confiable que entregar acceso a una plataforma desconocida porque el acceso nace desde su cuenta y puede revocarlo cuando quiera.

## Flujo recomendado

1. Abrir Meta Developers.
2. Crear una app propia.
3. Activar Marketing API o usar Graph API Explorer.
4. Generar un token con permisos de anuncios y paginas.
5. Pegar el token en el onboarding.
6. Elegir la cuenta publicitaria.
7. Elegir pagina de Facebook, Instagram conectado si aplica, y URL de destino.
8. Tocar `Actualizar datos reales` si el dashboard aun muestra datos demo.

## Permisos sugeridos

- Lectura de cuentas publicitarias.
- Lectura de insights.
- Gestion de anuncios.
- Lectura de paginas para encontrar la pagina correcta.

## Si el token vence

El dashboard pedira pegar un token nuevo. No significa que se perdio la cuenta: solo hay que generar un token vigente y pegarlo otra vez.
