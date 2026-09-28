import os
import re
from typing import List, Optional

import numpy as np

# Importación segura para entornos de consola o Jupyter
try:
    from IPython.display import SVG, display
    import ipywidgets as widgets
    EN_JUPYTER = True
except ImportError:
    EN_JUPYTER = False
    def display(*args, **kwargs): pass
    class SVG:
        def __init__(self, data): pass


# Palabras que, dentro del nombre de un marcador desconocido, indican que lo que pide es
# el número de canales de la polea. Las plantillas no siempre lo nombran igual
# (VAR_N_RANURAS, VAR_RANURAS, VAR_NUM_CANALES, VAR_N_BANDAS...), y dejar el dibujo con un
# guion por una diferencia de nomenclatura es peor que resolverlo por el significado.
_PALABRAS_NUMERO_CANALES = ("RANURA", "CANAL", "BANDA", "CORREA")

# Para el número de brazos hay que ser más selectivo: "VAR_A_BRAZO" y "VAR_H_BRAZO2" son
# COTAS del brazo, no su cantidad. Por eso se exige que el nombre mencione el brazo Y una
# palabra de conteo. Así "VAR_NUMERO_BRAZOS" se resuelve y "VAR_A_BRAZO_CORONA" no.
_PALABRA_BRAZO = "BRAZO"
_PALABRAS_CONTEO = ("NUM", "NÚM", "NRO", "CANT", "TOTAL", "_N_", "_Z_")


def pide_numero_de_brazos(marcador: str) -> bool:
    """Indica si un marcador desconocido está pidiendo la CANTIDAD de brazos."""
    if _PALABRA_BRAZO not in marcador:
        return False
    if any(p in marcador for p in _PALABRAS_CONTEO):
        return True
    # Casos como VAR_N_BRAZOS o VAR_NBRAZOS, donde la N va pegada al inicio del nombre.
    return bool(re.match(r"^VAR_N_?BRAZOS?$", marcador))


# ---------------------------------------------------------------------------
# COLOCACIÓN DEL TEXTO DE LAS COTAS
# ---------------------------------------------------------------------------
# Las plantillas se hicieron abriendo el plano original en Inkscape y escribiendo el
# marcador ENCIMA del número que había. Al editar un texto, Inkscape conserva su atributo x
# y su anclaje al inicio, de modo que el marcador arranca exactamente donde arrancaba el
# número. Por eso el valor que lo sustituye cae solo en su sitio y NO hay que recolocarlo:
# lo que se ve largo y descuadrado es el marcador dentro de la plantilla, no el plano
# terminado.
#
# Una versión anterior de este módulo recentraba cada cota sobre el centro del marcador.
# Eso parte de suponer que el dibujante colocó el marcador centrado sobre la línea de cota,
# y en estas plantillas no es así: la mayoría de las cotas son llamadas con línea de
# referencia y el texto pegado a su extremo. Recentrarlas las corría media anchura de
# marcador hacia la derecha y las despegaba de su línea. Se comprobó dibujando la plantilla
# y el plano terminado y comparándolos, y se retiró.
#
# Lo que sí hay que arreglar es el atributo dx, y de eso se ocupa _dividir_por_dx.

# Anchos de avance de cada carácter, en milésimas de em. Hacen falta para reconstruir la
# posición de cada letra en los textos que traen dx. Se extrajeron de las fuentes reales:
# Liberation Sans (métricamente idéntica a Arial y Helvetica) y DejaVu Sans.
_ANCHOS_ARIAL = {
    'A': 667, 'B': 667, 'C': 722, 'D': 722, 'E': 667, 'F': 611, 'G': 778, 'H': 722,
    'I': 278, 'J': 500, 'K': 667, 'L': 556, 'M': 833, 'N': 722, 'O': 778, 'P': 667,
    'Q': 778, 'R': 722, 'S': 667, 'T': 611, 'U': 722, 'V': 667, 'W': 944, 'X': 667,
    'Y': 667, 'Z': 611, 'a': 556, 'b': 556, 'c': 500, 'd': 556, 'e': 556, 'f': 278,
    'g': 556, 'h': 556, 'i': 222, 'j': 222, 'k': 500, 'l': 222, 'm': 833, 'n': 556,
    'o': 556, 'p': 556, 'q': 556, 'r': 333, 's': 500, 't': 278, 'u': 556, 'v': 500,
    'w': 722, 'x': 500, 'y': 500, 'z': 500, '0': 556, '1': 556, '2': 556, '3': 556,
    '4': 556, '5': 556, '6': 556, '7': 556, '8': 556, '9': 556, ' ': 278, '.': 278,
    ',': 278, '-': 333, '_': 556, '/': 278, '(': 333, ')': 333, ':': 278, '=': 584,
    '%': 889, "'": 191, '"': 355, '+': 584, '*': 389, '#': 556, '&': 667, '?': 556,
    '!': 278, ';': 278, '[': 278, ']': 278, '{': 334, '}': 334, '<': 584, '>': 584,
    '|': 260, '@': 1015, '$': 556, '~': 584, '^': 469, '`': 333, '\\': 278, '°': 400,
    'Ø': 778, 'Á': 667, 'É': 667, 'Í': 278, 'Ó': 778, 'Ú': 722, 'Ñ': 722, 'á': 556,
    'é': 556, 'í': 278, 'ó': 556, 'ú': 556, 'ñ': 556, 'Ü': 722, 'ü': 556, '×': 584,
    '±': 549, 'º': 365, 'ª': 370,
}

