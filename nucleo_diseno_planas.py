import os
import re
import math
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, List

# El reemplazo de los marcadores de las plantillas SVG se hace con la misma función que usa
# el módulo de bandas en V, para no mantener dos implementaciones distintas: esa resuelve los
# marcadores por token completo (y no en cadena, que dejaba restos como "0.04_BRAZO2") y
# recentra los textos de cota, de manera que la cota no se corra al cambiar un marcador largo
# por un valor corto. Si el módulo de visualización no estuviera disponible se conserva el
# reemplazo en cadena como respaldo, para que el plano se genere igualmente.
try:
    from visualizacion_correas import aplicar_reemplazos as _aplicar_reemplazos_svg
    _MOTIVO_SIN_RECENTRADO = ""
except Exception as _e:  # pragma: no cover - respaldo si falta el módulo de visualización
    _aplicar_reemplazos_svg = None
    _MOTIVO_SIN_RECENTRADO = f"{type(_e).__name__}: {_e}"


def _sustituir_marcadores(svg_content: str, reemplazos: dict, nombre_plantilla: str) -> str:
    """Sustituye los marcadores VAR_ de una plantilla y recentra los textos de cota."""
    if _aplicar_reemplazos_svg is not None:
        return _aplicar_reemplazos_svg(svg_content, reemplazos, nombre_plantilla)

    # Respaldo. Se avisa en voz alta: sin el módulo de visualización los planos salen con las
    # cotas descuadradas, y en pantalla eso se confunde con un fallo del recentrado.
    print(f"   [⚠️ Alerta]: no se pudo importar 'visualizacion_correas', de modo que las cotas "
          f"de '{nombre_plantilla}' NO se recentran. Motivo: {_MOTIVO_SIN_RECENTRADO}")

    # De la clave más larga a la más corta, para que ninguna clave corta se coma el prefijo
    # de otra más larga ("VAR_H" dentro de "VAR_H_BRAZO2").
    for var in sorted(reemplazos, key=len, reverse=True):
        svg_content = svg_content.replace(var, reemplazos[var])
    huerfanos = sorted(set(re.findall(r"VAR_[A-ZÁÉÍÓÚÑ0-9_]+", svg_content)))
    if huerfanos:
        print(f"Advertencia: marcadores sin valor en '{nombre_plantilla}': {', '.join(huerfanos)}")
        for h in huerfanos:
            svg_content = svg_content.replace(h, "—")
    return svg_content

@dataclass
class ResultadosDisenoPlana:
    potencia_nominal: float
    factor_servicio: float
    potencia_diseno: float
    n_conductora: float
    n_conducida: float
    tipo_flujo: str
    relacion_transmision: float
    D1_conductora: float
    D2_conducida: float
    D_pequena: float
    D_grande: float
    tipo_correa: str
    ancho_correa_b: float
    ancho_polea_bp: float
    dmin_catalogo: float
    cumple_dmin: bool
    distancia_ejes_preliminar: float
    longitud_teorica: float
    longitud_comercial: float
    distancia_ejes_final: float
    angulo_contacto_peq_deg: float
    angulo_contacto_gra_deg: float
    velocidad_lineal: float
    tension_t1: float
    tension_t2: float
    tension_t0: float
    fuerza_radial_eje: float
    mu_requerido: float
    mu_material: float
    corona_conductora: float | str
    corona_conducida: float | str
    buje_1: str = "N/A"
    chaveta_1: str = "N/A"
    buje_2: str = "N/A"
    chaveta_2: str = "N/A"
    d1_cubo_1: Optional[float] = None
    d1_cubo_2: Optional[float] = None
    tipo_polea_1_str: str = ""
    tipo_polea_2_str: str = ""
    detalles_constructivos_1: Optional[Dict[str, Any]] = None
    detalles_constructivos_2: Optional[Dict[str, Any]] = None
    d_eje_1: Optional[float] = None
    d_eje_2: Optional[float] = None
    # Criterio NEMA: minimo de eje de motor electrico. Se reporta siempre; solo gobierna
    # el diseno cuando el accionamiento efectivamente es un motor electrico.
    dmin_nema: float = 0.0
    aplica_criterio_nema: bool = True
    # Tensión admisible del lado tenso para el ancho adoptado (esfuerzo o Fu equivalente
    # × Cp × b) y factor de seguridad por tensión = T1 admisible / T1 requerida. Da una
    # idea de cuánto margen deja el ancho de banda escogido.
    tension_t1_admisible: float = 0.0
    factor_seguridad_tension: float = 0.0
    # Ancho que sale del cálculo, antes de llevarlo al nominal de la norma. Se reporta junto
    # al ancho adoptado para que en la memoria se vea de dónde viene el valor y cuánto se
    # aproximó. Queda en 0.0 cuando no se pudo calcular (la fuerza centrífuga consume toda
    # la capacidad del material a esa velocidad).
    ancho_correa_calculado: float = 0.0
    # Cómo se llegó al ancho adoptado: por la serie de la norma o porque lo fijó el usuario.
    criterio_ancho: str = ""

class BaseDatosPlanas:
    def __init__(self, ruta="DATOS_SOFTWARE_planas.xlsx"):
        possible_paths = [
            ruta,
            "DATOS_SOFTWARE_planas.xlsx",
            "/content/DATOS_SOFTWARE_planas.xlsx",
            os.path.join(os.getcwd(), "DATOS_SOFTWARE_planas.xlsx")
        ]
        archivo_encontrado = next((p for p in possible_paths if os.path.exists(p)), None)

        if not archivo_encontrado:
            if os.path.exists("/content/DATOS_SOFTWARE_planas.xlsx"):
                archivo_encontrado = "/content/DATOS_SOFTWARE_planas.xlsx"
            else:
                raise FileNotFoundError(f"❌ No se encontró el archivo '{ruta}'. Suba 'DATOS_SOFTWARE_planas.xlsx' al directorio.")

        self.xls = pd.ExcelFile(archivo_encontrado)
        self.belt_specifications = pd.read_excel(self.xls, 'especificaciones_bandas')
        self.ancho_bandas_iso = pd.read_excel(self.xls, 'anchos_bandas')
        self.diametros_poleas_iso = pd.read_excel(self.xls, 'diametros_poleas')
        self.correspondencia_bp = pd.read_excel(self.xls, 'correspondencia_banda_polea')
        self.crown_h_a1 = pd.read_excel(self.xls, 'tabla_coronas_1')
        self.crown_h_a2 = pd.read_excel(self.xls, 'tabla_coronas_2')

        # La hoja 'factor_cp' ya no gobierna el cálculo (la Tabla 17-4 vive embebida en el
        # código, ver CP_TABLA_17_4). Se sigue cargando si existe, solo por si alguna otra
        # parte del proyecto la consulta, pero su ausencia ya no rompe la carga del Excel.
        try:
            self.factor_cp_df = pd.read_excel(self.xls, 'factor_cp')
        except Exception:
            self.factor_cp_df = None

        # La hoja 'factor_c2' de este libro quedó sin uso: el factor de servicio de las
        # bandas planas se toma de 'Factor_Servicio_c2' del libro de bandas en V, que es la
        # misma tabla que gobierna esa tecnología. Se sigue cargando si existe, por si otra
        # parte del proyecto la consulta, pero su ausencia ya NO impide abrir el libro: al
        # eliminarla del Excel, la lectura fallaba y con ella toda la base de datos, de modo
        # que la interfaz se quedaba sin la lista de tipos de banda.
        try:
            self.df_raw_c2_matrix = pd.read_excel(self.xls, "factor_c2", header=None)
        except Exception:
            self.df_raw_c2_matrix = None

        def clean_col(n):
            if not isinstance(n, str): return n
            c = n.replace('\x18', 'd').replace('\x17', '3').replace('\x16', 'i').replace('\x12', 'a')
            if 'min polea' in c.lower(): return 'd min polea [mm]'
            if 'masa' in c.lower(): return 'Masa [kg/m2]'
            # Fuerza periférica admisible por unidad de ancho, Fu = T1 − T2 [N/mm]. La
            # hoja la ha rotulado de distintas formas ('Tensión permisible por unidad de
            # ancho', 'Fuerza periférica admisible por ancho'), así que se reconoce por
            # cualquiera de esas palabras y se normaliza a un solo nombre interno.
            if any(k in c.lower() for k in ('perif', 'admisible', 'permisible')):
                return 'Fuerza_periferica'
            if 'fric' in c.lower() and 'acero' in c.lower(): return 'Coef_friccion'
            return c.strip()
        self.belt_specifications.columns = [clean_col(c) for c in self.belt_specifications.columns]

# =====================================================================================
#  CRITERIO NEMA DE DIAMETRO MINIMO EN EL EJE DEL MOTOR
#  Un motor electrico normalizado tiene un limite de carga radial admisible en su eje:
#  por debajo de cierto diametro de polea, la tension de la banda lo sobrecarga. La tabla
#  vive en la hoja 'motor_electrico' del libro de bandas en V, asi que se lee de alli.
#  El criterio solo tiene sentido con motor electrico; con otra maquina motriz el
#  diametro minimo lo gobierna unicamente el catalogo de la banda.
# =====================================================================================

