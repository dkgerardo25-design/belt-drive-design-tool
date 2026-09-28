import os
import re
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
from scipy.optimize import brentq
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, List

FAMILIAS_PERFILES = {
    "METRICA": ["SPZ", "SPA", "SPB", "SPC"],
    "AMERICANA": ["A", "B", "C", "D", "E"],
    "ALTA_CAPACIDAD": ["3V", "5V", "8V"],
    "SERVICIO_LIVIANO": ["3L", "4L", "5L"]
}

# Factor de conversión entre sistemas de potencia. El núcleo de cálculo trabaja
# internamente en kW; la conversión se hace en el único punto donde se lee la tabla de
# capacidad, de modo que ninguna otra parte del programa ve unidades inglesas.
KW_POR_HP = 0.7457
N_POR_LBF = 4.4482216152605
MS_A_FTMIN = 196.8503937007874   # 1 m/s = 196,85 ft/min
LBFT_POR_KGM = 0.6719689751      # 1 kg/m = 0,672 lb/pie (masa lineal de la correa)

# Distancia radial entre la línea primitiva y el diámetro exterior de la polea, por
# lado, para los perfiles clásicos. Es la MISMA constante con la que
# generar_especificacion_comercial_polea() construye el diámetro exterior comercial, de
# modo que la conversión de ida y de vuelta (dd <-> De) es exacta y no introduce deriva.
# Para el resto de perfiles el valor se toma de la columna 'b_mm' de la hoja
# 'perfiles_v'. Los valores coinciden con esa columna; el de E se confirmó en 12,0 mm
# contra el catálogo.
OFFSET_DATUM_EXTERIOR_CLASICAS = {
    'Z': 2.5, '10': 2.5,
    'A': 3.3, '13': 3.3,
    'B': 4.2, '17': 4.2,
    'C': 5.7, '22': 5.7,
    'D': 8.1, '32': 8.1,
    'E': 12.0, '40': 12.0
}


@dataclass
class ResultadosDiseno:
    potencia_nominal: float
    factor_servicio: float
    potencia_diseno: float
    familia: str
    n1: float
    n2: float
    tipo_transmision_flujo: str
    relacion_transmision: float
    D1: float
    D2: float
    D_pequena: float
    D_grande: float
    perfil: str
    dmin_motor: float
    dmin_perfil_req: float
    dmin_gobernante: float
    cumple_dmin: bool
    distancia_ejes_preliminar: float
    longitud_teorica_ld: float
    longitud_comercial: float
    tipo_longitud_comercial: str
    referencia_comercial_correa: str
    distancia_ejes_final: float
    angulo_contacto_pequena_g: float
    factor_angulo_c1: float
    factor_longitud_c3: float
    potencia_corregida_banda: float
    num_bandas_entero: int
    velocidad_lineal: float
    fuerza_efectiva_te: float
    carga_dinamica_eje: float
    # Tensiones de la correa. Se calculaban desde siempre para llegar a la carga sobre el
    # eje, pero no se guardaban, de modo que la memoria de cálculo no podía mostrarlas.
    tension_t1: float = 0.0
    tension_t2: float = 0.0
    tension_t0: float = 0.0
    ancho_polea_1: float = 0.0
    ancho_polea_2: float = 0.0
    buje_1: str = "N/A"
    chaveta_1: str = "N/A"
    buje_2: str = "N/A"
    chaveta_2: str = "N/A"
    d1_cubo_1: Optional[float] = None
    d1_cubo_2: Optional[float] = None
    diametro_fijo_usuario: bool = False
    distancia_fija_usuario: bool = False
    dim_ranura_1: Optional[Dict[str, Any]] = None
    dim_ranura_2: Optional[Dict[str, Any]] = None
    tipo_polea_1_str: str = ""
    tipo_polea_2_str: str = ""
    detalles_constructivos_1: Optional[Dict[str, Any]] = None
    detalles_constructivos_2: Optional[Dict[str, Any]] = None
    d_eje_1: Optional[float] = None
    d_eje_2: Optional[float] = None
    referencia_comercial_polea_1: str = ""
    referencia_comercial_polea_2: str = ""
    alerta_flexion_1: str = ""
    alerta_flexion_2: str = ""
    # Capacidad leída directamente de la tabla, ANTES de aplicar C1 y C3. Se conserva
    # para poder mostrar en la memoria de cálculo de dónde sale la potencia corregida.
    potencia_nominal_banda: float = 0.0
    # Diámetro exterior con el que efectivamente se entró a la tabla de capacidad.
    diametro_exterior_consulta: float = 0.0
    convencion_diametro_consulta: str = "de"
    alerta_tabla_potencia: str = ""
    # Criterio NEMA de diámetro mínimo en el eje del motor. Solo aplica a accionamientos
    # por motor eléctrico; con otra máquina motriz el diámetro lo decide el usuario y
    # este valor queda como referencia.
    aplica_criterio_nema: bool = True
    alerta_diametro_usuario: str = ""
    # Modo de distancia entre centros con que se resolvió la geometría (FIJO, RANGO o
    # AUTOMATICO) y el aviso que deja el recálculo de C a partir de la longitud comercial.
    modo_centros: str = ""
    alerta_centros: str = ""
    # Límites del rango de centros ingresado (mm), para poder informarlos en cualquier
    # sistema de unidades. None cuando el modo no es RANGO.
    c_min_usuario: Optional[float] = None
    c_max_usuario: Optional[float] = None
    # False cuando el usuario pidió no llevar los diámetros a la serie comercial: las
    # poleas quedan como fabricación a medida y no tienen referencia de catálogo.
    diametros_normalizados: bool = True
    # Capacidad total de la transmisión (potencia corregida por banda × número de bandas;
    # en FHP, la de la única correa) y factor de seguridad por potencia = capacidad / Pd.
    # Como Pd ya incluye el factor de servicio, FS = 1 es el mínimo admisible y todo lo que
    # lo supere es margen adicional.
    capacidad_total_kw: float = 0.0
    factor_seguridad_potencia: float = 0.0
    # Tensiones POR BANDA (los campos anteriores son del conjunto de n_bandas correas) y
    # tensión centrífuga Fc = m·v², que depende de la masa lineal de la correa.
    tension_t1_banda: float = 0.0
    tension_t2_banda: float = 0.0
    tension_t0_banda: float = 0.0
    tension_centrifuga_banda: float = 0.0
    tension_centrifuga: float = 0.0
    fuerza_efectiva_te_banda: float = 0.0
    carga_dinamica_eje_banda: float = 0.0
    masa_lineal_correa: float = 0.0


class CapacidadFHPInsuficiente(ValueError):
    """Ningún diámetro admisible de ese perfil liviano alcanza la potencia pedida.
    No es un fallo numérico: es que el perfil se quedó corto, de modo que el llamador
    debe escalar al siguiente perfil de la familia."""
    pass


class DisenadorFHP:
    """Método de la norma de correas FHP (Fractional Horse Power) para los perfiles
    livianos 3L, 4L y 5L, que no se tabulan por catálogo sino por una ecuación de ajuste.

    La capacidad por correa, en HP, responde a:

        P(d, n) = r · [ (c1 · d^0,91) / r^0,09 − c2 − c3 · r² · d³ ],    r = n / 1000

    El primer término crece con el diámetro y el tercero, cúbico, representa las pérdidas
    por flexión y fuerza centrífuga. Su competencia hace que la curva tenga un MÁXIMO y
    después decaiga: para una potencia dada hay dos diámetros que la satisfacen, y el de
    interés es el menor.

    DIÁMETRO DE PASO. En la ecuación, d NO es el diámetro exterior de la polea sino el de
    paso, d = d0 − 2a, donde d0 es el diámetro exterior efectivo (Machinery's Handbook,
    31.ª ed., p. 2592). La misma fuente indica que la relación de transmisión y la
    velocidad de la banda se calculan con ese diámetro (nota a de la tabla de poleas
    ANSI/RMA IP-23, p. 2591). Todos los métodos de esta clase reciben y devuelven el
    diámetro EXTERIOR d0, que es con el que se designa y fabrica la polea, y restan 2a
    internamente. Antes se evaluaba la ecuación directamente con d0, lo que sobreestimaba
    la capacidad: entre 7 y 9 % en 3L y 4L, y entre 18 y 35 % en una 5L de 3,5 pulg.

    Parámetros por perfil (pulgadas):
        dos_a   valor 2a de la tabla de poleas ANSI/RMA IP-23.
        d0_min  diámetro exterior efectivo mínimo recomendado de la misma tabla. Antes se
                usaban 1,38 / 2,30 / 3,18 pulg, que no coinciden con la tabla (equivalen a
                restarle dos veces 2a al mínimo recomendado).
    """

    PARAMETROS = {
        "3L": {"c1": 0.2164, "c2": 0.2324, "c3": 0.0001396, "dos_a": 0.06, "d0_min": 1.5},
        "4L": {"c1": 0.4666, "c2": 0.7231, "c3": 0.0002286, "dos_a": 0.10, "d0_min": 2.5},
        "5L": {"c1": 0.7748, "c2": 1.727, "c3": 0.0003641, "dos_a": 0.16, "d0_min": 3.5}
    }

    @classmethod
    def dos_a_mm(cls, perfil: str) -> float:
        """Valor 2a del perfil, en mm (0 si el perfil no es liviano)."""
        p = cls.PARAMETROS.get(str(perfil).strip().upper())
        return p['dos_a'] * 25.4 if p else 0.0
    ORDEN_PERFILES = ["3L", "4L", "5L"]
    # Diámetro máximo razonable para una polea de correa liviana, en pulgadas. Acota la
    # búsqueda del máximo de la curva.
    D_MAX_BUSQUEDA_IN = 60.0

    # Factor de servicio COMBINADO de la norma FHP. A diferencia de los perfiles
    # industriales, que cruzan tipo de motor, tipo de transmisión y horas de servicio en
    # tablas separadas, aquí un solo coeficiente recoge todo y depende únicamente de DOS
    # entradas: el tipo de máquina accionada y la relación de transmisión.
    FACTORES_COMBINADOS = {
        "FANS AND BLOWERS": {"<1.5": 1.0, ">=1.5": 0.9},
        "DOMESTIC LAUNDRY MACHINES": {"<1.5": 1.1, ">=1.5": 1.0},
        "CENTRIFUGAL PUMPS": {"<1.5": 1.1, ">=1.5": 1.0},
        "GENERATORS": {"<1.5": 1.2, ">=1.5": 1.1},
        "ROTARY COMPRESSORS": {"<1.5": 1.2, ">=1.5": 1.1},
        "MACHINE TOOLS": {"<1.5": 1.3, ">=1.5": 1.2},
        "RECIPROCATING PUMPS": {"<1.5": 1.4, ">=1.5": 1.3},
        "RECIPROCATING COMPRESSORS": {"<1.5": 1.4, ">=1.5": 1.3},
        "WOODWORKING MACHINES": {"<1.5": 1.4, ">=1.5": 1.3}
    }

    # Nombres en español de las mismas máquinas, para poder presentarlas en la interfaz
    # sin que la clave de la tabla dependa de cómo estén escritas en pantalla.
    MAQUINAS_ES = {
        "FANS AND BLOWERS": "Ventiladores y sopladores",
        "DOMESTIC LAUNDRY MACHINES": "Máquinas de lavandería doméstica",
        "CENTRIFUGAL PUMPS": "Bombas centrífugas",
        "GENERATORS": "Generadores",
        "ROTARY COMPRESSORS": "Compresores rotativos",
        "MACHINE TOOLS": "Máquinas herramienta",
        "RECIPROCATING PUMPS": "Bombas reciprocantes",
        "RECIPROCATING COMPRESSORS": "Compresores reciprocantes",
        "WOODWORKING MACHINES": "Máquinas para trabajar madera",
    }

    @staticmethod
    def _sin_tildes(texto: str) -> str:
        reemplazos = str.maketrans("ÁÉÍÓÚÜÑáéíóúüñ", "AEIOUUNaeiouun")
        return str(texto).translate(reemplazos).strip().upper()

    @classmethod
    def normalizar_maquina(cls, nombre: Any) -> Optional[str]:
        """Traduce el nombre de la máquina a la clave de FACTORES_COMBINADOS.

        Acepta la designación original del catálogo y la versión en español que muestra
        la interfaz, con o sin tildes. Devuelve None si no reconoce la máquina, para que
        el llamador pueda avisar en vez de aplicar un factor por defecto en silencio.
        """
        if nombre is None:
            return None
        clave = cls._sin_tildes(nombre)
        if clave in cls.FACTORES_COMBINADOS:
            return clave
        for canonica, en_espanol in cls.MAQUINAS_ES.items():
            if clave == cls._sin_tildes(en_espanol):
                return canonica
        return None

    @classmethod
    def factor_servicio(cls, maquina: Any, relacion: float) -> Tuple[float, str]:
        """Factor de servicio combinado y, si la máquina no se reconoce, la advertencia.

        Devuelve (ks, advertencia).
        """
        canonica = cls.normalizar_maquina(maquina)
        if canonica is None:
            aviso = (
                f"No se reconoció la máquina accionada ('{maquina}') entre las que tabula "
                f"la norma FHP, así que se aplicó el factor de servicio por defecto "
                f"(1,20 / 1,10). Seleccione una de las máquinas de la lista para que el "
                f"factor salga de la tabla."
            )
            return (1.2 if relacion < 1.5 else 1.1), aviso
        fila = cls.FACTORES_COMBINADOS[canonica]
        return (fila["<1.5"] if relacion < 1.5 else fila[">=1.5"]), ""

    @staticmethod
    def ecuacion_hp(d0: float, rpm: float, hp_design: float, p: dict) -> float:
        """Capacidad menos potencia de diseño. d0 es el diámetro EXTERIOR efectivo, en
        pulgadas; la ecuación se evalúa con el de paso, d = d0 − 2a."""
        d = d0 - p['dos_a']
        r_norm = rpm / 1000.0
        return r_norm * ((p['c1'] * d**0.91) / (r_norm**0.09) - p['c2'] - p['c3'] * r_norm**2 * d**3) - hp_design

    @staticmethod
    def capacidad_hp(d0: float, rpm: float, p: dict) -> float:
        """Potencia que transmite la correa con una polea de diámetro exterior d0 (pulg)."""
        return DisenadorFHP.ecuacion_hp(d0, rpm, 0.0, p)

    def diametro_de_maxima_capacidad(self, rpm: float, p: dict) -> Tuple[float, float]:
        """Localiza la cima de la curva de capacidad: primero un barrido grueso y luego
        una búsqueda áurea. Es lo que permite acotar el intervalo donde sí existe una
        única raíz creciente."""
        ds = np.linspace(p['d0_min'], self.D_MAX_BUSQUEDA_IN, 400)
        caps = np.array([self.capacidad_hp(d, rpm, p) for d in ds])
        k = int(np.argmax(caps))

        lo = ds[max(0, k - 1)]
        hi = ds[min(len(ds) - 1, k + 1)]
        for _ in range(80):
            m1 = lo + (hi - lo) * 0.381966
            m2 = lo + (hi - lo) * 0.618034
            if self.capacidad_hp(m1, rpm, p) < self.capacidad_hp(m2, rpm, p):
                lo = m1
            else:
                hi = m2
        d_opt = 0.5 * (lo + hi)
        return d_opt, self.capacidad_hp(d_opt, rpm, p)

    def calcular_diametro_minimo(self, hp_design: float, rpm_pequena: float, perfil: str) -> float:
        """Menor diámetro, en pulgadas, cuya capacidad alcanza la potencia de diseño.

        El intervalo de búsqueda se acota entre el diámetro mínimo absoluto del perfil y
        la cima de la curva. Buscar en todo [0,5 ; 50] no funciona: la capacidad es
        negativa en ambos extremos —pequeña por falta de arco, negativa al otro lado por
        el término cúbico— y el solver no encuentra cambio de signo aunque la raíz exista.
        """
        p = self.PARAMETROS[perfil]

        capacidad_en_minimo = self.capacidad_hp(p['d0_min'], rpm_pequena, p)
        if capacidad_en_minimo >= hp_design:
            return p['d0_min']

        d_opt, capacidad_maxima = self.diametro_de_maxima_capacidad(rpm_pequena, p)
        if capacidad_maxima < hp_design:
            raise CapacidadFHPInsuficiente(
                f"El perfil {perfil} no alcanza {hp_design:.2f} HP a {rpm_pequena:.0f} RPM: "
                f"su capacidad máxima es {capacidad_maxima:.2f} HP, con una polea de "
                f"{d_opt:.2f} pulg."
            )

        return float(brentq(self.ecuacion_hp, p['d0_min'], d_opt,
                            args=(rpm_pequena, hp_design, p)))

    def indice_perfil_inicial(self, hp_design: float) -> int:
        """Perfil por el que conviene empezar, según los umbrales de potencia de la
        norma. El llamador escala desde ahí si el perfil se queda corto."""
        if hp_design <= 0.5:
            return 0
        if hp_design <= 1.5:
            return 1
        return 2

    def diametro_para_potencia(self, hp_design: float, rpm_pequena: float, perfil: str,
                               d_usuario_in: Optional[float] = None
                               ) -> Tuple[float, float, str]:
        """Diámetro de la polea pequeña para ese perfil, en pulgadas.

        Sin diámetro de usuario devuelve el mínimo que exige la potencia, redondeado hacia
        ARRIBA al décimo de pulgada, que es el escalón comercial de estas poleas.
        Redondear al más cercano podría bajar el diámetro y dejar la correa corta.

        Con diámetro de usuario lo RESPETA, y si queda por debajo del mínimo devuelve una
        advertencia en lugar de sustituirlo en silencio.

        Devuelve (diámetro_pulg, diámetro_mínimo_pulg, advertencia) y propaga
        CapacidadFHPInsuficiente si el perfil no alcanza la potencia a ninguna medida.
        """
        d_min = self.calcular_diametro_minimo(hp_design, rpm_pequena, perfil)

        if d_usuario_in is None:
            return float(np.ceil(d_min * 10.0 - 1e-9) / 10.0), d_min, ""

        advertencia = ""
        if d_usuario_in < d_min - 1e-9:
            capacidad_usuario = self.capacidad_hp(d_usuario_in, rpm_pequena, self.PARAMETROS[perfil])
            advertencia = (
                f"El diámetro indicado ({d_usuario_in:.2f} pulg) está por debajo del "
                f"mínimo que exige la potencia de diseño ({d_min:.2f} pulg) para el perfil "
                f"{perfil}: a ese diámetro la correa transmite {capacidad_usuario:.2f} HP "
                f"de los {hp_design:.2f} HP requeridos."
            )
        return float(d_usuario_in), d_min, advertencia


