"""
Envía 10, 25, 50 y 100 solicitudes simultáneas y mide lo que pide la tabla del informe:
tiempo medio y máximo, exitosas, errores con su código, filas guardadas en Excel,
notificaciones de Telegram y la ocupación de cada componente (API, Excel, Telegram).

Los resultados se guardan en pruebas/resultados/resultados_<modo>.json y se genera
pruebas/resultados/reporte.html con la comparación entre modos.

    python pruebas/prueba_carga.py --url https://TU-APP.onrender.com
    python pruebas/prueba_carga.py --url http://localhost:8000 --cantidades 10 25
    python pruebas/prueba_carga.py --solo-reporte
"""
import argparse
import asyncio
import json
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx

CARPETA = Path(__file__).parent
RESULTADOS = CARPETA / "resultados"
COMPONENTES = ("api", "excel", "telegram")


async def enviar(cliente: httpx.AsyncClient, etiqueta: str, i: int):
    inicio = time.perf_counter()
    try:
        response = await cliente.post(
            "/solicitudes",
            json={"estudiante": f"{etiqueta} #{i}", "tipo": "Certificado", "descripcion": "Solicitud de carga"},
        )
        codigo = response.status_code
    except httpx.HTTPError as e:
        codigo = type(e).__name__
    return time.perf_counter() - inicio, codigo


async def salud(cliente: httpx.AsyncClient) -> dict:
    return (await cliente.get("/salud", timeout=None)).json()


async def esperar_fin(cliente: httpx.AsyncClient, limite: float) -> dict:
    """Espera a que la API termine de responder, guardar en Excel y notificar por Telegram."""
    inicio = time.perf_counter()
    while True:
        estado = await salud(cliente)
        if not estado["trabajo_pendiente"]:
            return estado
        if time.perf_counter() - inicio > limite:
            print("  ⚠ La API no terminó a tiempo; los resultados pueden estar incompletos.")
            return estado
        await asyncio.sleep(1)


def ocupacion(antes: dict, despues: dict) -> tuple[float, dict]:
    """Duración de la prueba (en el reloj del servidor) y % de ese tiempo que cada componente trabajó."""
    m0, m1 = antes["metricas"], despues["metricas"]
    finales = [m1[c]["ultimo_fin"] for c in COMPONENTES if m1[c]["operaciones"] > m0[c]["operaciones"]]
    duracion = max(finales, default=m1["ahora"]) - m0["ahora"]
    return duracion, {
        c: round(100 * (m1[c]["ocupado_s"] - m0[c]["ocupado_s"]) / duracion, 1) if duracion > 0 else 0
        for c in COMPONENTES
    }


def marcar_fase(fase: str):
    """Deja la fase actual en un archivo para que capturar_monitor.js nombre las capturas."""
    RESULTADOS.mkdir(exist_ok=True)
    (RESULTADOS / "fase_actual.txt").write_text(fase, encoding="utf-8")


async def probar(cliente: httpx.AsyncClient, modo: str, corrida: str, n: int, limite: float) -> dict:
    etiqueta = f"Carga {corrida} n={n}"
    antes = await esperar_fin(cliente, limite)

    marcar_fase(f"{modo}-n{n}")
    print(f"[{datetime.now():%H:%M:%S}] Inicio: {n} solicitudes")
    resultados = await asyncio.gather(*(enviar(cliente, etiqueta, i) for i in range(n)))
    print(f"[{datetime.now():%H:%M:%S}] Respuestas recibidas; esperando a que la API termine de guardar y notificar")
    despues = await esperar_fin(cliente, limite)
    marcar_fase(f"{modo}-fin-n{n}")

    duracion, ocupado = ocupacion(antes, despues)
    tiempos = [t for t, _ in resultados]
    errores = Counter(str(codigo) for _, codigo in resultados if codigo != 201)
    solicitudes = (await cliente.get("/solicitudes", timeout=None)).json()
    propias = [s for s in solicitudes if s["estudiante"].startswith(etiqueta + " #")]
    numeros = sorted(s["numero"] for s in propias)
    t0, t1 = antes["telegram"], despues["telegram"]

    return {
        "n": n,
        "tiempo_medio": round(statistics.mean(tiempos), 3),
        "tiempo_max": round(max(tiempos), 3),
        "exitosas": sum(1 for _, codigo in resultados if codigo == 201),
        "errores": dict(errores),
        "filas_guardadas": len(propias),
        # Rango de "Solicitud N" que corresponde a esta prueba (para contarlas en Telegram y en el Excel)
        "numeros": [numeros[0], numeros[-1]] if numeros else [],
        "telegram": {clave: t1[clave] - t0[clave] for clave in t1},
        "duracion_s": round(duracion, 2),
        "ocupacion": ocupado,
    }


