import asyncio
import logging
import os

import httpx

import metricas

logger = logging.getLogger(__name__)

# Cliente HTTP compartido: reutiliza la conexión con Telegram en lugar de abrir una por mensaje
_cliente: httpx.AsyncClient | None = None

# Contadores para el informe de las pruebas de carga (se exponen en /salud)
estadisticas = {"mensajes_enviados": 0, "mensajes_fallidos": 0, "solicitudes_notificadas": 0}


async def iniciar():
    global _cliente
    _cliente = httpx.AsyncClient(timeout=httpx.Timeout(10.0))


async def cerrar():
    if _cliente is not None:
        await _cliente.aclose()


def _configuracion():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id or bot_token == "TU_TOKEN_AQUI" or chat_id == "TU_CHAT_ID_AQUI":
        return None
    return bot_token, chat_id


def _formatear(solicitud: dict) -> str:
    # Mensaje corto con el número consecutivo: permite contar en el chat cuántas solicitudes llegaron
    return f"Solicitud {solicitud['numero']}"


def _formatear_resumen(lote: list[dict]) -> str:
    return "\n".join(_formatear(s) for s in lote)


async def enviar_mensaje(texto: str, reintentos: int = 0) -> bool:
    """Envía un mensaje. Si Telegram responde 429, espera lo que indique retry_after y reintenta."""
    configuracion = _configuracion()
    if configuracion is None:
        logger.warning("Credenciales de Telegram no configuradas en el .env. Omitiendo notificación.")
        return False
    bot_token, chat_id = configuracion
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto}

    for intento in range(reintentos + 1):
        try:
            with metricas.telegram.medir():
                response = await _cliente.post(url, json=payload)
        except httpx.HTTPError as e:
            # No se registra str(e): puede incluir la URL con el token del bot
            logger.error("Error de red al enviar a Telegram: %s", type(e).__name__)
            if intento < reintentos:
                await asyncio.sleep(2**intento)
                continue
            break

        if response.status_code == 429 and intento < reintentos:
            espera = response.json().get("parameters", {}).get("retry_after", 1)
            logger.warning("Telegram limitó los mensajes (429). Reintentando en %s s.", espera)
            await asyncio.sleep(espera)
            continue
        if response.is_error:
            descripcion = response.json().get("description", "") if response.content else ""
            logger.error("Telegram respondió %s: %s", response.status_code, descripcion)
            break

        estadisticas["mensajes_enviados"] += 1
        return True

    estadisticas["mensajes_fallidos"] += 1
    return False


async def notificar_solicitud(solicitud: dict):
    """Modo directo: un mensaje por solicitud, sin cola ni reintentos."""
    if await enviar_mensaje(_formatear(solicitud)):
        estadisticas["solicitudes_notificadas"] += 1


class NotificadorTelegram:
    """
    Modo cola: envía las notificaciones en orden con una pausa entre mensajes y respeta
    retry_after. Con max_por_mensaje > 1 agrupa varias solicitudes en un mismo mensaje.
    """

    def __init__(self, intervalo: float = 1.0, max_por_mensaje: int = 1):
        self._intervalo = intervalo
        self._max_por_mensaje = max_por_mensaje
        self._cola: asyncio.Queue[dict] = asyncio.Queue()
        self._tarea: asyncio.Task | None = None

    def encolar(self, solicitud: dict):
        self._cola.put_nowait(solicitud)

    def pendientes(self) -> int:
        return self._cola.qsize()

    def iniciar(self):
        self._tarea = asyncio.create_task(self._trabajar())

    async def detener(self, timeout: float = 30):
        try:
            await asyncio.wait_for(self._cola.join(), timeout)
        except asyncio.TimeoutError:
            logger.error("Se cerró la app con %d notificaciones sin enviar.", self._cola.qsize())
        self._tarea.cancel()

    async def _trabajar(self):
        while True:
            lote = [await self._cola.get()]
            while len(lote) < self._max_por_mensaje and not self._cola.empty():
                lote.append(self._cola.get_nowait())
            try:
                texto = _formatear(lote[0]) if len(lote) == 1 else _formatear_resumen(lote)
                if await enviar_mensaje(texto, reintentos=3):
                    estadisticas["solicitudes_notificadas"] += len(lote)
                else:
                    logger.error("No se pudieron notificar %d solicitudes.", len(lote))
            except Exception:
                logger.exception("Error inesperado en el notificador de Telegram.")
            finally:
                for _ in lote:
                    self._cola.task_done()
            await asyncio.sleep(self._intervalo)