class BaseDatosCorreas:
    def __init__(self, ruta="DATOS SOFTWARE.xlsx"):
        possible_paths = [
            ruta, "DATOS SOFTWARE.xlsx", "DATOS SOFTWARE .xlsx",
            "/content/DATOS SOFTWARE.xlsx", os.path.join(os.getcwd(), "DATOS SOFTWARE.xlsx")
        ]
        archivo_encontrado = None
        for p in possible_paths:
            if os.path.exists(p):
                archivo_encontrado = p
                break

        if not archivo_encontrado:
            for root, dirs, files in os.walk(os.getcwd()):
                for file in files:
                    if "DATOS" in file.upper() and "SOFTWARE" in file.upper() and file.endswith(".xlsx"):
                        archivo_encontrado = os.path.join(root, file)
                        break
                if archivo_encontrado:
                    break

        if not archivo_encontrado:
            raise FileNotFoundError(f"❌ No se pudo encontrar el archivo 'DATOS SOFTWARE.xlsx'")

        self.xls = pd.ExcelFile(archivo_encontrado)
        self.perfiles_v = pd.read_excel(self.xls, "perfiles_v")
        self.motor_electrico = pd.read_excel(self.xls, "motor_electrico")
        self.seleccion_perfil = pd.read_excel(self.xls, "seleccion_perfil")
        self.longitudes_comerciales = pd.read_excel(self.xls, "Longitudes_comerciales")
        self.seccion_poleas = pd.read_excel(self.xls, "seccion_poleas")

        # 'pot_nominal' se lee SIN encabezado: la hoja trae filas de título y un
        # encabezado propio por cada perfil, así que no existe una única fila de
        # nombres de columna válida para todo el bloque. El posicionamiento es
        # posicional y la estructura se resuelve en _parsear_pot_nominal().
        self.pot_nominal = pd.read_excel(self.xls, "pot_nominal", header=None)
        self.tablas_potencia = self._parsear_pot_nominal()

        self.c1_tabla, self.c3_tabla = self._parsear_factores_correccion()

        self.c2_factores = parsear_factor_servicio_c2(
            pd.read_excel(self.xls, "Factor_Servicio_c2", header=None)
        )

    @staticmethod
    def _interpretar_banda_incremento(etiqueta: str) -> Optional[Tuple[float, float]]:
        """Traduce el nombre de una columna de incremento al rango de relación de
        transmisión que cubre. Acepta los dos formatos del catálogo:

            Inc_1.06_1.26  -> (1.06, 1.26)      rango cerrado
            Inc_GT_1.57    -> (1.57, infinito)  "mayor que"

        Devolver el rango en vez de fijarlo en el código permite que cada catálogo
        traiga sus propias bandas sin tocar el programa.
        """
        texto = str(etiqueta).strip()
        if not texto.lower().startswith('inc'):
            return None
        cuerpo = texto[3:].lstrip('_ ').strip()
        if cuerpo.upper().startswith('GT'):
            numeros = re.findall(r'\d+(?:\.\d+)?', cuerpo)
            return (float(numeros[0]), float('inf')) if numeros else None
        numeros = re.findall(r'\d+(?:\.\d+)?', cuerpo)
        if len(numeros) >= 2:
            return float(numeros[0]), float(numeros[1])
        return None

    def _parsear_pot_nominal(self) -> Dict[str, Dict[str, Any]]:
        """Convierte la hoja 'pot_nominal' en una tabla de doble entrada por perfil.

        Estructura de la hoja: bloques consecutivos, uno por perfil. Cada bloque abre
        con una fila de encabezado y sigue con una fila por cada rpm tabulada:

            perfil | rpm | [kW|HP] | [dd|De] | d_<D1> | d_<D2> | ... | Inc_<rango> | ...

        donde:
          • d_<D>  columnas de capacidad por canal, una por diámetro de polea motriz.
          • kW/HP  unidad de potencia del bloque. Si la celda falta se asume HP, que es
                   la unidad del catálogo INTERMEC con el que se armó la hoja. El bloque
                   del perfil E proviene de Optibelt y está en kW, así que lleva la celda.
          • dd/De  si los diámetros de las columnas son primitivos (dd) o exteriores
                   (De). Si la celda falta se deduce de la familia del perfil.
          • Inc_   columnas opcionales de incremento de potencia por relación de
                   transmisión, en la misma unidad que el bloque.

        Las celdas vacías corresponden a los guiones y a las zonas sombreadas del
        catálogo ("Consulte a INTERMEC"): se conservan como NaN, nunca como cero, porque
        un cero se interpretaría como capacidad nula y arrastraría la interpolación.

        Devuelve, por perfil, las rpm, los diámetros, la matriz de capacidad, la unidad,
        la convención de diámetro y las bandas de incremento.
        """
        df = self.pot_nominal
        tablas: Dict[str, Dict[str, Any]] = {}
        # Motivos por los que un bloque quedó descartado. Se conservan para poder
        # diagnosticar una hoja recién editada en vez de fallar con un KeyError mudo.
        self.avisos_pot_nominal: List[str] = []

        filas_encabezado = [
            r for r in range(df.shape[0])
            if any(str(v).strip().lower().startswith('d_') for v in df.iloc[r].tolist())
        ]

        # Una fila que dice 'perfil' y 'rpm' pero no trae ninguna columna 'd_' no se
        # reconoce como encabezado, de modo que su bloque entero queda invisible. Es el
        # error más difícil de notar al pegar una tabla nueva, así que se avisa.
        for r in range(df.shape[0]):
            if r in filas_encabezado:
                continue
            celdas = [str(v).strip().lower() for v in df.iloc[r].tolist()]
            if 'perfil' in celdas and 'rpm' in celdas:
                self.avisos_pot_nominal.append(
                    f"Fila {r + 1} de la hoja: parece un encabezado de bloque ('perfil' y "
                    f"'rpm'), pero ninguna columna de diámetro lleva el prefijo 'd_'. "
                    f"Rotúlelas d_450, d_500, etc.; el bloque se ignoró por completo."
                )

        for pos, fila_h in enumerate(filas_encabezado):
            etiquetas = [str(v).strip() for v in df.iloc[fila_h].tolist()]

            columnas_d: List[Tuple[int, float]] = []
            columnas_inc: List[Tuple[int, float, float]] = []
            unidad = None
            convencion = None
            # Las columnas 'perfil' y 'rpm' se localizan por su rótulo y no por su
            # posición: al declarar la unidad y la convención del bloque es natural
            # intercalar esas celdas, con lo que 'rpm' deja de estar en la columna B.
            col_perfil = None
            col_rpm = None

            for c, etiqueta in enumerate(etiquetas):
                bajo = etiqueta.lower()
                if bajo == 'perfil':
                    col_perfil = c
                    continue
                if bajo == 'rpm':
                    col_rpm = c
                    continue
                if bajo.startswith('d_'):
                    numero = re.sub(r'[^0-9.]', '', etiqueta[2:])
                    if numero:
                        columnas_d.append((c, float(numero)))
                elif bajo in ('kw', 'hp'):
                    unidad = bajo.upper() if bajo == 'hp' else 'KW'
                elif bajo in ('dd', 'de'):
                    convencion = bajo
                else:
                    banda = self._interpretar_banda_incremento(etiqueta)
                    if banda is not None:
                        columnas_inc.append((c, banda[0], banda[1]))

            if col_perfil is None:
                col_perfil = 0
            if col_rpm is None:
                col_rpm = 1

            if len(columnas_d) < 2:
                self.avisos_pot_nominal.append(
                    f"Fila {fila_h + 1} de la hoja: encabezado con menos de dos columnas "
                    f"'d_<diámetro>'; el bloque se omitió. Revise que cada columna de "
                    f"diámetro esté rotulada como d_450, d_500, etc."
                )
                continue

            fin = filas_encabezado[pos + 1] if pos + 1 < len(filas_encabezado) else df.shape[0]
            bloque = df.iloc[fila_h + 1:fin].copy()
            if bloque.empty:
                self.avisos_pot_nominal.append(
                    f"Fila {fila_h + 1} de la hoja: encabezado sin filas de datos debajo."
                )
                continue

            # El nombre del perfil se arrastra hacia abajo: basta escribirlo en la primera
            # fila del bloque. Sin esto, dejar la columna A en blanco en el resto de filas
            # —que es lo natural al pegar una tabla— reducía el bloque a una sola fila y
            # hacía que se descartara entero.
            columna_perfil = bloque.iloc[:, col_perfil].astype(str).str.strip()
            columna_perfil = columna_perfil.replace(
                {'': None, 'nan': None, 'NaN': None, 'None': None}
            ).ffill()
            bloque.iloc[:, col_perfil] = columna_perfil

            perfil = str(bloque.iloc[0, col_perfil]).strip().upper()
            if not perfil or perfil == 'NONE' or perfil == 'NAN':
                self.avisos_pot_nominal.append(
                    f"Fila {fila_h + 2} de la hoja: la columna 'perfil' está vacía, así que "
                    f"no se pudo identificar a qué perfil pertenece el bloque."
                )
                continue

            bloque = bloque[bloque.iloc[:, col_perfil].astype(str).str.strip().str.upper() == perfil]
            rpms = pd.to_numeric(bloque.iloc[:, col_rpm], errors='coerce').values.astype(float)
            matriz = bloque.iloc[:, [c for c, _ in columnas_d]].apply(
                pd.to_numeric, errors='coerce'
            ).values.astype(float)

            if columnas_inc:
                incrementos = bloque.iloc[:, [c for c, _, _ in columnas_inc]].apply(
                    pd.to_numeric, errors='coerce'
                ).values.astype(float)
            else:
                incrementos = None

            validas = ~np.isnan(rpms)
            rpms, matriz = rpms[validas], matriz[validas, :]
            if incrementos is not None:
                incrementos = incrementos[validas, :]
            if len(rpms) < 2:
                self.avisos_pot_nominal.append(
                    f"Perfil '{perfil}' (fila {fila_h + 1} de la hoja): solo se hallaron "
                    f"{len(rpms)} fila(s) con rpm numéricas; se necesitan al menos dos para "
                    f"interpolar, así que el bloque se omitió."
                )
                continue

            orden = np.argsort(rpms)
            rpms, matriz = rpms[orden], matriz[orden, :]
            if incrementos is not None:
                incrementos = incrementos[orden, :]

            _, unicas = np.unique(rpms, return_index=True)
            rpms, matriz = rpms[unicas], matriz[unicas, :]
            if incrementos is not None:
                incrementos = incrementos[unicas, :]

            diametros = np.array([d for _, d in columnas_d], dtype=float)
            orden_d = np.argsort(diametros)
            diametros, matriz = diametros[orden_d], matriz[:, orden_d]

            tablas[perfil] = {
                'rpms': rpms,
                'diametros': diametros,
                'matriz': matriz,
                'unidad': unidad or 'HP',
                'convencion_diametro': convencion,
                'bandas_incremento': [(lo, hi) for _, lo, hi in columnas_inc],
                'incrementos': incrementos
            }

        return tablas

    def _parsear_factores_correccion(self) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """Separa la hoja 'Factores_correcion' en sus dos bloques.

        Bloque 1: 'rel_diametro | Ángulo_contacto | C1'  → factor por arco de contacto.
        Bloque 2: 'Perfil | longitud_mm | C3'            → factor por longitud de correa.

        La hoja los apila uno debajo del otro, así que el corte se localiza por la fila
        de encabezado del segundo bloque en vez de por un número de fila fijo.
        """
        try:
            df = pd.read_excel(self.xls, "Factores_correcion", header=None)
        except Exception:
            return None, None

        fila_c3 = None
        for r in range(df.shape[0]):
            fila = [str(v).strip().lower() for v in df.iloc[r].tolist()]
            if 'perfil' in fila and any('longitud' in v for v in fila):
                fila_c3 = r
                break

        fin_c1 = fila_c3 if fila_c3 is not None else df.shape[0]
        c1 = df.iloc[1:fin_c1, [0, 1, 2]].copy()
        c1.columns = ['rel_diametro', 'angulo_contacto', 'C1']
        c1 = c1.apply(pd.to_numeric, errors='coerce').dropna(subset=['rel_diametro', 'C1'])
        c1 = c1.sort_values('rel_diametro').reset_index(drop=True)

        c3 = None
        if fila_c3 is not None:
            c3 = df.iloc[fila_c3 + 1:, [0, 1, 2]].copy()
            c3.columns = ['perfil', 'longitud_mm', 'C3']
            c3['perfil'] = c3['perfil'].astype(str).str.strip().str.upper()
            c3[['longitud_mm', 'C3']] = c3[['longitud_mm', 'C3']].apply(pd.to_numeric, errors='coerce')
            c3 = c3.dropna(subset=['longitud_mm', 'C3'])

        return (c1 if not c1.empty else None), (c3 if (c3 is not None and not c3.empty) else None)


def parsear_factor_servicio_c2(df_raw_c2: pd.DataFrame) -> pd.DataFrame:
    """Convierte la hoja 'Factor_Servicio_c2' en una tabla indexada por tipo de transmisión.

    La hoja tiene dos filas de encabezado: la primera agrupa por tipo de par del motor
    (Par Normal / Par Elevado) y la segunda da la categoría de horas de operación. Se
    combinan en nombres de columna del estilo 'Normal_10_a_16h'.

    Se dejó como función del módulo, y no dentro de BaseDatosCorreas, porque el módulo de
    bandas planas usa esta MISMA tabla y así no necesita construir toda la base de datos de
    bandas en V para consultarla.
    """
    df_data = df_raw_c2.iloc[2:].copy()
    new_cols = ['Tipo Transmision', 'Ejemplos_Resumidos']
    current_motor_group_name = None
    for col_idx in range(2, df_raw_c2.shape[1]):
        motor_group_cell = df_raw_c2.iloc[0, col_idx]
        hour_category_cell = df_raw_c2.iloc[1, col_idx]
        if isinstance(motor_group_cell, str) and ('Par Normal' in motor_group_cell or 'Par Elevado' in motor_group_cell):
            current_motor_group_name = 'Normal' if 'Par Normal' in motor_group_cell else 'Elevado'
        if current_motor_group_name and isinstance(hour_category_cell, str):
            new_cols.append(hour_category_cell.strip())
        else:
            new_cols.append(f'Unnamed_{col_idx}')
    df_data.columns = new_cols
    df_data = df_data.drop(columns=['Ejemplos_Resumidos'])
    return df_data.set_index('Tipo Transmision').apply(pd.to_numeric, errors='coerce')


class GestorBujes:
    def __init__(self, ruta_trans="Datos_Bujes.xlsx", ruta_chavetas="Chavetas_ANSI mm.xlsx"):
        if not os.path.exists(ruta_trans) or not os.path.exists(ruta_chavetas):
            self.activo = False
            return
        self.activo = True
        self.df_taper = pd.read_excel(ruta_trans, sheet_name='Geometria_Bujes_Taper')
        self.df_qd = pd.read_excel(ruta_trans, sheet_name='Geometria_Bujes_QD')
        self.df_chavetas = pd.read_excel(ruta_chavetas, sheet_name='Dimensiones_Chavetas_ANSI')
        self.longitudes_estandar_chavetas = [250, 220, 200, 180, 160, 140, 125, 110, 100, 90, 80, 70, 63, 56, 50, 45, 40, 36, 32, 28, 25, 22, 20, 18, 16, 14, 12, 10, 8, 6]

    def chaveta_para(self, diametro_eje_mm, longitud_disponible_mm):
        """Chaveta normalizada para ese eje, con la mayor longitud que quepa."""
        df_c = self.df_chavetas[(self.df_chavetas['Diametro_Eje_Min_mm'] < diametro_eje_mm) &
                                (self.df_chavetas['Diametro_Eje_Max_mm'] >= diametro_eje_mm)]
        if df_c.empty:
            return "Chaveta no estándar"
        fila = df_c.iloc[0]
        l_max = longitud_disponible_mm - 2.0
        l_final = next((l for l in self.longitudes_estandar_chavetas if l <= l_max), None)
        if not l_final:
            return "Longitud no estandarizable"
        return (f"{fila['Tipo_Chaveta']} {fila['Ancho_W_mm']:.2f} x "
                f"{fila['Alto_H_mm']:.2f} x {l_final} mm")

    def seleccionar_buje_maciza(self, d_interior_llanta_mm, diametro_eje_mm, ancho_polea_mm):
        """Acoplamiento de una polea MACIZA, donde el cubo debe caber dentro de la llanta.

        El espacio disponible no es el diámetro exterior de la polea sino el interior de
        la llanta, D − 2·(profundidad de ranura + espesor de llanta). El orden es:

          1. Buje QD, que es el preferido, con el menor diámetro de brida que quepa y
             admita el eje.
          2. Si ninguno cabe, buje Taper con la misma condición sobre la manzana mínima.
          3. Si tampoco, montaje directo sobre el eje, que es lo que queda cuando la
             polea es demasiado pequeña para cualquier buje comercial.

        Devuelve (buje, chaveta, diámetro del cubo o None si el montaje es directo).
        """
        if not self.activo or not diametro_eje_mm:
            return "N/A", "N/A", None

        qd = self.df_qd[(self.df_qd['Hueco_Max_Permisible_mm'] >= diametro_eje_mm) &
                        (self.df_qd['Diametro_Brida_M_mm'] <= d_interior_llanta_mm)]
        if not qd.empty:
            fila = qd.sort_values('Diametro_Brida_M_mm').iloc[0]
            return (f"QD {fila['Ref_Buje']}",
                    self.chaveta_para(diametro_eje_mm, float(fila['Longitud_L_mm'])),
                    float(fila['Diametro_Brida_M_mm']))

        taper = self.df_taper[(self.df_taper['Hueco_Max_Permisible_mm'] >= diametro_eje_mm) &
                              (self.df_taper['C_Min_Manzana_mm'] <= d_interior_llanta_mm)]
        if not taper.empty:
            fila = taper.sort_values('C_Min_Manzana_mm').iloc[0]
            return (f"Taper {fila['Ref_Buje']} (no cabe ningún QD)",
                    self.chaveta_para(diametro_eje_mm, float(fila['B_mm'])),
                    float(fila['C_Min_Manzana_mm']))

        largo = ancho_polea_mm if ancho_polea_mm else 2.5 * diametro_eje_mm
        return ("Montaje directo sobre el eje (ningún buje cabe en la llanta)",
                self.chaveta_para(diametro_eje_mm, largo), None)

    def seleccionar_buje_y_chaveta(self, familia, diametro_polea_mm, diametro_eje_mm):
        if not self.activo or not diametro_eje_mm:
            return "N/A", "N/A", None

        if familia.upper() == "SERVICIO_LIVIANO":
            return "Mecanizado a medida", "N/A", round(diametro_eje_mm * 1.75, 2)

        buje_seleccionado = "No encontrado"
        longitud_buje = 0.0
        d1_cubo = None

        if familia.upper() == "METRICA":
            df_fil = self.df_taper[(self.df_taper['Hueco_Max_Permisible_mm'] >= diametro_eje_mm) &
                                   (self.df_taper['C_Min_Manzana_mm'] <= diametro_polea_mm)].copy()
            if not df_fil.empty:
                df_fil = df_fil.sort_values(by=['Hueco_Max_Permisible_mm', 'C_Min_Manzana_mm'])
                fila = df_fil.iloc[0]
                buje_seleccionado = f"Taper {fila['Ref_Buje']}"
                longitud_buje = float(fila['B_mm'])
                d1_cubo = float(fila['C_Min_Manzana_mm'])

        elif familia.upper() in ["AMERICANA", "ALTA_CAPACIDAD"]:
            df_fil = self.df_qd[(self.df_qd['Hueco_Max_Permisible_mm'] >= diametro_eje_mm) &
                                (self.df_qd['Diametro_Brida_M_mm'] <= diametro_polea_mm)].copy()
            if not df_fil.empty:
                df_fil = df_fil.sort_values(by='Hueco_Max_Permisible_mm')
                fila = df_fil.iloc[0]
                buje_seleccionado = f"QD {fila['Ref_Buje']}"
                longitud_buje = float(fila['Longitud_L_mm'])
                d1_cubo = float(fila['Diametro_Brida_M_mm'])

        if buje_seleccionado == "No encontrado" or longitud_buje <= 0:
            return "Buje no compatible", "N/A", None

        df_c = self.df_chavetas[(self.df_chavetas['Diametro_Eje_Min_mm'] < diametro_eje_mm) &
                                (self.df_chavetas['Diametro_Eje_Max_mm'] >= diametro_eje_mm)]
        if df_c.empty:
            return buje_seleccionado, "Chaveta no estándar", d1_cubo

        fila_c = df_c.iloc[0]
        ancho = fila_c['Ancho_W_mm']
        alto = fila_c['Alto_H_mm']
        tipo = fila_c['Tipo_Chaveta']

        l_max = longitud_buje - 2.0
        l_final = next((l for l in self.longitudes_estandar_chavetas if l <= l_max), None)

        if l_final:
            chaveta_str = f"{tipo} {ancho:.2f} x {alto:.2f} x {l_final} mm"
        else:
            chaveta_str = "Longitud no estandarizable"

        return buje_seleccionado, chaveta_str, d1_cubo


