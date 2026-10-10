# API de Solicitudes Académicas

API REST en FastAPI para registrar, consultar y actualizar solicitudes académicas de estudiantes.
Cada solicitud se guarda como una fila en un archivo Excel en Google Drive y se notifica al personal
académico mediante un bot de Telegram.

```
Usuario ──► Página web / API (FastAPI) ──► Procesamiento (validar y orquestar) ──┬──► Excel en Google Drive (Drive API)
                                                                                  └──► Bot de Telegram (Bot API)
```

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/solicitudes` | Registra una solicitud y notifica por Telegram |
| `GET` | `/solicitudes` | Lista todas las solicitudes |
| `GET` | `/solicitudes/{id}` | Consulta una solicitud |
| `PUT` | `/solicitudes/{id}` | Actualiza el estado (`Pendiente`, `En proceso`, `Resuelta`, `Rechazada`) |
| `GET` | `/salud` | Modo de guardado, colas pendientes y contadores de Telegram |
| `GET` | `/` | Página web para usar la API |
| `GET` | `/monitor` | Panel en vivo de colas, Telegram y ocupación (para observar las pruebas de carga) |
| `GET` | `/docs` | Documentación interactiva (Swagger) |

Ejemplo de registro:

```json
POST /solicitudes
{ "estudiante": "Ana Gómez", "tipo": "Certificado", "descripcion": "Certificado de notas del semestre" }
```

Tipos válidos: `Certificado`, `Constancia`, `Homologación`, `Cancelación de asignatura`, `Reintegro`, `Otro`.
El servidor asigna `id`, `estado` (`Pendiente`) y `fecha`.

## Estructura del proyecto

```
main.py                 API FastAPI: modelos, endpoints y modo de guardado
cola_excel.py           Cola de escritura por lotes con reintentos (modo cola)
metricas.py             Medición de ocupación de API, Excel y Telegram
verificar_drive.py      Comprueba el acceso de la cuenta de servicio al Excel
reiniciar_excel.py      Deja el Excel de Drive vacío para repetir las pruebas
excel/
  solicitudes_academicas.xlsx   Plantilla del Excel para subir a Drive
integrations/
  excel.py              Lectura y escritura del Excel en Google Drive
  telegram.py           Envío de notificaciones y cola de Telegram
public/                 Página web (formulario y tabla de solicitudes)
pruebas/
  prueba_carga.py       Prueba de 10, 25, 50 y 100 solicitudes + reporte
  reporte_plantilla.html
  capturar_monitor.js   Captura /monitor cada N segundos durante las pruebas (Node 22+)
  locustfile.py         Prueba alternativa con Locust
  resultados/           JSON de resultados y reporte.html (se generan)
```

## Ejecutar en local

1. Crear el entorno e instalar dependencias:

   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Copiar `.env.example` como `.env` y completar los valores:
   - `TELEGRAM_BOT_TOKEN`: lo entrega @BotFather al crear el bot.
   - `TELEGRAM_CHAT_ID`: chat donde llegan las notificaciones.
   - `GOOGLE_APPLICATION_CREDENTIALS`: ruta al JSON de la cuenta de servicio de Google Cloud (con la Drive API habilitada).
   - `GOOGLE_DRIVE_FILE_ID`: ID del `.xlsx` en Drive (ver el paso 3).

3. Configurar el Excel en Google Drive:
   1. Sube `excel/solicitudes_academicas.xlsx` a tu Google Drive. Debe quedar como `.xlsx`: si en la
      configuración de Drive está activo «Convertir archivos subidos al formato del editor de Documentos
      de Google», desactívalo antes de subirlo.
   2. Clic derecho en el archivo → **Compartir** → agrega el correo de la cuenta de servicio
      (`client_email` en `credenciales.json`) con rol **Editor**.
   3. Copia el enlace del archivo y verifica los permisos:

      ```bash
      python verificar_drive.py "https://docs.google.com/spreadsheets/d/.../edit"
      ```

      El script muestra el correo de la cuenta de servicio, comprueba el formato y el permiso de edición,
      y al final imprime la línea `GOOGLE_DRIVE_FILE_ID=...` para pegar en el `.env`.

   Las solicitudes se guardan en la hoja `Solicitudes` (columnas numero, id, estudiante, tipo,
   descripcion, estado, fecha). Si el libro no la tiene, se crea con el primer registro.

   Para empezar las pruebas desde cero: `python reiniciar_excel.py --si` deja el Excel vacío
   (mismo archivo, mismo enlace y permisos).

4. Iniciar la API y abrir http://localhost:8000:

   ```bash
   python main.py
   ```

## Publicar en Render

1. Subir el repositorio a GitHub (el `.gitignore` excluye `.env` y `credenciales.json`).
2. En Render: **New → Blueprint** y elegir el repositorio. Render lee `render.yaml`
   (Python 3.12, `pip install -r requirements.txt`, `uvicorn main:app --host 0.0.0.0 --port $PORT`).
3. Completar las variables que pide: `GOOGLE_DRIVE_FILE_ID`, `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`
   (los mismos valores del `.env`).
4. En el servicio → **Environment → Secret Files**, agregar un archivo llamado `credenciales.json`
   con el contenido del JSON de la cuenta de servicio. Queda en `/etc/secrets/credenciales.json`.
5. Al terminar el despliegue, la app queda en `https://<nombre>.onrender.com`. El plan gratuito se
   duerme tras un rato sin uso: abre `/salud` un minuto antes de la sustentación.