_CACHE_TABLA_MOTOR = {}


def localizar_libro_motor(ruta_sugerida: str = "DATOS SOFTWARE.xlsx"):
    """Ubica el libro de bandas en V, que es donde vive la hoja 'motor_electrico'.

    Se prueban las variantes de nombre igual que hace BaseDatosCorreas, porque el archivo
    aparece indistintamente con espacio o con guion bajo segun quien lo haya guardado.
    """
    candidatos = [
        ruta_sugerida,
        "DATOS SOFTWARE.xlsx",
        "DATOS_SOFTWARE.xlsx",
        "DATOS SOFTWARE .xlsx",
        os.path.join(os.getcwd(), "DATOS SOFTWARE.xlsx"),
        os.path.join(os.getcwd(), "DATOS_SOFTWARE.xlsx"),
    ]
    for c in candidatos:
        if c and os.path.exists(c):
            return c

    # Ultimo recurso: buscar por nombre en la carpeta de trabajo.
    try:
        for archivo in os.listdir(os.getcwd()):
            nombre = archivo.upper()
            if "DATOS" in nombre and "SOFTWARE" in nombre and nombre.endswith(".XLSX")                     and "PLANAS" not in nombre:
                return os.path.join(os.getcwd(), archivo)
    except OSError:
        pass
    return None


def obtener_dmin_motor_nema(p_kw: float, rpm: float,
                            ruta_excel_motor: str = "DATOS SOFTWARE.xlsx") -> float:
    """Diametro minimo de polea admisible en el eje del motor, en mm.

    Devuelve 0.0 si la tabla no esta disponible, de modo que la ausencia del libro de
    bandas en V degrade el criterio en vez de romper el calculo de bandas planas.
    """
    try:
        from nucleo_diseno_correas import dmin_motor_desde_tabla
    except Exception:
        return 0.0

    ruta = localizar_libro_motor(ruta_excel_motor)
    if ruta is None:
        return 0.0

    try:
        if ruta not in _CACHE_TABLA_MOTOR:
            _CACHE_TABLA_MOTOR[ruta] = pd.read_excel(ruta, sheet_name="motor_electrico")
        return float(dmin_motor_desde_tabla(_CACHE_TABLA_MOTOR[ruta], p_kw, rpm))
    except Exception:
        return 0.0


_CACHE_TABLA_C2 = {}


def categoria_transmision_desde_condicion(condicion_operacion: str) -> Optional[str]:
    """Traduce la condición de operación que muestra la interfaz de bandas planas a la
    categoría de transmisión con que está indexada la tabla de factores de servicio:

        1. Servicio regular            -> LIGERA
        2. Servicio irregular medio    -> MEDIA
        3. Servicio irregular pesado   -> PESADA
        4. Servicio muy severo         -> MUY PESADA
    """
    texto = str(condicion_operacion).strip().lower()
    # El número de la condición manda; solo si no viene se recurre a las palabras clave.
    # Estas se evalúan de la más severa a la más suave, y "regular" se deja de última
    # porque la palabra está contenida dentro de "irregular": comprobándola primero, las
    # condiciones 2 y 3 se clasificaban como ligeras.
    for numero, categoria in (("1.", "LIGERA"), ("2.", "MEDIA"),
                              ("3.", "PESADA"), ("4.", "MUY PESADA")):
        if texto.startswith(numero):
            return categoria
    if "severo" in texto or "muy pesada" in texto:
        return "MUY PESADA"
    if "pesado" in texto or "pesada" in texto:
        return "PESADA"
    if "medio" in texto or "media" in texto:
        return "MEDIA"
    if "regular" in texto or "ligera" in texto:
        return "LIGERA"
    return None


def obtener_factor_servicio_planas(tipo_par: str, condicion_operacion: str,
                                   horas_operacion: str, db: BaseDatosPlanas = None,
                                   ruta_excel_motor: str = "DATOS SOFTWARE.xlsx") -> float:
    """Factor de servicio de una transmisión por bandas planas.

    Se toma de la MISMA tabla que gobierna las bandas en V: la hoja 'Factor_Servicio_c2'
    del libro 'DATOS SOFTWARE.xlsx', cruzando tipo de transmisión, tipo de par del motor y
    horas de operación. Antes se leía la hoja 'factor_c2' del libro de bandas planas, que
    tiene otra estructura (por grupo de banda), de modo que los índices no correspondían y
    el valor salía equivocado o se caía al valor por defecto.

    El parámetro db se conserva por compatibilidad con las llamadas existentes; ya no se
    usa. Si el libro de bandas en V no está disponible se devuelve 1,5 y se avisa por
    consola, para que la ausencia del archivo no detenga el cálculo en silencio.
    """
    from nucleo_diseno_correas import parsear_factor_servicio_c2, obtener_factor_servicio_c2

    categoria = categoria_transmision_desde_condicion(condicion_operacion)
    if categoria is None:
        print(f"No se reconoció la condición de operación '{condicion_operacion}'; "
              f"se aplicó el factor de servicio por defecto (1,5).")
        return 1.5

    ruta = localizar_libro_motor(ruta_excel_motor)
    if ruta is None:
        print("No se encontró 'DATOS SOFTWARE.xlsx', de donde sale la tabla de factores de "
              "servicio; se aplicó el factor por defecto (1,5).")
        return 1.5

    try:
        if ruta not in _CACHE_TABLA_C2:
            _CACHE_TABLA_C2[ruta] = parsear_factor_servicio_c2(
                pd.read_excel(ruta, sheet_name="Factor_Servicio_c2", header=None)
            )
        # Envoltorio mínimo: la función de bandas en V solo consulta el atributo
        # c2_factores, así que no hace falta construir toda su base de datos.
        contenedor = type("TablaC2", (), {"c2_factores": _CACHE_TABLA_C2[ruta]})()
        return float(obtener_factor_servicio_c2(tipo_par, categoria, horas_operacion, contenedor))
    except Exception as e:
        print(f"Error leyendo la tabla de factores de servicio: {e}")
        return 1.5

class CpNoDisponibleError(ValueError):
    """La combinación material + diámetro corresponde a una celda '—' de la Tabla 17-4,
    es decir, ese grado de banda no admite una polea tan pequeña. No es un dato faltante:
    es una combinación no permitida, por lo que el llamador debe descartar esa candidata."""
    pass

# --- Tabla 17-4: "Pulley Correction Factor Cp for Flat Belts" ---
# Shigley's Mechanical Engineering Design, 10a ed. (Budynas & Nisbett), Cap. 17.
# Valores promediados de curvas del Habasit Engineering Manual, Habasit Belting Inc.
# FILAS   = material / grado de la banda.
# COLUMNAS = diámetro de la polea PEQUEÑA, en PULGADAS.
# None = celda "—" del original: diámetro demasiado pequeño para ese grado.
CP_DIAM_MIN_IN = [1.6, 4.5, 9.0, 14.0, 18.0, 31.5]
CP_TABLA_17_4: Dict[str, List[Optional[float]]] = {
    #            1.6-4   4.5-8   9-12.5   14,16   18-31.5   >31.5
    "LEATHER": [  0.50,   0.60,   0.70,   0.80,    0.90,    1.00],
    "F-0":     [  0.95,   1.00,   1.00,   1.00,    1.00,    1.00],
    "F-1":     [  0.70,   0.92,   0.95,   1.00,    1.00,    1.00],
    "F-2":     [  0.73,   0.86,   0.96,   1.00,    1.00,    1.00],
    "A-2":     [  0.73,   0.86,   0.96,   1.00,    1.00,    1.00],
    "A-3":     [  None,   0.70,   0.87,   0.94,    0.96,    1.00],
    "A-4":     [  None,   None,   0.71,   0.80,    0.85,    0.92],
    "A-5":     [  None,   None,   None,   0.72,    0.77,    0.91],
}

def anchos_nominales_iso22(db) -> List[float]:
    """Serie de anchos nominales de banda de la ISO 22, en milímetros, de menor a mayor."""
    serie = pd.to_numeric(db.ancho_bandas_iso['Width_nom_mm'], errors='coerce').dropna()
    return sorted(float(a) for a in serie.unique())


def siguiente_ancho_iso22(db, b_min_mm: float) -> Optional[float]:
    """Primer ancho nominal de la ISO 22 que iguala o supera el ancho calculado.

    La aproximación es SIEMPRE hacia arriba, y no al más cercano como se hace con los
    diámetros: el ancho calculado es el mínimo que soporta la tensión del lado tenso, de
    modo que tomar el nominal inferior dejaría la banda por debajo de lo requerido. La
    tolerancia de 1e-9 es solo para que un ancho que cae exactamente sobre un nominal no se
    vaya al siguiente por el redondeo de la división.

    Devuelve None si el ancho calculado excede el mayor nominal de la serie.
    """
    return next((a for a in anchos_nominales_iso22(db) if a >= b_min_mm - 1e-9), None)