def _valor_mas_cercano(serie, valor: float) -> float:
    """Elemento de la serie más próximo al valor teórico, por encima o por debajo.

    Si el teórico cae exactamente a mitad de camino entre dos valores normalizados se
    toma el MAYOR, que es el lado conservador (más arco de contacto y más capacidad).
    """
    arr = np.asarray(serie, dtype=float)
    dif = np.abs(arr - float(valor))
    empatados = np.flatnonzero(np.isclose(dif, dif.min(), rtol=0.0, atol=1e-9))
    return float(arr[empatados[-1]])


# Tabla 8 de BS 3790:2006, diámetros primitivos preferentes.
SERIE_DIAMETROS_BS3790 = [
    20, 22.4, 25, 28, 31.5, 35.5, 40, 45, 50, 53, 56, 60, 63, 67, 71,
    75, 80, 85, 90, 95, 100, 106, 112, 118, 125, 132, 140, 150, 160,
    170, 180, 190, 200, 212, 224, 236, 250, 265, 280, 315, 355, 375,
    400, 425, 450, 475, 500, 530, 560, 630, 710, 800, 900, 1000, 1250, 1600, 2000
]


def redondear_serie_r40(valor: float) -> float:
    """Diámetro normalizado de BS 3790 más cercano al teórico.

    Antes se tomaba el primer valor de la serie MAYOR O IGUAL al teórico, de modo que un
    diámetro teórico de 504 mm pasaba a 530 mm aunque 500 mm estuviera más cerca.
    """
    return _valor_mas_cercano(SERIE_DIAMETROS_BS3790, valor)


def verificar_limite_flexion(perfil: str, diametro_mm: float) -> str:
    p = str(perfil).strip().upper()
    limites = {
        "SPZ": 63.0, "3V": 63.0,
        "SPA": 90.0,
        "SPB": 140.0, "5V": 140.0,
        "SPC": 224.0,
        "A": 71.0,
        "B": 112.0,
        "8V": 335.0,
        "3L": 38.0,
        "4L": 63.5,
        "5L": 88.9
    }
    limite_min = limites.get(p, 0.0)
    if limite_min > 0 and diametro_mm < limite_min:
        return (f"ADVERTENCIA: El diámetro de polea seleccionado ({diametro_mm:.1f} mm) "
                f"es menor al mínimo recomendado de {limite_min} mm para este perfil. "
                f"Riesgo de fatiga prematura de la correa. Considere sobredimensionar la polea "
                f"o usar la serie dentada de flancos abiertos (Serie X).")
    return ""


# =====================================================================================
#  CAPACIDAD DE TRANSMISIÓN POR CANAL
#  La hoja 'pot_nominal' tabula la potencia por banda en HP contra dos entradas:
#  rpm del eje rápido (filas) y DIÁMETRO EXTERIOR de la polea motriz en mm (columnas).
#  El núcleo calcula en kW, así que la conversión HP -> kW se hace aquí, en el único
#  punto donde se lee la tabla.
# =====================================================================================

def obtener_masa_lineal_correa(perfil: str, db: BaseDatosCorreas) -> float:
    """Masa por unidad de longitud de la correa, en kg/m, leída de la hoja 'perfiles_v'.

    Es el dato con el que se evalúa la tensión centrífuga Fc = m·v². La columna se busca
    por su nombre ('Peso_Kg_m', 'masa', …) y no por posición, para que añadir columnas a la
    hoja no rompa la lectura. Si el perfil no está o la celda no es numérica se devuelve 0,
    con lo que el cálculo se reduce al caso sin fuerza centrífuga en vez de fallar.
    """
    try:
        df = db.perfiles_v
        col_perfil = df.columns[0]
        col_masa = next(
            (c for c in df.columns
             if any(k in str(c).strip().lower() for k in ('peso', 'masa', 'kg_m', 'kg/m'))),
            None
        )
        if col_masa is None:
            return 0.0
        fila = df[df[col_perfil].astype(str).str.strip().str.upper() == str(perfil).strip().upper()]
        if fila.empty:
            return 0.0
        valor = pd.to_numeric(fila.iloc[0][col_masa], errors='coerce')
        return float(valor) if not pd.isna(valor) and valor > 0 else 0.0
    except Exception:
        return 0.0


def obtener_offset_datum_exterior(perfil: str, db: BaseDatosCorreas) -> float:
    """Distancia radial, por lado, entre la línea primitiva y el diámetro exterior de la
    polea, de modo que De = dd + 2·offset.

    Para los perfiles clásicos se usa OFFSET_DATUM_EXTERIOR_CLASICAS, que es la misma
    constante con la que se construye el diámetro exterior comercial; así la conversión
    de ida y vuelta es exacta. Para el resto se lee la columna 'b_mm' de 'perfiles_v',
    que en la hoja trae los valores normalizados de cada sección.
    """
    clave = str(perfil).strip().upper()
    if clave in OFFSET_DATUM_EXTERIOR_CLASICAS:
        return OFFSET_DATUM_EXTERIOR_CLASICAS[clave]
    try:
        col_perfil, col_b = db.perfiles_v.columns[0], db.perfiles_v.columns[2]
        fila = db.perfiles_v[
            db.perfiles_v[col_perfil].astype(str).str.strip().str.upper() == clave
        ]
        if fila.empty:
            return 0.0
        # Algunos valores traen anotaciones del catálogo (p. ej. "12.0*"): se limpian.
        crudo = re.sub(r'[^0-9.]', '', str(fila.iloc[0][col_b]))
        return float(crudo) if crudo else 0.0
    except Exception:
        return 0.0


def convencion_diametro_programa(perfil: str, familia: str) -> str:
    """Indica qué representa el diámetro con el que trabaja internamente el programa.

    La familia MÉTRICA se maneja en diámetro primitivo (serie R40 de BS 3790), mientras
    que AMERICANA, ALTA_CAPACIDAD y SERVICIO_LIVIANO se manejan en diámetro exterior,
    porque así los devuelve generar_especificacion_comercial_polea().
    """
    fam = str(familia).strip().upper()
    if fam == "METRICA" or str(perfil).strip().upper() in ["SPZ", "SPA", "SPB", "SPC"]:
        return 'dd'
    return 'de'


def adaptar_diametro_a_tabla(perfil: str, familia: str, diametro_mm: float,
                             db: BaseDatosCorreas) -> Tuple[float, str]:
    """Lleva el diámetro de polea a la convención en que están rotuladas las columnas
    del bloque correspondiente de 'pot_nominal'.

    Los bloques del catálogo INTERMEC están en diámetro exterior; el del perfil E, que
    proviene de Optibelt, está en diámetro primitivo. Cada bloque declara su convención
    en el encabezado ('dd' o 'De'); si no la declara se asume la de la familia, que es
    el comportamiento histórico. La conversión es De = dd + 2·offset en un sentido y
    dd = De − 2·offset en el otro, con el mismo offset en ambos casos.

    Devuelve (diámetro_para_la_tabla, convención_usada).
    """
    clave = str(perfil).strip().upper()
    origen = convencion_diametro_programa(perfil, familia)

    tabla = db.tablas_potencia.get(clave) or {}
    # Por omisión se asume diámetro exterior, que es la convención de los bloques de
    # INTERMEC con los que se armó la hoja. Un bloque de otro catálogo la declara en su
    # encabezado ('dd' o 'De'); el del perfil E, de Optibelt, está en primitivo.
    destino = tabla.get('convencion_diametro') or 'de'

    if origen == destino:
        return diametro_mm, destino

    offset = 2.0 * obtener_offset_datum_exterior(perfil, db)
    if origen == 'dd' and destino == 'de':
        return diametro_mm + offset, destino
    return max(1.0, diametro_mm - offset), destino


# Series de diámetros comerciales de polea, por familia. Son el punto de partida de la
# búsqueda; a ellas se suman los diámetros que tabula la propia hoja de capacidad.
SERIE_R40_BS3790 = [
    20, 22.4, 25, 28, 31.5, 35.5, 40, 45, 50, 53, 56, 60, 63, 67, 71,
    75, 80, 85, 90, 95, 100, 106, 112, 118, 125, 132, 140, 150, 160,
    170, 180, 190, 200, 212, 224, 236, 250, 265, 280, 315, 355, 375,
    400, 425, 450, 475, 500, 530, 560, 630, 710, 800, 900, 1000
]
SERIE_STOCK_AMERICANA = [
    50, 56, 63, 71, 80, 90, 100, 112, 125, 140, 160, 180, 200,
    224, 250, 280, 315, 355, 400, 450, 500, 560, 630, 710, 800, 900, 1000
]


def convertir_diametro_desde_tabla(perfil: str, familia: str, diametro_tabla_mm: float,
                                   db: BaseDatosCorreas) -> float:
    """Inverso de adaptar_diametro_a_tabla(): lleva un diámetro rotulado en la hoja de
    capacidad a la convención con la que trabaja internamente el programa."""
    clave = str(perfil).strip().upper()
    destino = convencion_diametro_programa(perfil, familia)
    origen = (db.tablas_potencia.get(clave) or {}).get('convencion_diametro') or 'de'

    if origen == destino:
        return diametro_tabla_mm

    offset = 2.0 * obtener_offset_datum_exterior(perfil, db)
    if origen == 'de' and destino == 'dd':
        return max(1.0, diametro_tabla_mm - offset)
    return diametro_tabla_mm + offset


def diametros_candidatos(perfil: str, familia: str, db: BaseDatosCorreas) -> List[float]:
    """Diámetros comerciales entre los que buscar la polea, en la convención del programa.

    Se combinan dos fuentes:

      • La serie normalizada de la familia (R40 de BS 3790, o el stock de la serie
        clásica americana).
      • Los diámetros que rotulan las columnas de la hoja 'pot_nominal', que también son
        medidas comerciales: son las que el fabricante tabula, de modo que elegir una de
        ellas hace que la consulta de capacidad caiga sobre una columna existente en vez
        de interpolar entre dos, y nunca fuera del rango que cubre el catálogo.

    Importa sobre todo en las familias de alta capacidad y americana, donde la serie fija
    del código es métrica y no coincide con las medidas en pulgadas que ofrece realmente
    el fabricante.
    """
    base = SERIE_STOCK_AMERICANA if str(familia).strip().upper() == "AMERICANA" else SERIE_R40_BS3790
    candidatos = [float(d) for d in base]

    tabla = db.tablas_potencia.get(str(perfil).strip().upper())
    if tabla is not None:
        for d_tabla in tabla['diametros']:
            candidatos.append(convertir_diametro_desde_tabla(perfil, familia, float(d_tabla), db))

    # Duplicados con tolerancia de una décima de milímetro: dos fuentes pueden aportar la
    # misma medida con redondeos distintos, y no tiene sentido evaluarla dos veces.
    unicos: List[float] = []
    for d in sorted(candidatos):
        if not unicos or abs(d - unicos[-1]) > 0.1:
            unicos.append(round(d, 2))
    return unicos


def obtener_potencia_nominal_por_banda(perfil: str, n_pequena: float, diametro_tabla_mm: float,
                                       db: BaseDatosCorreas,
                                       relacion_transmision: float = 1.0) -> Tuple[float, str]:
    """Potencia que transmite UNA banda, en kW, para el perfil dado.

    Se entra con las rpm de la polea pequeña y su diámetro, y se cruzan ambas entradas
    en la tabla del catálogo. Cuando el punto pedido cae entre valores tabulados se
    interpola linealmente en dos pasos, que es la forma en que se lee una tabla de doble
    entrada a mano:

      1. Para cada columna de diámetro, se interpola la potencia a las rpm pedidas
         usando SOLO las filas con dato en esa columna.
      2. Con esa fila de potencias se interpola entre las dos columnas de diámetro que
         encierran el diámetro pedido.

    Si el bloque trae columnas de incremento por relación de transmisión (es el caso del
    perfil E, tomado de Optibelt), se localiza la banda que contiene la relación pedida y
    su incremento se interpola contra las rpm por el mismo criterio, sumándose a la
    capacidad base. Los bloques sin esas columnas, como los de INTERMEC, ya traen la
    capacidad total y no reciben incremento alguno.

    La unidad del bloque (kW u HP) se declara en su encabezado y la conversión a kW se
    hace aquí, que es el único punto del programa donde se lee la tabla.

    Fuera del rango tabulado el valor se satura en el extremo (np.interp no extrapola),
    lo cual evita inventar capacidades por encima del catálogo, y se devuelve además un
    texto de advertencia para que la memoria de cálculo lo deje constatado.

    Devuelve (potencia_kW, advertencia).
    """
    clave = str(perfil).strip().upper()
    tabla = db.tablas_potencia.get(clave)
    if tabla is None:
        raise ValueError(
            f"La hoja 'pot_nominal' no contiene tabla de capacidad para el perfil '{clave}'. "
            f"Perfiles disponibles: {', '.join(sorted(db.tablas_potencia))}."
        )

    rpms, diametros, matriz = tabla['rpms'], tabla['diametros'], tabla['matriz']
    advertencias: List[str] = []

    rpm_consulta = float(n_pequena)
    if rpm_consulta < rpms.min() or rpm_consulta > rpms.max():
        advertencias.append(
            f"las {rpm_consulta:.0f} RPM quedan fuera del rango tabulado para {clave} "
            f"({rpms.min():.0f}–{rpms.max():.0f} RPM)"
        )
        rpm_consulta = float(np.clip(rpm_consulta, rpms.min(), rpms.max()))

    nombre_conv = 'primitivo' if tabla.get('convencion_diametro') == 'dd' else 'exterior'
    d_consulta = float(diametro_tabla_mm)
    if d_consulta < diametros.min() or d_consulta > diametros.max():
        advertencias.append(
            f"el diámetro {nombre_conv} {d_consulta:.1f} mm queda fuera del rango tabulado "
            f"para {clave} ({diametros.min():.0f}–{diametros.max():.0f} mm)"
        )
        d_consulta = float(np.clip(d_consulta, diametros.min(), diametros.max()))

    def interpolar_contra_rpm(columna: np.ndarray) -> float:
        """Potencia de una columna a las rpm pedidas, usando solo sus filas con dato."""
        con_dato = ~np.isnan(columna)
        if not con_dato.any():
            return float('nan')
        if con_dato.sum() == 1:
            return float(columna[con_dato][0])
        return float(np.interp(rpm_consulta, rpms[con_dato], columna[con_dato]))

    # Paso 1: potencia a las rpm pedidas, columna por columna de diámetro.
    potencias_por_diametro = np.array(
        [interpolar_contra_rpm(matriz[:, j]) for j in range(len(diametros))]
    )

    # Paso 2: interpolación entre columnas, ignorando las que el catálogo deja en blanco.
    utiles = ~np.isnan(potencias_por_diametro)
    if not utiles.any():
        raise ValueError(
            f"El catálogo no reporta capacidad para el perfil {clave} a {n_pequena:.0f} RPM. "
            f"Seleccione un perfil mayor o consulte al fabricante."
        )

    potencia_base = float(np.interp(d_consulta, diametros[utiles], potencias_por_diametro[utiles]))

    # Incremento por relación de transmisión, solo si el bloque lo tabula.
    incremento = 0.0
    bandas = tabla.get('bandas_incremento') or []
    incrementos = tabla.get('incrementos')
    if bandas and incrementos is not None:
        i_val = float(relacion_transmision)
        indice_banda = next(
            (k for k, (lo, hi) in enumerate(bandas) if lo <= i_val <= hi), None
        )
        if indice_banda is None:
            # Relación por debajo de la primera banda (transmisión casi 1:1): el catálogo
            # no reporta incremento porque es nulo.
            incremento = 0.0
        else:
            valor = interpolar_contra_rpm(incrementos[:, indice_banda])
            incremento = 0.0 if np.isnan(valor) else max(0.0, valor)

    potencia_total = potencia_base + incremento
    if potencia_total <= 0:
        raise ValueError(
            f"La capacidad interpolada para {clave} a {n_pequena:.0f} RPM y "
            f"D={diametro_tabla_mm:.1f} mm resultó nula. Verifique la hoja 'pot_nominal'."
        )

    aviso = ""
    if advertencias:
        aviso = ("Lectura saturada en el borde de la tabla porque " +
                 "; ".join(advertencias) + ". El valor usado es el del extremo tabulado.")

    # Unidad del bloque -> kW (unidad interna del núcleo de cálculo).
    factor = KW_POR_HP if tabla.get('unidad', 'HP') == 'HP' else 1.0
    return potencia_total * factor, aviso


def obtener_factor_c1(relacion_diametro: float, db: BaseDatosCorreas) -> float:
    """Factor de corrección por arco de contacto C1, interpolado sobre la relación
    (D_grande − D_pequeña)/C de la hoja 'Factores_correcion'. Con ejes muy separados la
    relación tiende a 0 y C1 a 1; al acercarse los ejes el arco se reduce y C1 baja."""
    if db.c1_tabla is None or db.c1_tabla.empty:
        return 1.0
    x = db.c1_tabla['rel_diametro'].values.astype(float)
    y = db.c1_tabla['C1'].values.astype(float)
    return float(np.interp(float(relacion_diametro), x, y))


def obtener_factor_c3(perfil: str, longitud_mm: float, db: BaseDatosCorreas) -> float:
    """Factor de corrección por longitud de correa C3, interpolado por perfil sobre la
    hoja 'Factores_correcion'. Una correa más larga flexiona menos veces por minuto y
    admite algo más de potencia (C3 > 1); una más corta penaliza (C3 < 1)."""
    if db.c3_tabla is None or db.c3_tabla.empty:
        return 1.0
    sub = db.c3_tabla[db.c3_tabla['perfil'] == str(perfil).strip().upper()]
    if sub.empty:
        return 1.0
    sub = sub.sort_values('longitud_mm')
    return float(np.interp(float(longitud_mm),
                           sub['longitud_mm'].values.astype(float),
                           sub['C3'].values.astype(float)))