_ANCHOS_DEJAVU = {
    'A': 684, 'B': 686, 'C': 698, 'D': 770, 'E': 632, 'F': 575, 'G': 775, 'H': 752,
    'I': 295, 'J': 295, 'K': 656, 'L': 557, 'M': 863, 'N': 748, 'O': 787, 'P': 603,
    'Q': 787, 'R': 695, 'S': 635, 'T': 611, 'U': 732, 'V': 684, 'W': 989, 'X': 685,
    'Y': 611, 'Z': 685, 'a': 613, 'b': 635, 'c': 550, 'd': 635, 'e': 615, 'f': 352,
    'g': 635, 'h': 634, 'i': 278, 'j': 278, 'k': 579, 'l': 278, 'm': 974, 'n': 634,
    'o': 612, 'p': 635, 'q': 635, 'r': 411, 's': 521, 't': 392, 'u': 634, 'v': 592,
    'w': 818, 'x': 592, 'y': 592, 'z': 525, '0': 636, '1': 636, '2': 636, '3': 636,
    '4': 636, '5': 636, '6': 636, '7': 636, '8': 636, '9': 636, ' ': 318, '.': 318,
    ',': 318, '-': 361, '_': 500, '/': 337, '(': 390, ')': 390, ':': 337, '=': 838,
    '%': 950, "'": 275, '"': 460, '+': 838, '*': 500, '#': 838, '&': 780, '?': 531,
    '!': 401, ';': 337, '[': 390, ']': 390, '{': 636, '}': 636, '<': 838, '>': 838,
    '|': 337, '@': 1000, '$': 636, '~': 838, '^': 838, '`': 500, '\\': 337, '°': 500,
    'Ø': 787, 'Á': 684, 'É': 632, 'Í': 295, 'Ó': 787, 'Ú': 732, 'Ñ': 748, 'á': 613,
    'é': 615, 'í': 278, 'ó': 612, 'ú': 634, 'ñ': 634, 'Ü': 732, 'ü': 634, '×': 838,
    '±': 838, 'º': 471, 'ª': 471,
}

# Century Gothic, que es la familia con la que están rotuladas las plantillas de este
# trabajo. Los valores son los de ITC Avant Garde Gothic Book, porque Century Gothic se
# dibujó precisamente para igualar los anchos de esa familia, de modo que un documento
# hecho con una se puede mostrar con la otra sin que cambie el ajuste del texto
# (WIKIPEDIA, 2025). Se tomaron del archivo de métricas de URW Gothic Book, el clon libre
# de ITC Avant Garde Gothic distribuido con Ghostscript (ARTIFEX SOFTWARE, 2024).
# Usar esta tabla y no la de Arial importa: en Century Gothic la caja baja es bastante más
# ancha, y medir " VAR_ANCHO_POLEA " con la tabla equivocada deja la cota varios píxeles
# descentrada.
_ANCHOS_CENTURY_GOTHIC = {
    'A': 740, 'B': 574, 'C': 813, 'D': 744, 'E': 536, 'F': 485, 'G': 872, 'H': 683,
    'I': 226, 'J': 482, 'K': 591, 'L': 462, 'M': 919, 'N': 740, 'O': 869, 'P': 592,
    'Q': 871, 'R': 607, 'S': 498, 'T': 426, 'U': 655, 'V': 702, 'W': 960, 'X': 609,
    'Y': 592, 'Z': 480, 'a': 683, 'b': 682, 'c': 647, 'd': 685, 'e': 650, 'f': 314,
    'g': 673, 'h': 610, 'i': 200, 'j': 203, 'k': 502, 'l': 200, 'm': 938, 'n': 610,
    'o': 655, 'p': 682, 'q': 682, 'r': 301, 's': 388, 't': 339, 'u': 608, 'v': 554,
    'w': 831, 'x': 480, 'y': 536, 'z': 425, '0': 554, '1': 554, '2': 554, '3': 554,
    '4': 554, '5': 554, '6': 554, '7': 554, '8': 554, '9': 554, ' ': 277, '.': 277,
    ',': 277, '-': 332, '_': 500, '/': 437, '(': 369, ')': 369, ':': 277, '=': 606,
    '%': 775, "'": 198, '"': 309, '+': 606, '*': 425, '#': 554, '&': 757, '?': 591,
    '!': 295, ';': 277, '[': 351, ']': 351, '{': 351, '}': 351, '<': 606, '>': 606,
    '|': 672, '@': 867, '$': 554, '~': 606, '^': 606, '`': 351, '\\': 605, '°': 400,
    'Ø': 869, 'Á': 740, 'É': 536, 'Í': 226, 'Ó': 869, 'Ú': 655, 'Ñ': 740, 'á': 683,
    'é': 650, 'í': 200, 'ó': 655, 'ú': 608, 'ñ': 610, 'Ü': 655, 'ü': 608, '×': 606,
    '±': 606, 'º': 369, 'ª': 369, 'θ': 655,
}

_PATRON_MARCADOR = re.compile(r"VAR_[A-ZÁÉÍÓÚÑ0-9_]+")

# La etiqueta de apertura se reconoce exigiendo que NO termine en "/>", para no confundir
# un elemento vacío <text/> con el inicio de un bloque: si se confundiera, el cuerpo
# capturado llegaría hasta el </text> del elemento siguiente y se reescribiría el que no es.
_PATRON_TEXT = r"(<text\b(?:[^>]*[^/>])?>)(.*?)(</text>)"
_PATRON_TSPAN = r"(<tspan\b(?:[^>]*[^/>])?>)(.*?)(</tspan>)"
_TAMANO_LETRA_POR_DEFECTO = 12.0


