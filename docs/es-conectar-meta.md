# Conectar mi cuenta de Facebook

## Paso seguro

El comprador conecta su propia cuenta de Facebook/Meta usando una clave creada por el mismo dentro de Facebook/Meta. Esto es mas confiable que entregar acceso a una plataforma desconocida porque el acceso nace desde su cuenta, queda guardado en su PC/VPS y puede revocarlo cuando quiera.

## Flujo recomendado

1. Abrir Facebook/Meta Developers.
2. Crear una app propia siguiendo las imagenes de guia.
3. Activar Marketing API o usar Graph API Explorer.
4. Generar una clave de acceso con permisos de anuncios y paginas.
5. Pegar la clave en el onboarding, en `Conectar mi cuenta de Facebook`.
6. Elegir la cuenta publicitaria.
7. Elegir pagina de Facebook, Instagram conectado si aplica, y URL de destino.
8. Tocar `Actualizar datos reales` si el dashboard aun muestra datos demo.

## Permisos sugeridos

- Lectura de cuentas publicitarias.
- Lectura de insights.
- Gestion de anuncios.
- Lectura de paginas para encontrar la pagina correcta.

## Si la clave vence

El dashboard pedira pegar una clave nueva. No significa que se perdio la cuenta: solo hay que generar una clave vigente y pegarla otra vez.
