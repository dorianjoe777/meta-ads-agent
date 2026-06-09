# Instalacion guiada en DigitalOcean

Esta opcion es para compradores que quieren dejar Admiro AI encendido aunque su PC este apagado.

El comprador entra a `https://admiroia.uboost.lat/access`, valida su email de compra y clave de acceso, y puede elegir `Instalar en la nube`.

Recomendamos DigitalOcean para esta opcion porque es un proveedor cloud confiable, simple de usar y con precios previsibles. Sus Droplets basicos suelen empezar cerca de US$4 a US$6 al mes, segun el tamano elegido. Las cuentas nuevas pueden ver credito inicial o promociones; el comprador siempre debe revisar el precio final en DigitalOcean antes de crear el servidor.

## Que hace el portal

1. Registra la llave publica SSH del comprador en su cuenta de DigitalOcean.
2. Crea un firewall donde el dashboard queda cerrado a la IP actual del comprador.
3. Crea un Droplet Ubuntu nuevo.
4. Instala Docker y Admiro AI con `cloud-init`.
5. Descarga la release privada usando una URL firmada del servidor de licencias.
6. Deja SSH abierto solo con llave para recuperacion, con contrasena SSH desactivada.
7. Deja el dashboard disponible en el puerto `7871`, protegido por firewall e inicio de sesion.
8. Crea un enlace seguro para abrir el dashboard aunque la IP del comprador cambie.
9. Si el servidor de licencias tiene DNS configurado en Vercel, crea un subdominio HTTPS y un certificado gratis de Let's Encrypt.

## Que necesita el comprador

- Una cuenta de DigitalOcean.
- Un token de DigitalOcean con permisos limitados.
- Una llave publica SSH de su equipo.
- Un metodo de pago activo en DigitalOcean.

En palabras simples:

1. Crear cuenta en DigitalOcean.
2. Agregar metodo de pago.
3. Abrir el area API de DigitalOcean.
4. Crear un token API.
5. Pegar ese token en el portal de Admiro AI.
6. Pegar la llave publica SSH.

Permisos recomendados para el token:

- Droplets: crear y leer.
- Firewalls: crear, leer y actualizar.
- SSH Keys: crear y leer.
- Tags: crear y leer.

El portal usa el token para crear el servidor, configurar la llave SSH, preparar el firewall e instalar Admiro AI. No se muestra una opcion confusa de "guardar token" en la pagina de acceso: el portal lo conserva cifrado para poder recuperar acceso o reinstalar sin pedirlo otra vez. Si el comprador borra el token desde DigitalOcean, puede pegar uno nuevo cuando lo necesite.

El token tambien queda dentro del Droplet del comprador para que el servidor pueda actualizar el acceso seguro cuando cambie la IP de su red.

Importante: crea este token sin fecha de vencimiento si DigitalOcean te da esa opcion. Si prefieres poner vencimiento, que sea largo y anotalo para renovarlo antes de que expire. Si el token vence, el Droplet puede seguir funcionando, pero no podra actualizar automaticamente el firewall cuando cambie la IP.

## Por que no usamos Marketplace en v1

DigitalOcean Marketplace puede ser una buena version futura, pero requiere empaquetado, revision y mantenimiento de imagenes. Para vender rapido, la instalacion guiada por API da una experiencia parecida a un click sin esperar aprobacion del marketplace.

## Flujo para soporte

1. Pedir al comprador que entre a `https://admiroia.uboost.lat/access`.
2. Validar email y clave de acceso.
3. Abrir `Instalar en la nube`.
4. Pegar token de DigitalOcean.
5. Pegar llave publica SSH.
6. Elegir region y tamano.
7. Clic en `Crear mi servidor`.
8. Esperar de 5 a 10 minutos.
9. Hacer clic en `Abrir mi dashboard`.
10. Completar el onboarding dentro del dashboard.

## Por que es seguro pegar la llave publica SSH

La llave SSH es la capa que evita que cualquier persona de internet pueda intentar entrar al dashboard. La parte privada queda guardada en el computador del comprador. El portal solo pide la parte publica.

La llave publica SSH se puede compartir porque por si sola no abre nada. Solo sirve para decirle al servidor: "permite entrar a quien tenga la llave privada correcta".

La llave privada es la parte secreta. Esa queda guardada en el computador del comprador y no debe compartirse. Sin esa llave privada, ni Admiro AI, ni soporte, ni otra persona puede entrar al servidor usando solo la llave publica.

En palabras simples para el comprador:

> La llave publica se puede pegar aqui. La llave privada no se comparte nunca.

## Abrir mi dashboard

Cuando el servidor termina de crearse, el portal muestra un boton grande:

```text
Abrir mi dashboard
```

Mientras DigitalOcean instala el producto, el portal muestra una barra de progreso. Esa barra empieza cuando el Droplet fue creado, luego revisa si la puerta segura del servidor ya responde, y finalmente cambia a `Acceder a mi dashboard` cuando el dashboard esta listo.

Ese boton no es un enlace directo simple. Primero abre una pequena puerta segura del Droplet, que hace esto:

1. Detecta la IP publica actual del comprador.
2. autoriza la IP actual en el firewall de DigitalOcean.
3. Redirige al dashboard normal.

En palabras simples para el comprador:

> Si tu internet cambia de direccion, no tienes que saberlo. Entra desde el mismo boton y el servidor acomoda el acceso antes de abrir.

Si HTTPS esta configurado, ese boton termina abriendo un enlace normal y seguro, por ejemplo:

```text
https://tu-servidor.cloud.admiroia.uboost.lat
```

Esto quita el aviso de `No seguro` del navegador. No cambia la propiedad del servidor: el Droplet sigue estando en la cuenta de DigitalOcean del comprador.

El hosting del portal puede seguir en Vercel. Solo usamos la API de Vercel DNS para crear automaticamente el registro A que apunta al Droplet.

El enlace de apertura usa una clave larga generada durante la instalacion. No contiene el token de DigitalOcean. No permite controlar el agente. Solo permite preparar la red actual para que el dashboard pueda cargar.

## Protector automatico de acceso avanzado

El helper local por hora sigue disponible como respaldo avanzado, pero no es el flujo principal para compradores.

Si se instala en el computador del comprador, corre cada hora. Su trabajo es simple:

1. Revisa la IP publica actual del computador.
2. Si cambio, entra al Droplet por SSH usando la llave privada del comprador.
3. Le pide al Droplet que actualice el firewall de DigitalOcean.
4. No guarda el token de DigitalOcean en el computador del comprador.

Esto evita que el comprador tenga que escribir a soporte solo porque su proveedor de internet le cambio la IP, pero en v1 el camino mas simple es usar siempre el boton `Abrir mi dashboard`.

Para que funcione, el computador debe estar encendido y debe conservar la llave privada SSH que corresponde a la llave publica pegada durante la instalacion.

Si el comprador pierde el enlace de apertura o el Droplet fue modificado manualmente, SSH queda como recuperacion tecnica:

```bash
ssh root@IP-DEL-VPS
```

Al entrar, el Droplet detecta la IP del computador y actualiza el firewall automaticamente. Si quieres forzarlo, corre:

```bash
~/.local/bin/meta-ads-refresh-access
```

Despues de eso el firewall vuelve a permitir la IP actual. Cuando el dashboard vuelva a cargar, puede usar el boton de configuracion para mantener esa red autorizada.

Si SSH no entra, normalmente significa que falta la llave correcta o que se cambio el acceso SSH. En ese caso usa la consola web del Droplet en DigitalOcean.