def _tabla_anchos(familia: str):
    """Elige la tabla de anchos según la familia tipográfica declarada en la plantilla.

    El nombre puede venir entrecomillado y con alternativas separadas por comas, como lo
    escribe Inkscape: font-family:'Century Gothic'. Se mira el nombre completo, de modo que
    basta con que la familia real aparezca en la lista.
    """
    f = (familia or "").lower().replace("'", "").replace('"', "")
    if "century gothic" in f or "avant garde" in f or "urw gothic" in f \
            or "twentieth century" in f:
        return _ANCHOS_CENTURY_GOTHIC, 554
    if "dejavu" in f or "verdana" in f or "bitstream vera" in f:
        return _ANCHOS_DEJAVU, 636
    return _ANCHOS_ARIAL, 556


def _ancho_texto(texto: str, tamano_letra: float, familia: str = "", peso: str = "") -> float:
    """Ancho que ocupa una cadena, en unidades de usuario del SVG."""
    tabla, por_defecto = _tabla_anchos(familia)
    milesimas = sum(tabla.get(c, por_defecto) for c in texto)
    ancho = milesimas / 1000.0 * tamano_letra
    p = (peso or "").lower()
    if "bold" in p or (p.isdigit() and int(p) >= 600):
        ancho *= 1.03
    return ancho


def _leer_atributo(etiqueta: str, nombre: str) -> Optional[str]:
    """Lee un atributo de la etiqueta de apertura, con comillas dobles o simples."""
    for patron in (rf'\b{nombre}\s*=\s*"([^"]*)"', rf"\b{nombre}\s*=\s*'([^']*)'"):
        m = re.search(patron, etiqueta)
        if m:
            return m.group(1)
    return None


def _leer_propiedad_estilo(etiqueta: str, propiedad: str) -> Optional[str]:
    estilo = _leer_atributo(etiqueta, "style") or ""
    m = re.search(rf'(?:^|;)\s*{propiedad}\s*:\s*([^;]+)', estilo)
    return m.group(1).strip() if m else None


def _propiedad(etiqueta: str, nombre: str) -> Optional[str]:
    """Valor de una propiedad, que puede venir en el atributo style o como atributo suelto.

    El style tiene prioridad, porque es así como lo resuelve el renderizador.
    """
    return _leer_propiedad_estilo(etiqueta, nombre) or _leer_atributo(etiqueta, nombre)


def _tamano_letra(etiqueta: str, heredado: float) -> float:
    """Convierte el font-size de la etiqueta a unidades de usuario.

    Si no se declara, o viene en unidades relativas (em, %), se conserva el valor heredado
    del elemento padre.
    """
    bruto = _propiedad(etiqueta, "font-size")
    if not bruto:
        return heredado
    m = re.match(r"\s*(-?[\d.]+)\s*([a-z%]*)", bruto.strip())
    if not m:
        return heredado
    try:
        valor = float(m.group(1))
    except ValueError:
        return heredado
    unidad = m.group(2)
    factores = {"": 1.0, "px": 1.0, "pt": 96.0 / 72.0, "pc": 16.0,
                "mm": 96.0 / 25.4, "cm": 96.0 / 2.54, "in": 96.0}
    if unidad not in factores or valor <= 0:
        return heredado
    return valor * factores[unidad]


def _anclaje(etiqueta: str, heredado: str) -> str:
    valor = _propiedad(etiqueta, "text-anchor")
    return (valor or heredado).strip().lower()


def _escribir_atributo(etiqueta: str, nombre: str, valor: str) -> str:
    """Sustituye el atributo si existe y lo añade si no, conservando el resto intacto."""
    for patron in (rf'(\b{nombre}\s*=\s*")[^"]*(")', rf"(\b{nombre}\s*=\s*')[^']*(')"):
        nueva, n = re.subn(patron, lambda m: m.group(1) + valor + m.group(2), etiqueta, count=1)
        if n:
            return nueva
    cierre = "/>" if etiqueta.rstrip().endswith("/>") else ">"
    cuerpo = etiqueta.rstrip()[:-len(cierre)].rstrip()
    return f'{cuerpo} {nombre}="{valor}"{cierre}'


def _texto_plano(cuerpo: str, conservar_espacios: bool) -> str:
    """Texto que se dibuja realmente: sin etiquetas internas y con el espaciado del SVG."""
    plano = re.sub(r"<[^>]*>", "", cuerpo)
    plano = plano.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    if conservar_espacios:
        return plano
    return re.sub(r"\s+", " ", plano).strip()


def _borrar_atributo(etiqueta: str, nombre: str) -> str:
    """Quita un atributo de la etiqueta de apertura, si está."""
    for patron in (rf'\s*\b{nombre}\s*=\s*"[^"]*"', rf"\s*\b{nombre}\s*=\s*'[^']*'"):
        nueva, n = re.subn(patron, "", etiqueta, count=1)
        if n:
            return nueva
    return etiqueta


def _formatear_numero(valor: float) -> str:
    """Seis decimales: las plantillas escriben las posiciones con esa precisión y truncarlas
    movería la cota unas centésimas de milésima. No se ve, pero ensucia la comprobación."""
    return f"{valor:.6f}".rstrip("0").rstrip(".") or "0"


