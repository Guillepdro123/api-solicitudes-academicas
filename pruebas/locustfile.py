"""
Prueba de carga con Locust (pip install locust).

Cada usuario envía una sola solicitud y se detiene, así N usuarios = N solicitudes:

    locust --headless -u 10 -r 10 --run-time 2m --host https://TU-APP.onrender.com --csv resultados_10
"""
import random

from locust import HttpUser, between, task
from locust.exception import StopUser

TIPOS = ["Certificado", "Constancia", "Homologación", "Cancelación de asignatura", "Reintegro", "Otro"]


class Estudiante(HttpUser):
    wait_time = between(0.5, 1)

    @task
    def registrar(self):
        self.client.post(
            "/solicitudes",
            json={
                "estudiante": f"Prueba {random.randint(1, 9999)}",
                "tipo": random.choice(TIPOS),
                "descripcion": "Solicitud de carga",
            },
        )
        raise StopUser()