def ancho_polea_para_banda(db, b_mm: float) -> float:
    """Ancho de polea que la norma hace corresponder a un ancho nominal de banda.

    Si el ancho no está en la tabla de correspondencia —lo que ocurre cuando el usuario fija
    un ancho cualquiera en el modo manual— se conserva el criterio anterior de 1,1·b, que es
    la holgura habitual para que la banda no se salga de la cara de la polea.
    """
    match = db.correspondencia_bp[db.correspondencia_bp['Belt_Width_mm'] == b_mm]
    if not match.empty:
        return float(match['Pulley_Width_mm'].iloc[0])
    return b_mm * 1.1


def normalizar_familia_banda(nombre: Any) -> Optional[str]:
    """Extrae la designación de grado ('F-1', 'A-4', 'LEATHER') del nombre de la banda,
    tolerando variantes de escritura: 'F1', 'f-1', 'Polyamide A-4', 'A_4', 'Cuero'.
    Devuelve None si el nombre no contiene ningún grado reconocible."""
    if nombre is None:
        return None
    s = str(nombre).strip().upper()
    if not s:
        return None
    if 'LEATHER' in s or 'CUERO' in s:
        return "LEATHER"
    m = re.search(r'\b([FA])\s*[-_ ]?\s*(\d)\b', s)
    return f"{m.group(1)}-{m.group(2)}" if m else None

def obtener_factor_cp(d_peq_mm: float, material_banda: Any) -> float:
    """Factor de corrección por polea Cp (Tabla 17-4, Shigley 10a ed.).

    Ubica el valor cruzando DOS entradas, como en la tabla original:
      - la FILA, por el material/grado de la banda (F-0..F-2, A-2..A-5, cuero);
      - la COLUMNA, por el diámetro de la polea pequeña, convertido de mm a pulgadas.

    El diámetro se asigna al rango cuyo límite INFERIOR es el mayor que no lo supera.
    Esto importa en los huecos que deja la tabla (entre 4 y 4.5 in, 8 y 9, 12.5 y 14,
    16 y 18): un diámetro que cae en un hueco se resuelve hacia el rango menor, que es
    el más conservador, en vez de premiarlo con el Cp del rango superior.
    """
    familia = normalizar_familia_banda(material_banda)
    if familia is None:
        raise ValueError(
            f"No se pudo identificar el grado de banda a partir de '{material_banda}'. El "
            f"factor de corrección por polea Cp se obtiene cruzando el GRADO de la banda "
            f"con el diámetro de la polea (Tabla 17-4), así que la banda debe ser una de "
            f"las del catálogo: {', '.join(sorted(CP_TABLA_17_4))}. Sin grado no hay Cp y "
            f"el diseño quedaría sin fundamento."
        )
    fila = CP_TABLA_17_4.get(familia)
    if fila is None:
        raise ValueError(
            f"El grado de banda '{familia}' no está en la Tabla 17-4. Grados disponibles: "
            f"{', '.join(sorted(CP_TABLA_17_4))}."
        )

    d_in = d_peq_mm / 25.4
    idx = 0
    for k, lim_inf in enumerate(CP_DIAM_MIN_IN):
        if d_in >= lim_inf:
            idx = k
        else:
            break

    val = fila[idx]
    if val is None:
        primer_valido = next(
            (CP_DIAM_MIN_IN[k] for k, v in enumerate(fila) if v is not None), None
        )
        raise CpNoDisponibleError(
            f"La Tabla 17-4 no admite el grado '{familia}' con una polea de {d_peq_mm:.1f} mm "
            f"({d_in:.2f} in): ese grado requiere al menos {primer_valido} in "
            f"({primer_valido * 25.4:.0f} mm) de diámetro."
        )
    return float(val)

class GestorBujes:
    def __init__(self, ruta_trans="Datos_Bujes.xlsx", ruta_chavetas="Chavetas_ANSI mm.xlsx"):
        if not os.path.exists(ruta_trans) or not os.path.exists(ruta_chavetas):
            self.activo = False
            return
        self.activo = True
        self.df_taper = pd.read_excel(ruta_trans, sheet_name='Geometria_Bujes_Taper')
        self.df_chavetas = pd.read_excel(ruta_chavetas, sheet_name='Dimensiones_Chavetas_ANSI')
        self.longitudes_estandar_chavetas = [250, 220, 200, 180, 160, 140, 125, 110, 100, 90, 80, 70, 63, 56, 50, 45, 40, 36, 32, 28, 25, 22, 20, 18, 16, 14, 12, 10, 8, 6]

    def seleccionar_buje_y_chaveta(self, diametro_polea_mm, diametro_eje_mm,
                                   d_interior_llanta_mm=None, ancho_polea_mm=None):
        """Buje Taper y chaveta de una polea plana.

        Con d_interior_llanta_mm (poleas macizas) el ajuste se mide contra el espacio que
        de verdad hay dentro de la llanta, D − 2·espesor de llanta, y no contra el
        diámetro exterior. Si ningún Taper cabe ahí, se recomienda montaje directo sobre
        el eje en lugar de proponer un buje que no entra.
        """
        if not self.activo or not diametro_eje_mm: return "N/A", "N/A", None
        espacio = d_interior_llanta_mm if d_interior_llanta_mm else diametro_polea_mm
        df_fil = self.df_taper[(self.df_taper['Hueco_Max_Permisible_mm'] >= diametro_eje_mm) & (self.df_taper['C_Min_Manzana_mm'] <= espacio)].copy()

        if df_fil.empty:
            if d_interior_llanta_mm:
                largo = ancho_polea_mm if ancho_polea_mm else 2.5 * diametro_eje_mm
                df_c = self.df_chavetas[(self.df_chavetas['Diametro_Eje_Min_mm'] < diametro_eje_mm) & (self.df_chavetas['Diametro_Eje_Max_mm'] >= diametro_eje_mm)]
                if df_c.empty:
                    return "Montaje directo sobre el eje (ningún buje cabe en la llanta)", "Chaveta no estándar", None
                fc = df_c.iloc[0]
                l_final = next((l for l in self.longitudes_estandar_chavetas if l <= largo - 2.0), None)
                ch = (f"{fc['Tipo_Chaveta']} {fc['Ancho_W_mm']:.2f}x{fc['Alto_H_mm']:.2f}x{l_final}mm"
                      if l_final else "No estandarizable")
                return "Montaje directo sobre el eje (ningún buje cabe en la llanta)", ch, None
            return "Buje no compatible", "N/A", None
        df_fil = df_fil.sort_values(by=['Hueco_Max_Permisible_mm', 'C_Min_Manzana_mm'])
        fila = df_fil.iloc[0]
        longitud_buje, d1_cubo = float(fila['B_mm']), float(fila['C_Min_Manzana_mm'])

        df_c = self.df_chavetas[(self.df_chavetas['Diametro_Eje_Min_mm'] < diametro_eje_mm) & (self.df_chavetas['Diametro_Eje_Max_mm'] >= diametro_eje_mm)]
        if df_c.empty: return f"Taper {fila['Ref_Buje']}", "Chaveta no estándar", d1_cubo

        fila_c = df_c.iloc[0]
        l_final = next((l for l in self.longitudes_estandar_chavetas if l <= (longitud_buje - 2.0)), None)
        chaveta_str = f"{fila_c['Tipo_Chaveta']} {fila_c['Ancho_W_mm']:.2f}x{fila_c['Alto_H_mm']:.2f}x{l_final}mm" if l_final else "No estandarizable"
        return f"Taper {fila['Ref_Buje']}", chaveta_str, d1_cubo

def calcular_corona(db: "BaseDatosPlanas", diam: float, ancho_polea: float) -> float:
    """Altura de bombeo (corona) h de la polea, en mm, según las tablas A.1 y A.2 de la
    ISO 22:1991, cargadas desde el Excel.

    Hasta 710 mm de diámetro se usa 'tabla_coronas_1'; de 800 mm en adelante,
    'tabla_coronas_2', que además distingue por ancho de polea.

    HUECOS ENTRE RANGOS: las tablas de la norma solo listan los diámetros normalizados de
    la serie R20, de modo que entre un rango y el siguiente quedan valores sin cubrir
    (por ejemplo 1500 mm, entre los rangos 1120–1400 y 1600–2000). Buscar un rango que
    contuviera exactamente el diámetro devolvía h = 0 para esos valores, lo que se nota
    sobre todo en el modo manual, donde el usuario puede escribir cualquier diámetro. Por
    eso se toma el rango cuyo límite INFERIOR es el mayor que no supera al diámetro: cada
    fila se entiende vigente hasta que empieza la siguiente. Un diámetro por debajo de la
    primera fila toma el valor de esa primera fila, y uno por encima de la última (más de
    2 000 mm, fuera del alcance de la norma) toma el de la última.
    """
    try:
        if diam < 800:
            tabla, columna = db.crown_h_a1.copy(), 'Crown_h_mm'
        else:
            tabla = db.crown_h_a2.copy()
            columna = 'Crown_h_b_leq_250_mm' if ancho_polea <= 250 else 'Crown_h_b_geq_280_mm'

        tabla = tabla.dropna(subset=['D_inf_mm', columna]).sort_values('D_inf_mm')
        if tabla.empty:
            return 0.0

        candidatas = tabla[tabla['D_inf_mm'] <= diam]
        fila = candidatas.iloc[-1] if not candidatas.empty else tabla.iloc[0]
        return float(fila[columna])
    except Exception:
        return 0.0