def _dividir_por_dx(apertura: str, texto: str, cierre: str, tamano_letra: float,
                    familia: str, peso: str, conservar_espacios: bool, avisos: dict) -> Optional[str]:
    """Parte en varios <tspan> un texto cuyas letras se posicionan con el atributo dx.

    Cuando una plantilla se importa desde un PDF, Inkscape puede fundir en un mismo tspan
    dos cotas que en el dibujo original eran textos separados, y mantenerlas apartadas con
    un salto grande dentro del atributo dx, que da un desplazamiento POR CARÁCTER:

        texto : " VAR_A_BRAZO  VAR_H_BRAZO2 "   (27 caracteres)
        dx    : 0 0 0 0 0 0 0 0 0 0 0 0 0 182.57712

    Eso no sobrevive a la sustitución. Al cambiar los marcadores por los valores el texto
    se acorta a la mitad, el salto deja de caer sobre la letra a la que correspondía y las
    dos cotas acaban una pegada a la otra, con la segunda a cientos de píxeles de su sitio.

    La solución es deshacer el apaño ANTES de sustituir: se calcula la posición absoluta de
    cada letra con los anchos de la fuente, se corta el texto allí donde hay un salto, y
    cada tramo se escribe como su propio <tspan> con su x absoluta y sin dx. Cada tramo
    conserva exactamente el sitio que ocupaba en la plantilla; no se recoloca nada.

    Devuelve None si el texto no se puede tratar con seguridad, para que el llamador lo deje
    como está en vez de descolocarlo de otra manera.
    """
    if texto != _texto_plano(texto, conservar_espacios):
        # Hay etiquetas anidadas o el espaciado se colapsa: los índices del dx dejarían de
        # corresponder con las letras que se dibujan.
        return None
    x_bruto = _leer_atributo(apertura, "x")
    dx_bruto = _leer_atributo(apertura, "dx")
    if x_bruto is None or dx_bruto is None:
        return None
    try:
        x0 = float(x_bruto)
        dx = [float(v) for v in re.split(r"[\s,]+", dx_bruto.strip()) if v]
    except ValueError:
        return None

    # El dx puede traer menos valores que letras: las restantes no llevan desplazamiento.
    dx = (dx + [0.0] * len(texto))[:len(texto)]

    # Posición absoluta de cada letra, acumulando desplazamiento y avance.
    posiciones, cursor = [], x0
    for i, caracter in enumerate(texto):
        cursor += dx[i]
        posiciones.append(cursor)
        cursor += _ancho_texto(caracter, tamano_letra, familia, peso)

    cortes = [0] + [i for i in range(1, len(texto)) if abs(dx[i]) > 1e-9]
    if len(cortes) < 2:
        return None  # un solo tramo: no hay nada que separar

    base = _borrar_atributo(_borrar_atributo(apertura, "dx"), "id")
    id_original = _leer_atributo(apertura, "id")
    piezas = []
    for n, inicio in enumerate(cortes):
        fin = cortes[n + 1] if n + 1 < len(cortes) else len(texto)
        tramo = texto[inicio:fin]
        # El primer tramo arranca justo en la x de la plantilla: se conserva su texto tal
        # cual, para no introducir ni el error del redondeo al reescribirla.
        x_tramo = x_bruto if inicio == 0 else _formatear_numero(posiciones[inicio])
        etiqueta = _escribir_atributo(base, "x", x_tramo)
        if id_original:
            etiqueta = _escribir_atributo(etiqueta, "id", f"{id_original}-{n + 1}")
        piezas.append(etiqueta + tramo + cierre)
    avisos.setdefault("separados", []).append(id_original or "tspan con dx")
    return "".join(piezas)


def separar_cotas_fundidas(svg_content: str, nombre_plantilla: str = "") -> str:
    """Separa en tspans independientes las cotas que la plantilla trae fundidas con dx.

    Es la única corrección de posición que se hace sobre la plantilla. El resto del texto no
    se toca: su x ya es la del número original del plano (ver la nota de cabecera).
    """
    avisos: dict = {}

    def procesar_text(coincidencia) -> str:
        apertura, cuerpo, cierre = coincidencia.group(1), coincidencia.group(2), coincidencia.group(3)
        if "VAR_" not in cuerpo or "dx" not in cuerpo:
            return coincidencia.group(0)

        tamano_padre = _tamano_letra(apertura, _TAMANO_LETRA_POR_DEFECTO)
        espacios_padre = (_leer_atributo(apertura, "xml:space") or "") == "preserve"
        familia_padre = _propiedad(apertura, "font-family") or ""
        peso_padre = _propiedad(apertura, "font-weight") or ""

        nuevo_cuerpo = cuerpo
        # De atrás hacia adelante, para que las posiciones ya localizadas sigan siendo
        # válidas mientras se reescribe el cuerpo.
        for t in reversed(list(re.finditer(_PATRON_TSPAN, cuerpo, re.S))):
            if _leer_atributo(t.group(1), "dx") is None:
                continue
            if not _PATRON_MARCADOR.search(t.group(2)):
                continue
            if _anclaje(t.group(1), _anclaje(apertura, "start")) != "start":
                continue
            espacios = espacios_padre or (_leer_atributo(t.group(1), "xml:space") or "") == "preserve"
            nuevo = _dividir_por_dx(
                t.group(1), t.group(2), t.group(3),
                _tamano_letra(t.group(1), tamano_padre),
                _propiedad(t.group(1), "font-family") or familia_padre,
                _propiedad(t.group(1), "font-weight") or peso_padre,
                espacios, avisos)
            if nuevo is not None:
                nuevo_cuerpo = nuevo_cuerpo[:t.start(0)] + nuevo + nuevo_cuerpo[t.end(0):]
        return apertura + nuevo_cuerpo + cierre

    resultado = re.sub(_PATRON_TEXT, procesar_text, svg_content, flags=re.S)

    separados = avisos.get("separados", [])
    if separados:
        origen = f" en '{nombre_plantilla}'" if nombre_plantilla else ""
        print(f"   [i] Cotas fundidas separadas{origen}: {', '.join(sorted(set(separados)))}")
    return resultado


