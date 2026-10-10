"""
Comprueba que la cuenta de servicio puede usar el Excel de Google Drive.

    python verificar_drive.py                      usa GOOGLE_DRIVE_FILE_ID del .env
    python verificar_drive.py <ID o enlace>        prueba otro archivo antes de configurarlo

No modifica el archivo: solo lee sus datos y permisos.
"""
import json
import os
import re
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from integrations import excel

GOOGLE_SHEETS = "application/vnd.google-apps.spreadsheet"


def correo_cuenta_servicio() -> str:
    contenido = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if contenido:
        return json.loads(contenido)["client_email"]
    ruta = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credenciales.json")
    with open(ruta, encoding="utf-8") as archivo:
        return json.load(archivo)["client_email"]


def extraer_id(texto: str) -> str:
    """Acepta el ID o el enlace completo de Drive / Google Sheets."""
    coincidencia = re.search(r"/d/([\w-]+)", texto) or re.search(r"[?&]id=([\w-]+)", texto)
    return coincidencia.group(1) if coincidencia else texto.strip()


def main():
    correo = correo_cuenta_servicio()
    print(f"Cuenta de servicio (comparte el Excel con este correo como Editor):\n  {correo}\n")

    if len(sys.argv) > 1:
        os.environ["GOOGLE_DRIVE_FILE_ID"] = extraer_id(sys.argv[1])
    file_id = excel._file_id()

    try:
        archivo = excel._servicio().files().get(
            fileId=file_id, fields="name,mimeType,owners(emailAddress),capabilities(canEdit),webViewLink"
        ).execute()
    except Exception as e:
        print(f"✗ No se pudo abrir el archivo {file_id}.")
        print("  Revisa que el ID sea correcto y que el archivo esté compartido con la cuenta de servicio.")
        print(f"  Detalle: {getattr(e, 'reason', e)}")
        sys.exit(1)

    print(f"✓ Archivo encontrado: {archivo['name']}")
    print(f"  Propietario: {', '.join(o['emailAddress'] for o in archivo.get('owners', []))}")
    print(f"  Enlace: {archivo['webViewLink']}")

    if archivo["mimeType"] == GOOGLE_SHEETS:
        print("✗ El archivo se convirtió a Hoja de cálculo de Google y la API necesita un .xlsx.")
        print("  En Drive: Archivo > Descargar > Microsoft Excel (.xlsx) y vuelve a subirlo con la conversión desactivada")
        print("  (Configuración de Drive > «Convertir archivos subidos al formato del editor de Documentos de Google»).")
        sys.exit(1)
    if archivo["mimeType"] != excel.XLSX_MIME:
        print(f"✗ El archivo no es un Excel .xlsx (tipo: {archivo['mimeType']}).")
        sys.exit(1)
    print("✓ Formato .xlsx")

    if not archivo["capabilities"]["canEdit"]:
        print(f"✗ La cuenta de servicio solo puede leer. Compártelo con {correo} como Editor.")
        sys.exit(1)
    print("✓ La cuenta de servicio tiene permiso de edición")

    libro = excel._descargar_libro()
    if excel.HOJA in libro.sheetnames:
        hoja = libro[excel.HOJA]
        encabezados = [c.value for c in hoja[1]][: len(excel.COLUMNAS)]
        if encabezados != excel.COLUMNAS:
            print(f"⚠ La hoja «{excel.HOJA}» tiene encabezados distintos: {encabezados}")
            print(f"  Se esperaban: {excel.COLUMNAS}")
            sys.exit(1)
        print(f"✓ Hoja «{excel.HOJA}» lista ({hoja.max_row - 1} solicitudes)")
    else:
        print(f"✓ Libro legible. La hoja «{excel.HOJA}» se creará con el primer registro.")

    if len(sys.argv) > 1:
        print(f"\nTodo listo. Pon esto en tu .env:\n  GOOGLE_DRIVE_FILE_ID={file_id}")
    else:
        print("\nTodo listo: la API puede registrar y actualizar solicitudes en este Excel.")


if __name__ == "__main__":
    main()