> Ejecuta **un solo proceso** (sin `--workers`). La cola que ordena las escrituras al Excel vive
> en memoria; con varios procesos volverían los choques entre escrituras.

## Pruebas de carga

La variable `MODO_GUARDADO` permite comparar la versión base con la mejorada:

| Modo | Comportamiento |
|---|---|
| `directo` (versión base) | Cada petición descarga el Excel, agrega la fila y lo sube **antes de responder**, con una llamada bloqueante. Telegram envía un mensaje por solicitud, sin reintentos. |
| `cola` (versión mejorada) | La petición responde de inmediato. Una cola guarda en segundo plano, **por lotes** (una descarga y una subida por lote), con reintentos y espera creciente. Telegram envía con pausa, respeta `retry_after` y agrupa las notificaciones acumuladas. |

Procedimiento:

1. Publica la app con `MODO_GUARDADO=directo` y ejecuta:

   ```bash
   python pruebas/prueba_carga.py --url https://TU-APP.onrender.com
   ```

   El script envía 10, 25, 50 y 100 solicitudes simultáneas y mide, para cada cantidad:
   - tiempo medio y máximo de respuesta,
   - solicitudes exitosas y errores con su código,
   - filas guardadas en Excel y solicitudes notificadas por Telegram,
   - **ocupación de cada componente** (API, Excel, Telegram): el porcentaje del tiempo de la prueba
     en que estuvo trabajando. Un componente cerca del 100 % es el cuello de botella.

2. Cambia a `MODO_GUARDADO=cola`, vuelve a desplegar y repite la misma prueba.

3. Abre `pruebas/resultados/reporte.html`. Muestra los resultados de cada modo y cantidad, con el
   diagnóstico (todo fluye / se degrada / se rompe), un gráfico del tiempo medio y la tabla comparativa.
   Los datos crudos quedan en `pruebas/resultados/resultados_<modo>.json`.
   - `reporte.html#cola-100` abre directamente un modo y una cantidad.
   - `reporte.html?solo=panel-grafico` muestra un solo panel (útil para capturas del informe).

Para dejar evidencia visual mientras corre la prueba, abre `/monitor` o captúralo automáticamente
(las imágenes quedan en `pruebas/capturas/`, nombradas con la fase, por ejemplo `cola-n1000_16-41-55.jpg`):

```bash
node pruebas/capturar_monitor.js --url https://TU-APP.onrender.com/monitor --intervalo 10
```

También se incluye `pruebas/locustfile.py` para hacer la prueba con Locust (`pip install locust`):

```bash
locust -f pruebas/locustfile.py --headless -u 50 -r 50 --run-time 2m --host https://TU-APP.onrender.com --csv resultados_50
```

## Puntos débiles identificados

1. **Cada petición espera a Drive.** En modo directo, la respuesta incluye descargar y subir el libro
   completo. Al crecer la carga, el tiempo aumenta casi linealmente y pueden aparecer timeouts o errores
   429 de Google.
2. **Llamadas externas bloqueantes.** El cliente de Google es síncrono. Dentro de una ruta `async`
   bloquea el servidor, así que todas las peticiones hacen fila detrás de la que está usando Drive.
3. **Escrituras simultáneas.** Guardar en Excel es descargar, modificar y subir el archivo completo.
   Si dos escrituras se ejecutan en paralelo (varios procesos, o rutas que corren en hilos), la segunda
   sobrescribe a la primera y se pierden filas.
4. **Límite de mensajes de Telegram.** Telegram limita los mensajes por segundo al mismo chat. Si se
   envían muchos de golpe, responde 429 y en modo directo esas notificaciones se pierden.

**Mejora aplicada (modo `cola`):** una sola cola en segundo plano serializa las escrituras, las agrupa en
lotes, reintenta con espera creciente y guarda en `fallidos.jsonl` lo que no se pudo escribir para
reenviarlo al reiniciar. Las notificaciones de Telegram también pasan por una cola con pausa, reintentos
según `retry_after` y agrupación en un resumen.

## Seguridad

- Las credenciales van en variables de entorno, nunca en el repositorio. Solo se sube `.env.example`.
- Si un token o la clave de la cuenta de servicio se filtra, revócalo y genera uno nuevo.
- Los mensajes de Telegram escapan el texto de los usuarios (HTML) y el Excel guarda todo como texto,
  para que un valor como `=HYPERLINK(...)` no se ejecute como fórmula.