def aplicar_reemplazos(svg_content: str, reemplazos: dict, nombre_plantilla: str = "",
                       numero_canales: Optional[int] = None,
                       numero_brazos: Optional[int] = None) -> str:
    """Sustituye los marcadores VAR_ de una plantilla y avisa de los que queden sueltos.

    La sustitución se hace por TOKEN COMPLETO, con una sola pasada de expresión regular,
    y no encadenando reemplazos de texto. Encadenar reemplazos hace que una clave corta se
    coma el prefijo de un nombre más largo: "VAR_H" dejaba "12.34_BRAZO" donde la
    plantilla decía "VAR_H_BRAZO", y "VAR_Z" dejaba "14.75_RANURAS" donde decía
    "VAR_Z_RANURAS". Ordenar las claves de mayor a menor longitud resuelve el choque entre
    claves conocidas, pero no frente a un marcador desconocido, porque ese no está en la
    lista. Capturando el nombre entero el problema desaparece de raíz.

    MARCADORES DESCONOCIDOS: si el nombre menciona ranuras, canales, bandas o correas se
    resuelve con el número de canales, porque es lo único que puede estar pidiendo; las
    plantillas no siempre lo nombran igual. El resto se sustituye por un guion, para no
    imprimir "VAR_LOQUESEA" sobre el dibujo. En ambos casos se informa por consola con el
    nombre exacto, para poder incorporarlo después.
    """
    resueltos: set = set()
    sin_valor: set = set()

    def valor_de(nombre: str) -> str:
        if nombre in reemplazos:
            return str(reemplazos[nombre])
        if numero_brazos is not None and pide_numero_de_brazos(nombre):
            resueltos.add(nombre)
            return str(int(numero_brazos))
        if numero_canales is not None and any(p in nombre for p in _PALABRAS_NUMERO_CANALES):
            resueltos.add(nombre)
            return str(int(numero_canales))
        sin_valor.add(nombre)
        return "—"

    # La separación de cotas fundidas va ANTES de sustituir, porque reconstruye la posición
    # de cada letra a partir del texto de la plantilla. No mueve ninguna cota de sitio.
    svg_content = separar_cotas_fundidas(svg_content, nombre_plantilla)

    svg_content = _PATRON_MARCADOR.sub(lambda m: valor_de(m.group(0)), svg_content)

    origen = f" en '{nombre_plantilla}'" if nombre_plantilla else ""
    if resueltos:
        print(f"   [i] Marcadores resueltos por su significado{origen}: "
              f"{', '.join(sorted(resueltos))}")
    if sin_valor:
        print(f"   [⚠️ Alerta]: marcadores sin valor{origen}: {', '.join(sorted(sin_valor))}")

    return svg_content


def seleccionar_plantilla_svg(D1: float, D2: float) -> str:
    tolerancia = 0.5
    if abs(D1 - D2) <= tolerancia:
        return "Transmisión - caso 1.svg"
    elif D1 < D2:
        proporcion = D1 / D2
        return "Transmisión - caso 2.svg" if proporcion >= 0.7 else "Transmisión - caso 3.svg"
    else:
        proporcion = D2 / D1
        return "Transmisión - caso 4.svg" if proporcion >= 0.7 else "Transmisión - caso 5.svg"


# Numeración romana del tipo constructivo de polea, tal como la nombran los planos:
#   I = maciza, II = aligerada o de discos, III = de brazos.
_ROMANOS = {1: "I", 2: "II", 3: "III"}


def numero_tipo_polea(tipo_str: str) -> int:
    """Traduce la descripción del tipo constructivo al número 1, 2 o 3.

    Se evalúa primero el Tipo III porque la cadena "tipo ii" está contenida dentro de
    "tipo iii" y, comprobando en el otro orden, una polea de brazos se clasificaría como
    aligerada.
    """
    tipo_lower = str(tipo_str).lower()
    if "brazos" in tipo_lower or "tipo iii" in tipo_lower or "iii" in tipo_lower:
        return 3
    if "aligerada" in tipo_lower or "discos" in tipo_lower or "agujeros" in tipo_lower or "tipo ii" in tipo_lower:
        return 2
    return 1


def nombres_plantilla_polea(tipo_str: str, es_liviana: bool = False) -> List[str]:
    """Nombres de archivo candidatos para el plano de la polea, en orden de preferencia.

    Las correas de servicio liviano (3L, 4L, 5L) tienen sus propios planos, distintos de
    los de bandas en V, porque la geometría de la ranura y las proporciones del cuerpo no
    son las mismas. Se admiten dos grafías del número de tipo —romana, que es como los
    nombra el juego de planos de bandas livianas, y arábiga, que es como se nombran los de
    bandas en V— para no depender de cuál se haya usado al guardar los archivos.
    """
    n = numero_tipo_polea(tipo_str)
    if es_liviana:
        return [f"Polea banda liviana tipo {_ROMANOS[n]}.svg",
                f"Polea banda liviana tipo {n}.svg"]
    return [f"Polea en V tipo {n}.svg",
            f"Polea en V tipo {_ROMANOS[n]}.svg"]


def seleccionar_plantilla_polea(tipo_str: str, es_liviana: bool = False) -> str:
    """Primer nombre candidato que exista en disco.

    Si no existe ninguno se devuelve el preferido de todos modos, para que el mensaje de
    error nombre el archivo que realmente se esperaba y no uno de otra familia.
    """
    candidatos = nombres_plantilla_polea(tipo_str, es_liviana)
    for nombre in candidatos:
        if os.path.exists(nombre):
            return nombre
    return candidatos[0]


