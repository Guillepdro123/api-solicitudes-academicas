"""
Deja el Excel de Google Drive vacío (solo encabezados) para empezar las pruebas desde cero.
Reemplaza el contenido del mismo archivo, así que el enlace y los permisos no cambian.

    python reiniciar_excel.py --si          reinicia el archivo de GOOGLE_DRIVE_FILE_ID
    python reiniciar_excel.py --plantilla   solo regenera excel/solicitudes_academicas.xlsx
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from integrations import excel

PLANTILLA = os.path.join("excel", "solicitudes_academicas.xlsx")


def main():
    excel.libro_vacio().save(PLANTILLA)
    print(f"Plantilla actualizada: {PLANTILLA}")
    if "--plantilla" in sys.argv:
        return
    if "--si" not in sys.argv:
        print("Esto borra todas las solicitudes del Excel en Drive. Ejecuta con --si para confirmar.")
        sys.exit(1)
    antes = len(excel.leer_solicitudes())
    excel.reiniciar_drive()
    print(f"Excel reiniciado en Drive: se borraron {antes} solicitudes; quedan {len(excel.leer_solicitudes())}.")


if __name__ == "__main__":
    main()
