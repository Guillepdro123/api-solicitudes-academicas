import threading
import time
from contextlib import contextmanager


class Ocupacion:
    """
    Mide cuánto tiempo estuvo trabajando un componente: el tiempo en que tuvo al menos
    una operación en curso. Ocupación cercana al 100 % durante una prueba = cuello de botella.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._activas = 0
        self._desde = 0.0
        self._ocupado = 0.0
        self._ultimo_fin = 0.0
        self.operaciones = 0

    @contextmanager
    def medir(self):
        with self._lock:
            if self._activas == 0:
                self._desde = time.monotonic()
            self._activas += 1
        try:
            yield
        finally:
            with self._lock:
                ahora = time.monotonic()
                self._activas -= 1
                self.operaciones += 1
                self._ultimo_fin = ahora
                if self._activas == 0:
                    self._ocupado += ahora - self._desde

    def resumen(self) -> dict:
        with self._lock:
            ocupado = self._ocupado
            if self._activas:
                ocupado += time.monotonic() - self._desde
            return {
                "ocupado_s": round(ocupado, 3),
                "en_curso": self._activas,
                "operaciones": self.operaciones,
                "ultimo_fin": self._ultimo_fin,
            }


api = Ocupacion()
excel = Ocupacion()
telegram = Ocupacion()


def resumen() -> dict:
    return {
        "ahora": time.monotonic(),
        "api": api.resumen(),
        "excel": excel.resumen(),
        "telegram": telegram.resumen(),
    }