def generar_svg_correas(res, is_ing: bool = False) -> str:
    ruta_template = seleccionar_plantilla_svg(res.D1, res.D2)
    if not os.path.exists(ruta_template):
        ruta_template = "Transmisión - caso 1.svg"

    with open(ruta_template, 'r', encoding='utf-8') as f:
        svg_content = f.read()

    d1 = res.D1 / 25.4 if is_ing else res.D1
    d2 = res.D2 / 25.4 if is_ing else res.D2
    dc = res.distancia_ejes_final / 25.4 if is_ing else res.distancia_ejes_final
    lc = res.longitud_comercial / 25.4 if is_ing else res.longitud_comercial

    reemplazos = {
        "VAR_D1": f"{d1:.2f}",
        "VAR_D2": f"{d2:.2f}",
        "VAR_C": f"{dc:.2f}",
        "VAR_LC": f"{lc:.2f}",
        "VAR_RPM1": f"{res.n1:.0f}",
        "VAR_RPM2": f"{res.n2:.0f}",
        # Sin el símbolo de grado: la plantilla ya lo lleva escrito detrás del marcador
        # ("θ1= VAR_ANG1°"), de modo que añadirlo aquí imprimía dos.
        "VAR_ANG1": f"{res.angulo_contacto_pequena_g:.1f}",
        "VAR_ANG2": f"{180.0 - (res.angulo_contacto_pequena_g - 180.0):.1f}",
        "VAR_N_RANURAS": str(res.num_bandas_entero),
        "VAR_ANCHO_POLEA1": f"{(res.ancho_polea_1 / 25.4 if is_ing else res.ancho_polea_1):.2f}",
        "VAR_ANCHO_POLEA2": f"{(res.ancho_polea_2 / 25.4 if is_ing else res.ancho_polea_2):.2f}",
    }

    return aplicar_reemplazos(svg_content, reemplazos, ruta_template,
                              numero_canales=res.num_bandas_entero)


