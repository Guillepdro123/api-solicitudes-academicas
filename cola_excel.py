import asyncio
import json
import logging
import os

from integrations import excel

logger = logging.getLogger(__name__)

# Solicitudes que no se pudieron guardar tras agotar los reintentos; se reenvían al reiniciar
ARCHIVO_FALLIDOS = "fallidos.jsonl"


class ColaExcel:
    """
    Serializa todas las escrituras al Excel en una sola cola.

    - Evita que dos peticiones descarguen, modifiquen y suban el libro a la vez (pérdida de filas).
    - Agrupa en lotes: una descarga y una subida por lote en lugar de una por solicitud.
    - Reintenta con espera creciente y registra los fallos para reenviarlos.
    """

    def __init__(self, tam_lote: int = 50, reintentos: int = 4):
        self._tam_lote = tam_lote
        self._reintentos = reintentos
        self._cola: asyncio.Queue[dict] = asyncio.Queue()
        self._por_guardar: dict[str, dict] = {}
        self._en_proceso = 0
        self._tarea: asyncio.Task | None = None

    def iniciar(self):
        self._reencolar_fallidos()
        self._tarea = asyncio.create_task(self._trabajar())

    async def detener(self, timeout: float = 60):
        try:
            await asyncio.wait_for(self._cola.join(), timeout)
        except asyncio.TimeoutError:
            logger.error("Se cerró la app con %d escrituras pendientes.", self._cola.qsize())
        self._tarea.cancel()

    def encolar_creacion(self, solicitud: dict):
        self._por_guardar[solicitud["id"]] = solicitud
        self._cola.put_nowait({"tipo": "crear", "solicitud": solicitud})

    async def actualizar(self, id: str, estado: str) -> dict | None:
        futuro = asyncio.get_running_loop().create_future()
        self._cola.put_nowait({"tipo": "actualizar", "id": id, "estado": estado, "futuro": futuro})
        return await futuro

    def por_guardar(self) -> list[dict]:
        """Solicitudes aceptadas que todavía no están en el Excel."""
        return list(self._por_guardar.values())

    def pendientes(self) -> int:
        """Operaciones en cola más las del lote que se está guardando."""
        return self._cola.qsize() + self._en_proceso

    async def _trabajar(self):
        while True:
            lote = [await self._cola.get()]
            while len(lote) < self._tam_lote and not self._cola.empty():
                lote.append(self._cola.get_nowait())
            self._en_proceso = len(lote)
            try:
                await self._procesar(lote)
            except Exception as e:
                logger.exception("Error inesperado en la cola de Excel.")
                for op in lote:
                    if op["tipo"] == "actualizar" and not op["futuro"].done():
                        op["futuro"].set_exception(e)
            finally:
                self._en_proceso = 0
                for _ in lote:
                    self._cola.task_done()

    async def _procesar(self, lote: list[dict]):
        operaciones = [{k: v for k, v in op.items() if k != "futuro"} for op in lote]
        for intento in range(self._reintentos + 1):
            try:
                resultados = await asyncio.to_thread(excel.aplicar_operaciones, operaciones)
                break
            except Exception as e:
                if intento == self._reintentos:
                    self._registrar_fallo(lote, e)
                    return
                espera = 2**intento
                logger.warning("Fallo al guardar un lote de %d (%s). Reintento en %d s.", len(lote), e, espera)
                await asyncio.sleep(espera)

        for op, resultado in zip(lote, resultados):
            if op["tipo"] == "crear":
                self._por_guardar.pop(op["solicitud"]["id"], None)
            elif not op["futuro"].done():
                op["futuro"].set_result(resultado)

    def _registrar_fallo(self, lote: list[dict], error: Exception):
        logger.error("No se pudo guardar un lote de %d tras %d reintentos: %s", len(lote), self._reintentos, error)
        with open(ARCHIVO_FALLIDOS, "a", encoding="utf-8") as archivo:
            for op in lote:
                if op["tipo"] == "crear":
                    archivo.write(json.dumps(op["solicitud"], ensure_ascii=False) + "\n")
                    self._por_guardar.pop(op["solicitud"]["id"], None)
                elif not op["futuro"].done():
                    op["futuro"].set_exception(error)

    def _reencolar_fallidos(self):
        if not os.path.exists(ARCHIVO_FALLIDOS):
            return
        with open(ARCHIVO_FALLIDOS, encoding="utf-8") as archivo:
            solicitudes = [json.loads(linea) for linea in archivo if linea.strip()]
        os.remove(ARCHIVO_FALLIDOS)
        for solicitud in solicitudes:
            self.encolar_creacion(solicitud)
        if solicitudes:
            logger.info("Reenviando %d solicitudes que habían fallado.", len(solicitudes))