def generar_especificacion_comercial_polea(perfil: str, dp_teorico: float, z: int, familia: str) -> Tuple[float, str, str]:
    p_clean = str(perfil).strip().upper()
    fam_clean = str(familia).strip().upper()

    if fam_clean == "METRICA" or p_clean in ["SPZ", "SPA", "SPB", "SPC"]:
        dr_com = redondear_serie_r40(dp_teorico)
        ref_comercial = f"PT {z}-{p_clean}{int(dr_com)}"
        alerta = verificar_limite_flexion(p_clean, dr_com)
        return dr_com, ref_comercial, alerta

    elif fam_clean == "AMERICANA" and p_clean in OFFSET_DATUM_EXTERIOR_CLASICAS:
        # Única fuente del offset primitivo->exterior; ver OFFSET_DATUM_EXTERIOR_CLASICAS.
        i_val = OFFSET_DATUM_EXTERIOR_CLASICAS[p_clean]
        de_teorico = dp_teorico + 2 * i_val
        de_pulgadas = de_teorico / 25.4
        de_pulg_red = round(de_pulgadas * 2) / 2.0
        de_com_mm = de_pulg_red * 25.4

        ref_comercial = f"{z}{p_clean} x {de_pulg_red}\""
        alerta = verificar_limite_flexion(p_clean, de_com_mm)
        return de_com_mm, ref_comercial, alerta

    elif fam_clean == "ALTA_CAPACIDAD" or p_clean in ["3V", "5V", "8V"]:
        de_pulg = dp_teorico / 25.4
        de_pulg_red = round(de_pulg * 10) / 10.0
        de_com_mm = de_pulg_red * 25.4

        ref_comercial = f"TB {z}-{p_clean}{int(de_pulg_red * 100)}"
        alerta = verificar_limite_flexion(p_clean, de_com_mm)
        return de_com_mm, ref_comercial, alerta

    elif fam_clean == "SERVICIO_LIVIANO" or p_clean in ["2L", "3L", "4L", "5L"]:
        if z > 1:
            raise ValueError("Perfiles FHP livianos solo admiten poleas monocanal. Para transmisiones múltiples migrar a Perfil Clásico A o Métrico SPZ.")
        de_pulg = dp_teorico / 25.4
        de_pulg_red = round(de_pulg * 10) / 10.0
        de_com_mm = de_pulg_red * 25.4

        ref_comercial = f"Polea FHP Monocanal {p_clean} x {de_pulg_red}\""
        alerta = verificar_limite_flexion(p_clean, de_com_mm)
        return de_com_mm, ref_comercial, alerta

    else:
        dr_com = round(dp_teorico, 2)
        ref_comercial = f"Polea {p_clean} z={z} D={dr_com}"
        alerta = verificar_limite_flexion(p_clean, dr_com)
        return dr_com, ref_comercial, alerta


def referencia_comercial_polea(perfil: str, diametro_final_mm: float, z: int, familia: str) -> Tuple[str, str]:
    """Etiqueta comercial de la polea a partir de su diámetro COMERCIAL ya resuelto.

    Se separa de generar_especificacion_comercial_polea() porque esa función parte del
    diámetro teórico y, en las familias clásicas y de alta capacidad, le aplica la
    corrección de fibra neutra para obtener el diámetro exterior. Volver a pasarle un
    diámetro ya convertido la aplicaría por segunda vez y la etiqueta quedaría media
    pulgada por encima del diámetro real. Aquí solo se formatea.

    Devuelve (referencia, alerta_de_flexion).
    """
    p_clean = str(perfil).strip().upper()
    fam_clean = str(familia).strip().upper()
    alerta = verificar_limite_flexion(p_clean, diametro_final_mm)

    if fam_clean == "METRICA" or p_clean in ["SPZ", "SPA", "SPB", "SPC"]:
        return f"PT {z}-{p_clean}{int(round(diametro_final_mm))}", alerta

    de_pulg = diametro_final_mm / 25.4

    if fam_clean == "AMERICANA":
        return f"{z}{p_clean} x {round(de_pulg * 2) / 2.0}\"", alerta

    if fam_clean == "ALTA_CAPACIDAD" or p_clean in ["3V", "5V", "8V"]:
        return f"TB {z}-{p_clean}{int(round(de_pulg * 100))}", alerta

    if fam_clean == "SERVICIO_LIVIANO" or p_clean in ["2L", "3L", "4L", "5L"]:
        return f"Polea FHP Monocanal {p_clean} x {round(de_pulg * 10) / 10.0}\"", alerta

    return f"Polea {p_clean} z={z} D={round(diametro_final_mm, 2)}", alerta


def determinar_tipo_polea_real(perfil: str, N: int, D: float) -> dict:
    perfil_norm = str(perfil).strip().upper()
    grupo_fhp = {"3L", "4L", "5L"}
    grupo_medio = {"A", "B", "SPZ", "SPA", "3V"}
    grupo_pesado = {"C", "D", "E", "SPB", "SPC", "5V", "8V"}

    tipo, grupo, descripcion = "", "", ""

    if perfil_norm in grupo_fhp:
        grupo = "FHP"
        d_in = D / 25.4
        if d_in <= 3.5:
            tipo, descripcion = "Tipo I", "Maciza"
        elif 3.5 < d_in <= 6.0:
            tipo, descripcion = "Tipo II", "Aligerada (Web)"
        else:
            tipo, descripcion = "Tipo III", "De brazos"
    elif perfil_norm in grupo_medio:
        grupo = "Industrial Medio"
        if D < 115:
            tipo, descripcion = "Tipo I", "Maciza"
        elif 115 <= D < 230:
            tipo, descripcion = "Tipo II", "Aligerada (Web)"
        else:
            tipo, descripcion = "Tipo III", "De brazos"
    elif perfil_norm in grupo_pesado:
        grupo = "Industrial Pesado"
        if D < 160:
            tipo, descripcion = "Tipo I", "Maciza"
        elif 160 <= D < 300:
            tipo, descripcion = "Tipo II", "Aligerada (Web)"
        else:
            tipo, descripcion = "Tipo III", "De brazos"
    else:
        tipo, descripcion = "Desconocido", "N/A"

    return {"tipo": tipo, "grupo": grupo, "descripcion": descripcion}


def numero_brazos_polea(D_ext: float, es_liviana: bool = False) -> int:
    """Número de brazos de una polea de Tipo III.

    Las poleas de correa de servicio liviano se fabrican siempre con 4 brazos: su rango de
    diámetros es estrecho y la carga baja, de modo que no hay razón para escalonar el
    número. En las poleas industriales sí se escalona con el diámetro, porque el paso
    entre brazos crece con la corona y llega un punto en que la llanta flexa entre apoyos.
    """
    if es_liviana:
        return 4
    if D_ext <= 700:
        return 4
    if D_ext <= 2200:
        return 6
    return 8


def calcular_detalles_constructivos(tipo_str: str, D_ext: float, d_eje: Optional[float],
                                    d1_cubo: Optional[float], dim_ranura: Optional[Dict],
                                    es_liviana: bool = False) -> dict:
    """Dimensiones del cuerpo de la polea según su tipo constructivo.

    ORDEN DE COMPROBACIÓN: el Tipo III se evalúa ANTES que el Tipo II. La cadena
    "Tipo II" está contenida dentro de "Tipo III", así que comprobando en el orden natural
    toda polea de brazos entraba por la rama del alma aligerada y jamás calculaba el ancho
    ni el espesor de sus brazos. Es el mismo choque de subcadenas que ya obligó a invertir
    el orden en la selección de plantillas.
    """
    d_eje_efectivo = d_eje if (d_eje is not None and d_eje > 0) else max(20.0, 0.25 * D_ext)
    d1_cubo_efectivo = d1_cubo if (d1_cubo is not None and d1_cubo > 0) else (1.8 * d_eje_efectivo)

    try:
        h_ranura = float(dim_ranura.get('h', 0)) if dim_ranura else 5.0
        b_ranura = float(dim_ranura.get('b', 0)) if dim_ranura else 10.0
    except Exception:
        h_ranura, b_ranura = 5.0, 10.0

    D_ranura = h_ranura + b_ranura

    # Espesor de la llanta. Si el catálogo de ranura lo aporta se usa ese; si no, se
    # recurre a la regla proporcional al diámetro, que es la que emplea el módulo de
    # bandas planas. Antes se calculaba pero no se guardaba, de modo que el plano no
    # tenía de dónde tomarlo y la cota salía vacía.
    espesor_llanta = None
    if dim_ranura:
        try:
            valor = dim_ranura.get('espesor_llanta')
            if valor is not None and float(valor) > 0:
                espesor_llanta = float(valor)
        except Exception:
            espesor_llanta = None
    if espesor_llanta is None:
        espesor_llanta = 0.75 * D_ranura if D_ranura > 0 else (D_ext / 200.0 + 3.0)

    detalles = {
        "Espesor de llanta (t)": espesor_llanta,
        "d_eje": d_eje_efectivo,
        "l_buje": 0.8 * D_ext * 0.3,
        "m_buje": d1_cubo_efectivo,
    }

    if "Tipo III" in tipo_str:
        h_brazo = 1.15 * d_eje_efectivo
        a_brazo = 0.45 * h_brazo
        h_brazo_2 = 0.8 * h_brazo
        a_brazo_2 = 0.8 * a_brazo

        detalles.update({
            "Tipo": "Brazos (Spoke)",
            "Número de brazos": numero_brazos_polea(D_ext, es_liviana),
            "h (Ancho brazo en base)": h_brazo,
            "a (Espesor brazo en base)": a_brazo,
            "h' (Ancho brazo en corona)": h_brazo_2,
            "a' (Espesor brazo en corona)": a_brazo_2,
        })

    elif "Tipo II" in tipo_str:
        D_cp = max(0.0, 0.5 * (D_ext - 2 * (D_ranura + espesor_llanta) + d1_cubo_efectivo))
        d_ag = max(0.0, 0.35 * (D_ext - 2 * (D_ranura + espesor_llanta) - d1_cubo_efectivo))
        z = max(0.0, 0.625 * (d1_cubo_efectivo - d_eje_efectivo))

        detalles.update({
            "Tipo": "Alma Aligerada con Agujeros",
            "D_cp (Diam. Circunf. Agujeros)": D_cp,
            "d_ag (Diam. Agujero Aligeramiento)": d_ag,
            "z (Espesor del alma)": z,
        })

    else:
        # POLEA MACIZA. Aquí no hay cubo separado del cuerpo: la polea es maciza desde el
        # agujero hasta la llanta, de modo que la cota que el plano rotula como diámetro de
        # cubo (VAR_M_BUJE) no puede ser el diámetro de brida del buje, como en los otros
        # tipos. Lo que tiene sentido dibujar es el diámetro INTERIOR de la llanta, donde
        # termina la ranura y empieza el cuerpo macizo:
        #
        #     D_interior = D_ext − 2·(profundidad de ranura + espesor de llanta)
        #
        # Se resta dos veces porque es un diámetro y el material se descuenta por los dos
        # lados. Antes se heredaba el diámetro del buje, que en poleas pequeñas resulta
        # mayor que la propia llanta y producía una cota imposible.
        #
        # El buje siempre cabe dentro de ese diámetro, porque en las macizas se escoge
        # midiendo contra él (QD, luego Taper y, si ninguno entra, montaje directo).
        detalles.update({
            "Tipo": "Maciza (Solid)",
            "m_buje": D_ext - 2 * (D_ranura + espesor_llanta),
        })

    return detalles


def diametro_interior_llanta(D_ext: float, dim_ranura: Optional[Dict]) -> float:
    """Diámetro donde termina la llanta y empieza el cuerpo de la polea:

        D_interior = D_ext − 2·(profundidad de ranura + espesor de llanta)

    Es el espacio real disponible para el cubo, y por tanto contra lo que hay que medir
    si un buje cabe o no. El espesor de llanta sale del catálogo de ranura cuando está
    disponible y, si no, de la regla proporcional.
    """
    try:
        h = float(dim_ranura.get('h', 5.0)) if dim_ranura else 5.0
        b = float(dim_ranura.get('b', 10.0)) if dim_ranura else 10.0
    except (TypeError, ValueError):
        h, b = 5.0, 10.0
    d_ranura = h + b
    espesor = None
    if dim_ranura:
        try:
            valor = dim_ranura.get('espesor_llanta')
            if valor is not None and float(valor) > 0: espesor = float(valor)
        except (TypeError, ValueError):
            espesor = None
    if espesor is None:
        espesor = 0.75 * d_ranura if d_ranura > 0 else (D_ext / 200.0 + 3.0)
    return D_ext - 2 * (d_ranura + espesor)


# Diámetro mínimo que debe tener un agujero de aligeramiento para que valga la pena. Por
# debajo de él (o si el espacio sale negativo) la polea se construye maciza. Es un criterio
# práctico del programa, no de norma.
D_AGUJERO_ALIGERAMIENTO_MIN_MM = 10.0


def ajustar_tipo_por_espacio_cubo(tipo: dict, D_ext: float, d_eje: Optional[float],
                                  d1_cubo: Optional[float], dim_ranura: Optional[Dict]) -> dict:
    """Corrige el tipo constructivo cuando el cubo no deja espacio dentro de la llanta.

    determinar_tipo_polea_real() decide solo por el diámetro exterior. Pero entre el cubo
    (diámetro del buje o, si no hay, 1,8 veces el eje) y el interior de la llanta
    (D − 2·(profundidad de ranura + espesor de llanta)) tiene que quedar un anillo para el
    alma aligerada o para los brazos. Con poleas pequeñas y bujes grandes ese anillo puede
    ser mínimo o incluso negativo: el cubo ocupa todo el interior. Antes se calculaba igual
    como Tipo II y el agujero de aligeramiento salía de 0,00 mm.

    El espacio se evalúa con las mismas fórmulas de calcular_detalles_constructivos(): si
    el agujero de aligeramiento que cabría es menor que D_AGUJERO_ALIGERAMIENTO_MIN_MM, la
    polea se construye maciza (Tipo I).
    """
    if tipo.get("tipo") not in ("Tipo II", "Tipo III"):
        return tipo
    prueba = calcular_detalles_constructivos("Tipo II", D_ext, d_eje, d1_cubo, dim_ranura)
    d_ag = float(prueba.get("d_ag (Diam. Agujero Aligeramiento)", 0.0))
    if d_ag >= D_AGUJERO_ALIGERAMIENTO_MIN_MM:
        return tipo
    return {
        "tipo": "Tipo I",
        "grupo": tipo.get("grupo", ""),
        "descripcion": "Maciza: no queda espacio para aligerar entre el cubo y la llanta",
    }


def _longitud_minima_geometrica(d_peq: Optional[float], d_gra: Optional[float]) -> float:
    """Longitud primitiva mínima que puede tener la correa para dos poleas dadas.

    Corresponde al caso límite en que las poleas quedan prácticamente en contacto,
    C = (D1 + D2)/2. Cualquier longitud comercial por debajo de este valor es
    geométricamente imposible: al resolver la distancia entre centros no existe raíz
    positiva, el solver cae en el respaldo y devuelve ~0, lo que produce ángulos de
    contacto negativos. Sirve entonces como cota inferior para descartar candidatas.
    """
    if not d_peq or not d_gra or d_peq <= 0 or d_gra <= 0:
        return 0.0
    c_min = (d_peq + d_gra) / 2.0
    return 2 * c_min + 1.5708 * (d_peq + d_gra) + ((d_gra - d_peq) ** 2) / (4 * c_min)


def _elegir_longitud_comercial(valores: np.ndarray, objetivo_ld: float,
                               desplazamiento_a_ld: float, ld_minimo: float) -> Optional[float]:
    """Elige el valor comercial más cercano al objetivo entre los que son factibles.

    'valores' está en la magnitud que tabula la hoja (Li, Ld o La según el perfil) y
    'desplazamiento_a_ld' es la constante que lleva ese valor a longitud primitiva Ld,
    que es la magnitud sobre la que se evalúa la factibilidad geométrica.
    Devuelve None si ninguna longitud del catálogo alcanza el mínimo.
    """
    if len(valores) == 0:
        return None
    ld_equivalente = valores + desplazamiento_a_ld
    factibles = valores[ld_equivalente >= ld_minimo - 1e-6]
    if len(factibles) == 0:
        return None
    objetivo = objetivo_ld - desplazamiento_a_ld
    return float(factibles[np.abs(factibles - objetivo).argmin()])


def convertir_y_seleccionar_longitud(perfil: str, Ld_calculado_mm: float, db: BaseDatosCorreas, familia: str,
                                     d_peq: Optional[float] = None, d_gra: Optional[float] = None) -> dict:
    perfil_norm = str(perfil).strip().upper()
    # Cota inferior de factibilidad. Si no se reciben los diámetros el filtro queda
    # inactivo (ld_minimo = 0) y la función se comporta como antes.
    ld_minimo = _longitud_minima_geometrica(d_peq, d_gra)
    constantes_clasicas = {'Z': 22.0, 'A': 30.0, 'B': 40.0, 'C': 58.0, 'D': 75.0, 'E': 80.0}
    if perfil_norm in constantes_clasicas:
        constante = constantes_clasicas[perfil_norm]
        Li_teorico = Ld_calculado_mm - constante
        col = next((c for c in db.longitudes_comerciales.columns if str(c).strip().upper() == perfil_norm), None)
        Li_comercial = Li_teorico
        if col:
            vals = pd.to_numeric(db.longitudes_comerciales[col], errors='coerce').dropna().values
            elegida = _elegir_longitud_comercial(vals, Ld_calculado_mm, constante, ld_minimo)
            if elegida is None and len(vals) > 0:
                raise ValueError(
                    f"Ninguna longitud comercial del perfil {perfil_norm} alcanza la longitud "
                    f"mínima de {ld_minimo:.0f} mm que exigen las poleas de "
                    f"{d_peq:.0f} y {d_gra:.0f} mm. Seleccione un perfil mayor, reduzca la "
                    f"relación de transmisión o use diámetros menores."
                )
            if elegida is not None:
                Li_comercial = elegida
        return {"tipo_longitud": "Longitud Interna (Li)", "valor_comercial_mm": round(Li_comercial, 2), "Ld_comercial_mm": round(Li_comercial + constante, 2), "referencia_comercial": f"{perfil_norm} {round(Li_comercial / 25.4)}"}

    perfiles_metricos = ['SPZ', 'SPA', 'SPB', 'SPC']
    if perfil_norm in perfiles_metricos or familia.upper() == "METRICA":
        col = next((c for c in db.longitudes_comerciales.columns if str(c).strip().upper() == perfil_norm), None)
        Ld_comercial = round(Ld_calculado_mm)
        if col:
            vals = pd.to_numeric(db.longitudes_comerciales[col], errors='coerce').dropna().values
            elegida = _elegir_longitud_comercial(vals, Ld_calculado_mm, 0.0, ld_minimo)
            if elegida is None and len(vals) > 0:
                raise ValueError(
                    f"Ninguna longitud comercial del perfil {perfil_norm} alcanza la longitud "
                    f"mínima de {ld_minimo:.0f} mm que exigen las poleas de "
                    f"{d_peq:.0f} y {d_gra:.0f} mm. Seleccione un perfil mayor, reduzca la "
                    f"relación de transmisión o use diámetros menores."
                )
            if elegida is not None:
                Ld_comercial = elegida
        return {"tipo_longitud": "Longitud Primitiva / Referencia (Ld)", "valor_comercial_mm": round(Ld_comercial, 2), "Ld_comercial_mm": round(Ld_comercial, 2), "referencia_comercial": f"{perfil_norm} {round(Ld_comercial)} Ld"}

    constantes_alta_capacidad = {'3V': 4.0, '5V': 11.0, '8V': 0.0}
    if '3V' in perfil_norm or '5V' in perfil_norm or '8V' in perfil_norm or familia.upper() == "ALTA_CAPACIDAD":
        key = '3V' if '3V' in perfil_norm else ('5V' if '5V' in perfil_norm else '8V')
        delta = constantes_alta_capacidad.get(key, 0.0)
        La_teorico = Ld_calculado_mm + delta
        col = next((c for c in db.longitudes_comerciales.columns if str(c).strip().upper() == perfil_norm), None)
        La_comercial = La_teorico
        if col:
            vals = pd.to_numeric(db.longitudes_comerciales[col], errors='coerce').dropna().values
            elegida = _elegir_longitud_comercial(vals, Ld_calculado_mm, -delta, ld_minimo)
            if elegida is None and len(vals) > 0:
                raise ValueError(
                    f"Ninguna longitud comercial del perfil {perfil_norm} alcanza la longitud "
                    f"mínima de {ld_minimo:.0f} mm que exigen las poleas de "
                    f"{d_peq:.0f} y {d_gra:.0f} mm. Seleccione un perfil mayor, reduzca la "
                    f"relación de transmisión o use diámetros menores."
                )
            if elegida is not None:
                La_comercial = elegida
        nombre_base = "3V" if "3V" in perfil_norm else ("5V" if "5V" in perfil_norm else "8V")
        return {"tipo_longitud": "Longitud Exterior (La)", "valor_comercial_mm": round(La_comercial, 2), "Ld_comercial_mm": round(La_comercial - delta, 2), "referencia_comercial": f"{nombre_base} {round((La_comercial / 25.4) * 10)}"}

    constantes_servicio_liviano = {'2L': 8.0, '3L': 8.0, '4L': 13.0, '5L': 18.0}
    if perfil_norm in constantes_servicio_liviano or familia.upper() == "SERVICIO_LIVIANO":
        delta = constantes_servicio_liviano.get(perfil_norm, 8.0)
        La_teorico = Ld_calculado_mm + delta
        col = next((c for c in db.longitudes_comerciales.columns if str(c).strip().upper() == perfil_norm), None)
        if col:
            # A diferencia del resto de la hoja, las columnas de los perfiles livianos
            # (3L, 4L, 5L) están tabuladas en PULGADAS, porque así se designa la correa
            # comercialmente (4L340 = 34.0 pulgadas de longitud exterior). Sin convertir
            # a mm, la búsqueda del valor más cercano comparaba magnitudes distintas y
            # devolvía la longitud más grande de la lista, lo que colapsaba la distancia
            # entre centros y producía ángulos de contacto imposibles.
            vals_pulg = pd.to_numeric(db.longitudes_comerciales[col], errors='coerce').dropna().values
            vals = vals_pulg * 25.4
            elegida = _elegir_longitud_comercial(vals, Ld_calculado_mm, -delta, ld_minimo)
            La_comercial = elegida if elegida is not None else (
                float(vals[-1]) if len(vals) > 0 else La_teorico
            )
        else:
            La_comercial = La_teorico
        return {"tipo_longitud": "Longitud Exterior (La)", "valor_comercial_mm": round(La_comercial, 2), "Ld_comercial_mm": round(La_comercial - delta, 2), "referencia_comercial": f"{perfil_norm}{round((La_comercial / 25.4) * 10)}"}

    return {"tipo_longitud": "Longitud Primitiva (Ld)", "valor_comercial_mm": round(Ld_calculado_mm, 2), "Ld_comercial_mm": round(Ld_calculado_mm, 2), "referencia_comercial": f"{perfil_norm} {round(Ld_calculado_mm)}"}