def generar_svg_polea_texto(tipo_str, ancho_cara, D_nominal, detalles_dict, ranura_dict,
                            is_ing: bool = False, num_ranuras: int = 1,
                            es_liviana: bool = False) -> str:
    ruta_template = seleccionar_plantilla_polea(tipo_str, es_liviana)
    if not os.path.exists(ruta_template):
        # Se degrada al Tipo I de la MISMA familia, nunca al de la otra: dibujar una
        # correa liviana sobre el plano de una polea en V daría una geometría de ranura
        # que no corresponde.
        respaldo = nombres_plantilla_polea("Tipo I", es_liviana)
        ruta_template = next((n for n in respaldo if os.path.exists(n)), None)
        if ruta_template is None:
            familia_txt = "banda liviana" if es_liviana else "banda en V"
            print(f"   [⚠️ Alerta]: no se encontró ninguna plantilla de polea de "
                  f"{familia_txt}. Se esperaba "
                  f"'{nombres_plantilla_polea(tipo_str, es_liviana)[0]}'.")
            return ""

    with open(ruta_template, 'r', encoding='utf-8') as f:
        svg_content = f.read()

    factor = 1 / 25.4 if is_ing else 1.0

    detalles = detalles_dict if isinstance(detalles_dict, dict) else {}
    ranura = ranura_dict if isinstance(ranura_dict, dict) else {}

    def extraer_valor(*keys, default=0.0):
        """Primer valor numérico hallado entre los diccionarios de detalles y de ranura.

        Devuelve 'default' si ninguna clave existe, y ese default puede ser None cuando la
        magnitud no aplica al tipo de polea: así el marcador queda sin resolver en lugar de
        recibir un número inventado.
        """
        for k in keys:
            if k in detalles and detalles[k] is not None:
                try: return float(detalles[k])
                except (TypeError, ValueError): pass
            if k in ranura and ranura[k] is not None:
                try: return float(ranura[k])
                except (TypeError, ValueError): pass
        return default

    l_buje = extraer_valor('l_buje', 'L_buje', 'LBuje', default=ancho_cara * 0.8)
    m_buje = extraer_valor('m_buje', 'M_buje', 'DBuje', 'd1_cubo', default=D_nominal * 0.35)
    d_eje = extraer_valor('d_eje', 'D_eje', 'Deje', 'diametro_eje', default=D_nominal * 0.2)
    d_ag = extraer_valor('d_ag', 'd_ag (Diam. Agujero Aligeramiento)', 'diametro_agujero', default=D_nominal * 0.12)
    d_cp = extraer_valor('D_cp', 'D_cp (Diam. Circunf. Agujeros)', 'diametro_circunferencia_pernos', default=D_nominal * 0.55)
    # Espesor del alma. SIN respaldo al espesor de la llanta: son magnitudes distintas
    # —el alma es el disco que une cubo y corona, la llanta es la pared bajo la ranura— y
    # usar una como suplente de la otra produciría una cota creíble pero falsa. Las poleas
    # Tipo I y Tipo III no tienen alma, así que ahí el valor sencillamente no existe y el
    # marcador se queda sin resolver, que es lo honesto.
    z_val = extraer_valor('z (Espesor del alma)', default=None)

    # OJO con el orden de las claves: la tabla de ranura tiene su propia 'h' (profundidad
    # de la ranura) y su propia 'b'. Buscando 'h' primero, el ancho del brazo tomaba la
    # profundidad de la ranura, que no tiene ninguna relación con él. Por eso se consulta
    # antes el nombre completo, que es inequívoco.
    h_brazo = extraer_valor('h (Ancho brazo en base)', default=1.15 * d_eje)
    a_brazo = extraer_valor('a (Espesor brazo en base)', default=0.45 * h_brazo)
    h_brazo_2 = extraer_valor("h' (Ancho brazo en corona)", default=0.8 * h_brazo)
    a_brazo_2 = extraer_valor("a' (Espesor brazo en corona)", default=0.8 * a_brazo)

    # Espesor de llanta y número de brazos: los aporta el núcleo, y si faltan se estiman
    # con las mismas reglas, para que la cota nunca quede vacía en el plano.
    t_llanta = extraer_valor('Espesor de llanta (t)', 'espesor_llanta',
                             default=D_nominal / 200.0 + 3.0)
    try:
        n_brazos = int(detalles.get('Número de brazos', 4) or 4)
    except (TypeError, ValueError):
        n_brazos = 4

    reemplazos = {
        "VAR_ANCHO_POLEA": f"{ancho_cara * factor:.2f}",
        "VAR_D_NOMINAL": f"{D_nominal * factor:.2f}",
        "VAR_W_DG": f"{extraer_valor('W_dg') * factor:.2f}",
        "VAR_E": f"{extraer_valor('e_nominal', 'e') * factor:.2f}",
        "VAR_F": f"{extraer_valor('f_nominal', 'f') * factor:.2f}",
        "VAR_G": f"{extraer_valor('g') * factor:.2f}",
        # El ángulo de la ranura aparece en las plantillas como VAR_A_ANG, no como
        # VAR_ANG_A: se definen los dos nombres porque el plano que lo pide con el nombre
        # que el código no tenía estaba imprimiendo un guion en lugar del ángulo.
        "VAR_ANG_A": f"{extraer_valor('Angulo_A_nominal', 'A')}°",
        "VAR_A_ANG": f"{extraer_valor('Angulo_A_nominal', 'A')}°",
        "VAR_D_AG": f"{d_ag * factor:.2f}",
        "VAR_D_CP": f"{d_cp * factor:.2f}",
        "VAR_M_BUJE": f"{m_buje * factor:.2f}",
        "VAR_DBUJE": f"{m_buje * factor:.2f}",
        "VAR_L_BUJE": f"{l_buje * factor:.2f}",
        "VAR_LBÚJE": f"{l_buje * factor:.2f}",
        "VAR_D_EJE": f"{d_eje * factor:.2f}",
        "VAR_DEJE": f"{d_eje * factor:.2f}",
        "VAR_B": f"{extraer_valor('b') * factor:.2f}",
        "VAR_H": f"{extraer_valor('h') * factor:.2f}",
        "VAR_H_BRAZO": f"{h_brazo * factor:.2f}",
        "VAR_A_BRAZO": f"{a_brazo * factor:.2f}",
        # Las dos grafías del subíndice: los planos de bandas en V usan "_2" y los de
        # bandas planas y livianas usan "2" pegado. Se definen ambas para no depender de
        # cuál se haya escrito en cada plantilla.
        "VAR_H_BRAZO_2": f"{h_brazo_2 * factor:.2f}",
        "VAR_A_BRAZO_2": f"{a_brazo_2 * factor:.2f}",
        "VAR_H_BRAZO2": f"{h_brazo_2 * factor:.2f}",
        "VAR_A_BRAZO2": f"{a_brazo_2 * factor:.2f}",
        # Espesor de llanta y número de brazos: antes no existían como marcadores, de modo
        # que la plantilla los pedía y el plano los mostraba como un guion.
        "VAR_T_LLANTA": f"{t_llanta * factor:.2f}",
        "VAR_ESPESOR_LLANTA": f"{t_llanta * factor:.2f}",
        "VAR_N_BRAZOS": str(n_brazos),
        "VAR_NUM_BRAZOS": str(n_brazos),
        "VAR_NUMERO_BRAZOS": str(n_brazos),
        "VAR_NÚMERO_BRAZOS": str(n_brazos),
        "VAR_NRO_BRAZOS": str(n_brazos),
        "VAR_CANT_BRAZOS": str(n_brazos),
        "VAR_BRAZOS": str(n_brazos),
        "VAR_Z_BRAZOS": str(n_brazos),
        # Número de canales de la polea. Es el mismo dato que el número de correas de la
        # transmisión, y faltaba: la plantilla de polea lo pedía y nadie lo sustituía, así
        # que el texto "VAR_N_RANURAS" quedaba impreso sobre el plano.
        "VAR_N_RANURAS": str(int(num_ranuras)),
        "VAR_N_CANALES": str(int(num_ranuras)),
        # Escrito sin el guion bajo, tal como lo pide la plantilla de polea en V.
        "VAR_NRANURAS": str(int(num_ranuras)),
        "VAR_NCANALES": str(int(num_ranuras)),
    }

    # Solo se define el marcador del alma cuando la polea realmente tiene alma.
    if z_val is not None:
        reemplazos["VAR_Z"] = f"{z_val * factor:.2f}"
        reemplazos["VAR_ESPESOR_ALMA"] = f"{z_val * factor:.2f}"

    return aplicar_reemplazos(svg_content, reemplazos, ruta_template,
                              numero_canales=int(num_ranuras),
                              numero_brazos=n_brazos)


