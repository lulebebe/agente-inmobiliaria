"""
Tool: Consulta de apartamentos disponibles en Google Sheets
------------------------------------------------------------

Lee una hoja de Google Sheets con información de apartamentos
disponibles para alquiler.

Expone UNA sola tool al agente:

- buscar_apartamentos_disponibles

La herramienta permite buscar apartamentos:
- sin filtros: devuelve todos los apartamentos disponibles
- por barrio
- por número mínimo de habitaciones
- por número mínimo de baños
- por alquiler máximo
- por condición de amoblado
- mediante texto libre

La herramienta es SOLO LECTURA.

Autor: Luis Betancourt
"""

import os
import re
import unicodedata
from typing import Optional

from dotenv import load_dotenv, find_dotenv
from langchain_core.tools import tool

import gspread
from google.oauth2.service_account import Credentials


# ============================================================
# CARGA DE VARIABLES DE ENTORNO
# ============================================================

load_dotenv(find_dotenv())


# ============================================================
# CONFIGURACIÓN
# ============================================================

GOOGLE_SHEET_ID = os.getenv("GOOGLE_APARTAMENTOS_SHEET_ID")

GOOGLE_SHEETS_WORKSHEET = os.getenv(
    "GOOGLE_APARTAMENTOS_WORKSHEET",
    "Apartamentos"
)

GOOGLE_SHEETS_HEADER_ROW = int(
    os.getenv("GOOGLE_APARTAMENTOS_HEADER_ROW", "2")
)

GOOGLE_APPLICATION_CREDENTIALS = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "credentials/service-account.json",
)


# Scope de SOLO LECTURA
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]


if not GOOGLE_SHEET_ID:
    raise ValueError(
        "❌ Falta la variable GOOGLE_APARTAMENTOS_SHEET_ID en .env"
    )


# ============================================================
# CLIENTE GSPREAD
# ============================================================

_worksheet = None


def _resolve_credentials_path(path: str) -> str:
    """
    Si la ruta es relativa, la resuelve contra el directorio
    raíz del proyecto.
    """

    if os.path.isabs(path):
        return path

    project_root = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )

    return os.path.join(project_root, path)


def _get_worksheet():
    """
    Conecta con Google Sheets de forma lazy y devuelve
    el worksheet configurado.
    """

    global _worksheet

    if _worksheet is not None:
        return _worksheet

    creds_path = _resolve_credentials_path(
        GOOGLE_APPLICATION_CREDENTIALS
    )

    if not os.path.isfile(creds_path):
        raise FileNotFoundError(
            f"No se encontró el JSON de la cuenta de servicio en "
            f"'{creds_path}'. "
            f"Verifica GOOGLE_APPLICATION_CREDENTIALS."
        )

    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=SCOPES
    )

    client = gspread.authorize(creds)

    sheet = client.open_by_key(GOOGLE_SHEET_ID)

    _worksheet = sheet.worksheet(GOOGLE_SHEETS_WORKSHEET)

    return _worksheet


# ============================================================
# UTILIDADES
# ============================================================

def _normalize(text) -> str:
    """
    Normaliza texto:
    - minúsculas
    - elimina acentos
    - elimina espacios sobrantes
    """

    if text is None:
        return ""

    s = unicodedata.normalize(
        "NFKD",
        str(text)
    )

    s = "".join(
        c for c in s
        if not unicodedata.combining(c)
    )

    return " ".join(s.lower().strip().split())


def _parse_number(value) -> Optional[float]:
    """
    Convierte valores numéricos provenientes de Google Sheets
    a float.

    Ejemplos:
        2350
        "2350"
        "2.350"
        "2,350"
        "2.350,50"
        "R$ 2.350,50"
    """

    if value is None:
        return None

    s = str(value).strip()

    if not s:
        return None

    # Elimina moneda, espacios y caracteres no numéricos
    s = re.sub(r"[^\d,.\-]", "", s)

    if not s:
        return None

    # Formato brasileño:
    # 2.350,50 -> 2350.50
    if "," in s and "." in s:

        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "")
            s = s.replace(",", ".")

        else:
            s = s.replace(",", "")

    # 2350,50
    elif "," in s:

        partes = s.split(",")

        if len(partes[-1]) == 2:
            s = s.replace(",", ".")

        else:
            s = s.replace(",", "")

    # 2.350
    elif "." in s:

        partes = s.split(".")

        # Si parece separador de miles
        if len(partes[-1]) == 3 and len(partes) > 1:
            s = s.replace(".", "")

    try:
        return float(s)

    except ValueError:
        return None