def calcular_distancia_centros_desde_longitud(Ld_comercial: float, D1: float, D2: float) -> float:
    def eq(c): return 2*c + 1.5708*(D1 + D2) + ((D2 - D1)**2)/(4*c) - Ld_comercial
    try: return brentq(eq, 0.1, 50000.0)
    except ValueError:
        k = Ld_comercial - 1.57 * (D1 + D2)
        return max(0.1, (k + np.sqrt(max(0, k**2 - 2 * (D2 - D1)**2))) / 4)


def calcular_ancho_polea(perfil: str, num_bandas: int,
                         dim_ranura: Optional[Dict[str, Any]] = None) -> float:
    """Ancho de la cara de la polea:  B = (z − 1)·e + 2·f

    e = paso entre ejes de ranuras consecutivas y f = distancia del eje de la ranura
    extrema al borde de la polea. Con una sola ranura no hay ningún paso entre canales,
    de modo que B = 2·f. Antes la rama monocanal devolvía 2·f + e, que es el ancho de una
    polea de DOS canales: toda polea de un canal —y por tanto todas las de servicio
    liviano, que siempre lo son— salía sobredimensionada.

    e y f se toman de la hoja 'seccion_poleas' a través de dim_ranura, que es la misma
    fuente de la que sale la sección de ranura de la memoria de cálculo; así el ancho y
    la ranura nunca se contradicen. La tabla interna es solo un respaldo por si la hoja
    no trae el perfil, y replica sus valores (incluido el perfil E).
    """
    respaldo = {
        'Z': (12.0, 8.0), 'SPZ': (12.0, 8.0), 'A': (15.0, 10.0), 'SPA': (15.0, 10.0),
        'B': (19.0, 12.5), 'SPB': (19.0, 12.5), 'C': (25.5, 17.0), 'SPC': (25.5, 17.0),
        'D': (37.0, 24.0), 'E': (44.5, 29.0),
        '3V': (10.32, 8.73), '5V': (17.46, 12.70), '8V': (28.58, 19.05),
        '3L': (0.0, 8.0), '4L': (0.0, 10.0), '5L': (0.0, 12.5),
    }
    e, f = respaldo.get(str(perfil).strip().upper(), (15.0, 10.0))

    if dim_ranura:
        try:
            e_hoja = float(dim_ranura.get('e_nominal', np.nan))
            f_hoja = float(dim_ranura.get('f_nominal', np.nan))
            if not np.isnan(f_hoja) and f_hoja > 0:
                f = f_hoja
                if not np.isnan(e_hoja):
                    e = e_hoja
        except (TypeError, ValueError):
            pass

    z = max(1, int(num_bandas))
    return round((z - 1) * e + 2 * f, 2)


def obtener_factor_servicio_c2(tipo_motor, tipo_transmision, horas_operacion, db):
    df_c2 = db.c2_factores.copy()
    motor_norm = tipo_motor.lower()
    trans_norm = tipo_transmision.lower()
    horas_norm = horas_operacion.lower()
    horas_suffix_map = {"hasta 10 horas": "_hasta_10h", "10 a 16 horas": "_10_a_16h", "mas de 16 horas": "_mas_de_16h"}
    hour_suffix = horas_suffix_map.get(horas_norm)
    if not hour_suffix: return 1.0
    motor_prefix = "Normal" if 'par normal' in motor_norm else "Elevado" if 'par elevado' in motor_norm else None
    if not motor_prefix: return 1.0
    target_col = f"{motor_prefix}{hour_suffix}"
    if target_col not in df_c2.columns: return 1.0
    df_c2.index = df_c2.index.astype(str).str.strip().str.lower()
    trans_type_map = {"ligera": "transmisiones ligeras", "media": "transmisiones medias", "pesada": "transmisiones pesadas", "muy pesada": "transmisiones muy pesadas"}
    trans_index_key = trans_type_map.get(trans_norm)
    if not trans_index_key: return 1.0
    try:
        val = pd.to_numeric(df_c2.loc[trans_index_key, target_col], errors='coerce')
        return float(val) if not pd.isna(val) else 1.0
    except: return 1.0


def dmin_motor_desde_tabla(df_motor, p_kw, rpm):
    """Diámetro mínimo de polea admisible en el eje de un motor eléctrico, en mm.

    Criterio NEMA: un motor normalizado tiene un límite de carga radial en su eje, de modo
    que por debajo de cierto diámetro de polea la tracción de la correa lo sobrecarga. La
    tabla cruza potencia del motor y velocidad sincrónica.

    Se separa de obtener_dmin_motor_electrico() para poder reutilizarla desde el módulo de
    bandas planas sin tener que construir toda la base de datos de bandas en V.
    """
    df = df_motor.copy()
    df.iloc[:, 0] = pd.to_numeric(df.iloc[:, 0], errors='coerce')
    df = df.dropna(subset=[df.columns[0]])
    pots_hp = df.iloc[:, 0].values.astype(float)
    rpms = np.array([float(re.search(r'\d+', str(c)).group()) for c in df.columns[1:] if re.search(r'\d+', str(c))])
    df_vals = df.iloc[:, 1:len(rpms)+1].apply(pd.to_numeric, errors='coerce')
    df_vals = df_vals.ffill(axis=1).bfill(axis=1).fillna(280.0)
    vals = df_vals.values.astype(float)

    rpms_u, r_idx = np.unique(rpms, return_index=True)
    pots_u, p_idx = np.unique(pots_hp, return_index=True)
    vals_u = vals[np.ix_(p_idx, r_idx)]

    p_hp = p_kw / KW_POR_HP
    if p_hp > pots_u.max():
        p_hp = pots_u.max()

    idx_p_closest = np.abs(pots_u - p_hp).argmin()
    idx_r_closest = np.abs(rpms_u - rpm).argmin()

    res = vals_u[idx_p_closest, idx_r_closest]
    return max(10.0, float(res) if not np.isnan(res) else 280.0)


def obtener_dmin_motor_electrico(p_kw, rpm, db):
    return dmin_motor_desde_tabla(db.motor_electrico, p_kw, rpm)


def seleccionar_perfil_por_curva_frontera(pd_kw, rpm, fam, db):
    perfiles = FAMILIAS_PERFILES.get(fam.upper(), ["SPZ"])
    df_curvas = db.seleccion_perfil.copy()
    df_curvas.columns = [str(c).strip().upper() for c in df_curvas.columns]
    col_p, col_kw, col_rpm = df_curvas.columns[0], df_curvas.columns[1], df_curvas.columns[2]
    for p in perfiles:
        sub = df_curvas[df_curvas[col_p].astype(str).str.strip().str.upper() == p.upper()].copy()
        sub[col_kw] = pd.to_numeric(sub[col_kw], errors='coerce')
        sub[col_rpm] = pd.to_numeric(sub[col_rpm], errors='coerce')
        sub = sub.dropna(subset=[col_kw, col_rpm]).sort_values(by=col_rpm)
        if not sub.empty:
            f = interp1d(sub[col_rpm], sub[col_kw], fill_value="extrapolate", kind='linear')
            if pd_kw <= float(f(rpm)): return p
    return perfiles[-1]


def obtener_dimensiones_ranura(perfil, diametro, db):
    df = db.seccion_poleas.copy()
    df.columns = [str(c).strip() for c in df.columns]

    perfil_clean = perfil.upper().strip()
    mask = df['Seccion'].astype(str).str.upper().apply(
        lambda x: perfil_clean in [p.strip() for p in x.split('/')]
    )
    df_p = df[mask]

    if df_p.empty: return None

    df_f = df_p[(df_p['dd_min'] <= diametro) & (df_p['dd_max'] >= diametro)]

    if df_f.empty:
        if diametro < df_p['dd_min'].min():
            fila = df_p.loc[df_p['dd_min'].idxmin()]
        else:
            fila = df_p.loc[df_p['dd_max'].idxmax()]
    else:
        fila = df_f.iloc[0]

    fila_dict = fila.to_dict()
    try:
        h_val = float(fila_dict.get('h', 0))
        b_val = float(fila_dict.get('b', 0))
        fila_dict['espesor_llanta'] = 0.75 * (h_val + b_val)
    except:
        fila_dict['espesor_llanta'] = 0.0

    return fila_dict


def redondear_clasica_stock(valor_mm: float) -> float:
    """Diámetro de stock de la serie clásica americana más cercano al teórico."""
    return _valor_mas_cercano(SERIE_STOCK_AMERICANA, valor_mm)


def redondear_fabricacion(d_mm: float, is_ing: bool = False, hacia_arriba: bool = False) -> float:
    """Redondeo de un diámetro NO normalizado a una cifra fabricable, en mm.

    En sistema métrico se lleva al milímetro entero; en sistema inglés, a la centésima de
    pulgada. Por defecto se toma el valor más cercano. Con hacia_arriba=True se redondea
    por exceso, que es lo que corresponde cuando el diámetro proviene de un MÍNIMO (NEMA,
    perfil o potencia): redondearlo por defecto dejaría la polea por debajo de él.
    """
    if is_ing:
        valor = float(d_mm) / 25.4 * 100.0
        valor = np.ceil(valor - 1e-9) if hacia_arriba else np.round(valor)
        return float(valor / 100.0 * 25.4)
    valor = float(d_mm)
    return float(np.ceil(valor - 1e-9) if hacia_arriba else np.round(valor))


def referencia_polea_a_medida(perfil: str, familia: str, diametro_mm: float, z: int,
                              is_ing: bool = False) -> str:
    """Designación de una polea con diámetro no normalizado. No puede llevar referencia de
    catálogo, porque no existe en stock: se fabrica a medida."""
    conv = "dd" if convencion_diametro_programa(perfil, familia) == 'dd' else "De"
    canales = "monocanal" if int(z) == 1 else f"{int(z)} canales"
    medida = f"{diametro_mm / 25.4:.2f} pulg" if is_ing else f"{diametro_mm:.0f} mm"
    return f"Polea a medida {canales} {str(perfil).strip().upper()}, {conv} = {medida}"


# Números de canales que el fabricante ofrece en poleas de stock.
BANDAS_PERMITIDAS = [1, 2, 3, 4, 5, 6, 8, 10, 12]