def diametro_interior_llanta_plana(D_ext: float) -> float:
    """Diámetro interior de la llanta de una polea plana: D − 2·espesor de llanta.

    Es el espacio disponible para el cubo y, en las poleas macizas, lo que se acota en el
    plano. El espesor sigue la misma regla proporcional que usa el resto del módulo.
    """
    return D_ext - 2 * (D_ext / 200.0 + 3.0)


def determinar_tipo_polea_real(D: float) -> dict:
    if D < 151: return {"tipo": "Tipo I", "descripcion": "Maciza (Solid)"}
    elif 151 <= D <= 300: return {"tipo": "Tipo II", "descripcion": "De discos (Web)"}
    else: return {"tipo": "Tipo III", "descripcion": "De brazos (Spokes)"}

def calcular_detalles_constructivos_planas(tipo_str: str, D_ext: float, bp: float, d_eje: Optional[float], d1_cubo: Optional[float]) -> dict:
    d_eje_ef = d_eje if (d_eje and d_eje > 0) else max(20.0, 0.15 * D_ext)
    d1_cubo_ef = d1_cubo if (d1_cubo and d1_cubo > 0) else (1.8 * d_eje_ef)
    espesor_llanta = (D_ext / 200.0) + 3.0
    detalles = {"Espesor de llanta (t)": espesor_llanta}

    if "Tipo III" in tipo_str:
        h_brazo = 1.15 * d_eje_ef
        n_brazos = 4 if D_ext <= 700 else (6 if D_ext <= 2200 else 8)
        detalles.update({
            "Tipo": "Brazos Elípticos", "Número de brazos": n_brazos,
            "h (Ancho brazo en base)": h_brazo, "a (Espesor brazo en base)": 0.45 * h_brazo,
            "h' (Ancho brazo en corona)": 0.8 * h_brazo, "a' (Espesor brazo en corona)": 0.8 * 0.45 * h_brazo,
            "d_eje": d_eje_ef, "l_buje": 0.8 * D_ext * 0.3, "m_buje": d1_cubo_ef
        })
    elif "Tipo II" in tipo_str:
        detalles.update({
            "Tipo": "De discos",
            "D_cp (Diam. Circunf. Agujeros)": max(0.0, 0.5 * (D_ext - 2 * espesor_llanta + d1_cubo_ef)),
            "d_ag (Diam. Agujero Aligeramiento)": max(0.0, 0.35 * (D_ext - 2 * espesor_llanta - d1_cubo_ef)),
            # Mismo termino que en el modulo de bandas en V: el disco que une cubo y
            # corona se llama alma en ambos. La formula no cambia; el piso bp/3 liga el
            # espesor al ancho de la polea y es propio de las bandas planas.
            "z (Espesor del alma)": max(0.625 * (d1_cubo_ef - d_eje_ef), bp/3),
            "d_eje": d_eje_ef, "l_buje": 0.8 * D_ext * 0.3, "m_buje": d1_cubo_ef
        })
    else:
        # En una polea maciza no hay cubo separado del cuerpo: lo que se acota es el
        # diámetro interior de la llanta, donde termina la corona y empieza el macizo.
        detalles.update({
            "Tipo": "Maciza", "d_eje": d_eje_ef, "l_buje": 0.8 * D_ext * 0.3,
            "m_buje": diametro_interior_llanta_plana(D_ext)
        })
    return detalles

# =====================================================================================
#  CONVERSIÓN DE UNIDADES
#  El software se desarrolló y calcula SIEMPRE en sistema métrico (mm, kW, N, m/s,
#  MPa, kg/m3). Cuando is_ing=True, las entradas llegan en sistema inglés y se
#  convierten a métrico al ingresar; los resultados se convierten de vuelta a inglés
#  justo antes de retornar. El núcleo de cálculo nunca ve unidades inglesas.
#
#  Correspondencia entrada <-> salida en modo inglés:
#     longitudes .......... in          potencia ......... hp
#     fuerzas ............. lbf         velocidad ........ ft/min
#     esfuerzo admisible .. psi         densidad ......... lb/in3
#     ángulos (grados), rpm y adimensionales no cambian en ningún modo.
# =====================================================================================
MM_POR_PULGADA   = 25.4
KW_POR_HP        = 0.7457              # misma constante usada al convertir la entrada
N_POR_LBF        = 4.4482216152605
MPA_POR_PSI      = 0.0068947572932
KGM3_POR_LBIN3   = 27679.9047
MS_A_FTMIN       = 196.8503937007874   # 1 m/s = 196.85 ft/min

# Claves de 'detalles_constructivos' que NO son longitudes y por tanto no se convierten.
_CLAVES_ADIMENSIONALES = {"Tipo", "Número de brazos"}

def _aplicar_conversion(valor, funcion):
    """Aplica la conversión solo si el valor es numérico; deja intactos None y textos
    (p. ej. corona puede venir como str, y los detalles traen claves de texto)."""
    if valor is None or isinstance(valor, str):
        return valor
    try:
        return funcion(float(valor))
    except (TypeError, ValueError):
        return valor

def convertir_resultados_a_ingles(res: ResultadosDisenoPlana) -> ResultadosDisenoPlana:
    """Convierte un resultado calculado en métrico al sistema inglés, para que las
    unidades de salida coincidan con las de entrada. Modifica el objeto recibido, que
    siempre es uno recién construido dentro de la función de diseño."""
    a_pulg  = lambda x: x / MM_POR_PULGADA
    a_hp    = lambda x: x / KW_POR_HP
    a_lbf   = lambda x: x / N_POR_LBF
    a_ftmin = lambda x: x * MS_A_FTMIN

    longitudes = [
        "D1_conductora", "D2_conducida", "D_pequena", "D_grande",
        "ancho_correa_b", "ancho_correa_calculado", "ancho_polea_bp", "dmin_catalogo",
        "distancia_ejes_preliminar", "longitud_teorica", "longitud_comercial",
        "distancia_ejes_final", "corona_conductora", "corona_conducida",
        "d1_cubo_1", "d1_cubo_2", "d_eje_1", "d_eje_2", "dmin_nema",
    ]
    for campo in longitudes:
        setattr(res, campo, _aplicar_conversion(getattr(res, campo), a_pulg))

    for campo in ["potencia_nominal", "potencia_diseno"]:
        setattr(res, campo, _aplicar_conversion(getattr(res, campo), a_hp))

    for campo in ["tension_t1", "tension_t2", "tension_t0", "fuerza_radial_eje",
                  "tension_t1_admisible"]:
        setattr(res, campo, _aplicar_conversion(getattr(res, campo), a_lbf))

    res.velocidad_lineal = _aplicar_conversion(res.velocidad_lineal, a_ftmin)

    for campo in ["detalles_constructivos_1", "detalles_constructivos_2"]:
        det = getattr(res, campo)
        if det:
            setattr(res, campo, {
                k: (v if k in _CLAVES_ADIMENSIONALES else _aplicar_conversion(v, a_pulg))
                for k, v in det.items()
            })

    # NO se convierten: factor de servicio, relación de transmisión, coeficientes de
    # fricción, ángulos de contacto (grados) ni rpm, por ser adimensionales o invariantes.
    # Tampoco las cadenas de buje y chaveta: son referencias de catálogo (Taper, ANSI)
    # cuyas designaciones son métricas por definición del proveedor.
    return res

def redondear_serie_r40(valor: float) -> float:
    serie = [100, 112, 125, 140, 160, 180, 200, 224, 250, 280, 315, 355, 400, 450, 500, 560, 630, 710, 800, 900, 1000, 1120, 1250, 1400, 1600, 1800, 2000, 2240, 2500, 2800, 3150, 3550, 4000, 4500, 5000]
    if valor > 5000.0: return float(valor)
    return float(serie[np.abs(np.array(serie) - valor).argmin()])