def _cargar_datos():
    """
    Lee la hoja y devuelve:
        headers, data_rows
    """

    ws = _get_worksheet()

    all_values = ws.get_all_values()

    header_idx = GOOGLE_SHEETS_HEADER_ROW - 1

    if header_idx >= len(all_values):
        raise ValueError(
            f"La hoja no tiene la fila "
            f"{GOOGLE_SHEETS_HEADER_ROW} como encabezado."
        )

    header_row = all_values[header_idx]

    headers = [
        (h or "").strip()
        for h in header_row
    ]

    # Eliminar columnas completamente vacías
    valid_indexes = [
        i
        for i, h in enumerate(headers)
        if h
    ]

    headers = [
        headers[i]
        for i in valid_indexes
    ]

    data_rows = []

    for row in all_values[header_idx + 1:]:

        # Ignorar filas completamente vacías
        if not any(str(c).strip() for c in row):
            continue

        clean_row = []

        for i in valid_indexes:
            if i < len(row):
                clean_row.append(row[i])
            else:
                clean_row.append("")

        data_rows.append(clean_row)

    return headers, data_rows


def _convertir_registros(headers, rows):
    """
    Convierte las filas del Sheet en una lista de diccionarios.
    """

    registros = []

    for row in rows:

        registro = {}

        for i, header in enumerate(headers):

            if i < len(row):
                registro[header] = row[i]
            else:
                registro[header] = ""

        registros.append(registro)

    return registros


def _buscar_columna(headers, candidatos):
    """
    Busca una columna por diferentes nombres posibles.
    """

    candidatos_norm = [
        _normalize(c)
        for c in candidatos
    ]

    for header in headers:

        header_norm = _normalize(header)

        for candidato in candidatos_norm:

            if candidato == header_norm:
                return header

    # Segunda búsqueda: contiene el término
    for header in headers:

        header_norm = _normalize(header)

        for candidato in candidatos_norm:

            if candidato in header_norm:
                return header

    return None


# ============================================================
# FORMATEO
# ============================================================

def _formatear_apartamento(registro, headers):
    """
    Convierte un registro en una respuesta legible para el LLM.
    """

    id_col = _buscar_columna(
        headers,
        ["ID"]
    )

    inmueble_col = _buscar_columna(
        headers,
        ["Inmueble"]
    )

    tipo_col = _buscar_columna(
        headers,
        ["Tipo"]
    )

    barrio_col = _buscar_columna(
        headers,
        ["Barrio"]
    )

    direccion_col = _buscar_columna(
        headers,
        ["Dirección", "Direccion"]
    )

    metros_col = _buscar_columna(
        headers,
        ["Metros Cuadrados", "Metros"]
    )

    habitaciones_col = _buscar_columna(
        headers,
        ["Habitaciones"]
    )

    banos_col = _buscar_columna(
        headers,
        ["Baños", "Banos"]
    )

    cocheras_col = _buscar_columna(
        headers,
        ["Cocheras"]
    )

    alquiler_col = _buscar_columna(
        headers,
        [
            "Alquiler Mensual (BRL)",
            "Alquiler Mensual",
            "Alquiler"
        ]
    )

    iptu_col = _buscar_columna(
        headers,
        [
            "IPTU Mensual (BRL)",
            "IPTU Mensual",
            "IPTU"
        ]
    )

    agua_col = _buscar_columna(
        headers,
        [
            "Agua / SANASA",
            "Agua",
            "SANASA"
        ]
    )

    amoblado_col = _buscar_columna(
        headers,
        [
            "Estado Amoblado",
            "Amoblado",
            "Estado"
        ]
    )

    partes = []

    if id_col:
        partes.append(
            f"- ID: {registro.get(id_col, '')}"
        )

    if inmueble_col:
        partes.append(
            f"- Inmueble: {registro.get(inmueble_col, '')}"
        )

    if tipo_col:
        partes.append(
            f"- Tipo: {registro.get(tipo_col, '')}"
        )

    if barrio_col:
        partes.append(
            f"- Barrio: {registro.get(barrio_col, '')}"
        )

    if direccion_col:
        partes.append(
            f"- Dirección: {registro.get(direccion_col, '')}"
        )

    if metros_col:
        partes.append(
            f"- Metros cuadrados: {registro.get(metros_col, '')} m²"
        )

    if habitaciones_col:
        partes.append(
            f"- Habitaciones: {registro.get(habitaciones_col, '')}"
        )

    if banos_col:
        partes.append(
            f"- Baños: {registro.get(banos_col, '')}"
        )

    if cocheras_col:
        partes.append(
            f"- Cocheras: {registro.get(cocheras_col, '')}"
        )

    if alquiler_col:
        partes.append(
            f"- Alquiler mensual: R$ {registro.get(alquiler_col, '')}"
        )

    if iptu_col:
        partes.append(
            f"- IPTU mensual: R$ {registro.get(iptu_col, '')}"
        )

    if agua_col:
        partes.append(
            f"- Agua / SANASA: {registro.get(agua_col, '')}"
        )

    if amoblado_col:
        partes.append(
            f"- Estado amoblado: {registro.get(amoblado_col, '')}"
        )

    return "\n".join(partes)