def ejecutar_diseno_transmision(potencia_in, n1, n2, tipo_motor, tipo_transmision, horas_operacion,
                                familia="METRICA", D1_usuario_in=None,
                                modo_centros="FIJO", c_valor_1=None, c_valor_2=None,
                                is_ing=False, d_eje_1_in=None, d_eje_2_in=None, ruta_excel="DATOS SOFTWARE.xlsx",
                                es_motor_electrico=True, normalizar_diametros=True):
    """normalizar_diametros=False deja los diámetros en su valor teórico (redondeado al mm
    entero, o a la centésima de pulgada en sistema inglés) en lugar de llevarlos a la serie
    comercial. Las longitudes de correa se normalizan SIEMPRE."""
    db = BaseDatosCorreas(ruta_excel)
    gestor_bujes = GestorBujes()

    i = max(n1/n2, n2/n1)
    rpm_peq = max(n1, n2)
    tipo_flujo = "REDUCCIÓN" if n1 >= n2 else "AUMENTO"

    aviso_factor_servicio = ""
    if familia.upper() == "SERVICIO_LIVIANO":
        # En FHP el factor combinado depende SOLO de la máquina accionada y de la
        # relación de transmisión: no intervienen ni el tipo de motor ni las horas de
        # servicio, que sí gobiernan en los perfiles industriales.
        ks, aviso_factor_servicio = DisenadorFHP.factor_servicio(tipo_transmision, i)
    else:
        ks = obtener_factor_servicio_c2(tipo_motor, tipo_transmision, horas_operacion, db)

    factor_conv = 25.4 if is_ing else 1.0
    p_kw_base = float(potencia_in) * (KW_POR_HP if is_ing else 1.0)
    d1_mm_base = float(D1_usuario_in) * factor_conv if D1_usuario_in else None

    c_min_mm = float(c_valor_1) * factor_conv if c_valor_1 else None
    c_max_mm = float(c_valor_2) * factor_conv if c_valor_2 else None
    c_fijo_mm = float(c_valor_1) * factor_conv if (modo_centros.upper() == "FIJO" and c_valor_1) else None

    d_eje_1_mm = float(d_eje_1_in) * factor_conv if d_eje_1_in else None
    d_eje_2_mm = float(d_eje_2_in) * factor_conv if d_eje_2_in else None

    pd_kw_base = p_kw_base * ks
    # El valor NEMA se calcula siempre, porque el informe lo muestra como referencia, pero
    # solo entra en el mínimo gobernante cuando el accionamiento es un motor eléctrico.
    dmin_motor = obtener_dmin_motor_electrico(p_kw_base, n1, db)
    dmin_motor_efectivo = dmin_motor if es_motor_electrico else 0.0

    is_fixed_diameter = (d1_mm_base is not None)
    is_fixed_center = (modo_centros.upper() == "FIJO" and c_fijo_mm is not None)
    es_fhp = (familia.upper() == "SERVICIO_LIVIANO")

    # =================================================================================
    #  DIÁMETRO DE POLEA A PARTIR DEL TEÓRICO
    #  Único punto donde se decide entre normalizar a la serie comercial o dejar el valor
    #  teórico. Recibe el diámetro PRIMITIVO teórico y devuelve el diámetro en la
    #  convención con que trabaja el programa (primitivo en métricas, exterior en el resto).
    # =================================================================================
    es_americana_clasica = (familia.upper() == "AMERICANA")

    def a_primitivo(perfil_actual: str, d_programa: float) -> float:
        """Inverso de la conversión primitivo -> exterior de las poleas americanas.

        La relación de transmisión se cumple entre diámetros PRIMITIVOS. Antes el diámetro
        conducido se obtenía multiplicando el EXTERIOR de la conductora por i y sumándole
        otra vez el offset de la ranura, de modo que este se contaba dos veces y la
        relación real se desviaba (1,93 en lugar de 1,80 en una prueba con perfil C).
        """
        clave = str(perfil_actual).strip().upper()
        if es_americana_clasica and clave in OFFSET_DATUM_EXTERIOR_CLASICAS:
            return d_programa - 2 * OFFSET_DATUM_EXTERIOR_CLASICAS[clave]
        if es_fhp and clave in DisenadorFHP.PARAMETROS:
            # Perfiles livianos: diámetro de paso d = d0 − 2a (ANSI/RMA IP-23).
            return d_programa - DisenadorFHP.dos_a_mm(clave)
        return d_programa

    def diametro_polea(perfil_actual: str, dd_teorico: float, hacia_arriba: bool = False) -> float:
        """Recibe el diámetro PRIMITIVO (o de paso) teórico y devuelve el de la polea en la
        convención del programa: primitivo en métricas, exterior en el resto."""
        d = dd_teorico
        clave = str(perfil_actual).strip().upper()
        if es_americana_clasica and clave in OFFSET_DATUM_EXTERIOR_CLASICAS:
            if normalizar_diametros:
                return generar_especificacion_comercial_polea(perfil_actual, dd_teorico, 1, familia)[0]
            d = dd_teorico + 2 * OFFSET_DATUM_EXTERIOR_CLASICAS[clave]
        elif es_fhp and clave in DisenadorFHP.PARAMETROS:
            d = dd_teorico + DisenadorFHP.dos_a_mm(clave)
            if normalizar_diametros:
                return generar_especificacion_comercial_polea(perfil_actual, d, 1, familia)[0]
        elif normalizar_diametros:
            return generar_especificacion_comercial_polea(perfil_actual, dd_teorico, 1, familia)[0]
        return redondear_fabricacion(d, is_ing, hacia_arriba)

    # =================================================================================
    #  GEOMETRÍA DE LA TRANSMISIÓN
    #  Se resuelve igual para cualquier perfil, así que se factoriza: recibe los dos
    #  diámetros comerciales y devuelve longitud, distancia entre centros y ángulo.
    # =================================================================================
    def resolver_geometria(d_peq: float, d_gra: float, perfil_actual: str) -> dict:
        """Longitud comercial y distancia entre centros definitiva.

        En los tres modos la secuencia es la misma:
          1. Con la distancia de partida (la fija, la media del rango o la sugerida) se
             calcula la longitud primitiva teórica.
          2. Se toma la longitud comercial MÁS CERCANA a esa teórica.
          3. Con la longitud comercial se RECALCULA la distancia entre centros.

        El paso 3 se aplica también cuando la distancia es fija: una correa de longitud
        comercial no cierra exactamente en la distancia teórica, y antes se conservaba la
        fija como si lo hiciera, de modo que longitud, distancia y ángulo de contacto no
        eran coherentes entre sí. En modo RANGO la distancia recalculada tampoco se recorta
        a los límites —recortarla producía la misma incoherencia—; si queda fuera del
        rango se deja constancia en el informe.
        """
        aviso_centros = ""
        if is_fixed_center:
            c_prelim = c_fijo_mm
        elif modo_centros.upper() == "RANGO" and c_min_mm is not None and c_max_mm is not None:
            c_prelim = (c_min_mm + c_max_mm) / 2.0
        else:
            c_prelim = 0.7 * (d_peq + d_gra) + d_gra

        ld_teorico = 2 * c_prelim + 1.5708 * (d_peq + d_gra) + ((d_gra - d_peq)**2) / (4 * c_prelim)
        info = convertir_y_seleccionar_longitud(perfil_actual, ld_teorico, db, familia, d_peq, d_gra)
        c_final = calcular_distancia_centros_desde_longitud(info["Ld_comercial_mm"], d_peq, d_gra)

        if is_fixed_center:
            aviso_centros = (
                f"La distancia entre centros se recalculó con la longitud comercial "
                f"({info['Ld_comercial_mm']:.0f} mm Ld): pasa de {c_prelim:.1f} mm "
                f"(ingresada) a {c_final:.1f} mm ({c_final - c_prelim:+.1f} mm). El montaje "
                f"debe permitir ese desplazamiento del eje."
            )
        elif modo_centros.upper() == "RANGO" and c_min_mm is not None and c_max_mm is not None:
            if not (c_min_mm - 1e-6 <= c_final <= c_max_mm + 1e-6):
                aviso_centros = (
                    f"Con la longitud comercial más cercana ({info['Ld_comercial_mm']:.0f} mm "
                    f"Ld) la distancia entre centros resulta {c_final:.1f} mm, fuera del "
                    f"rango indicado ({c_min_mm:.0f}–{c_max_mm:.0f} mm)."
                )

        ang = 180 - 60 * (d_gra - d_peq) / c_final
        if not (0 < ang <= 180):
            raise ValueError(
                f"La geometría resultante para el perfil {perfil_actual} da un ángulo de "
                f"contacto de {ang:.1f}°, físicamente imposible. La longitud comercial "
                f"disponible no es compatible con estos diámetros."
            )
        return {
            "C_preliminar": c_prelim, "Ld_teorico": ld_teorico, "info": info,
            "C_final": c_final, "ang": ang, "aviso_centros": aviso_centros
        }

    # =================================================================================
    #  INTENTO DE DISEÑO PARA UN PERFIL CONCRETO
    #  Lanza ValueError si el perfil no admite solución, para que el llamador escale al
    #  siguiente de la familia en vez de devolver un diseño inválido.
    # =================================================================================
    def intentar_perfil(perfil_actual: str) -> dict:
        dmin_perfil = 224.0
        sub_d = db.perfiles_v[db.perfiles_v.iloc[:, 0].astype(str).str.strip().str.upper() == perfil_actual.upper()]
        if not sub_d.empty:
            val_dmin_tabla = pd.to_numeric(sub_d.iloc[0, 1], errors='coerce')
            if not pd.isna(val_dmin_tabla) and val_dmin_tabla <= 355.0:
                dmin_perfil = val_dmin_tabla
        dmin_gobernante = max(dmin_motor_efectivo, dmin_perfil)

        if is_fixed_diameter:
            if not normalizar_diametros:
                d1_arranque = d1_mm_base
            elif familia.upper() == "AMERICANA":
                d1_arranque = redondear_clasica_stock(d1_mm_base)
            else:
                d1_arranque = redondear_serie_r40(d1_mm_base)
        elif not normalizar_diametros:
            # Sin normalizar, cualquier diámetro cumple la relación de transmisión exacta,
            # así que se parte del MÍNIMO gobernante. Si con él hicieran falta más correas
            # de las de stock, más abajo se lanza el error y el llamador escala de perfil.
            d1_arranque = dmin_gobernante
        else:
            lista_candidatos = diametros_candidatos(perfil_actual, familia, db)
            # El mínimo gobernante se compara contra el diámetro COMERCIAL que resultará
            # de cada candidato, no contra el candidato crudo: al normalizar al valor más
            # cercano, un candidato apenas por encima del mínimo podría bajar de él.
            candidatos_validos = [
                d for d in lista_candidatos
                if generar_especificacion_comercial_polea(perfil_actual, d, 1, familia)[0]
                >= dmin_gobernante - 0.01
            ]
            if not candidatos_validos:
                raise ValueError(
                    f"Para el perfil {perfil_actual} no hay diámetro de stock que respete el "
                    f"mínimo de {dmin_gobernante:.0f} mm."
                )

            # Se busca el candidato que mejor respete la relación de transmisión y que
            # además resulte constructible con un número de canales de stock.
            mejor_opcion = None
            min_error_i = 999.0
            for d1_cand in candidatos_validos[:10]:
                d1_test, _, _ = generar_especificacion_comercial_polea(perfil_actual, d1_cand, 1, familia)
                d2_test, _, _ = generar_especificacion_comercial_polea(perfil_actual, d1_cand * i, 1, familia)
                i_real = max(d1_test, d2_test) / min(d1_test, d2_test)
                error_i = abs(i_real - i)
                try:
                    d_tabla, _ = adaptar_diametro_a_tabla(
                        perfil_actual, familia, min(d1_test, d2_test), db
                    )
                    p_test_kw, _ = obtener_potencia_nominal_por_banda(
                        perfil_actual, rpm_peq, d_tabla, db, i_real
                    )
                except ValueError:
                    continue
                if p_test_kw > 0 and (pd_kw_base / p_test_kw) <= max(BANDAS_PERMITIDAS):
                    if error_i < min_error_i:
                        min_error_i = error_i
                        mejor_opcion = d1_cand
            d1_arranque = mejor_opcion if mejor_opcion is not None else candidatos_validos[0]

        # Diámetros definitivos. El número de canales todavía no se conoce (depende de C1 y
        # C3, que dependen de la geometría); el DIÁMETRO no depende de él.
        if is_fixed_diameter:
            # El diámetro ingresado es el de la CONDUCTORA, y D2 = D1·n1/n2 vale tanto en
            # reducción como en aumento. Antes se trataba siempre como la polea pequeña,
            # así que en un aumento de velocidad el valor terminaba en la conducida.
            d1_final = diametro_polea(perfil_actual, d1_arranque)
            d2_final = diametro_polea(perfil_actual, a_primitivo(perfil_actual, d1_final) * n1 / n2)
        else:
            # En modo automático d1_arranque es la polea PEQUEÑA, que es la que gobiernan
            # los mínimos: sin normalizar se redondea por exceso para no quedar bajo ellos.
            d_chica = diametro_polea(perfil_actual, d1_arranque, hacia_arriba=True)
            d_grande_ = diametro_polea(perfil_actual, a_primitivo(perfil_actual, d_chica) * i)
            d1_final, d2_final = (d_chica, d_grande_) if n1 >= n2 else (d_grande_, d_chica)

        d_peq = min(d1_final, d2_final)
        d_gra = max(d1_final, d2_final)

        geo = resolver_geometria(d_peq, d_gra, perfil_actual)

        # Capacidad por banda y número de canales. Con la geometría cerrada ya se pueden
        # evaluar C1 (arco de contacto) y C3 (longitud):  N = Pd / (P_banda · C1 · C3)
        d_tabla, conv = adaptar_diametro_a_tabla(perfil_actual, familia, d_peq, db)
        p_nom_kw, aviso = obtener_potencia_nominal_por_banda(
            perfil_actual, rpm_peq, d_tabla, db, i
        )
        relacion_diametro = (d_gra - d_peq) / geo["C_final"] if geo["C_final"] > 0 else 0.0
        c1 = obtener_factor_c1(relacion_diametro, db)
        c3 = obtener_factor_c3(perfil_actual, geo["info"]["Ld_comercial_mm"], db)
        p_corr_kw = p_nom_kw * c1 * c3
        if p_corr_kw <= 0:
            raise ValueError(f"Capacidad corregida nula para el perfil {perfil_actual}.")

        n_calc_raw = pd_kw_base / p_corr_kw
        n_bandas = next((b for b in BANDAS_PERMITIDAS if b >= n_calc_raw), None)
        if n_bandas is None:
            raise ValueError(
                f"El perfil {perfil_actual} requeriría {n_calc_raw:.1f} correas, por encima "
                f"de las {max(BANDAS_PERMITIDAS)} de stock."
            )

        return {
            "perfil": perfil_actual, "dmin_perfil": dmin_perfil, "dmin_gobernante": dmin_gobernante,
            "D1_final": d1_final, "D2_final": d2_final, "D_peq": d_peq, "D_grande": d_gra,
            "geo": geo, "c1": c1, "c3": c3, "p_nom_kw": p_nom_kw, "p_corr_kw": p_corr_kw,
            "n_bandas": n_bandas, "diametro_tabla": d_tabla, "convencion": conv, "aviso": aviso
        }

    # =================================================================================
    #  SELECCIÓN DE PERFIL
    # =================================================================================
    if es_fhp:
        # El método FHP no pasa por tabla de catálogo ni por C1 y C3: su ecuación de
        # ajuste ya está formulada sobre la geometría real de la transmisión.
        #
        # Estas correas son SIEMPRE monocanal. Por eso no existe un "número de correas"
        # que ajustar: si una sola correa no alcanza la potencia, la salida no es poner
        # dos, sino pasar al siguiente perfil de la familia (3L -> 4L -> 5L).
        hp_d_fhp = pd_kw_base / KW_POR_HP
        dis = DisenadorFHP()

        def conductora_a_pequena_in(d1_conductora_mm: float, perfil_actual: str) -> float:
            """Diámetro exterior de la polea PEQUEÑA, en pulgadas, a partir del de la
            conductora. En reducción son la misma; en aumento la pequeña es la conducida y
            la relación se aplica sobre los diámetros de PASO (d = d0 − 2a)."""
            if n1 >= n2:
                return d1_conductora_mm / 25.4
            dos_a = DisenadorFHP.dos_a_mm(perfil_actual)
            return ((d1_conductora_mm - dos_a) / i + dos_a) / 25.4

        def pequena_a_conductora_in(d_pequena_in: float, perfil_actual: str) -> float:
            """Inverso de conductora_a_pequena_in()."""
            if n1 >= n2:
                return d_pequena_in
            dos_a_in = DisenadorFHP.PARAMETROS[perfil_actual]['dos_a']
            return (d_pequena_in - dos_a_in) * i + dos_a_in

        def intentar_perfil_fhp(perfil_actual: str) -> dict:
            """Resuelve la transmisión con un perfil liviano concreto.

            Lanza CapacidadFHPInsuficiente si ese perfil no puede con una sola correa,
            para que el llamador escale al siguiente.
            """
            # El diámetro ingresado es el de la CONDUCTORA; el método FHP razona sobre la
            # polea PEQUEÑA. Se traduce por perfil, porque 2a depende del perfil.
            d1_manual_in_fhp = (conductora_a_pequena_in(d1_mm_base, perfil_actual)
                                if d1_mm_base else None)
            d_calc_in, dmin_perfil_in, alerta_usr = dis.diametro_para_potencia(
                hp_d_fhp, rpm_peq, perfil_actual, d1_manual_in_fhp
            )
            dmin_perf = dmin_perfil_in * 25.4
            dmin_gob = max(dmin_motor_efectivo, dmin_perf)

            # Normalizando, el mínimo por potencia se lleva al SIGUIENTE décimo de pulgada
            # (escalón comercial de estas poleas). Sin normalizar se parte del mínimo exacto
            # y más abajo se redondea por exceso al mm o a la centésima de pulgada.
            if not normalizar_diametros and not is_fixed_diameter:
                d_calc_in = dmin_perfil_in
            d_peq = d_calc_in * 25.4
            d_gra = a_primitivo(perfil_actual, d_peq) * i + DisenadorFHP.dos_a_mm(perfil_actual)

            # El mínimo del eje del motor puede exigir una polea mayor que la que pide la
            # potencia. Solo se eleva cuando el usuario no fijó el diámetro; si lo fijó,
            # su valor manda y la discrepancia se advierte en el informe.
            if d_peq < dmin_gob:
                if not is_fixed_diameter:
                    ratio = dmin_gob / d_peq
                    d_peq, d_gra = dmin_gob, d_gra * ratio
                elif es_motor_electrico and d_peq < dmin_motor_efectivo:
                    aviso_nema = (
                        f"El diámetro indicado ({d_peq / 25.4:.2f} pulg = {d_peq:.1f} mm) "
                        f"queda por debajo del mínimo NEMA de {dmin_motor_efectivo:.1f} mm "
                        f"para un motor eléctrico de esta potencia y velocidad: la carga "
                        f"radial sobre el eje del motor puede exceder lo admisible."
                    )
                    alerta_usr = (alerta_usr + " " + aviso_nema).strip() if alerta_usr else aviso_nema

            # Normalización al décimo de pulgada MÁS CERCANO. Si eso deja la polea pequeña
            # por debajo del mínimo gobernante (lo que solo ocurre cuando el mínimo NEMA la
            # elevó a un valor intermedio), se sube un escalón: el mínimo es una restricción
            # y no puede violarse por el redondeo. Con diámetro fijado por el usuario no se
            # toca nada; la discrepancia ya quedó advertida arriba.
            d_base = d_peq
            for _ in range(3):
                # d_base es diámetro EXTERIOR; diametro_polea() recibe el de paso y le vuelve
                # a sumar 2a. La relación de transmisión se aplica entre diámetros de paso.
                d_chica = diametro_polea(perfil_actual, a_primitivo(perfil_actual, d_base),
                                         hacia_arriba=not is_fixed_diameter)
                d_grande_ = diametro_polea(perfil_actual, a_primitivo(perfil_actual, d_chica) * i)
                d1_f, d2_f = (d_chica, d_grande_) if n1 >= n2 else (d_grande_, d_chica)
                if is_fixed_diameter or min(d1_f, d2_f) >= dmin_gob - 0.01:
                    break
                d_base += 2.54

            d_peq, d_gra = min(d1_f, d2_f), max(d1_f, d2_f)

            # Capacidad REAL en el diámetro comercial finalmente adoptado. Hay que
            # evaluarla aquí y no antes: el mínimo NEMA y el redondeo comercial pueden
            # haber movido el diámetro, y como la curva de capacidad decae pasada su cima,
            # una polea MAYOR no garantiza más potencia.
            parametros = DisenadorFHP.PARAMETROS[perfil_actual]

            # Un diámetro fijado por el usuario puede quedar por debajo del mínimo ABSOLUTO
            # del perfil, donde la ecuación de ajuste ya no es válida (puede dar capacidades
            # negativas). Ese perfil se descarta por esa razón, sin evaluar la ecuación.
            d0_min_mm = parametros['d0_min'] * 25.4
            if d_peq < d0_min_mm - 0.01:
                raise CapacidadFHPInsuficiente(
                    f"{perfil_actual}: la polea pequeña de {d_peq:.1f} mm "
                    f"({d_peq / 25.4:.2f} pulg) está por debajo del diámetro exterior mínimo "
                    f"del perfil ({d0_min_mm:.1f} mm = {parametros['d0_min']:.2f} pulg)."
                )

            capacidad = DisenadorFHP.capacidad_hp(d_peq / 25.4, rpm_peq, parametros)

            if capacidad < hp_d_fhp - 1e-9:
                if capacidad <= 0:
                    detalle_cap = "a ese diámetro la correa no transmite potencia útil"
                else:
                    detalle_cap = (f"la correa transmite {capacidad:.2f} HP de los "
                                   f"{hp_d_fhp:.2f} HP requeridos")
                raise CapacidadFHPInsuficiente(
                    f"{perfil_actual}: con la polea de {d_peq:.1f} mm "
                    f"({d_peq / 25.4:.2f} pulg) {detalle_cap}, y el perfil es monocanal."
                )

            geo_local = resolver_geometria(d_peq, d_gra, perfil_actual)

            return {
                "perfil": perfil_actual, "dmin_perfil": dmin_perf, "dmin_gobernante": dmin_gob,
                "D1_final": d1_f, "D2_final": d2_f, "D_peq": d_peq, "D_grande": d_gra,
                "geo": geo_local, "capacidad_hp": capacidad, "alerta_usuario": alerta_usr
            }

        # Orden de prueba: primero el perfil que marcan los umbrales de potencia de la
        # norma y los mayores que él; después, como último recurso, los MENORES.
        # El respaldo importa a velocidades altas: el término cúbico de pérdidas crece con
        # el diámetro, de modo que pasado cierto régimen un perfil mayor transmite MENOS
        # que uno menor (a 7000 RPM el 3L da 0,57 HP y el 4L solo 0,28 HP). Sin este
        # respaldo el programa rechazaría transmisiones que un perfil más pequeño resuelve.
        indice_inicial = dis.indice_perfil_inicial(hp_d_fhp)
        orden_prueba = (DisenadorFHP.ORDEN_PERFILES[indice_inicial:] +
                        list(reversed(DisenadorFHP.ORDEN_PERFILES[:indice_inicial])))

        solucion_fhp = None
        perfiles_probados: List[str] = []
        motivos: List[str] = []
        for perfil_candidato in orden_prueba:
            perfiles_probados.append(perfil_candidato)
            try:
                solucion_fhp = intentar_perfil_fhp(perfil_candidato)
                break
            except CapacidadFHPInsuficiente as e:
                motivos.append(str(e))
                continue
            except ValueError as e:
                motivos.append(f"{perfil_candidato}: {e}")
                continue

        if solucion_fhp is None and is_fixed_diameter:
            # Con diámetro fijado, lo más útil es decir cuánto tendría que medir la polea
            # conductora en cada perfil. El mínimo se calcula para la polea PEQUEÑA; en un
            # aumento de velocidad la conductora es la grande, así que se escala por i.
            u_in = is_ing
            minimos: List[str] = []
            for p_fhp in DisenadorFHP.ORDEN_PERFILES:
                try:
                    d_min_in = pequena_a_conductora_in(
                        dis.calcular_diametro_minimo(hp_d_fhp, rpm_peq, p_fhp), p_fhp)
                    d_min_mm = d_min_in * 25.4
                    minimos.append(f"{p_fhp} = {d_min_in:.2f} pulg" if u_in
                                   else f"{p_fhp} = {d_min_mm:.1f} mm")
                except CapacidadFHPInsuficiente:
                    minimos.append(f"{p_fhp} = no alcanza la potencia a ningún diámetro")
            d_usr_txt = (f"{d1_mm_base / 25.4:.2f} pulg" if u_in else f"{d1_mm_base:.1f} mm")
            detalle = "\n   • ".join(motivos) if motivos else "sin detalle"
            raise ValueError(
                f"Con D1 = {d_usr_txt} ningún perfil de servicio liviano transmite "
                f"{hp_d_fhp:.2f} HP a {rpm_peq:.0f} RPM con una sola correa.\n"
                f"   Diámetro mínimo necesario de la polea conductora: {'; '.join(minimos)}.\n"
                f"   Suba el diámetro o use un perfil clásico (A) o métrico (SPZ), que sí "
                f"admiten varias correas.\n   Detalle por perfil:\n   • {detalle}"
            )

        if solucion_fhp is None:
            detalle = "\n   • ".join(motivos) if motivos else "sin detalle"
            raise ValueError(
                f"Ningún perfil de servicio liviano transmite {hp_d_fhp:.2f} HP a "
                f"{rpm_peq:.0f} RPM con una sola correa, que es lo único que admiten estos "
                f"perfiles.\n   • {detalle}\n   Migre a un perfil clásico (A) o métrico "
                f"(SPZ), que sí admiten transmisiones múltiples."
            )

        perfil = solucion_fhp["perfil"]
        # Si la solución salió de un perfil MENOR que el que indican los umbrales, conviene
        # dejarlo dicho: es una decisión deliberada por régimen de giro, no un descuido.
        if DisenadorFHP.ORDEN_PERFILES.index(perfil) < indice_inicial:
            nota_menor = (
                f"El perfil {perfil} es menor que el que sugieren los umbrales de potencia "
                f"({DisenadorFHP.ORDEN_PERFILES[indice_inicial]}), pero a {rpm_peq:.0f} RPM "
                f"transmite más, porque en los perfiles mayores dominan las pérdidas por "
                f"flexión y fuerza centrífuga."
            )
            alerta_usuario_extra = nota_menor
        else:
            alerta_usuario_extra = ""
        dmin_perfil = solucion_fhp["dmin_perfil"]
        dmin_gobernante = solucion_fhp["dmin_gobernante"]
        D1_final, D2_final = solucion_fhp["D1_final"], solucion_fhp["D2_final"]
        D_peq_mm, D_gra_mm = solucion_fhp["D_peq"], solucion_fhp["D_grande"]
        geo = solucion_fhp["geo"]
        alerta_usuario = " ".join(
            x for x in (solucion_fhp["alerta_usuario"], alerta_usuario_extra,
                        aviso_factor_servicio) if x
        )

        c1 = c3 = 1.0
        p_nominal_banda_kw = p_corr_kw = solucion_fhp["capacidad_hp"] * KW_POR_HP
        n_bandas = 1
        # Se guarda el diámetro de PASO con que se evaluó la ecuación, para que la memoria
        # de cálculo muestre con qué valor se entró (d = d0 − 2a).
        de_consulta = a_primitivo(perfil, D_peq_mm)
        convencion_consulta = "paso"
        alerta_tabla = ""
    else:
        alerta_usuario = ""
        perfiles_familia = FAMILIAS_PERFILES.get(familia.upper(), ["SPZ"])
        perfil_inicial = seleccionar_perfil_por_curva_frontera(pd_kw_base, rpm_peq, familia, db)
        idx_inicial = perfiles_familia.index(perfil_inicial) if perfil_inicial in perfiles_familia else 0

        # Escalado real de perfil: si el perfil sugerido por la curva frontera no admite
        # solución (no hay tabla de capacidad, la longitud comercial no alcanza o harían
        # falta más correas de las que existen en stock), se prueba el siguiente de la
        # familia. Antes el lazo terminaba siempre en la primera iteración, de modo que
        # un perfil sin solución se devolvía como diseño válido o abortaba el cálculo.
        solucion = None
        perfiles_probados: List[str] = []
        motivos: List[str] = []
        for perfil_candidato in perfiles_familia[idx_inicial:]:
            perfiles_probados.append(perfil_candidato)
            try:
                solucion = intentar_perfil(perfil_candidato)
                break
            except ValueError as e:
                motivos.append(f"{perfil_candidato}: {e}")
                continue

        if solucion is None:
            detalle = "\n   • ".join(motivos) if motivos else "sin detalle"
            raise ValueError(
                f"Ningún perfil de la familia {familia.upper()} admite esta transmisión "
                f"({p_kw_base:.2f} kW, {n1:.0f} -> {n2:.0f} RPM).\n   • {detalle}"
            )

        perfil = solucion["perfil"]
        dmin_perfil = solucion["dmin_perfil"]
        dmin_gobernante = solucion["dmin_gobernante"]
        D1_final, D2_final = solucion["D1_final"], solucion["D2_final"]
        D_peq_mm, D_gra_mm = solucion["D_peq"], solucion["D_grande"]
        geo = solucion["geo"]
        c1, c3 = solucion["c1"], solucion["c3"]
        p_nominal_banda_kw = solucion["p_nom_kw"]
        p_corr_kw = solucion["p_corr_kw"]
        n_bandas = solucion["n_bandas"]
        de_consulta = solucion["diametro_tabla"]
        convencion_consulta = solucion["convencion"]
        alerta_tabla = solucion["aviso"]

    info_comercial = geo["info"]
    Lc = info_comercial["valor_comercial_mm"]
    C_final = geo["C_final"]
    C_preliminar = geo["C_preliminar"]
    Ld_teorico = geo["Ld_teorico"]
    ang = geo["ang"]
    aviso_centros = geo.get("aviso_centros", "")

    # La velocidad de la banda se calcula con el diámetro PRIMITIVO (o de paso) de la polea
    # pequeña, no con el exterior: en livianas d = d0 − 2a y en americanas dd = De − 2·offset.
    v = (np.pi * a_primitivo(perfil, D_peq_mm) * rpm_peq) / 60000

    # Referencias comerciales definitivas, ya con el número de canales real. Se formatean
    # a partir del diámetro comercial final, sin volver a convertirlo.
    ref_polea_1, alerta_p1 = referencia_comercial_polea(perfil, D1_final, n_bandas, familia)
    ref_polea_2, alerta_p2 = referencia_comercial_polea(perfil, D2_final, n_bandas, familia)
    if not normalizar_diametros:
        # Un diámetro fuera de la serie no tiene referencia de catálogo.
        ref_polea_1 = referencia_polea_a_medida(perfil, familia, D1_final, n_bandas, is_ing)
        ref_polea_2 = referencia_polea_a_medida(perfil, familia, D2_final, n_bandas, is_ing)

    # --- Tensiones en la correa -------------------------------------------------------
    # Se calcula POR BANDA y al final se escala al conjunto, porque la tensión centrífuga
    # es propia de cada correa: depende de su masa por unidad de longitud.
    #
    # Fuerza efectiva o tangencial, la que transmite la potencia:  Te = T1 − T2 = 1000·Pd/v
    te = (1000 * pd_kw_base) / v if v > 0 else 0.0
    te_banda = te / n_bandas if n_bandas else te

    # Tensión centrífuga:  Fc = m·v²,  con m la masa lineal de la correa (kg/m). La correa
    # que gira arrastra su propia masa contra las poleas, y esa tensión NO transmite
    # potencia: se suma a T1 y a T2 por igual y se descuenta de la pretensión de montaje.
    masa_lineal = obtener_masa_lineal_correa(perfil, db)
    fc_banda = masa_lineal * v ** 2

    # Relación de tensiones en el límite de fricción, con el coeficiente efectivo de una
    # correa trapezoidal (μ corregido por el ángulo de ranura). Con fuerza centrífuga:
    #     (T1 − Fc)/(T2 − Fc) = e^(μ'·θ)  =>  T1 = Te/(1 − e^(−μ'·θ)) + Fc
    angulo_rad = ang * np.pi / 180
    t1_banda = te_banda / (1 - np.exp(-0.5123 * angulo_rad)) + fc_banda
    t2_banda = t1_banda - te_banda
    # Pretensión de montaje (Shigley):  Ti = (T1 + T2)/2 − Fc. Es la tensión que se mide
    # con la transmisión detenida, cuando la fuerza centrífuga todavía no existe.
    ti_banda = (t1_banda + t2_banda) / 2 - fc_banda
    # Resultante sobre el eje: composición de las tensiones sobre el arco de contacto,
    # evaluada con la pretensión, que es la parte que realmente carga el eje.
    rad_banda = 2 * ti_banda * np.sin(ang * np.pi / 360)

    # Valores del conjunto de n_bandas correas.
    fc_total = fc_banda * n_bandas
    t1 = t1_banda * n_bandas
    t2 = t2_banda * n_bandas
    ts = ti_banda * n_bandas
    rad = rad_banda * n_bandas

    # La ranura se consulta ANTES que el ancho, porque el ancho toma e y f de ella.
    dim_ranura_1 = obtener_dimensiones_ranura(perfil, D1_final, db)
    dim_ranura_2 = obtener_dimensiones_ranura(perfil, D2_final, db)

    ancho_p1 = calcular_ancho_polea(perfil, n_bandas, dim_ranura_1)
    ancho_p2 = calcular_ancho_polea(perfil, n_bandas, dim_ranura_2)

    b1, ch1, d1_c1 = gestor_bujes.seleccionar_buje_y_chaveta(familia, D1_final, d_eje_1_mm)
    b2, ch2, d1_c2 = gestor_bujes.seleccionar_buje_y_chaveta(familia, D2_final, d_eje_2_mm)

    tipo_p1 = determinar_tipo_polea_real(perfil, n_bandas, D1_final)
    tipo_p2 = determinar_tipo_polea_real(perfil, n_bandas, D2_final)
    # El tipo por diámetro exterior no basta: si el cubo del buje no deja espacio radial
    # dentro de la llanta, no hay alma que aligerar ni brazos que poner.
    tipo_p1 = ajustar_tipo_por_espacio_cubo(tipo_p1, D1_final, d_eje_1_mm, d1_c1, dim_ranura_1)
    tipo_p2 = ajustar_tipo_por_espacio_cubo(tipo_p2, D2_final, d_eje_2_mm, d1_c2, dim_ranura_2)
    # En una polea MACIZA el cubo tiene que caber dentro de la llanta, así que el buje se
    # vuelve a escoger contra ese espacio: primero QD, luego Taper y, si ninguno entra,
    # montaje directo sobre el eje. En Tipo II y Tipo III se conserva la selección previa.
    d_int_1 = diametro_interior_llanta(D1_final, dim_ranura_1)
    d_int_2 = diametro_interior_llanta(D2_final, dim_ranura_2)
    if tipo_p1['tipo'] == "Tipo I" and d_eje_1_mm:
        b1, ch1, d1_c1 = gestor_bujes.seleccionar_buje_maciza(d_int_1, d_eje_1_mm, ancho_p1)
    if tipo_p2['tipo'] == "Tipo I" and d_eje_2_mm:
        b2, ch2, d1_c2 = gestor_bujes.seleccionar_buje_maciza(d_int_2, d_eje_2_mm, ancho_p2)

    str_p1 = f"{tipo_p1['tipo']} ({tipo_p1['descripcion']})"
    str_p2 = f"{tipo_p2['tipo']} ({tipo_p2['descripcion']})"

    det_const_1 = calcular_detalles_constructivos(tipo_p1['tipo'], D1_final, d_eje_1_mm, d1_c1,
                                                 dim_ranura_1, es_liviana=es_fhp)
    det_const_2 = calcular_detalles_constructivos(tipo_p2['tipo'], D2_final, d_eje_2_mm, d1_c2,
                                                 dim_ranura_2, es_liviana=es_fhp)

    cumple_estricto = (D_peq_mm >= (dmin_gobernante - 0.01))

    if len(perfiles_probados) > 1:
        descartados = ", ".join(perfiles_probados[:-1])
        nota_escalado = (f" Se escaló desde {descartados}, que no admitía solución.")
        alerta_tabla = (alerta_tabla + nota_escalado).strip()

    return ResultadosDiseno(
        potencia_nominal=p_kw_base,
        factor_servicio=ks,
        potencia_diseno=pd_kw_base,
        familia=familia,
        n1=n1,
        n2=n2,
        tipo_transmision_flujo=tipo_flujo,
        relacion_transmision=i,
        D1=D1_final,
        D2=D2_final,
        D_pequena=D_peq_mm,
        D_grande=D_gra_mm,
        perfil=perfil,
        dmin_motor=dmin_motor,
        dmin_perfil_req=dmin_perfil,
        dmin_gobernante=dmin_gobernante,
        cumple_dmin=cumple_estricto,
        distancia_ejes_preliminar=C_preliminar,
        longitud_teorica_ld=round(Ld_teorico, 2),
        longitud_comercial=Lc,
        tipo_longitud_comercial=info_comercial["tipo_longitud"],
        referencia_comercial_correa=info_comercial["referencia_comercial"],
        distancia_ejes_final=C_final,
        angulo_contacto_pequena_g=ang,
        factor_angulo_c1=c1,
        factor_longitud_c3=c3,
        potencia_corregida_banda=p_corr_kw,
        num_bandas_entero=n_bandas,
        velocidad_lineal=v,
        fuerza_efectiva_te=te,
        carga_dinamica_eje=rad,
        tension_t1=t1,
        tension_t2=t2,
        tension_t0=ts,
        ancho_polea_1=ancho_p1,
        ancho_polea_2=ancho_p2,
        buje_1=b1,
        chaveta_1=ch1,
        buje_2=b2,
        chaveta_2=ch2,
        d1_cubo_1=d1_c1,
        d1_cubo_2=d1_c2,
        diametro_fijo_usuario=is_fixed_diameter,
        distancia_fija_usuario=is_fixed_center,
        dim_ranura_1=dim_ranura_1,
        dim_ranura_2=dim_ranura_2,
        tipo_polea_1_str=str_p1,
        tipo_polea_2_str=str_p2,
        detalles_constructivos_1=det_const_1,
        detalles_constructivos_2=det_const_2,
        d_eje_1=d_eje_1_mm,
        d_eje_2=d_eje_2_mm,
        referencia_comercial_polea_1=ref_polea_1,
        referencia_comercial_polea_2=ref_polea_2,
        alerta_flexion_1=alerta_p1,
        alerta_flexion_2=alerta_p2,
        potencia_nominal_banda=p_nominal_banda_kw,
        diametro_exterior_consulta=de_consulta,
        convencion_diametro_consulta=convencion_consulta,
        alerta_tabla_potencia=alerta_tabla,
        aplica_criterio_nema=es_motor_electrico,
        alerta_diametro_usuario=alerta_usuario,
        modo_centros=("FIJO" if is_fixed_center else
                      "RANGO" if (modo_centros.upper() == "RANGO" and c_min_mm is not None
                                  and c_max_mm is not None) else "AUTOMATICO"),
        alerta_centros=aviso_centros,
        diametros_normalizados=bool(normalizar_diametros),
        tension_t1_banda=t1_banda,
        tension_t2_banda=t2_banda,
        tension_t0_banda=ti_banda,
        tension_centrifuga_banda=fc_banda,
        tension_centrifuga=fc_total,
        fuerza_efectiva_te_banda=te_banda,
        carga_dinamica_eje_banda=rad_banda,
        masa_lineal_correa=masa_lineal,
        capacidad_total_kw=p_corr_kw * n_bandas,
        factor_seguridad_potencia=(p_corr_kw * n_bandas / pd_kw_base) if pd_kw_base > 0 else 0.0,
        c_min_usuario=c_min_mm if (modo_centros.upper() == "RANGO" and not is_fixed_center) else None,
        c_max_usuario=c_max_mm if (modo_centros.upper() == "RANGO" and not is_fixed_center) else None
    )