def ejecutar_diseno_bandas_planas(
    potencia_in: Optional[float], n_conductora: float, n_conducida: float,
    condicion_operacion: str, horas_servicio: str, tipo_par: str, user_d_driver: Optional[float],
    C_usuario: Optional[float], d_eje_1_in: Optional[float] = None, d_eje_2_in: Optional[float] = None,
    f_seg: float = 1.0, grupo_correa_usuario: str = "A", is_ing: bool = False, ruta_excel="DATOS_SOFTWARE_planas.xlsx",
    user_nombre_correa: Optional[str] = None,
    user_esfuerzo_adm: Optional[float] = None,
    user_mu: Optional[float] = None,
    user_espesor: Optional[float] = None,
    user_densidad: Optional[float] = None,
    user_ancho_manual: Optional[float] = None,
    user_cp: Optional[float] = None,
    es_motor_electrico: bool = True,
    ruta_excel_motor: str = "DATOS SOFTWARE.xlsx"
) -> ResultadosDisenoPlana:
    grupo_correa = grupo_correa_usuario.upper().strip()

    db = BaseDatosPlanas(ruta_excel)
    gestor_bujes = GestorBujes()

    # --- ENTRADA: todo se lleva a métrico, que es como calcula el núcleo ---
    f_conv = MM_POR_PULGADA if is_ing else 1.0
    d_user_mm = user_d_driver * f_conv if user_d_driver else None
    C_user_mm = C_usuario * f_conv if C_usuario else None
    d_eje1_mm = d_eje_1_in * f_conv if d_eje_1_in else None
    d_eje2_mm = d_eje_2_in * f_conv if d_eje_2_in else None

    # Entradas de material de la rama MANUAL: antes NO se convertían, de modo que en
    # modo inglés se interpretaban como si ya fueran métricas y corrompían el cálculo.
    if is_ing:
        if user_espesor:      user_espesor      = user_espesor * MM_POR_PULGADA      # in   -> mm
        if user_ancho_manual: user_ancho_manual = user_ancho_manual * MM_POR_PULGADA # in   -> mm
        if user_esfuerzo_adm: user_esfuerzo_adm = user_esfuerzo_adm * MPA_POR_PSI    # psi  -> MPa
        if user_densidad:     user_densidad     = user_densidad * KGM3_POR_LBIN3     # lb/in3 -> kg/m3

    es_reduccion = (n_conductora >= n_conducida)
    n_peq, n_gra = max(n_conductora, n_conducida), min(n_conductora, n_conducida)
    i = n_peq / n_gra if n_gra > 0 else 1.0

    f_serv = obtener_factor_servicio_planas(tipo_par, condicion_operacion, horas_servicio, db)

    pot_kw = (potencia_in * 0.7457) if (potencia_in and is_ing) else (potencia_in if potencia_in else 10.0)
    p_diseno = pot_kw * f_serv * f_seg

    # El valor se calcula siempre para poder informarlo; solo entra en el minimo
    # gobernante cuando el accionamiento es un motor electrico.
    dmin_nema = obtener_dmin_motor_nema(pot_kw, n_conductora, ruta_excel_motor)
    dmin_nema_efectivo = dmin_nema if es_motor_electrico else 0.0

    # GESTIÓN DE PROPIEDADES MANUALES ACADÉMICAS
    if grupo_correa == "MANUAL":
        t_perm = user_esfuerzo_adm if (user_esfuerzo_adm is not None and user_esfuerzo_adm > 0) else 22.6
        mu = user_mu if (user_mu is not None and user_mu > 0) else 0.8
        esp_val = user_espesor if (user_espesor is not None and user_espesor > 0) else 5.5
        densidad_mat = user_densidad if (user_densidad is not None and user_densidad > 0) else 909.1

        m_area = densidad_mat * (esp_val / 1000.0)

        # CONVERSIÓN ESFUERZO ADMISIBLE -> TENSIÓN ADMISIBLE POR UNIDAD DE ANCHO
        # El usuario ingresa 't_perm' como ESFUERZO admisible del material [MPa = N/mm²].
        # Multiplicándolo por el espesor de la banda se obtiene la TENSIÓN admisible por
        # unidad de ancho [N/mm], que es la magnitud con la que realmente se dimensiona:
        #   t_perm [N/mm²] * esp_val [mm] = t1_max_equiv [N/mm]
        # Queda con el mismo nombre y las mismas unidades que en la rama de catálogo, donde
        # t1_max_equiv se obtiene del Fu nominal; así ambos flujos usan la misma magnitud y
        # las fórmulas de ancho y de tensión máxima admisible son idénticas en los dos casos.
        t1_max_equiv = t_perm * esp_val

        d_min_mat = 50.0
        tipo_actual = user_nombre_correa if user_nombre_correa else "Banda Académica / Manual"

        if user_nombre_correa:
            match_mat = db.belt_specifications[db.belt_specifications['Tipo de correa'].str.strip() == user_nombre_correa.strip()]
            if not match_mat.empty:
                cols_dmin = [c for c in match_mat.columns if 'min polea' in c.lower() or 'ø' in c.lower() or 'd min' in c.lower()]
                if cols_dmin:
                    d_min_mat = float(match_mat[cols_dmin[0]].values[0])

        diams_iso = sorted(pd.to_numeric(db.diametros_poleas_iso['Pulley_Diameter_nom_mm'], errors='coerce').dropna().unique())
        if d_user_mm is not None:
            d_peq = d_user_mm
            d_gra = d_user_mm * i
        else:
            d_peq = max(d_min_mat, dmin_nema_efectivo, 350.0 if not diams_iso else diams_iso[0])
            d_gra = d_peq * i

        cumple_d = (d_peq >= d_min_mat)
        if not cumple_d:
            raise ValueError(f"El diámetro de la polea conductora ({d_peq} mm) es menor que el diámetro mínimo admisible ({d_min_mat} mm) para el material {tipo_actual}.")

        V = (math.pi * d_peq * n_peq) / 60000
        if V <= 0: raise ValueError("La velocidad tangencial debe ser mayor a cero.")

        # --- Cp: Tabla 17-4, cruzando grado de banda (fila) y diámetro de polea (columna) ---
        # En modo manual el material puede ser uno inventado para un ejercicio, sin grado
        # reconocible; para esos casos 'user_cp' permite entregar el valor directamente.
        if user_cp is not None and user_cp > 0:
            cp_val = float(user_cp)
        else:
            cp_val = obtener_factor_cp(d_peq, user_nombre_correa)

        C_pre = C_user_mm if C_user_mm else (0.7 * (d_peq + d_gra) + d_gra)

        delta_ang = 2 * math.asin(np.clip((d_gra - d_peq) / (2 * C_pre), -1, 1))
        theta_rad_peq = math.pi - delta_ang
        theta_rad_gra = math.pi + delta_ang

        term_euler = 1 - 1 / math.exp(mu * theta_rad_peq)
        Fc_b_1mm = (m_area / 1000) * (V**2)

        # Fuerza efectiva requerida por la potencia de diseño
        diff_t = (p_diseno * 1000) / V if V > 0 else 0.0

        # CÁLCULO GOBERNADO POR EL ESFUERZO ADMISIBLE SI EL ANCHO ESTÁ VACÍO
        # Se parte de t1_max_equiv [N/mm] (esfuerzo admisible ya convertido con el espesor)
        # y se le aplica cp_val; se le resta la tensión centrífuga por unidad de ancho.
        # El ancho mínimo se calcula siempre, incluso cuando el usuario lo fija, para poder
        # reportarlo en la memoria junto al ancho adoptado.
        denominador_b = (t1_max_equiv * cp_val) - Fc_b_1mm
        b_calculado = (diff_t / term_euler) / denominador_b if denominador_b > 0 else 0.0

        if user_ancho_manual is None or user_ancho_manual <= 0:
            if denominador_b <= 0:
                raise ValueError(f"El esfuerzo admisible ({t_perm} MPa) es muy bajo para soportar la fuerza centrífuga a esta velocidad.")
            # El ancho calculado se lleva al nominal inmediatamente superior de la ISO 22,
            # igual que en la rama de catálogo: un ancho cualquiera no se fabrica, y
            # aproximar hacia abajo dejaría la banda por debajo de la tensión requerida.
            b_iso = siguiente_ancho_iso22(db, b_calculado)
            if b_iso is None:
                mayor = anchos_nominales_iso22(db)[-1]
                raise ValueError(
                    f"El ancho requerido ({b_calculado:.1f} mm) supera el mayor ancho nominal "
                    f"de la ISO 22 disponible ({mayor:.0f} mm). Aumente el diámetro de la polea "
                    f"menor, la velocidad de giro o el esfuerzo admisible del material.")
            criterio_ancho = "Aproximado al nominal superior de la ISO 22"
        else:
            # Un ancho fijado por el usuario se respeta tal como lo escribió: es un dato del
            # ejercicio, y aproximarlo cambiaría el enunciado. El ancho calculado queda en la
            # memoria al lado, para que se vea si el fijado alcanza y con cuánto margen.
            b_iso = float(user_ancho_manual)
            criterio_ancho = "Fijado por el usuario"

        bp_iso = ancho_polea_para_banda(db, b_iso)
        D1_final, D2_final = (d_peq, d_gra) if es_reduccion else (d_gra, d_peq)

        # Antes esta rama fijaba h_1 = h_2 = 0.0 y nunca determinaba el tipo de polea ni los
        # detalles constructivos, por lo que el generador de planos recibía una cadena vacía
        # y siempre caía en "Tipo I (maciza)". Ahora se resuelve igual que en la rama de catálogo.
        h_1 = calcular_corona(db, D1_final, bp_iso)
        h_2 = calcular_corona(db, D2_final, bp_iso)

        t_p1_m = determinar_tipo_polea_real(D1_final)
        t_p2_m = determinar_tipo_polea_real(D2_final)
        b1_m, ch1_m, d1_c1_m = gestor_bujes.seleccionar_buje_y_chaveta(
            D1_final, d_eje1_mm,
            diametro_interior_llanta_plana(D1_final) if t_p1_m['tipo'] == "Tipo I" else None,
            bp_iso)
        b2_m, ch2_m, d1_c2_m = gestor_bujes.seleccionar_buje_y_chaveta(
            D2_final, d_eje2_mm,
            diametro_interior_llanta_plana(D2_final) if t_p2_m['tipo'] == "Tipo I" else None,
            bp_iso)
        det_1_m = calcular_detalles_constructivos_planas(t_p1_m['tipo'], D1_final, bp_iso, d_eje1_mm, d1_c1_m)
        det_2_m = calcular_detalles_constructivos_planas(t_p2_m['tipo'], D2_final, bp_iso, d_eje2_mm, d1_c2_m)

        T1 = (diff_t / term_euler) + (Fc_b_1mm * b_iso)

        # Tensión máxima admisible total [N] = tensión admisible por unidad de ancho [N/mm]
        # * Cp * ancho [mm]. Equivale a esfuerzo_admisible * área_sección * Cp.
        t1_max_admisible = t1_max_equiv * cp_val * b_iso
        # La tensión requerida NUNCA puede superar la admisible. Antes se toleraba un 5 %
        # por encima; ahora solo se admite la diferencia de redondeo numérico, que aparece
        # cuando el ancho se calcula justo en el límite (T1 = T1 admisible).
        if T1 > t1_max_admisible * (1 + 1e-9):
            raise ValueError(f"La tensión requerida T1 ({T1:.1f} N) excede la fuerza admisible del material ({t1_max_admisible:.1f} N) para el esfuerzo de {t_perm} MPa, Cp={cp_val:.2f} y sección {b_iso:.1f}x{esp_val} mm.")

        T2 = T1 - diff_t
        T0 = ((T1 + T2) / 2) - (Fc_b_1mm * b_iso)
        R_eje = math.sqrt(T1**2 + T2**2 + 2 * T1 * T2 * math.cos(math.radians(180 - math.degrees(theta_rad_peq))))

        L_teorica = 2 * C_pre + 1.5708 * (D1_final + D2_final) + ((D2_final - D1_final)**2) / (4 * C_pre)
        L_comercial = L_teorica
        C_final = C_pre

        # --- Enfoque alternativo para mu_requerido (mismo principio aplicado antes en la rama de catálogo) ---
        # Con la fórmula anterior, ln[(T1-Fc*b)/(T2-Fc*b)]/theta se simplifica algebraicamente y
        # SIEMPRE da exactamente 'mu' (el material), sin importar b_iso, porque T1 se construye
        # justamente en el límite de fricción mínimo. Para que mu_requerido sí refleje el margen
        # que da un ancho comercial mayor, se evalúa contra la capacidad MÁXIMA real disponible
        # para ese ancho (t1_max_admisible), no contra el T1 mínimo requerido por la potencia.
        T1_max_disponible = t1_max_admisible
        T2_max_disponible = T1_max_disponible - diff_t
        T1_util_max = T1_max_disponible - Fc_b_1mm * b_iso
        T2_util_max = T2_max_disponible - Fc_b_1mm * b_iso
        mu_requerido = (math.log(T1_util_max / T2_util_max) / theta_rad_peq
                        if T2_util_max > 0 else float('inf'))

        resultado = ResultadosDisenoPlana(
            potencia_nominal=pot_kw, factor_servicio=f_serv,
            potencia_diseno=p_diseno, n_conductora=n_conductora, n_conducida=n_conducida,
            tipo_flujo="REDUCCIÓN" if es_reduccion else "AUMENTO", relacion_transmision=i,
            D1_conductora=D1_final, D2_conducida=D2_final, D_pequena=d_peq, D_grande=d_gra,
            tipo_correa=tipo_actual, ancho_correa_b=b_iso, ancho_polea_bp=bp_iso, dmin_catalogo=d_min_mat,
            cumple_dmin=cumple_d, distancia_ejes_preliminar=C_pre, longitud_teorica=L_teorica,
            longitud_comercial=L_comercial, distancia_ejes_final=C_final,
            angulo_contacto_peq_deg=math.degrees(theta_rad_peq),
            angulo_contacto_gra_deg=math.degrees(theta_rad_gra),
            velocidad_lineal=V, tension_t1=T1, tension_t2=T2, tension_t0=T0, fuerza_radial_eje=R_eje,
            mu_requerido=mu_requerido,
            tension_t1_admisible=t1_max_admisible,
            factor_seguridad_tension=(t1_max_admisible / T1) if T1 > 0 else 0.0,
            ancho_correa_calculado=b_calculado, criterio_ancho=criterio_ancho,
            mu_material=mu, corona_conductora=h_1, corona_conducida=h_2,
            buje_1=b1_m, chaveta_1=ch1_m, buje_2=b2_m, chaveta_2=ch2_m,
            d1_cubo_1=d1_c1_m, d1_cubo_2=d1_c2_m,
            tipo_polea_1_str=f"{t_p1_m['tipo']} ({t_p1_m['descripcion']})",
            tipo_polea_2_str=f"{t_p2_m['tipo']} ({t_p2_m['descripcion']})",
            detalles_constructivos_1=det_1_m, detalles_constructivos_2=det_2_m,
            d_eje_1=d_eje1_mm, d_eje_2=d_eje2_mm,
            dmin_nema=dmin_nema, aplica_criterio_nema=es_motor_electrico
        )
        # SALIDA: se devuelve en las mismas unidades en que entraron los datos.
        return convertir_resultados_a_ingles(resultado) if is_ing else resultado

    # FLUJO ESTÁNDAR CON BASE DE DATOS (Catálogo Comercial)
    candidatas = db.belt_specifications[db.belt_specifications['Tipo de correa'].str.startswith(grupo_correa)].sort_values('Espesor [mm]')

    for tipo_actual in candidatas['Tipo de correa'].unique():
        sel_belt = db.belt_specifications[db.belt_specifications['Tipo de correa'] == tipo_actual].iloc[0]
        m_area, d_min_mat = float(sel_belt['Masa [kg/m2]']), float(sel_belt['d min polea [mm]'])
        # Fuerza periférica admisible por unidad de ancho, Fu = T1 − T2 [N/mm], tal como
        # la da el catálogo: referida a un arco de contacto de 180° y velocidad ~0. NO es
        # una tensión T1 admisible directa; más abajo se convierte.
        t_perm = float(sel_belt['Fuerza_periferica'])
        mu = float(sel_belt['Coef_friccion'])

        diams_iso = sorted(pd.to_numeric(db.diametros_poleas_iso['Pulley_Diameter_nom_mm'], errors='coerce').dropna().unique())

        if d_user_mm is not None:
            d_peq = d_user_mm
            d_gra = d_user_mm * i
        else:
            d_mínimo_gobernante = max(d_min_mat, dmin_nema_efectivo)
            d_arranque = next((v for v in diams_iso if v >= d_mínimo_gobernante), None)
            if not d_arranque: continue
            d_peq = d_arranque
            d_gra = min(diams_iso, key=lambda x: abs(x - (d_peq * i)))

        if d_peq < d_min_mat:
            raise ValueError(f"El diámetro ingresado ({d_peq} mm) es menor que el diámetro mínimo admisible por catálogo ({d_min_mat} mm).")

        V = (math.pi * d_peq * n_peq) / 60000
        if V <= 0: continue

        C_pre = C_user_mm if C_user_mm else (0.7 * (d_peq + d_gra) + d_gra)
        theta_rad_peq = math.pi - 2 * math.asin(np.clip((d_gra - d_peq) / (2 * C_pre), -1, 1))
        theta_rad_gra = math.pi + 2 * math.asin(np.clip((d_gra - d_peq) / (2 * C_pre), -1, 1))

        # --- Cp: Tabla 17-4, cruzando grado de banda (fila) y diámetro de polea (columna) ---
        # El grado sale del propio nombre de catálogo ('Tipo de correa': F-0..F-2, A-2..A-5).
        # Si la tabla marca "—" para ese grado a este diámetro, la combinación no es admisible:
        # se descarta esta candidata y se prueba la siguiente, en vez de abortar la búsqueda.
        if user_cp is not None and user_cp > 0:
            cp_val = float(user_cp)
        else:
            try:
                cp_val = obtener_factor_cp(d_peq, tipo_actual)
            except CpNoDisponibleError:
                continue

        Fc_b = (m_area / 1000) * (V**2)
        term_euler = 1 - 1 / math.exp(mu * theta_rad_peq)

        # --- Corrección: recuperar la tensión T1 máxima implícita en el Fu de catálogo ---
        # t_perm fue obtenido por el fabricante a 180° y v≈0 (Fc≈0), por lo que:
        #   t_perm = T1_max * (1 - e^(-mu*pi))  =>  T1_max = t_perm / term_euler_ref180
        term_euler_ref180 = 1 - 1 / math.exp(mu * math.pi)
        t1_max_equiv = t_perm / term_euler_ref180

        den = V * term_euler * (t1_max_equiv * cp_val - Fc_b)

        b_min = (p_diseno * 1000) / den if den > 0 else 9999

        b_iso = siguiente_ancho_iso22(db, b_min)

        if b_iso:
            bp_iso = ancho_polea_para_banda(db, b_iso)

            D1_final, D2_final = (d_peq, d_gra) if es_reduccion else (d_gra, d_peq)

            h_1 = calcular_corona(db, D1_final, bp_iso)
            h_2 = calcular_corona(db, D2_final, bp_iso)

            diff_t = (p_diseno * 1000) / V
            T1 = (diff_t / term_euler) + (Fc_b * b_iso)

            # Validación estricta sin topes arbitrarios pequeños: T1 se rige por la tensión admisible del material y área.
            # Se usa t1_max_equiv (tensión T1 máxima real), no t_perm directamente (que es Fu, no T1).
            t1_max_admisible = t1_max_equiv * b_iso * cp_val
            # La tensión requerida NUNCA puede superar la admisible. Antes se aceptaba hasta
            # un 25 % por encima, lo que daba diseños con factor de seguridad menor que 1.
            if T1 > t1_max_admisible * (1 + 1e-9):
                continue  # Si requiere más tensión de la permitida, buscar un ancho mayor de banda

            T2 = T1 - diff_t
            if T2 < 0:
                continue  # T2 no puede ser negativa

            T0 = ((T1 + T2) / 2) - (Fc_b * b_iso)
            R_eje = math.sqrt(T1**2 + T2**2 + 2 * T1 * T2 * math.cos(math.radians(180 - math.degrees(theta_rad_peq))))

            L_teorica = 2 * C_pre + 1.5708 * (D1_final + D2_final) + ((D2_final - D1_final)**2) / (4 * C_pre)
            L_comercial = redondear_serie_r40(L_teorica)

            def eq_c(c): return 2*c + 1.5708*(D1_final + D2_final) + ((D2_final - D1_final)**2)/(4*c) - L_comercial
            try: C_final = brentq(eq_c, 0.1, 50000.0)
            except ValueError: C_final = C_pre

            t_p1, t_p2 = determinar_tipo_polea_real(D1_final), determinar_tipo_polea_real(D2_final)
            # En las macizas el buje se mide contra el interior de la llanta.
            b1, ch1, d1_c1 = gestor_bujes.seleccionar_buje_y_chaveta(
                D1_final, d_eje1_mm,
                diametro_interior_llanta_plana(D1_final) if t_p1['tipo'] == "Tipo I" else None,
                bp_iso)
            b2, ch2, d1_c2 = gestor_bujes.seleccionar_buje_y_chaveta(
                D2_final, d_eje2_mm,
                diametro_interior_llanta_plana(D2_final) if t_p2['tipo'] == "Tipo I" else None,
                bp_iso)
            det_1 = calcular_detalles_constructivos_planas(t_p1['tipo'], D1_final, bp_iso, d_eje1_mm, d1_c1)
            det_2 = calcular_detalles_constructivos_planas(t_p2['tipo'], D2_final, bp_iso, d_eje2_mm, d1_c2)

            # --- Enfoque alternativo para mu_requerido (mismo principio que en la rama MANUAL) ---
            # En vez de evaluar el margen con T1 fijado en el límite mínimo de fricción (que por
            # construcción siempre reproduce mu_material, sin importar b_iso), se evalúa qué fricción
            # haría falta si la banda se tensiona hasta la capacidad MÁXIMA real que su ancho
            # comercial (b_iso) puede soportar. Esto sí refleja el margen que da un ancho mayor a b_min:
            # a mayor ancho, mayor T1 disponible, T1/T2 se acerca a 1, y el mu requerido baja.
            T1_max_disponible = t1_max_equiv * cp_val * b_iso
            T2_max_disponible = T1_max_disponible - diff_t
            T1_util_max = T1_max_disponible - Fc_b * b_iso
            T2_util_max = T2_max_disponible - Fc_b * b_iso
            mu_requerido = (math.log(T1_util_max / T2_util_max) / theta_rad_peq
                            if T2_util_max > 0 else float('inf'))

            resultado = ResultadosDisenoPlana(
                potencia_nominal=pot_kw, factor_servicio=f_serv,
                potencia_diseno=p_diseno, n_conductora=n_conductora, n_conducida=n_conducida,
                tipo_flujo="REDUCCIÓN" if es_reduccion else "AUMENTO", relacion_transmision=i,
                D1_conductora=D1_final, D2_conducida=D2_final, D_pequena=d_peq, D_grande=d_gra,
                tipo_correa=tipo_actual, ancho_correa_b=b_iso, ancho_polea_bp=bp_iso, dmin_catalogo=d_min_mat,
                cumple_dmin=True, distancia_ejes_preliminar=C_pre, longitud_teorica=L_teorica,
                longitud_comercial=L_comercial, distancia_ejes_final=C_final,
                angulo_contacto_peq_deg=math.degrees(theta_rad_peq),
                angulo_contacto_gra_deg=math.degrees(theta_rad_gra),
                velocidad_lineal=V, tension_t1=T1, tension_t2=T2, tension_t0=T0, fuerza_radial_eje=R_eje,
                mu_requerido=mu_requerido,
                tension_t1_admisible=t1_max_admisible,
                factor_seguridad_tension=(t1_max_admisible / T1) if T1 > 0 else 0.0,
                mu_material=mu, corona_conductora=h_1, corona_conducida=h_2,
                buje_1=b1, chaveta_1=ch1, buje_2=b2, chaveta_2=ch2, d1_cubo_1=d1_c1, d1_cubo_2=d1_c2,
                tipo_polea_1_str=f"{t_p1['tipo']} ({t_p1['descripcion']})", tipo_polea_2_str=f"{t_p2['tipo']} ({t_p2['descripcion']})",
                detalles_constructivos_1=det_1, detalles_constructivos_2=det_2, d_eje_1=d_eje1_mm, d_eje_2=d_eje2_mm,
                dmin_nema=dmin_nema, aplica_criterio_nema=es_motor_electrico,
                ancho_correa_calculado=b_min,
                criterio_ancho="Aproximado al nominal superior de la ISO 22"
            )
            # SALIDA: se devuelve en las mismas unidades en que entraron los datos.
            return convertir_resultados_a_ingles(resultado) if is_ing else resultado
    raise ValueError(f"No se encontró ninguna banda de la familia {grupo_correa} capaz de transmitir la potencia sin exceder los límites geométricos de la polea.")