# ============================================================
# TOOL
# ============================================================

@tool
def buscar_apartamentos_disponibles(
    barrio: str = "",
    habitaciones_min: int = 0,
    banos_min: int = 0,
    alquiler_max: float = 0,
    amoblado: str = "",
    consulta: str = ""
) -> str:
    """
    Busca apartamentos disponibles para alquiler en Google Sheets.

    Esta es una herramienta de SOLO LECTURA.

    Úsala cuando un usuario:
    - pregunte qué apartamentos están disponibles;
    - busque un apartamento para alquilar;
    - pregunte por apartamentos en un barrio;
    - indique un presupuesto máximo;
    - indique un número mínimo de habitaciones;
    - indique un número mínimo de baños;
    - pregunte por apartamentos amoblados o no amoblados;
    - proporcione características que permitan filtrar apartamentos.

    Si no se proporciona ningún criterio, devuelve todos los apartamentos
    disponibles registrados en Google Sheets.

    Args:
        barrio:
            Barrio donde desea el apartamento.
            Ejemplo: "Cidade Universitária".

        habitaciones_min:
            Número mínimo de habitaciones.
            Ejemplo: 2.

        banos_min:
            Número mínimo de baños.
            Ejemplo: 1.

        alquiler_max:
            Valor máximo del alquiler mensual en BRL.
            Ejemplo: 3000.

        amoblado:
            Preferencia de amoblado.
            Puede ser:
            "amoblado"
            "no amoblado"
            o dejarse vacío.

        consulta:
            Texto libre con características adicionales.
            Ejemplo:
            "apartamento cerca de UNICAMP con una cochera".

    IMPORTANTE:
        No inventes apartamentos, precios, direcciones ni características.
        Toda la información debe provenir de Google Sheets.
    """

    print(
        "   🏠 Buscando apartamentos: "
        f"barrio='{barrio}', "
        f"habitaciones_min={habitaciones_min}, "
        f"banos_min={banos_min}, "
        f"alquiler_max={alquiler_max}, "
        f"amoblado='{amoblado}', "
        f"consulta='{consulta}'"
    )

    try:

        # ----------------------------------------------------
        # 1. CARGAR DATOS
        # ----------------------------------------------------

        headers, rows = _cargar_datos()

        registros = _convertir_registros(
            headers,
            rows
        )

        if not registros:
            return (
                "No hay apartamentos registrados "
                "actualmente en Google Sheets."
            )

        # ----------------------------------------------------
        # 2. IDENTIFICAR COLUMNAS
        # ----------------------------------------------------

        barrio_col = _buscar_columna(
            headers,
            ["Barrio"]
        )

        habitaciones_col = _buscar_columna(
            headers,
            ["Habitaciones"]
        )

        banos_col = _buscar_columna(
            headers,
            ["Baños", "Banos"]
        )

        alquiler_col = _buscar_columna(
            headers,
            [
                "Alquiler Mensual (BRL)",
                "Alquiler Mensual",
                "Alquiler"
            ]
        )

        amoblado_col = _buscar_columna(
            headers,
            [
                "Estado Amoblado",
                "Amoblado"
            ]
        )

        # ----------------------------------------------------
        # 3. FILTRAR
        # ----------------------------------------------------

        resultados = []

        barrio_norm = _normalize(barrio)
        amoblado_norm = _normalize(amoblado)
        consulta_norm = _normalize(consulta)

        for registro in registros:

            # -----------------------------------------------
            # Barrio
            # -----------------------------------------------

            if barrio_norm and barrio_col:

                valor_barrio = _normalize(
                    registro.get(barrio_col, "")
                )

                if barrio_norm not in valor_barrio:
                    continue

            # -----------------------------------------------
            # Habitaciones
            # -----------------------------------------------

            if habitaciones_min and habitaciones_col:

                habitaciones = _parse_number(
                    registro.get(habitaciones_col)
                )

                if habitaciones is None:
                    continue

                if habitaciones < habitaciones_min:
                    continue

            # -----------------------------------------------
            # Baños
            # -----------------------------------------------

            if banos_min and banos_col:

                banos = _parse_number(
                    registro.get(banos_col)
                )

                if banos is None:
                    continue

                if banos < banos_min:
                    continue

            # -----------------------------------------------
            # Alquiler máximo
            # -----------------------------------------------

            if alquiler_max and alquiler_col:

                alquiler = _parse_number(
                    registro.get(alquiler_col)
                )

                if alquiler is None:
                    continue

                if alquiler > alquiler_max:
                    continue

            # -----------------------------------------------
            # Amoblado
            # -----------------------------------------------

            if amoblado_norm and amoblado_col:

                estado_amoblado = _normalize(
                    registro.get(amoblado_col, "")
                )

                if amoblado_norm == "amoblado":

                    if "no amoblado" in estado_amoblado:
                        continue

                    if "amoblado" not in estado_amoblado:
                        continue

                elif amoblado_norm in (
                    "no amoblado",
                    "noamoblado"
                ):

                    if "no amoblado" not in estado_amoblado:
                        continue

            # -----------------------------------------------
            # Consulta libre
            # -----------------------------------------------

            if consulta_norm:

                texto_registro = " ".join(
                    _normalize(str(v))
                    for v in registro.values()
                )

                palabras = consulta_norm.split()

                # Solo utilizamos palabras relevantes de longitud >= 3
                palabras_relevantes = [
                    p
                    for p in palabras
                    if len(p) >= 3
                    and p not in {
                        "con",
                        "para",
                        "los",
                        "las",
                        "una",
                        "uno",
                        "por",
                        "del",
                        "que",
                    }
                ]

                if palabras_relevantes:

                    coincidencias = sum(
                        1
                        for palabra in palabras_relevantes
                        if palabra in texto_registro
                    )

                    # Al menos una coincidencia
                    if coincidencias == 0:
                        continue

            resultados.append(registro)

        # ----------------------------------------------------
        # 4. SIN RESULTADOS
        # ----------------------------------------------------

        if not resultados:

            criterios = []

            if barrio:
                criterios.append(
                    f"barrio '{barrio}'"
                )

            if habitaciones_min:
                criterios.append(
                    f"{habitaciones_min} o más habitaciones"
                )

            if banos_min:
                criterios.append(
                    f"{banos_min} o más baños"
                )

            if alquiler_max:
                criterios.append(
                    f"alquiler máximo de R$ {alquiler_max:,.2f}"
                )

            if amoblado:
                criterios.append(
                    f"estado '{amoblado}'"
                )

            if consulta:
                criterios.append(
                    f"características '{consulta}'"
                )

            if criterios:

                descripcion = ", ".join(criterios)

                return (
                    "No encontré apartamentos disponibles que "
                    f"cumplan con los criterios indicados: "
                    f"{descripcion}."
                )

            return (
                "No encontré apartamentos disponibles "
                "en este momento."
            )

        # ----------------------------------------------------
        # 5. CONSTRUIR RESPUESTA
        # ----------------------------------------------------

        partes = [
            f"🏠 Encontré {len(resultados)} "
            "apartamento(s) disponible(s):"
        ]

        for i, registro in enumerate(resultados, start=1):

            partes.append("")
            partes.append(
                f"### Apartamento {i}"
            )

            partes.append(
                _formatear_apartamento(
                    registro,
                    headers
                )
            )

        partes.append("")
        partes.append(
            "Los datos anteriores provienen "
            "exclusivamente de Google Sheets."
        )

        return "\n".join(partes)

    except Exception as e:

        print(
            "❌ ERROR REAL GOOGLE SHEETS APARTAMENTOS: "
            f"{type(e).__name__}: {e}"
        )

        raise


# ============================================================
# PRUEBA DIRECTA OPCIONAL
# ============================================================

if __name__ == "__main__":

    print("=" * 60)
    print("🏠 PRUEBA TOOL APARTAMENTOS")
    print("=" * 60)

    try:

        resultado = buscar_apartamentos_disponibles.invoke({})

        print()
        print(resultado)

    except Exception as e:

        print()
        print(
            f"❌ Error: {type(e).__name__}: {e}"
        )