def generar_planos_svg(res, ruta_plantilla: str, ruta_salida: str, is_ing: bool = False):
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
        "VAR_N_CANALES": str(res.num_bandas_entero),
        "VAR_ANCHO_POLEA1": fmt(res.ancho_polea_1 * conv),
        "VAR_ANCHO_POLEA2": fmt(res.ancho_polea_2 * conv),
        "VAR_D_EJE1": fmt(res.d_eje_1 * conv if res.d_eje_1 else None),
        "VAR_D_EJE2": fmt(res.d_eje_2 * conv if res.d_eje_2 else None),
    }

    svg_content = aplicar_reemplazos(svg_content, reemplazos, ruta_plantilla,
                                     numero_canales=res.num_bandas_entero)

    with open(ruta_salida, 'w', encoding='utf-8') as f:
        f.write(svg_content)


def escribir_plano(ruta_salida: str, contenido: str) -> bool:
    """Guarda el plano solo si hay contenido.

    Escribir un SVG vacío sería peor que no escribir nada: el archivo existiría, el visor
    lo daría por válido y fallaría al rasterizarlo con un error sin relación aparente. Si
    no hay contenido se borra cualquier plano anterior, para que no quede en pantalla el
    resultado de un cálculo previo haciéndose pasar por el actual.
    """
    if contenido:
        with open(ruta_salida, "w", encoding="utf-8") as f:
            f.write(contenido)
        return True
    if os.path.exists(ruta_salida):
        os.remove(ruta_salida)
    return False


def es_transmision_liviana(res) -> bool:
    """Indica si el resultado corresponde a la familia de servicio liviano (FHP).

    Se mira tanto la familia como el perfil, porque el perfil es el dato que sobrevive si
    el resultado se construye por otra vía.
    """
    familia = str(getattr(res, "familia", "")).strip().upper()
    perfil = str(getattr(res, "perfil", "")).strip().upper()
    return familia == "SERVICIO_LIVIANO" or perfil in ("2L", "3L", "4L", "5L")


def exportar_planos_completos(res, is_ing: bool = False, carpeta_salida: str = "") -> dict:
    """Genera los tres planos (transmisión, polea conductora y polea conducida).

    carpeta_salida es la carpeta donde se escriben. La interfaz gráfica pasa una carpeta
    temporal que borra al cerrarse, para que los planos no se acumulen junto al programa;
    si se deja vacía se escriben en la carpeta de trabajo, como antes. Las PLANTILLAS se
    siguen leyendo de la carpeta del programa.

    Devuelve las rutas de los tres planos: {'transmision', 'conductora', 'conducida'}.
    """
    rutas = {
        "transmision": os.path.join(carpeta_salida, "Plano_Transmision.svg"),
        "conductora": os.path.join(carpeta_salida, "Plano_Polea_Conductora.svg"),
        "conducida": os.path.join(carpeta_salida, "Plano_Polea_Conducida.svg"),
    }
    # Se borra lo del cálculo anterior: si una plantilla faltara, no debe quedar en
    # pantalla el plano viejo haciéndose pasar por el nuevo.
    for ruta in rutas.values():
        if os.path.exists(ruta):
            os.remove(ruta)

    liviana = es_transmision_liviana(res)
    d1 = res.D1
    d2 = res.D2
    caso = 1

    if abs(d1 - d2) < 0.1: caso = 1
    elif d1 < d2 and d1 > 0.65 * d2: caso = 2
    elif d1 <= 0.65 * d2: caso = 3
    elif d2 <= 0.65 * d1: caso = 4
    elif d2 < d1 and d2 > 0.65 * d1: caso = 5

    # Plano general de transmisión
    generar_planos_svg(res, f"Transmisión - caso {caso}.svg", rutas["transmision"], is_ing)

    # Plano de la polea conductora
    svg_p1 = generar_svg_polea_texto(
        res.tipo_polea_1_str, res.ancho_polea_1, res.D1,
        res.detalles_constructivos_1, res.dim_ranura_1, is_ing,
        num_ranuras=res.num_bandas_entero, es_liviana=liviana
    )
    escribir_plano(rutas["conductora"], svg_p1)

    # Plano de la polea conducida
    svg_p2 = generar_svg_polea_texto(
        res.tipo_polea_2_str, res.ancho_polea_2, res.D2,
        res.detalles_constructivos_2, res.dim_ranura_2, is_ing,
        num_ranuras=res.num_bandas_entero, es_liviana=liviana
    )
    escribir_plano(rutas["conducida"], svg_p2)

    return rutas


def mostrar_pestanas_transmision(res, is_ing=False):
    if EN_JUPYTER:
        svg_general = generar_svg_correas(res, is_ing=is_ing)
        widget_general = widgets.Output()
        with widget_general:
            display(SVG(svg_general))

        liviana = es_transmision_liviana(res)
        svg_polea1 = generar_svg_polea_texto(
            res.tipo_polea_1_str, res.ancho_polea_1, res.D1,
            res.detalles_constructivos_1, res.dim_ranura_1, is_ing,
            num_ranuras=res.num_bandas_entero, es_liviana=liviana
        )
        svg_polea2 = generar_svg_polea_texto(
            res.tipo_polea_2_str, res.ancho_polea_2, res.D2,
            res.detalles_constructivos_2, res.dim_ranura_2, is_ing,
            num_ranuras=res.num_bandas_entero, es_liviana=liviana
        )

        widget_poleas = widgets.Output()
        with widget_poleas:
            print("=== POLEA 1 (CONDUCTORA) ===")
            display(SVG(svg_polea1))
            print("\n=== POLEA 2 (CONDUCIDA) ===")
            display(SVG(svg_polea2))

        pestanas = widgets.Tab(children=[widget_general, widget_poleas])
        pestanas.set_title(0, "Plano General de Transmisión")
        pestanas.set_title(1, "Planos Detallados de Poleas")
        display(pestanas)