ejecutar_diseno_planas = ejecutar_diseno_bandas_planas

def generar_informe_planas(res: ResultadosDisenoPlana, is_ing: bool = False) -> str:
    """El informe debe rotular con las MISMAS unidades en que se entregó el resultado.
    Cuando is_ing=True, los valores ya vienen convertidos a sistema inglés, así que aquí
    solo cambian las etiquetas; los números no se vuelven a tocar."""
    if not res: return "No se encontraron soluciones válidas."

    u_pot = "HP"     if is_ing else "kW"
    u_dim = "pulg"   if is_ing else "mm"
    u_vel = "ft/min" if is_ing else "m/s"
    u_fza = "lbf"    if is_ing else "N"
    dec_h = 4 if is_ing else 2   # la corona es pequeña: en pulgadas necesita más decimales

    # El ancho se reporta en dos líneas: el que sale del cálculo de la tensión admisible y el
    # que finalmente se adopta. Así queda a la vista cuánto se aproximó y con qué criterio.
    # Cuando la fuerza centrífuga consume toda la capacidad del material el ancho calculado no
    # existe, y en ese caso se dice en lugar de imprimir un cero que parecería un resultado.
    if res.ancho_correa_calculado and res.ancho_correa_calculado > 0:
        txt_ancho_calc = f"{res.ancho_correa_calculado:.2f} {u_dim}"
    else:
        txt_ancho_calc = "No determinable a esta velocidad"
    txt_criterio = f" ({res.criterio_ancho})" if res.criterio_ancho else ""

    return f"""====================================================
  MEMORIA DE CÁLCULO: TRANSMISIÓN POR BANDAS PLANAS
  Sistema de unidades: {"INGLÉS" if is_ing else "MÉTRICO"}
====================================================
1. PARÁMETROS OPERATIVOS Y DE DISEÑO
    - Accionamiento       : {"Motor eléctrico (mínimo NEMA aplicado)" if res.aplica_criterio_nema else "Distinto de motor eléctrico (NEMA no aplicado)"}
    - Mínimo NEMA de eje  : {f"{res.dmin_nema:.2f} {u_dim}" if res.dmin_nema > 0 else "No disponible"}
    - Tipo de Transmisión : {res.tipo_flujo}
    - Relación de Transm. : {res.relacion_transmision:.2f}
    - Potencia Nominal    : {res.potencia_nominal:.2f} {u_pot}
    - Potencia de Diseño  : {res.potencia_diseno:.2f} {u_pot}
    - Factor de Servicio  : {res.factor_servicio:.2f}

2. SELECCIÓN DE CORREA Y CINEMÁTICA
    - Tipo / Material     : {res.tipo_correa}
    - Velocidad Tangencial: {res.velocidad_lineal:.2f} {u_vel}
    - Ancho calculado (b) : {txt_ancho_calc}
    - Ancho escogido  (b) : {res.ancho_correa_b:.2f} {u_dim}{txt_criterio}
    - Distancia ejes final: {res.distancia_ejes_final:.2f} {u_dim}
    - Longitud comercial  : {res.longitud_comercial:.2f} {u_dim}

3. GEOMETRÍA DE POLEAS Y CONSTRUCCIÓN
    - Diámetro Conductora (D1): {res.D1_conductora:.2f} {u_dim} (Mín. admisible: {res.dmin_catalogo:.2f} {u_dim})
    - Diámetro Conducida (D2) : {res.D2_conducida:.2f} {u_dim}
    - Ancho de Polea (bp)     : {res.ancho_polea_bp:.2f} {u_dim}
    - Ángulo de Contacto (D1) : {res.angulo_contacto_peq_deg:.1f}°
    - Ángulo de Contacto (D2) : {res.angulo_contacto_gra_deg:.1f}°
    - Altura de bombeo Polea 1 (h): {res.corona_conductora:.{dec_h}f} {u_dim}
    - Altura de bombeo Polea 2 (h): {res.corona_conducida:.{dec_h}f} {u_dim}
    - Tipo Polea 1            : {res.tipo_polea_1_str or "No determinado"}
    - Tipo Polea 2            : {res.tipo_polea_2_str or "No determinado"}

4. ACOPLAMIENTO (BUJES Y CHAVETAS)
    - Polea 1 -> Buje: {res.buje_1} | Chaveta: {res.chaveta_1}
    - Polea 2 -> Buje: {res.buje_2} | Chaveta: {res.chaveta_2}

5. TENSIONES Y DINÁMICA DE LA BANDA
    - Tensión Lado Tenso (T1)     : {res.tension_t1:.1f} {u_fza}
    - Tensión Lado Flojo (T2)     : {res.tension_t2:.1f} {u_fza}
    - Tensión Inicial (T0)        : {res.tension_t0:.1f} {u_fza}
    - Fuerza Radial en Ejes (R)   : {res.fuerza_radial_eje:.1f} {u_fza}
    - Fricción Requerida (μ req)  : {res.mu_requerido:.2f} (Material: {res.mu_material:.2f})
    - Tensión Admisible T1 (banda): {res.tension_t1_admisible:.1f} {u_fza}
    - Factor de Seguridad por Tensión (T1 adm / T1): {res.factor_seguridad_tension:.2f}
====================================================
"""