def generar_informe_completo(res: ResultadosDiseno, is_ing: bool = False) -> str:
    p_m, p_d = res.potencia_nominal, res.potencia_diseno
    d1_mm, d2_mm = res.D1, res.D2
    dm_mot, dm_perf, dm = res.dmin_motor, res.dmin_perfil_req, res.dmin_gobernante
    lc, dc, rad = res.longitud_comercial, res.distancia_ejes_final, res.carga_dinamica_eje
    te = res.fuerza_efectiva_te
    t1, t2, t0 = res.tension_t1, res.tension_t2, res.tension_t0
    fc = res.tension_centrifuga
    te_b, t1_b, t2_b = res.fuerza_efectiva_te_banda, res.tension_t1_banda, res.tension_t2_banda
    t0_b, fc_b, rad_b = res.tension_t0_banda, res.tension_centrifuga_banda, res.carga_dinamica_eje_banda
    masa = res.masa_lineal_correa
    u_m = "kg/m"
    vel = res.velocidad_lineal
    w_p1, w_p2 = res.ancho_polea_1, res.ancho_polea_2
    p_corr = res.potencia_corregida_banda
    p_nom_banda = res.potencia_nominal_banda
    cap_total = res.capacidad_total_kw
    de_consulta = res.diametro_exterior_consulta

    d1_pulg = d1_mm / 25.4
    d2_pulg = d2_mm / 25.4

    u_p, u_d, u_f = "kW", "mm", "N"
    u_v = "m/s"

    def formatear_ranura(dim, is_ing):
        if not dim: return "Datos de ranura no disponibles en catálogo."
        def cvt(val):
            if is_ing:
                try: return float(val) / 25.4
                except: return val
            return val

        w = cvt(dim.get('W_dg', 0))
        b_val = cvt(dim.get('b', 0))
        h_val = cvt(dim.get('h', 0))
        e = cvt(dim.get('e_nominal', 0))
        f = cvt(dim.get('f_nominal', 0))
        ang = dim.get('Angulo_A_nominal', 0)
        g_val = cvt(dim.get('g', 0))
        t_ll = cvt(dim.get('espesor_llanta', 0))
        u_str = "pulg" if is_ing else "mm"

        return (f"A: {ang}° | W_dg: {w:.2f} | b: {b_val:.2f} | h: {h_val:.2f} | "
                f"e: {e:.2f} | f: {f:.2f} | g: {g_val:.2f} | t_llanta: {t_ll:.2f} [{u_str}]")

    def format_detalles(detalles, is_ing):
        if not detalles: return "   • No calculado."
        if "error" in detalles: return f"   • {detalles['error']}"

        conv = 1/25.4 if is_ing else 1.0
        u_str = "pulg" if is_ing else "mm"
        lineas = []
        for k, v in detalles.items():
            if k == "Tipo":
                lineas.append(f"   • {k}: {v}")
            elif k == "Número de brazos":
                # Es una cantidad, no una longitud: no se convierte ni lleva unidades.
                lineas.append(f"   • {k}: {int(v)}")
            elif isinstance(v, (int, float)):
                lineas.append(f"   • {k}: {v * conv:.2f} {u_str}")
            else:
                lineas.append(f"   • {k}: {v}")
        return "\n".join(lineas)

    str_ranura_1 = formatear_ranura(res.dim_ranura_1, is_ing)
    str_ranura_2 = formatear_ranura(res.dim_ranura_2, is_ing)
    str_detalles_1 = format_detalles(res.detalles_constructivos_1, is_ing)
    str_detalles_2 = format_detalles(res.detalles_constructivos_2, is_ing)

    d1_disp = d1_mm
    d2_disp = d2_mm
    de_disp = de_consulta
    if is_ing:
        p_m /= KW_POR_HP; p_d /= KW_POR_HP
        d1_disp /= 25.4; d2_disp /= 25.4
        de_disp /= 25.4
        dm_mot /= 25.4; dm_perf /= 25.4; dm /= 25.4
        lc /= 25.4; dc /= 25.4
        # Fuerzas: N -> lbf.  Velocidad: m/s -> ft/min, igual que en bandas planas.
        rad /= N_POR_LBF; te /= N_POR_LBF
        t1 /= N_POR_LBF; t2 /= N_POR_LBF; t0 /= N_POR_LBF; fc /= N_POR_LBF
        te_b /= N_POR_LBF; t1_b /= N_POR_LBF; t2_b /= N_POR_LBF
        t0_b /= N_POR_LBF; fc_b /= N_POR_LBF; rad_b /= N_POR_LBF
        masa *= LBFT_POR_KGM
        u_m = "lb/pie"
        vel *= MS_A_FTMIN
        w_p1 /= 25.4; w_p2 /= 25.4
        p_corr /= KW_POR_HP
        p_nom_banda /= KW_POR_HP
        cap_total /= KW_POR_HP
        u_p, u_d, u_f = "HP", "pulg", "lbf"
        u_v = "ft/min"

    if res.cumple_dmin:
        check = "✔ CUMPLE"
    elif res.diametro_fijo_usuario:
        check = f"❌ ALERTA: DIÁMETRO MUY PEQUEÑO (Mínimo recomendado: {dm:.2f} {u_d})"
    else:
        check = f"✔ SELECCIONADO AUTOMÁTICAMENTE SEGÚN MÍNIMO ({dm:.2f} {u_d})"

    if dm_mot <= 0:
        mot_str = "N/A"
    elif res.aplica_criterio_nema:
        mot_str = f"{dm_mot:.2f} {u_d} (NEMA, aplicado)"
    else:
        # Sin motor eléctrico el criterio no gobierna, pero se informa igual para que el
        # usuario tenga la referencia de qué exigiría un motor de esa potencia.
        mot_str = f"{dm_mot:.2f} {u_d} (NEMA, solo referencia)"
    # En los tres modos la distancia final sale de la longitud comercial; lo que cambia es
    # de dónde partió el cálculo. (Antes se comprobaba "RANGO" dentro del texto de un
    # número, condición que nunca se cumplía.)
    c_partida = res.distancia_ejes_preliminar / 25.4 if is_ing else res.distancia_ejes_preliminar
    if res.modo_centros == "FIJO":
        estado_centros = (f"(Recalculada con la longitud comercial; distancia ingresada: "
                          f"{c_partida:.2f} {u_d})")
    elif res.modo_centros == "RANGO":
        estado_centros = (f"(Recalculada con la longitud comercial; partió de la media del "
                          f"rango: {c_partida:.2f} {u_d})")
    else:
        estado_centros = "(Recalculada con la longitud comercial)"
    # El aviso se redacta aquí, y no se toma tal cual del núcleo, para que salga en las
    # mismas unidades que el resto del informe.
    linea_centros = ""
    if res.alerta_centros:
        f_u = (1 / 25.4) if is_ing else 1.0
        c_fin_u = res.distancia_ejes_final * f_u
        if res.modo_centros == "FIJO":
            linea_centros = (
                f"\n    • ADVERTENCIA: la longitud comercial no cierra en la distancia "
                f"ingresada; C pasa de {c_partida:.2f} a {c_fin_u:.2f} {u_d} "
                f"({c_fin_u - c_partida:+.2f} {u_d}). El montaje debe permitir ese "
                f"desplazamiento del eje."
            )
        elif res.modo_centros == "RANGO" and res.c_min_usuario is not None:
            linea_centros = (
                f"\n    • ADVERTENCIA: con la longitud comercial más cercana, C = "
                f"{c_fin_u:.2f} {u_d} queda fuera del rango indicado "
                f"({res.c_min_usuario * f_u:.2f}–{res.c_max_usuario * f_u:.2f} {u_d})."
            )
        else:
            linea_centros = f"\n    • ADVERTENCIA: {res.alerta_centros}"

    # La convención del diámetro depende del catálogo de cada bloque, así que se nombra
    # según lo que declare la hoja en vez de suponer que siempre es exterior.
    nombre_conv = "diám. primitivo" if res.convencion_diametro_consulta == "dd" else "diám. exterior"
    if res.convencion_diametro_consulta == "paso":
        # Perfiles livianos: la capacidad sale de la ecuación, evaluada con el diámetro de
        # paso d = d0 − 2a de la polea pequeña.
        linea_consulta = (f"    • Capacidad obtenida por ecuación FHP con el diámetro de paso "
                          f"d = d0 − 2a = {de_disp:.2f} {u_d} @ {max(res.n1, res.n2):.0f} RPM")
    else:
        linea_consulta = (f"    • Entrada a tabla de capacidad: {de_disp:.2f} {u_d} ({nombre_conv}) @ "
                          f"{max(res.n1, res.n2):.0f} RPM") if de_consulta > 0 else \
                     "    • Capacidad obtenida por ecuación FHP (no por tabla)"
    linea_alerta = f"\n    • {res.alerta_tabla_potencia}" if res.alerta_tabla_potencia else ""
    tipo_accionamiento = ("Motor eléctrico (se aplica el mínimo NEMA de eje)"
                          if res.aplica_criterio_nema
                          else "Distinto de motor eléctrico (el mínimo NEMA no se aplica)")
    linea_diam_usuario = (f"\n    • ADVERTENCIA: {res.alerta_diametro_usuario}"
                          if res.alerta_diametro_usuario else "")
    rotulo_d = "Comercial" if res.diametros_normalizados else "A medida"
    # La equivalencia en pulgadas solo aporta en sistema métrico; en inglés repetiría el valor.
    eq_d1 = "" if is_ing else f"  ({d1_pulg:.2f} pulg)"
    eq_d2 = "" if is_ing else f"  ({d2_pulg:.2f} pulg)"
    linea_normalizacion = ("" if res.diametros_normalizados else
                           f"\n    • NOTA: diámetros no normalizados por elección del usuario "
                           f"(fabricación a medida; redondeo a "
                           f"{'0,01 pulg' if is_ing else '1 mm'}).")

    return f"""
================================================================================
            MEMORIA DE CÁLCULO: TRANSMISIÓN POR CORREAS ({res.tipo_transmision_flujo})
================================================================================
1. PARÁMETROS OPERATIVOS
    • Potencia Motor: {p_m:.2f} {u_p} | Pd: {p_d:.2f} {u_p}
    • Factor de Servicio (Ks): {res.factor_servicio:.2f}
    • Velocidades: n1={res.n1:.0f} RPM -> n2={res.n2:.0f} RPM
    • Accionamiento: {tipo_accionamiento}

2. COMPONENTES Y PERFIL
    • Perfil Seleccionado: {res.perfil}
    • Referencia Comercial Correa: {res.referencia_comercial_correa}
    • Tipo de Longitud: {res.tipo_longitud_comercial}
    • D1 ({rotulo_d}): {d1_disp:.2f} {u_d}{eq_d1}  [{res.tipo_polea_1_str}]
      └─ Especificación: {res.referencia_comercial_polea_1}
    • D2 ({rotulo_d}): {d2_disp:.2f} {u_d}{eq_d2}  [{res.tipo_polea_2_str}]
      └─ Especificación: {res.referencia_comercial_polea_2}
    • Restricción Motor: {mot_str} | Restricción Perfil: {dm_perf:.2f} {u_d}
    • Diámetro Mínimo Gobernador ({dm:.2f} {u_d}): {check}{linea_diam_usuario}{linea_normalizacion}

3. GEOMETRÍA FINAL
    • Longitud Comercial: {lc:.2f} {u_d}
    • Distancia Centros: {dc:.2f} {u_d} {estado_centros}{linea_centros}
    • Ángulo de Contacto: {res.angulo_contacto_pequena_g:.1f}°

4. CAPACIDAD DE TRANSMISIÓN
{linea_consulta}{linea_alerta}
    • Potencia Nominal por Banda ({'ecuación FHP' if res.convencion_diametro_consulta == 'paso' else 'catálogo'}): {p_nom_banda:.2f} {u_p}
    • Factor por Arco de Contacto (C1): {res.factor_angulo_c1:.3f}
    • Factor por Longitud de Correa (C3): {res.factor_longitud_c3:.3f}
    • Potencia Corregida por Banda (Pn = P·C1·C3): {p_corr:.2f} {u_p}
    • Número de Correas: {res.num_bandas_entero}
    • Capacidad Total de la Transmisión (Pn · z): {cap_total:.2f} {u_p}
    • Factor de Seguridad por Potencia (Capacidad / Pd): {res.factor_seguridad_potencia:.2f}
    • Ancho Cara Polea 1 (Conductora): {w_p1:.2f} {u_d}
    • Ancho Cara Polea 2 (Conducida):  {w_p2:.2f} {u_d}

5. TENSIONES Y CARGA SOBRE LOS EJES
    • Velocidad Tangencial de la Correa: {vel:.2f} {u_v}
    • Masa Lineal de la Correa (catálogo): {masa:.3f} {u_m}
                                                  Por banda        Conjunto ({res.num_bandas_entero})
    • Tensión Centrífuga (Fc = m·v²):        {fc_b:>10.1f} {u_f}  {fc:>10.1f} {u_f}
    • Fuerza Efectiva / Tangencial (Te):     {te_b:>10.1f} {u_f}  {te:>10.1f} {u_f}
    • Tensión Lado Tenso (T1 = Te/(1-e^-μ'θ) + Fc):
                                             {t1_b:>10.1f} {u_f}  {t1:>10.1f} {u_f}
    • Tensión Lado Flojo (T2 = T1 - Te):     {t2_b:>10.1f} {u_f}  {t2:>10.1f} {u_f}
    • Pretensión de Montaje (Ti = (T1+T2)/2 - Fc):
                                             {t0_b:>10.1f} {u_f}  {t0:>10.1f} {u_f}
    • Fuerza Resultante sobre el Eje (2·Ti·sen(θ/2)):
                                             {rad_b:>10.1f} {u_f}  {rad:>10.1f} {u_f}

6. ACOPLAMIENTO MECÁNICO (BUJES Y CHAVETAS)
    • Eje Conductor (Motor):   Buje: {res.buje_1:<10} | Chaveta: {res.chaveta_1}
    • Eje Conducido (Máquina): Buje: {res.buje_2:<10} | Chaveta: {res.chaveta_2}

7. ESPECIFICACIONES DE LA RANURA (ISO/RMA)
    • Polea Conductora (D1): {str_ranura_1}
    • Polea Conducida (D2):  {str_ranura_2}

8. DETALLES CONSTRUCTIVOS DE POLEAS (MECANIZADO Y FUNDICIÓN)
  [Polea Conductora D1]:
{str_detalles_1}
  [Polea Conducida D2]:
{str_detalles_2}

9. ADVERTENCIAS DE FLEXIÓN Y SEGURIDAD MECÁNICA
    • Polea Conductora: {res.alerta_flexion_1 if res.alerta_flexion_1 else "Sin alertas de fatiga por flexión."}
    • Polea Conducida:  {res.alerta_flexion_2 if res.alerta_flexion_2 else "Sin alertas de fatiga por flexión."}
================================================================================
"""