def imprimir(r: dict):
    errores = sum(r["errores"].values())
    tg = r["telegram"]
    print(f"{r['n']} solicitudes  (la prueba duró {r['duracion_s']} s)")
    print(f"  Tiempo de respuesta: media {r['tiempo_medio']:.2f} s · máximo {r['tiempo_max']:.2f} s")
    print(f"  Exitosas: {r['exitosas']} / {r['n']}")
    print(f"  Con error: {errores} {r['errores'] if errores else ''}")
    rango = f" (Solicitud {r['numeros'][0]} a Solicitud {r['numeros'][1]})" if r["numeros"] else ""
    print(f"  Excel: {r['filas_guardadas']} filas guardadas{rango}")
    print(
        f"  Telegram: {tg['solicitudes_notificadas']} solicitudes notificadas en {tg['mensajes_enviados']} mensajes, "
        f"{tg['mensajes_fallidos']} mensajes fallidos"
    )
    print("  Ocupación: " + " · ".join(f"{c} {r['ocupacion'][c]:.0f} %" for c in COMPONENTES) + "\n")


def guardar(modo: str, url: str, nuevos: list[dict]):
    RESULTADOS.mkdir(exist_ok=True)
    archivo = RESULTADOS / f"resultados_{modo}.json"
    datos = json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else {"resultados": {}}
    datos.update(url=url, fecha=datetime.now().isoformat(timespec="seconds"))
    for r in nuevos:
        datos["resultados"][str(r["n"])] = r
    archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def generar_reporte() -> Path:
    datos = {
        archivo.stem.removeprefix("resultados_"): json.loads(archivo.read_text(encoding="utf-8"))
        for archivo in sorted(RESULTADOS.glob("resultados_*.json"))
    }
    plantilla = (CARPETA / "reporte_plantilla.html").read_text(encoding="utf-8")
    reporte = RESULTADOS / "reporte.html"
    reporte.write_text(plantilla.replace("/*DATOS*/{}", json.dumps(datos, ensure_ascii=False)), encoding="utf-8")
    return reporte


async def ejecutar(url: str, cantidades: list[int], timeout: float, limite: float):
    limites = httpx.Limits(max_connections=None, max_keepalive_connections=None)
    async with httpx.AsyncClient(base_url=url, timeout=timeout, limits=limites) as cliente:
        modo = (await salud(cliente))["modo"]
        corrida = datetime.now().strftime("%H%M%S")
        print(f"Modo de la API: {modo} · corrida {corrida}\n")

        for n in cantidades:
            resultado = await probar(cliente, modo, corrida, n, limite)
            imprimir(resultado)
            guardar(modo, url, [resultado])

    marcar_fase("inactivo")
    print(f"Reporte: {generar_reporte()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--cantidades", type=int, nargs="+", default=[10, 25, 50, 100])
    parser.add_argument("--timeout", type=float, default=120, help="segundos máximos por petición")
    parser.add_argument("--limite", type=float, default=3600, help="segundos máximos esperando que la API termine")
    parser.add_argument("--solo-reporte", action="store_true", help="regenera el reporte sin hacer pruebas")
    args = parser.parse_args()

    if args.solo_reporte:
        print(f"Reporte: {generar_reporte()}")
    else:
        asyncio.run(ejecutar(args.url, args.cantidades, args.timeout, args.limite))