def obtener_tipo_num(tipo_str: str) -> int:
    if "Tipo III" in tipo_str: return 3
    elif "Tipo II" in tipo_str: return 2
    else: return 1

def generar_svg_polea(res: ResultadosDisenoPlana, es_conductora: bool = True,
                      carpeta_salida: str = "") -> str:
    """Genera el plano de una polea plana y devuelve su ruta. carpeta_salida es donde se
    escribe (la interfaz usa una carpeta temporal que borra al cerrarse); las plantillas
    se leen de la carpeta del programa."""
    if es_conductora:
        diametro = res.D1_conductora
        detalles = res.detalles_constructivos_1 or {}
        tipo_str = res.tipo_polea_1_str
        sufijo = "conductora"
    else:
        diametro = res.D2_conducida
        detalles = res.detalles_constructivos_2 or {}
        tipo_str = res.tipo_polea_2_str
        sufijo = "conducida"

    tipo_num = obtener_tipo_num(tipo_str)
    nombre_plantilla = f"Banda plana tipo {tipo_num}.svg"
    if not os.path.exists(nombre_plantilla): return ""

    with open(nombre_plantilla, "r", encoding="utf-8") as f:
        svg_content = f.read()

    # Valores de respaldo coherentes con calcular_detalles_constructivos_planas, para que
    # una plantilla que pida cotas de brazos o de disco no quede nunca con el texto crudo
    # "VAR_..." aunque la polea sea de otro tipo.
    d_eje_ref      = float(detalles.get("d_eje", max(20.0, 0.15 * diametro)))
    d1_cubo_ref    = float(detalles.get("m_buje", 1.8 * d_eje_ref))
    espesor_llanta = float(detalles.get("Espesor de llanta (t)", diametro / 200.0 + 3.0))
    h_brazo        = float(detalles.get("h (Ancho brazo en base)", 1.15 * d_eje_ref))
    a_brazo        = float(detalles.get("a (Espesor brazo en base)", 0.45 * h_brazo))
    h_brazo2       = float(detalles.get("h' (Ancho brazo en corona)", 0.8 * h_brazo))
    a_brazo2       = float(detalles.get("a' (Espesor brazo en corona)", 0.8 * a_brazo))
    corona         = float(res.corona_conductora if es_conductora else res.corona_conducida)

    # TODOS los marcadores se definen siempre, sin condicionar al tipo de polea: antes
    # las cotas de brazos y de disco solo se llenaban para ciertos tipos y, si la plantilla
    # las pedía, el plano terminaba mostrando "VAR_A_BRAZO" como texto.
    reemplazos = {
        "VAR_ANCHO_POLEA": f"{res.ancho_polea_bp:.1f}",
        "VAR_D_NOMINAL":   f"{diametro:.1f}",
        "VAR_T_LLANTA":    f"{espesor_llanta:.1f}",
        "VAR_D_EJE":       f"{d_eje_ref:.1f}",
        "VAR_L_BUJE":      f"{float(detalles.get('l_buje', 0.8 * diametro * 0.3)):.1f}",
        "VAR_M_BUJE":      f"{d1_cubo_ref:.1f}",
        "VAR_H":           f"{corona:.2f}",
        # VAR_Z se define mas abajo, solo si la polea tiene alma.
        "VAR_D_CP":        f"{float(detalles.get('D_cp (Diam. Circunf. Agujeros)', diametro * 0.4)):.1f}",
        "VAR_D_AG":        f"{float(detalles.get('d_ag (Diam. Agujero Aligeramiento)', diametro * 0.15)):.1f}",
        "VAR_A_BRAZO":     f"{a_brazo:.1f}",
        "VAR_A_BRAZO2":    f"{a_brazo2:.1f}",
        "VAR_H_BRAZO":     f"{h_brazo:.1f}",
        "VAR_H_BRAZO2":    f"{h_brazo2:.1f}",
        "VAR_N_BRAZOS":    f"{int(detalles.get('Número de brazos', 4))}",
    }

    # El espesor del alma solo existe en las poleas de discos (Tipo II). En una maciza o
    # en una de brazos no hay alma que medir, de modo que el marcador se deja sin definir
    # y la red de seguridad lo sustituye por un guion. Antes se rellenaba con bp/3, que
    # daba una cota creible y falsa en poleas que no tienen esa pared.
    espesor_alma = detalles.get('z (Espesor del alma)')
    if espesor_alma is not None:
        try:
            reemplazos["VAR_Z"] = f"{float(espesor_alma):.1f}"
        except (TypeError, ValueError):
            pass

    # La sustitución se hace por token completo y con el recentrado de las cotas incluido.
    # Los marcadores que la plantilla pida y el código no conozca se sustituyen por un guion
    # y se avisan por consola, para no imprimir "VAR_LOQUESEA" sobre el dibujo.
    svg_content = _sustituir_marcadores(svg_content, reemplazos, nombre_plantilla)

    nombre_salida = os.path.join(carpeta_salida, f"plano_{sufijo}_tipo{tipo_num}.svg")
    with open(nombre_salida, "w", encoding="utf-8") as f:
        f.write(svg_content)
    return nombre_salida