def generar_planos_svg(res: ResultadosDiseno, ruta_plantilla: str, ruta_salida: str, is_ing: bool = False):
    if not os.path.exists(ruta_plantilla):
        print(f"   [⚠️ Alerta]: No se encontró la plantilla '{ruta_plantilla}'. Se omitió este plano.")
        return

    with open(ruta_plantilla, 'r', encoding='utf-8') as f:
        svg_content = f.read()

    conv = 1/25.4 if is_ing else 1.0

    def fmt(val):
        if val is None: return "N/A"
        if isinstance(val, (int, float)): return f"{val:.2f}"
        return str(val)

    def c_dim(dim_dict, key):
        if not dim_dict or key not in dim_dict: return "N/A"
        val = dim_dict[key]
        if is_ing and isinstance(val, (int, float)) and key != "Angulo_A_nominal" and not "Angulo" in key:
            return f"{val * conv:.3f}"
        if isinstance(val, (int, float)):
            return f"{val:.2f}"
        return str(val)

    reemplazos = {
        "VAR_D1": fmt(res.D1 * conv),
        "VAR_D2": fmt(res.D2 * conv),
        "VAR_RPM1": fmt(res.n1),
        "VAR_RPM2": fmt(res.n2),
        "VAR_C": fmt(res.distancia_ejes_final * conv),
        "VAR_LC": fmt(res.longitud_comercial * conv),
        "VAR_ANG1": fmt(res.angulo_contacto_pequena_g),
        "VAR_ANG2": fmt(360.0 - res.angulo_contacto_pequena_g),
        "VAR_N_RANURAS": str(res.num_bandas_entero),
        "VAR_ANCHO_POLEA1": fmt(res.ancho_polea_1 * conv),
        "VAR_ANCHO_POLEA2": fmt(res.ancho_polea_2 * conv),
        "VAR_D_EJE1": fmt(res.d_eje_1 * conv if res.d_eje_1 else None),
        "VAR_D_EJE2": fmt(res.d_eje_2 * conv if res.d_eje_2 else None),

        # Polea 1
        "VAR_ANG_A1": c_dim(res.dim_ranura_1, "Angulo_A_nominal"),
        "VAR_W_DG1": c_dim(res.dim_ranura_1, "W_dg"),
        "VAR_E1": c_dim(res.dim_ranura_1, "e_nominal"),
        "VAR_F1": c_dim(res.dim_ranura_1, "f_nominal"),
        "VAR_B1": c_dim(res.dim_ranura_1, "b"),
        "VAR_H1": c_dim(res.dim_ranura_1, "h"),
        "VAR_G1": c_dim(res.dim_ranura_1, "g"),
        "VAR_T_LLANTA1": c_dim(res.dim_ranura_1, "espesor_llanta"),

        # Polea 2
        "VAR_ANG_A2": c_dim(res.dim_ranura_2, "Angulo_A_nominal"),
        "VAR_W_DG2": c_dim(res.dim_ranura_2, "W_dg"),
        "VAR_E2": c_dim(res.dim_ranura_2, "e_nominal"),
        "VAR_F2": c_dim(res.dim_ranura_2, "f_nominal"),
        "VAR_B2": c_dim(res.dim_ranura_2, "b"),
        "VAR_H2": c_dim(res.dim_ranura_2, "h"),
        "VAR_G2": c_dim(res.dim_ranura_2, "g"),
        "VAR_T_LLANTA2": c_dim(res.dim_ranura_2, "espesor_llanta")
    }

    if res.detalles_constructivos_1:
        d_c1 = res.detalles_constructivos_1
        reemplazos.update({
            "VAR_D_CP1": fmt(d_c1.get("D_cp (Diam. Circunf. Agujeros)") * conv if isinstance(d_c1.get("D_cp (Diam. Circunf. Agujeros)"), (int, float)) else None),
            "VAR_D_AG1": fmt(d_c1.get("d_ag (Diam. Agujero Aligeramiento)") * conv if isinstance(d_c1.get("d_ag (Diam. Agujero Aligeramiento)"), (int, float)) else None),
            "VAR_Z1": fmt(d_c1.get("z (Espesor del alma)") * conv if isinstance(d_c1.get("z (Espesor del alma)"), (int, float)) else None),
            "VAR_H_BR1": fmt(d_c1.get("h (Ancho brazo en base)") * conv if isinstance(d_c1.get("h (Ancho brazo en base)"), (int, float)) else None),
            "VAR_A_BR1": fmt(d_c1.get("a (Espesor brazo en base)") * conv if isinstance(d_c1.get("a (Espesor brazo en base)"), (int, float)) else None),
            "VAR_H_BR_COR1": fmt(d_c1.get("h' (Ancho brazo en corona)") * conv if isinstance(d_c1.get("h' (Ancho brazo en corona)"), (int, float)) else None),
            "VAR_A_BR_COR1": fmt(d_c1.get("a' (Espesor brazo en corona)") * conv if isinstance(d_c1.get("a' (Espesor brazo en corona)"), (int, float)) else None),
            "VAR_L_BUJE1": fmt(d_c1.get("l_buje") * conv if isinstance(d_c1.get("l_buje"), (int, float)) else None),
            "VAR_M_BUJE1": fmt(d_c1.get("m_buje") * conv if isinstance(d_c1.get("m_buje"), (int, float)) else None),
            "VAR_D_EJE1": fmt(d_c1.get("d_eje") * conv if isinstance(d_c1.get("d_eje"), (int, float)) else None)
        })

    if res.detalles_constructivos_2:
        d_c2 = res.detalles_constructivos_2
        reemplazos.update({
            "VAR_D_CP2": fmt(d_c2.get("D_cp (Diam. Circunf. Agujeros)") * conv if isinstance(d_c2.get("D_cp (Diam. Circunf. Agujeros)"), (int, float)) else None),
            "VAR_D_AG2": fmt(d_c2.get("d_ag (Diam. Agujero Aligeramiento)") * conv if isinstance(d_c2.get("d_ag (Diam. Agujero Aligeramiento)"), (int, float)) else None),
            "VAR_Z2": fmt(d_c2.get("z (Espesor del alma)") * conv if isinstance(d_c2.get("z (Espesor del alma)"), (int, float)) else None),
            "VAR_H_BR2": fmt(d_c2.get("h (Ancho brazo en base)") * conv if isinstance(d_c2.get("h (Ancho brazo en base)"), (int, float)) else None),
            "VAR_A_BR2": fmt(d_c2.get("a (Espesor brazo en base)") * conv if isinstance(d_c2.get("a (Espesor brazo en base)"), (int, float)) else None),
            "VAR_H_BR_COR2": fmt(d_c2.get("h' (Ancho brazo en corona)") * conv if isinstance(d_c2.get("h' (Ancho brazo en corona)"), (int, float)) else None),
            "VAR_A_BR_COR2": fmt(d_c2.get("a' (Espesor brazo en corona)") * conv if isinstance(d_c2.get("a' (Espesor brazo en corona)"), (int, float)) else None),
            "VAR_L_BUJE2": fmt(d_c2.get("l_buje") * conv if isinstance(d_c2.get("l_buje"), (int, float)) else None),
            "VAR_M_BUJE2": fmt(d_c2.get("m_buje") * conv if isinstance(d_c2.get("m_buje"), (int, float)) else None),
            "VAR_D_EJE2": fmt(d_c2.get("d_eje") * conv if isinstance(d_c2.get("d_eje"), (int, float)) else None)
        })

    for clave, valor in reemplazos.items():
        svg_content = svg_content.replace(clave, str(valor))

    with open(ruta_salida, 'w', encoding='utf-8') as f:
        f.write(svg_content)

    print(f"   [✔] Plano renderizado: {ruta_salida}")


def exportar_planos_completos(res: ResultadosDiseno, is_ing: bool = False):
    print("\n===============================================================================")
    print("                RENDERIZADO DE PLANOS DE FABRICACIÓN (SVG)                 ")
    print("===============================================================================")

    d1 = res.D1
    d2 = res.D2
    caso = 1

    if abs(d1 - d2) < 0.1: caso = 1
    elif d1 < d2 and d1 > 0.65 * d2: caso = 2
    elif d1 <= 0.65 * d2: caso = 3
    elif d2 <= 0.65 * d1: caso = 4
    elif d2 < d1 and d2 > 0.65 * d1: caso = 5

    print(f"[*] Seleccionando plantilla de transmisión (Caso {caso})...")
    generar_planos_svg(res, f"Transmisión - caso {caso}.svg", "Plano_Transmision.svg", is_ing)

    def extr_tipo(tipo_str):
        if "Tipo I" in tipo_str and "Tipo II" not in tipo_str and "Tipo III" not in tipo_str: return 1
        elif "Tipo II" in tipo_str and "Tipo III" not in tipo_str: return 2
        elif "Tipo III" in tipo_str: return 3
        return 1

    t1 = extr_tipo(res.tipo_polea_1_str)
    print(f"[*] Seleccionando plantilla Polea Conductora (Tipo {t1})...")
    generar_planos_svg(res, f"Polea en V tipo {t1}.svg", "Plano_Polea_Conductora.svg", is_ing)

    t2 = extr_tipo(res.tipo_polea_2_str)
    print(f"[*] Seleccionando plantilla Polea Conducida (Tipo {t2})...")
    generar_planos_svg(res, f"Polea en V tipo {t2}.svg", "Plano_Polea_Conducida.svg", is_ing)
