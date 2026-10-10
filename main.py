import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

# Cargar variables de entorno
load_dotenv()

# Importar las integraciones
import metricas
from cola_excel import ColaExcel
from integrations import excel, telegram

logging.basicConfig(level=logging.INFO)
# El log INFO de httpx imprime la URL de Telegram, que incluye el token del bot
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# "directo": versión base (cada petición espera a Drive). "cola": versión mejorada.
# Ejecuta la prueba de carga con ambos modos para comparar el antes y el después.
MODO = os.getenv("MODO_GUARDADO", "cola").lower()
if MODO not in {"directo", "cola"}:
    raise ValueError("MODO_GUARDADO debe ser 'directo' o 'cola'.")
ZONA_HORARIA = ZoneInfo(os.getenv("ZONA_HORARIA", "America/Bogota"))

TipoSolicitud = Literal["Certificado", "Constancia", "Homologación", "Cancelación de asignatura", "Reintegro", "Otro"]
EstadoSolicitud = Literal["Pendiente", "En proceso", "Resuelta", "Rechazada"]


# Modelos de Pydantic para validación de datos
class SolicitudEntrada(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    estudiante: str = Field(min_length=3, max_length=100)
    tipo: TipoSolicitud
    descripcion: str = Field(min_length=5, max_length=500)


class Solicitud(BaseModel):
    numero: int
    id: str
    estudiante: str
    tipo: str
    descripcion: str
    estado: str
    fecha: str


class CambioEstado(BaseModel):
    estado: EstadoSolicitud


cola_excel = ColaExcel()
notificador = telegram.NotificadorTelegram(
    intervalo=float(os.getenv("TELEGRAM_INTERVALO", "1")),
    max_por_mensaje=int(os.getenv("TELEGRAM_MAX_POR_MENSAJE", "1")),
)

# Número consecutivo de cada solicitud ("Solicitud 1", "Solicitud 2"...), continúa desde el Excel
ultimo_numero = {"valor": 0}


def siguiente_numero() -> int:
    ultimo_numero["valor"] += 1
    return ultimo_numero["valor"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        ultimo_numero["valor"] = await asyncio.to_thread(excel.ultimo_numero)
    except Exception:
        logger.exception("No se pudo leer el último número del Excel; la numeración empieza en 1.")
    await telegram.iniciar()
    if MODO == "cola":
        cola_excel.iniciar()
        notificador.iniciar()
    logger.info("API iniciada en modo '%s'.", MODO)
    yield
    if MODO == "cola":
        await cola_excel.detener()
        await notificador.detener()
    await telegram.cerrar()


app = FastAPI(title="API de Solicitudes Académicas", lifespan=lifespan)
app.mount("/public", StaticFiles(directory="public"), name="public")


@app.get("/", include_in_schema=False)
async def read_root():
    """Sirve la página web de la aplicación."""
    return FileResponse(os.path.join("public", "index.html"))


@app.get("/monitor", include_in_schema=False)
async def monitor():
    """Panel en vivo de las colas y la ocupación, para observar las pruebas de carga."""
    return FileResponse(os.path.join("public", "monitor.html"))


@app.middleware("http")
async def medir_api(request: Request, call_next):
    """Mide la ocupación de la API (solo las rutas de solicitudes)."""
    if not request.url.path.startswith("/solicitudes"):
        return await call_next(request)
    with metricas.api.medir():
        return await call_next(request)


@app.get("/salud")
async def salud():
    """Estado de la API, de las colas y ocupación de cada componente. Útil durante las pruebas de carga."""
    resumen = metricas.resumen()
    pendientes_excel = cola_excel.pendientes() if MODO == "cola" else 0
    pendientes_telegram = notificador.pendientes() if MODO == "cola" else notificaciones_directas["pendientes"]
    return {
        "modo": MODO,
        "pendientes_excel": pendientes_excel,
        "pendientes_telegram": pendientes_telegram,
        "trabajo_pendiente": bool(
            pendientes_excel
            or pendientes_telegram
            or any(resumen[c]["en_curso"] for c in ("api", "excel", "telegram"))
        ),
        "telegram": telegram.estadisticas,
        "metricas": resumen,
    }


# Modo directo: notificaciones programadas con BackgroundTasks que aún no terminan
notificaciones_directas = {"pendientes": 0}


async def _notificar_directo(solicitud: dict):
    try:
        await telegram.notificar_solicitud(solicitud)
    finally:
        notificaciones_directas["pendientes"] -= 1


@app.post("/solicitudes", status_code=201, response_model=Solicitud)
async def registrar_solicitud(entrada: SolicitudEntrada, background_tasks: BackgroundTasks):
    """Registra una solicitud, la guarda en Excel (Google Drive) y notifica por Telegram."""
    solicitud = {
        "numero": siguiente_numero(),
        "id": uuid.uuid4().hex[:8],
        **entrada.model_dump(),
        "estado": "Pendiente",
        "fecha": datetime.now(ZONA_HORARIA).isoformat(timespec="seconds"),
    }

    if MODO == "cola":
        # Responde de inmediato; la cola guarda en Excel y notifica en segundo plano
        cola_excel.encolar_creacion(solicitud)
        notificador.encolar(solicitud)
        return solicitud

    # Modo directo: la petición espera a Drive con una llamada bloqueante
    try:
        excel.aplicar_operaciones([{"tipo": "crear", "solicitud": solicitud}])
    except Exception:
        logger.exception("Error al guardar la solicitud en Excel.")
        raise HTTPException(status_code=502, detail="No se pudo guardar la solicitud en Excel.")
    notificaciones_directas["pendientes"] += 1
    background_tasks.add_task(_notificar_directo, solicitud)
    return solicitud


async def _leer_solicitudes() -> list[dict]:
    try:
        if MODO == "directo":
            return excel.leer_solicitudes()
        guardadas = await asyncio.to_thread(excel.leer_solicitudes)
    except Exception:
        logger.exception("Error al leer las solicitudes de Excel.")
        raise HTTPException(status_code=502, detail="No se pudieron leer las solicitudes de Excel.")
    # Incluye las solicitudes aceptadas que la cola aún no ha escrito
    ids = {s["id"] for s in guardadas}
    return guardadas + [s for s in cola_excel.por_guardar() if s["id"] not in ids]


@app.get("/solicitudes", response_model=list[Solicitud])
async def listar_solicitudes():
    """Lista todas las solicitudes registradas."""
    return await _leer_solicitudes()


@app.get("/solicitudes/{id}", response_model=Solicitud)
async def consultar_solicitud(id: str):
    """Consulta una solicitud por su id."""
    for solicitud in await _leer_solicitudes():
        if solicitud["id"] == id:
            return solicitud
    raise HTTPException(status_code=404, detail="Solicitud no encontrada")


@app.put("/solicitudes/{id}", response_model=Solicitud)
async def actualizar_estado(id: str, cambio: CambioEstado):
    """Actualiza el estado de una solicitud, por ejemplo de «Pendiente» a «Resuelta»."""
    try:
        if MODO == "cola":
            actualizada = await cola_excel.actualizar(id, cambio.estado)
        else:
            [actualizada] = excel.aplicar_operaciones([{"tipo": "actualizar", "id": id, "estado": cambio.estado}])
    except Exception:
        logger.exception("Error al actualizar la solicitud en Excel.")
        raise HTTPException(status_code=502, detail="No se pudo actualizar la solicitud en Excel.")
    if actualizada is None:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    return actualizada


# Si se ejecuta este archivo directamente
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
