# Monitor de la web de Reclutamiento de Defensa

Proyecto minimo que comprueba cada cinco minutos si ha cambiado el HTML de una pagina de Reclutamiento de Defensa. Calcula un SHA256 del contenido, conserva el ultimo hash en el repositorio y envia una alerta por Telegram cuando detecta un cambio.

## Que contiene

- `.github/workflows/monitor.yml`: workflow programado cada cinco minutos y ejecutable manualmente.
- `monitor.py`: descarga, calcula el hash, compara y envia la notificacion.
- `page_hash.txt`: estado persistente del ultimo contenido observado.
- `requirements.txt`: dependencia `requests`.

## 1. Crear el bot de Telegram

1. En Telegram, abre el chat oficial `@BotFather`.
2. Envia `/newbot`.
3. Sigue las instrucciones para elegir el nombre y el nombre de usuario del bot.
4. BotFather te entregara un token. Guardalo: sera el secreto `BOT_TOKEN`.
5. Abre el chat de tu nuevo bot y pulsa **Start**, o enviale cualquier mensaje.
6. En un navegador abre esta direccion, sustituyendo `<TOKEN>` por el token real:

   `https://api.telegram.org/bot<TOKEN>/getUpdates`

7. Busca en la respuesta una seccion parecida a `"chat":{"id":123456789,...}`. Ese numero es tu `CHAT_ID`.

Si `result` aparece vacio, vuelve a enviar un mensaje al bot y recarga la direccion. No publiques ni compartas el token.

## 2. Crear el repositorio

1. Crea un repositorio nuevo en GitHub, publico o privado.
2. Sube **el contenido de esta carpeta**, manteniendo exactamente la ruta `.github/workflows/monitor.yml`.
3. No subas la carpeta contenedora como un unico archivo ZIP. Descomprime primero y sube los archivos.

La forma mas sencilla desde la web de GitHub es **Add file > Upload files** y arrastrar todos los archivos y carpetas. Comprueba despues que el workflow aparece en la pestana **Actions**.

## 3. Crear los GitHub Secrets

En el repositorio ve a:

**Settings > Secrets and variables > Actions > New repository secret**

Crea exactamente estos dos secretos:

- `BOT_TOKEN`: el token entregado por BotFather.
- `CHAT_ID`: el identificador numerico obtenido con `getUpdates`.

Los nombres distinguen mayusculas y minusculas.

## 4. Permitir que Actions haga commits

El workflow solicita solamente `contents: write`. Normalmente esto basta gracias al bloque `permissions` incluido.

Si el `git push` recibe un error de permisos, ve a:

**Settings > Actions > General > Workflow permissions**

Selecciona **Read and write permissions** y guarda los cambios. Si la rama predeterminada tiene protecciones que impiden pushes directos, tendras que permitir el push del bot o usar una rama sin esa restriccion.

## 5. Primera ejecucion

1. Abre **Actions** en el repositorio.
2. Selecciona **Monitor de Reclutamiento Defensa**.
3. Pulsa **Run workflow**.
4. La primera ejecucion guarda el hash inicial y realiza un commit, pero no envia Telegram. Esto evita una falsa alarma.
5. Las siguientes ejecuciones comparan el HTML con ese estado inicial. Solo si cambia se actualiza el hash, se hace commit y se envia el mensaje.

## Comportamiento ante errores

- Un fallo HTTP, una respuesta vacia o un timeout hacen fallar la ejecucion sin sustituir el hash.
- Telegram se ejecuta despues del `git push`, por lo que solo se avisa cuando el nuevo estado ya esta guardado.
- El control de concurrencia evita dos ejecuciones simultaneas del monitor.
- GitHub puede retrasar los workflows programados. El cron solicita una ejecucion cada cinco minutos, pero no garantiza que empiece exactamente en el segundo previsto.

## Prueba opcional de Telegram

Tras crear los Secrets, puedes comprobar el aviso temporalmente desde una ejecucion local solo si defines `BOT_TOKEN` y `CHAT_ID` como variables de entorno. No guardes estos valores en archivos del repositorio.

## Notas

El hash se calcula sobre los bytes completos del HTML, tal como devuelve el servidor. Esto detecta cualquier alteracion, incluso cambios tecnicos no visibles. El proyecto no descarga ni compara el contenido de los PDF enlazados; detecta cambios en la pagina HTML y sus enlaces.