def generar_svg_transmision(res: ResultadosDisenoPlana, carpeta_salida: str = "") -> tuple:
    d1 = res.D1_conductora
    d2 = res.D2_conducida
    dif = abs(d2 - d1)

    if math.isclose(d1, d2, abs_tol=1.0): caso = 1
    elif d1 < d2: caso = 2 if dif <= 120 else 3
    else: caso = 4 if dif <= 120 else 5

    nombre_plantilla = f"Transmisión - caso {caso}.svg"
    if not os.path.exists(nombre_plantilla): return "", caso

    with open(nombre_plantilla, "r", encoding="utf-8") as f:
        svg_content = f.read()

    ang1 = getattr(res, 'angulo_contacto_peq_deg', 180.0)
    ang2 = getattr(res, 'angulo_contacto_gra_deg', 360.0 - ang1)

    # Las plantillas de transmisión son las mismas que usa el módulo de bandas en V, de modo
    # que los nombres tienen que coincidir con los de allí:
    #  - la longitud se pide como VAR_LC, no como VAR_L. Con el nombre anterior la plantilla
    #    imprimía "L = 1500.0C", porque el reemplazo en cadena de VAR_L dejaba suelta la C.
    #  - los ángulos van SIN el símbolo de grado, porque la plantilla ya lo trae escrito
    #    detrás del marcador ("θ1= VAR_ANG1°") y salían dos.
    reemplazos = {
        "VAR_D1": f"{d1:.1f}", "VAR_D2": f"{d2:.1f}",
        "VAR_C": f"{res.distancia_ejes_final:.1f}",
        "VAR_LC": f"{res.longitud_comercial:.1f}", "VAR_L": f"{res.longitud_comercial:.1f}",
        "VAR_ANCHO": f"{res.ancho_correa_b:.1f}", "VAR_RPM1": f"{res.n_conductora:.0f}",
        "VAR_RPM2": f"{res.n_conducida:.0f}", "VAR_ANG1": f"{ang1:.1f}", "VAR_ANG2": f"{ang2:.1f}",
    }
    svg_content = _sustituir_marcadores(svg_content, reemplazos, nombre_plantilla)

    nombre_salida = os.path.join(carpeta_salida, f"plano_transmision_caso{caso}.svg")
    with open(nombre_salida, "w", encoding="utf-8") as f:
        f.write(svg_content)
    return nombre_salida, caso
