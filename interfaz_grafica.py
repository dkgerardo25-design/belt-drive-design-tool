import os, sys

if getattr(sys, "frozen", False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

os.chdir(base_dir)

if base_dir not in os.environ["PATH"]:
    os.environ["PATH"] = base_dir + os.pathsep + os.environ["PATH"]

try:
    os.add_dll_directory(base_dir)
except (AttributeError, OSError):
    pass

import tkinter as tk
from tkinter import messagebox, ttk
import io
import atexit
import shutil
import tempfile
import time
import cairosvg
from PIL import Image, ImageTk
import nucleo_diseno_correas
import visualizacion_correas
import nucleo_diseno_planas


# =====================================================================================
#  ARCHIVOS TEMPORALES DE VISUALIZACIÓN
#  Los planos SVG que se muestran en las pestañas se escriben en una carpeta temporal
#  propia de cada sesión, dentro de la carpeta temporal del sistema (en Windows,
#  AppData\Local\Temp, que ya es oculta), y se borran al cerrar el programa. Antes se
#  escribían con nombres fijos en la carpeta del programa y quedaban ahí indefinidamente.
# =====================================================================================
PREFIJO_TEMPORAL = "diseno_transmisiones_"

# Nombres con que las versiones anteriores dejaban los planos en la carpeta del programa.
# Se eliminan al arrancar para limpiar lo que quedó de sesiones previas.
PLANOS_HEREDADOS = (
    ["Plano_Transmision.svg", "Plano_Polea_Conductora.svg", "Plano_Polea_Conducida.svg"]
    + [f"plano_conductora_tipo{n}.svg" for n in (1, 2, 3)]
    + [f"plano_conducida_tipo{n}.svg" for n in (1, 2, 3)]
    + [f"plano_transmision_caso{n}.svg" for n in (1, 2, 3, 4, 5)]
)


def _ocultar_en_windows(ruta: str) -> None:
    """Marca la carpeta como oculta en Windows. En otros sistemas no hace nada."""
    if os.name != "nt":
        return
    try:
        import ctypes
        FILE_ATTRIBUTE_HIDDEN = 0x02
        ctypes.windll.kernel32.SetFileAttributesW(str(ruta), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass


def _limpiar_restos_anteriores(carpeta_programa: str) -> None:
    """Borra los planos que versiones anteriores dejaban junto al programa y las carpetas
    temporales de sesiones que no se cerraron bien (por ejemplo, si el programa se forzó a
    cerrar). Solo se tocan carpetas temporales con más de un día, para no interferir con
    otra ventana del programa que esté abierta al mismo tiempo."""
    for nombre in PLANOS_HEREDADOS:
        ruta = os.path.join(carpeta_programa, nombre)
        try:
            if os.path.isfile(ruta):
                os.remove(ruta)
        except OSError:
            pass

    raiz = tempfile.gettempdir()
    limite = time.time() - 24 * 3600
    try:
        for nombre in os.listdir(raiz):
            ruta = os.path.join(raiz, nombre)
            if (nombre.startswith(PREFIJO_TEMPORAL) and os.path.isdir(ruta)
                    and os.path.getmtime(ruta) < limite):
                shutil.rmtree(ruta, ignore_errors=True)
    except OSError:
        pass

class AppDisenoCorreas(tk.Tk):
    def __init__(self):
        super().__init__()

        # Carpeta temporal de esta sesión para los planos de visualización.
        _limpiar_restos_anteriores(base_dir)
        self.carpeta_temporal = tempfile.mkdtemp(prefix=PREFIJO_TEMPORAL)
        _ocultar_en_windows(self.carpeta_temporal)
        # Doble seguro: al cerrar la ventana y, si el intérprete termina por otra vía,
        # también al salir de Python.
        atexit.register(self._borrar_carpeta_temporal)
        self.protocol("WM_DELETE_WINDOW", self._al_cerrar)
        self.title("Software de Diseño de Transmisiones por Correas y Bandas")
        self.geometry("1380x950")
        self.minsize(720, 480)   # se puede achicar: el contenido ahora se desplaza

        self._crear_area_scrollable()
        self.crear_interfaz()
        self.cambiar_modo_tecnologia()
        self.bind("<Configure>", self._al_redimensionar_ventana)

    # =================== CIERRE Y LIMPIEZA ===================
    def _borrar_carpeta_temporal(self):
        carpeta = getattr(self, "carpeta_temporal", None)
        if carpeta and os.path.isdir(carpeta):
            shutil.rmtree(carpeta, ignore_errors=True)

    def _al_cerrar(self):
        self._borrar_carpeta_temporal()
        self.destroy()

    # =================== ÁREA DESPLAZABLE ===================
    def _crear_area_scrollable(self):
        """Todo el contenido vive dentro de un Canvas con barras de desplazamiento.
        Antes se empacaba directamente en la ventana, de modo que al reducirla la
        información simplemente quedaba fuera de vista y sin forma de alcanzarla."""
        marco = ttk.Frame(self)
        marco.pack(fill=tk.BOTH, expand=True)

        self.canvas_scroll = tk.Canvas(marco, highlightthickness=0)
        barra_v = ttk.Scrollbar(marco, orient=tk.VERTICAL, command=self.canvas_scroll.yview)
        barra_h = ttk.Scrollbar(marco, orient=tk.HORIZONTAL, command=self.canvas_scroll.xview)
        self.canvas_scroll.configure(yscrollcommand=barra_v.set, xscrollcommand=barra_h.set)

        barra_v.pack(side=tk.RIGHT, fill=tk.Y)
        barra_h.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas_scroll.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.contenido = ttk.Frame(self.canvas_scroll)
        self._id_ventana_scroll = self.canvas_scroll.create_window((0, 0), window=self.contenido, anchor="nw")

        self.contenido.bind(
            "<Configure>",
            lambda e: self.canvas_scroll.configure(scrollregion=self.canvas_scroll.bbox("all"))
        )
        self.canvas_scroll.bind("<Configure>", self._ajustar_ancho_contenido)

        # Rueda del ratón solo mientras el puntero está sobre el área desplazable
        self.canvas_scroll.bind("<Enter>", self._activar_rueda)
        self.canvas_scroll.bind("<Leave>", self._desactivar_rueda)

    def _ajustar_ancho_contenido(self, event):
        """El contenido nunca es más angosto que el canvas (para que llene la ventana),
        pero sí puede ser más ancho, y entonces aparece la barra horizontal."""
        self.canvas_scroll.itemconfigure(
            self._id_ventana_scroll,
            width=max(event.width, self.contenido.winfo_reqwidth())
        )

    def _activar_rueda(self, event=None):
        self.canvas_scroll.bind_all("<MouseWheel>", self._rueda)        # Windows / macOS
        self.canvas_scroll.bind_all("<Button-4>", self._rueda)          # Linux arriba
        self.canvas_scroll.bind_all("<Button-5>", self._rueda)          # Linux abajo

    def _desactivar_rueda(self, event=None):
        for evento in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas_scroll.unbind_all(evento)

    def _rueda(self, event):
        if getattr(event, "num", None) == 4:
            paso = -1
        elif getattr(event, "num", None) == 5:
            paso = 1
        else:
            paso = -1 if event.delta > 0 else 1
        self.canvas_scroll.yview_scroll(paso, "units")

    def crear_interfaz(self):
        frame_top_master = ttk.Frame(self.contenido)
        frame_top_master.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        ttk.Label(frame_top_master, text="Tecnología de Transmisión:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        self.cmb_tecnologia = ttk.Combobox(frame_top_master, values=["Bandas en V (BS-3790)", "Bandas Planas"], state="readonly", width=30)
        self.cmb_tecnologia.set("Bandas en V (BS-3790)")
        self.cmb_tecnologia.pack(side=tk.LEFT, padx=5)
        self.cmb_tecnologia.bind("<<ComboboxSelected>>", self.cambiar_modo_tecnologia)

        self.frame_inputs = ttk.LabelFrame(self.contenido, text=" Parámetros de Entrada y Guía de Selección ")
        self.frame_inputs.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)

        # Campos comunes dinámicos (Fila 0)
        self.lbl_pot = ttk.Label(self.frame_inputs, text="Potencia Nominal (kW):")
        self.lbl_pot.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.ent_potencia = ttk.Entry(self.frame_inputs, width=22)
        self.ent_potencia.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        self.lbl_n1 = ttk.Label(self.frame_inputs, text="Velocidad n1 (RPM):")
        self.lbl_n1.grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self.ent_n1 = ttk.Entry(self.frame_inputs, width=22)
        self.ent_n1.grid(row=0, column=3, padx=5, pady=5, sticky="ew")

        self.lbl_n2 = ttk.Label(self.frame_inputs, text="Velocidad n2 (RPM):")
        self.lbl_n2.grid(row=0, column=4, padx=5, pady=5, sticky="w")
        self.ent_n2 = ttk.Entry(self.frame_inputs, width=22)
        self.ent_n2.grid(row=0, column=5, padx=5, pady=5, sticky="ew")

        # Específicos V-Belt
        self.lbl_v1 = ttk.Label(self.frame_inputs, text="Familia Normativa:")
        self.cmb_v_familia = ttk.Combobox(self.frame_inputs, values=["METRICA", "AMERICANA", "ALTA_CAPACIDAD", "SERVICIO_LIVIANO"], state="readonly", width=20)
        self.cmb_v_familia.set("METRICA")
        self.cmb_v_familia.bind("<<ComboboxSelected>>", self.cambiar_modo_familia_v)

        # Selector propio de la familia de servicio liviano. La norma FHP usa un factor de
        # servicio COMBINADO que depende solo de la maquina accionada y de la relacion de
        # transmision, de modo que aqui no intervienen ni el tipo de motor ni las horas de
        # operacion. La lista se toma del nucleo para no duplicar los nombres.
        self.lbl_fhp_maquina = ttk.Label(self.frame_inputs, text="Maquina accionada:")
        self.cmb_fhp_maquina = ttk.Combobox(
            self.frame_inputs,
            values=list(nucleo_diseno_correas.DisenadorFHP.MAQUINAS_ES.values()),
            state="readonly", width=34
        )
        self.cmb_fhp_maquina.set(
            nucleo_diseno_correas.DisenadorFHP.MAQUINAS_ES["CENTRIFUGAL PUMPS"]
        )

        self.lbl_v2 = ttk.Label(self.frame_inputs, text="Tipo de Motor:")
        self.cmb_v_motor = ttk.Combobox(self.frame_inputs, values=["PAR NORMAL", "PAR ELEVADO"], state="readonly", width=20)
        self.cmb_v_motor.set("PAR NORMAL")

        self.lbl_v3 = ttk.Label(self.frame_inputs, text="Tipo de Transmisión:")
        self.cmb_v_trans = ttk.Combobox(self.frame_inputs, values=["LIGERA", "MEDIA", "PESADA", "MUY PESADA"], state="readonly", width=20)
        self.cmb_v_trans.set("PESADA")

        self.lbl_v4 = ttk.Label(self.frame_inputs, text="Horas de Operación:")
        self.cmb_v_horas = ttk.Combobox(self.frame_inputs, values=["HASTA 10 HORAS", "10 A 16 HORAS", "MAS DE 16 HORAS"], state="readonly", width=20)
        self.cmb_v_horas.set("10 A 16 HORAS")

        self.lbl_v5 = ttk.Label(self.frame_inputs, text="Modo de Centros:")
        self.cmb_v_centros = ttk.Combobox(self.frame_inputs, values=["AUTOMATICO", "FIJO", "RANGO"], state="readonly", width=20)
        self.cmb_v_centros.set("RANGO")
        self.cmb_v_centros.bind("<<ComboboxSelected>>", self.actualizar_campos_centros_v)

        self.lbl_v6 = ttk.Label(self.frame_inputs, text="Dist. Mínima / C1 (mm):")
        self.ent_v_c1 = ttk.Entry(self.frame_inputs, width=22)

        self.lbl_v7 = ttk.Label(self.frame_inputs, text="Dist. Máxima / C2 (mm):")
        self.ent_v_c2 = ttk.Entry(self.frame_inputs, width=22)

        self.lbl_v8 = ttk.Label(self.frame_inputs, text="Sistema de Unidades:")
        self.cmb_v_unidades = ttk.Combobox(self.frame_inputs, values=["Métrico (mm / kW)", "Inglés (pulg / HP)"], state="readonly", width=20)
        self.cmb_v_unidades.set("Métrico (mm / kW)")
        self.cmb_v_unidades.bind("<<ComboboxSelected>>", self.actualizar_etiquetas_unidades)

        # --- Específicos Bandas Planas ---
        self.lbl_p_modo = ttk.Label(self.frame_inputs, text="Modo de Selección:", font=("Arial", 9, "bold"))
        self.cmb_p_modo = ttk.Combobox(self.frame_inputs, values=["Catálogo Comercial (Base de Datos)", "Manual"], state="readonly", width=35)
        self.cmb_p_modo.set("Catálogo Comercial (Base de Datos)")
        self.cmb_p_modo.bind("<<ComboboxSelected>>", self.cambiar_modo_planas)

        self.lbl_p1 = ttk.Label(self.frame_inputs, text="Serie de la Correa:")
        self.cmb_p_serie = ttk.Combobox(self.frame_inputs, values=[
            "Serie A (Caucho NBR - Uso general)", 
            "Serie F (Ambientes sucios / choques)"
        ], state="readonly", width=38)
        self.cmb_p_serie.set("Serie A (Caucho NBR - Uso general)")

        # Selector de Material / Banda Académica (Cargado desde Excel)
        self.lbl_pm_nombre = ttk.Label(self.frame_inputs, text="Nombre/Tipo de Banda:")
        # Solo bandas del catálogo. No hay opción "Personalizado / Manual": el factor de
        # corrección por polea (Cp, Tabla 17-4 de Shigley) se lee cruzando el GRADO de la
        # banda con el diámetro, de modo que sin un grado reconocido (F-0 a F-2, A-2 a
        # A-5) ese factor no existe y el diseño queda sin fundamento. Las propiedades del
        # material sí se pueden editar: lo que no se admite es una banda sin grado.
        nombres_bandas_excel = []
        try:
            db_temp = nucleo_diseno_planas.BaseDatosPlanas("DATOS_SOFTWARE_planas.xlsx")
            if hasattr(db_temp, 'belt_specifications') and not db_temp.belt_specifications.empty:
                nombres_bandas_excel = db_temp.belt_specifications['Tipo de correa'].dropna().unique().tolist()
        except Exception as e:
            # Antes este fallo se ignoraba en silencio y el desplegable quedaba vacío sin
            # ninguna pista de por qué.
            print(f"No se pudo leer la lista de bandas planas del Excel: {e}")

        self.cmb_pm_nombre = ttk.Combobox(self.frame_inputs, values=nombres_bandas_excel, state="readonly", width=20)
        if nombres_bandas_excel:
            self.cmb_pm_nombre.set(nombres_bandas_excel[0])
        self.cmb_pm_nombre.bind("<<ComboboxSelected>>", self.al_seleccionar_material_manual)

        self.lbl_pm_esfuerzo = ttk.Label(self.frame_inputs, text="Esfuerzo Admisible (MPa):")
        self.ent_pm_esfuerzo = ttk.Entry(self.frame_inputs, width=22)

        self.lbl_pm_mu = ttk.Label(self.frame_inputs, text="Coef. Fricción (μ):")
        self.ent_pm_mu = ttk.Entry(self.frame_inputs, width=22)

        self.lbl_pm_espesor = ttk.Label(self.frame_inputs, text="Espesor (mm):")
        self.ent_pm_espesor = ttk.Entry(self.frame_inputs, width=22)

        self.lbl_pm_densidad = ttk.Label(self.frame_inputs, text="Densidad (kg/m³):")
        self.ent_pm_densidad = ttk.Entry(self.frame_inputs, width=22)

        self.lbl_pm_ancho = ttk.Label(self.frame_inputs, text="Ancho de Banda (mm):")
        self.ent_pm_ancho = ttk.Entry(self.frame_inputs, width=22)

        self.al_seleccionar_material_manual()

        self.lbl_p_par = ttk.Label(self.frame_inputs, text="Tipo de Par del Motor:")
        self.cmb_p_par = ttk.Combobox(self.frame_inputs, values=["Par Normal (Hasta 1.8 veces)", "Par Elevado (Superior a 1.8 veces)"], state="readonly", width=35)
        self.cmb_p_par.set("Par Normal (Hasta 1.8 veces)")

        self.lbl_p2 = ttk.Label(self.frame_inputs, text="Condición de Operación:")
        self.cmb_p_condicion = ttk.Combobox(self.frame_inputs, values=[
            "1. Servicio regular (Motores normales, bombas)", 
            "2. Servicio irregular medio (Máquinas herramienta, ventiladores)", 
            "3. Servicio irregular pesado (Compresores, prensas)", 
            "4. Servicio muy severo (Trituradoras, molinos)"
        ], state="readonly", width=38)
        self.cmb_p_condicion.set("1. Servicio regular (Motores normales, bombas)")

        self.lbl_p_horas = ttk.Label(self.frame_inputs, text="Horas de Operación:")
        self.cmb_p_horas = ttk.Combobox(self.frame_inputs, values=["HASTA 10 HORAS", "10 A 16 HORAS", "MAS DE 16 HORAS"], state="readonly", width=20)
        self.cmb_p_horas.set("10 A 16 HORAS")

        self.lbl_p_unidades = ttk.Label(self.frame_inputs, text="Sistema de Unidades:")
        self.cmb_p_unidades = ttk.Combobox(self.frame_inputs, values=["Métrico (mm / kW)", "Inglés (pulg / HP)"], state="readonly", width=20)
        self.cmb_p_unidades.set("Métrico (mm / kW)")
        self.cmb_p_unidades.bind("<<ComboboxSelected>>", self.actualizar_etiquetas_unidades)

        self.lbl_p4 = ttk.Label(self.frame_inputs, text="Dist. Centros (mm) (Opcional):")
        self.ent_p_centros = ttk.Entry(self.frame_inputs, width=22)

        # Compartidos / Opcionales con unidades dinámicas
        self.lbl_d1 = ttk.Label(self.frame_inputs, text="D1 Conductora (mm) (Opcional):")
        self.ent_d1 = ttk.Entry(self.frame_inputs, width=22)

        self.lbl_eje1 = ttk.Label(self.frame_inputs, text="Diámetro Eje Motor d1 (mm):")
        self.ent_eje1 = ttk.Entry(self.frame_inputs, width=22)

        self.lbl_eje2 = ttk.Label(self.frame_inputs, text="Diámetro Eje Conducida d2 (mm):")
        self.ent_eje2 = ttk.Entry(self.frame_inputs, width=22)

        # El criterio NEMA de diametro minimo de polea nace del limite de carga radial
        # admisible en el eje de un motor electrico normalizado. Con otra maquina motriz
        # (motor de combustion, turbina, eje intermedio) esa restriccion no aplica, y el
        # diametro debe decidirlo el usuario. Se deja marcada por defecto porque el motor
        # electrico es el caso habitual.
        self.chk_motor_electrico_var = tk.BooleanVar(value=True)
        self.chk_motor_electrico = ttk.Checkbutton(
            self.frame_inputs,
            text="El accionamiento es un motor electrico (aplicar minimo NEMA de eje)",
            variable=self.chk_motor_electrico_var
        )

        # Normalización de diámetros (solo bandas en V). Marcada, las poleas se llevan al
        # diámetro comercial más cercano; desmarcada, se dejan en el valor teórico
        # redondeado al mm (o a 0,01 pulg) y se tratan como fabricación a medida. Las
        # longitudes de correa se normalizan siempre.
        self.chk_normalizar_var = tk.BooleanVar(value=True)
        self.chk_normalizar = ttk.Checkbutton(
            self.frame_inputs,
            text="Aproximar a diámetros comerciales (desmarcar = poleas a medida)",
            variable=self.chk_normalizar_var
        )

        # Contenedor para botones de acción
        self.frame_botones = ttk.Frame(self.frame_inputs)
        self.btn_calcular = ttk.Button(self.frame_botones, text="Calcular Diseño", command=self.ejecutar_calculo)
        self.btn_limpiar = ttk.Button(self.frame_botones, text="🧹 Limpiar Datos", command=self.limpiar_datos)

        self.btn_calcular.pack(side=tk.LEFT, padx=5)
        self.btn_limpiar.pack(side=tk.LEFT, padx=5)

        # --- TABLA DE REFERENCIA DE CLASES DE MÁQUINAS ---
        self.lbl_ref_titulo = ttk.Label(self.frame_inputs, text="Guía de Selección (Doble clic para auto-seleccionar):", font=("Arial", 9, "bold"))
        self.lbl_ref_titulo.grid(row=0, column=6, columnspan=2, padx=10, pady=(0, 2), sticky="w")

        self.tree_maquinas = ttk.Treeview(self.frame_inputs, columns=("Clase", "Maquina"), show="headings", height=7)
        self.tree_maquinas.heading("Clase", text="Clase / Servicio")
        self.tree_maquinas.heading("Maquina", text="Aplicación / Tipo de Máquina")
        self.tree_maquinas.column("Clase", width=130, anchor="w")
        self.tree_maquinas.column("Maquina", width=300, anchor="w")
        
        tree_scroll = ttk.Scrollbar(self.frame_inputs, orient=tk.VERTICAL, command=self.tree_maquinas.yview)
        self.tree_maquinas.configure(yscrollcommand=tree_scroll.set)

        self.tree_maquinas.grid(row=1, column=6, rowspan=7, padx=(10, 0), pady=2, sticky="nsew")
        tree_scroll.grid(row=1, column=7, rowspan=7, pady=2, sticky="ns")

        datos_maquinas = [
            ("Clase 1 (Ligera)", "Agitadores (densidad uniforme)"),
            ("Clase 1 (Ligera)", "Sopladores y ventiladores (hasta 7.5 kW)"),
            ("Clase 1 (Ligera)", "Compresores y bombas centrífugas"),
            ("Clase 1 (Ligera)", "Transportadores de banda (carga uniforme)"),
            ("Clase 2 (Media)", "Agitadores y mezcladores (densidad variable)"),
            ("Clase 2 (Media)", "Sopladores y ventiladores (más de 7.5 kW)"),
            ("Clase 2 (Media)", "Compresores y bombas rotativas"),
            ("Clase 2 (Media)", "Transportadores de banda (no uniforme)"),
            ("Clase 2 (Media)", "Generadores y excitatrices"),
            ("Clase 2 (Media)", "Maquinaria de lavandería y líneas de ejes"),
            ("Clase 2 (Media)", "Herramientas y máquinas de taller"),
            ("Clase 2 (Media)", "Maquinaria de impresión y aserraderos"),
            ("Clase 2 (Media)", "Cribas rotativas (Screens)"),
            ("Clase 3 (Pesada)", "Maquinaria para ladrillo y elevadores"),
            ("Clase 3 (Pesada)", "Compresores y bombas reciprocantes"),
            ("Clase 3 (Pesada)", "Transportadores pesados y polipastos"),
            ("Clase 3 (Pesada)", "Molinos de martillos y pulverizadores"),
            ("Clase 3 (Pesada)", "Punzonadoras, prensas y cizallas"),
            ("Clase 3 (Pesada)", "Plantas de cantera y caucho"),
            ("Clase 3 (Pesada)", "Cribas vibratorias y textil"),
            ("Clase 4 (Extra Pesada)", "Trituradoras (giratorias / mandíbula / rodillos)"),
            ("Clase 4 (Extra Pesada)", "Molinos (bolas / barras / tubos)")
        ]
        for item in datos_maquinas:
            self.tree_maquinas.insert("", tk.END, values=item)

        self.tree_maquinas.bind("<Double-1>", self.seleccionar_maquina_desde_tabla)

        # Zona inferior (Informe y Gráficos)
        frame_bottom = ttk.Frame(self.contenido)
        frame_bottom.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, padx=10, pady=5)

        frame_output = ttk.LabelFrame(frame_bottom, text=" Memoria de Cálculo ")
        frame_output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self.txt_output = tk.Text(frame_output, wrap=tk.WORD, font=("Consolas", 9))
        scrollbar = ttk.Scrollbar(frame_output, orient=tk.VERTICAL, command=self.txt_output.yview)
        self.txt_output.configure(yscrollcommand=scrollbar.set)
        
        self.txt_output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        frame_graficas_container = ttk.LabelFrame(frame_bottom, text=" Visualización Gráfica ")
        # expand=True para que el panel de dibujos crezca con la ventana en vez de
        # quedar fijo y recortar el plano.
        frame_graficas_container.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        self.notebook_graficos = ttk.Notebook(frame_graficas_container)
        self.notebook_graficos.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.tab_transmision = ttk.Frame(self.notebook_graficos)
        self.notebook_graficos.add(self.tab_transmision, text=" Transmisión ")
        self.lbl_transmision = ttk.Label(self.tab_transmision, text="[ Sin Gráfico ]", anchor="center")
        self.lbl_transmision.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.tab_conductora = ttk.Frame(self.notebook_graficos)
        self.notebook_graficos.add(self.tab_conductora, text=" Polea Conductora ")
        self.lbl_conductora = ttk.Label(self.tab_conductora, text="[ Sin Gráfico ]", anchor="center")
        self.lbl_conductora.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.tab_conducida = ttk.Frame(self.notebook_graficos)
        self.notebook_graficos.add(self.tab_conducida, text=" Polea Conducida ")
        self.lbl_conducida = ttk.Label(self.tab_conducida, text="[ Sin Gráfico ]", anchor="center")
        self.lbl_conducida.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def al_seleccionar_material_manual(self, event=None):
        seleccion = self.cmb_pm_nombre.get()
        if not seleccion:
            return

        try:
            db_auto = nucleo_diseno_planas.BaseDatosPlanas("DATOS_SOFTWARE_planas.xlsx")
            fila = db_auto.belt_specifications[db_auto.belt_specifications['Tipo de correa'].str.strip() == seleccion.strip()]
            if not fila.empty:
                esp = float(fila['Espesor [mm]'].values[0])
                
                # Buscar la columna de tensión permisible de forma flexible
                # Fuerza periférica admisible por unidad de ancho (Fu, en N/mm). El
                # núcleo ya normaliza el nombre de esa columna al leer el Excel.
                t_perm = float(fila['Fuerza_periferica'].values[0])
                
                mu_val = float(fila['Coef_friccion'].values[0])
                masa_val = float(fila['Masa [kg/m2]'].values[0])
                densidad_calc = masa_val / (esp / 1000.0) if esp > 0 else 909.1

                # CORRECCIÓN: El esfuerzo admisible (MPa) es la tensión permisible (N/mm) dividida entre el espesor (mm)
                esfuerzo_adm = (t_perm / esp) if esp > 0 else 0.0

                # El Excel está en métrico; si la interfaz está en inglés hay que convertir
                # antes de escribir, o quedarían números métricos bajo rótulos en psi/pulg.
                if self._es_sistema_ingles():
                    esfuerzo_adm  = esfuerzo_adm / self.MPA_POR_PSI          # MPa    -> psi
                    esp           = esp / self.MM_POR_PULGADA               # mm     -> pulg
                    densidad_calc = densidad_calc / self.KGM3_POR_LBIN3     # kg/m³  -> lb/pulg³
                    fmt_esf, fmt_esp, fmt_den = f"{esfuerzo_adm:.1f}", f"{esp:.4f}", f"{densidad_calc:.6f}"
                else:
                    fmt_esf, fmt_esp, fmt_den = f"{esfuerzo_adm:.2f}", str(esp), f"{densidad_calc:.1f}"

                self.ent_pm_esfuerzo.delete(0, tk.END); self.ent_pm_esfuerzo.insert(0, fmt_esf)
                self.ent_pm_mu.delete(0, tk.END); self.ent_pm_mu.insert(0, str(mu_val))
                self.ent_pm_espesor.delete(0, tk.END); self.ent_pm_espesor.insert(0, fmt_esp)
                self.ent_pm_densidad.delete(0, tk.END); self.ent_pm_densidad.insert(0, fmt_den)
        except Exception as e:
            print(f"Error al autocompletar material manual: {e}")

    def seleccionar_maquina_desde_tabla(self, event):
        selected_item = self.tree_maquinas.selection()
        if not selected_item: return
        item_values = self.tree_maquinas.item(selected_item, "values")
        clase_str = item_values[0]

        tecnologia = self.cmb_tecnologia.get()
        if "Planas" not in tecnologia and self.cmb_v_familia.get().strip().upper() == "SERVICIO_LIVIANO":
            # La guia de clases pertenece al metodo industrial; en FHP el factor sale del
            # selector de maquina, asi que el doble clic no debe tocar nada.
            return
        if "Planas" in tecnologia:
            if "Clase 1" in clase_str: self.cmb_p_condicion.set("1. Servicio regular (Motores normales, bombas)")
            elif "Clase 2" in clase_str: self.cmb_p_condicion.set("2. Servicio irregular medio (Máquinas herramienta, ventiladores)")
            elif "Clase 3" in clase_str: self.cmb_p_condicion.set("3. Servicio irregular pesado (Compresores, prensas)")
            elif "Clase 4" in clase_str: self.cmb_p_condicion.set("4. Servicio muy severo (Trituradoras, molinos)")
        else:
            if "Clase 1" in clase_str: self.cmb_v_trans.set("LIGERA")
            elif "Clase 2" in clase_str: self.cmb_v_trans.set("MEDIA")
            elif "Clase 3" in clase_str: self.cmb_v_trans.set("PESADA")
            elif "Clase 4" in clase_str: self.cmb_v_trans.set("MUY PESADA")

    def cambiar_modo_tecnologia(self, event=None):
        tecnologia = self.cmb_tecnologia.get()
        
        widgets_a_ocultar = [
            self.lbl_v1, self.cmb_v_familia, self.lbl_v2, self.cmb_v_motor, self.lbl_v3, self.cmb_v_trans,
            self.lbl_fhp_maquina, self.cmb_fhp_maquina,
            self.lbl_v4, self.cmb_v_horas, self.lbl_v5, self.cmb_v_centros, self.lbl_v6, self.ent_v_c1,
            self.lbl_v7, self.ent_v_c2, self.lbl_v8, self.cmb_v_unidades,
            self.lbl_p_modo, self.cmb_p_modo, self.lbl_p1, self.cmb_p_serie,
            self.lbl_pm_nombre, self.cmb_pm_nombre, self.lbl_pm_esfuerzo, self.ent_pm_esfuerzo,
            self.lbl_pm_mu, self.ent_pm_mu, self.lbl_pm_espesor, self.ent_pm_espesor,
            self.lbl_pm_densidad, self.ent_pm_densidad, self.lbl_pm_ancho, self.ent_pm_ancho,
            self.lbl_p_par, self.cmb_p_par, self.lbl_p2, self.cmb_p_condicion, self.lbl_p_horas, self.cmb_p_horas,
            self.lbl_p_unidades, self.cmb_p_unidades,
            self.lbl_p4, self.ent_p_centros, self.lbl_d1, self.ent_d1,
            self.lbl_eje1, self.ent_eje1, self.lbl_eje2, self.ent_eje2, self.frame_botones,
            self.chk_motor_electrico, self.chk_normalizar
        ]
        for w in widgets_a_ocultar:
            w.grid_remove()

        if "Planas" in tecnologia:
            self.lbl_p_modo.grid(row=1, column=0, padx=5, pady=5, sticky="w")
            self.cmb_p_modo.grid(row=1, column=1, columnspan=2, padx=5, pady=5, sticky="ew")

            self.cambiar_modo_planas()
        else:
            self.lbl_n2.config(text="Velocidad n2 (RPM):")
            self.lbl_v1.grid(row=1, column=0, padx=5, pady=5, sticky="w")
            self.cmb_v_familia.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
            self.lbl_v2.grid(row=1, column=2, padx=5, pady=5, sticky="w")
            self.cmb_v_motor.grid(row=1, column=3, padx=5, pady=5, sticky="ew")
            self.lbl_v3.grid(row=1, column=4, padx=5, pady=5, sticky="w")
            self.cmb_v_trans.grid(row=1, column=5, padx=5, pady=5, sticky="ew")

            self.lbl_v4.grid(row=2, column=0, padx=5, pady=5, sticky="w")
            self.cmb_v_horas.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
            self.lbl_d1.grid(row=2, column=2, padx=5, pady=5, sticky="w")
            self.ent_d1.grid(row=2, column=3, padx=5, pady=5, sticky="ew")
            self.lbl_v5.grid(row=2, column=4, padx=5, pady=5, sticky="w")
            self.cmb_v_centros.grid(row=2, column=5, padx=5, pady=5, sticky="ew")
            self.cmb_v_centros.bind("<<ComboboxSelected>>", self.actualizar_campos_centros_v)

            self.lbl_v6.grid(row=3, column=0, padx=5, pady=5, sticky="w")
            self.ent_v_c1.grid(row=3, column=1, padx=5, pady=5, sticky="ew")
            self.lbl_v7.grid(row=3, column=2, padx=5, pady=5, sticky="w")
            self.ent_v_c2.grid(row=3, column=3, padx=5, pady=5, sticky="ew")
            self.lbl_v8.grid(row=3, column=4, padx=5, pady=5, sticky="w")
            self.cmb_v_unidades.grid(row=3, column=5, padx=5, pady=5, sticky="ew")

            self.lbl_eje1.grid(row=4, column=0, padx=5, pady=5, sticky="w")
            self.ent_eje1.grid(row=4, column=1, padx=5, pady=5, sticky="ew")
            self.lbl_eje2.grid(row=4, column=2, padx=5, pady=5, sticky="w")
            self.ent_eje2.grid(row=4, column=3, padx=5, pady=5, sticky="ew")

            self.chk_motor_electrico.grid(row=4, column=4, columnspan=2, padx=5, pady=5, sticky="w")
            self.chk_normalizar.grid(row=5, column=0, columnspan=4, padx=5, pady=5, sticky="w")

            self.frame_botones.grid(row=6, column=0, columnspan=6, pady=10)
            self.actualizar_campos_centros_v()
            self.cambiar_modo_familia_v()

        self.actualizar_etiquetas_unidades()

    def cambiar_modo_familia_v(self, event=None):
        """Muestra los campos que corresponden a la familia normativa elegida.

        SERVICIO_LIVIANO (perfiles 3L, 4L y 5L) se rige por la norma FHP, cuyo factor de
        servicio combinado depende unicamente de la maquina accionada y de la relacion de
        transmision. Por eso se ocultan el tipo de motor, el tipo de transmision y las
        horas de operacion: en esta familia no intervienen en ningun calculo, y dejarlos a
        la vista sugiere que si lo hacen.
        """
        if "Planas" in self.cmb_tecnologia.get():
            return

        es_fhp = self.cmb_v_familia.get().strip().upper() == "SERVICIO_LIVIANO"

        industriales = (self.lbl_v2, self.cmb_v_motor,      # tipo de motor
                        self.lbl_v3, self.cmb_v_trans,      # tipo de transmision
                        self.lbl_v4, self.cmb_v_horas)      # horas de operacion

        if es_fhp:
            for w in industriales:
                w.grid_remove()
            self.lbl_fhp_maquina.grid(row=1, column=2, padx=5, pady=5, sticky="w")
            self.cmb_fhp_maquina.grid(row=1, column=3, columnspan=3, padx=5, pady=5, sticky="ew")
        else:
            self.lbl_fhp_maquina.grid_remove()
            self.cmb_fhp_maquina.grid_remove()
            self.lbl_v2.grid(row=1, column=2, padx=5, pady=5, sticky="w")
            self.cmb_v_motor.grid(row=1, column=3, padx=5, pady=5, sticky="ew")
            self.lbl_v3.grid(row=1, column=4, padx=5, pady=5, sticky="w")
            self.cmb_v_trans.grid(row=1, column=5, padx=5, pady=5, sticky="ew")
            self.lbl_v4.grid(row=2, column=0, padx=5, pady=5, sticky="w")
            self.cmb_v_horas.grid(row=2, column=1, padx=5, pady=5, sticky="ew")

    def cambiar_modo_planas(self, event=None):
        modo = self.cmb_p_modo.get()
        
        if "Catálogo" in modo:
            self.lbl_pm_nombre.grid_remove(); self.cmb_pm_nombre.grid_remove()
            self.lbl_pm_esfuerzo.grid_remove(); self.ent_pm_esfuerzo.grid_remove()
            self.lbl_pm_mu.grid_remove(); self.ent_pm_mu.grid_remove()
            self.lbl_pm_espesor.grid_remove(); self.ent_pm_espesor.grid_remove()
            self.lbl_pm_densidad.grid_remove(); self.ent_pm_densidad.grid_remove()
            self.lbl_pm_ancho.grid_remove(); self.ent_pm_ancho.grid_remove()

            self.lbl_p1.grid(row=2, column=0, padx=5, pady=5, sticky="w")
            self.cmb_p_serie.grid(row=2, column=1, columnspan=2, padx=5, pady=5, sticky="ew")
            self.lbl_n2.config(text="Velocidad n2 (RPM):")
        else:
            self.lbl_p1.grid_remove(); self.cmb_p_serie.grid_remove()

            self.lbl_pm_nombre.grid(row=2, column=0, padx=5, pady=5, sticky="w")
            self.cmb_pm_nombre.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
            self.lbl_pm_esfuerzo.grid(row=2, column=2, padx=5, pady=5, sticky="w")
            self.ent_pm_esfuerzo.grid(row=2, column=3, padx=5, pady=5, sticky="ew")

            self.lbl_pm_mu.grid(row=3, column=0, padx=5, pady=5, sticky="w")
            self.ent_pm_mu.grid(row=3, column=1, padx=5, pady=5, sticky="ew")
            self.lbl_pm_espesor.grid(row=3, column=2, padx=5, pady=5, sticky="w")
            self.ent_pm_espesor.grid(row=3, column=3, padx=5, pady=5, sticky="ew")

            self.lbl_pm_densidad.grid(row=4, column=0, padx=5, pady=5, sticky="w")
            self.ent_pm_densidad.grid(row=4, column=1, padx=5, pady=5, sticky="ew")
            self.lbl_pm_ancho.grid(row=4, column=2, padx=5, pady=5, sticky="w")
            self.ent_pm_ancho.grid(row=4, column=3, padx=5, pady=5, sticky="ew")

            self.lbl_n2.config(text="Velocidad n2 (RPM) (Opcional):")

        r_base = 3 if "Catálogo" in modo else 5
        
        self.lbl_p_par.grid(row=r_base, column=0, padx=5, pady=5, sticky="w")
        self.cmb_p_par.grid(row=r_base, column=1, columnspan=2, padx=5, pady=5, sticky="ew")

        self.lbl_p2.grid(row=r_base+1, column=0, padx=5, pady=5, sticky="w")
        self.cmb_p_condicion.grid(row=r_base+1, column=1, columnspan=2, padx=5, pady=5, sticky="ew")

        self.lbl_p_horas.grid(row=r_base+2, column=0, padx=5, pady=5, sticky="w")
        self.cmb_p_horas.grid(row=r_base+2, column=1, padx=5, pady=5, sticky="ew")

        self.lbl_p_unidades.grid(row=r_base+2, column=2, padx=5, pady=5, sticky="w")
        self.cmb_p_unidades.grid(row=r_base+2, column=3, padx=5, pady=5, sticky="ew")

        self.lbl_p4.grid(row=r_base+3, column=0, padx=5, pady=5, sticky="w")
        self.ent_p_centros.grid(row=r_base+3, column=1, padx=5, pady=5, sticky="ew")

        self.lbl_d1.grid(row=r_base+3, column=2, padx=5, pady=5, sticky="w")
        self.ent_d1.grid(row=r_base+3, column=3, padx=5, pady=5, sticky="ew")

        self.chk_motor_electrico.grid(row=r_base+4, column=0, columnspan=3, padx=5, pady=5, sticky="w")

        self.lbl_eje1.grid(row=r_base+5, column=0, padx=5, pady=5, sticky="w")
        self.ent_eje1.grid(row=r_base+5, column=1, padx=5, pady=5, sticky="ew")

        self.lbl_eje2.grid(row=r_base+5, column=2, padx=5, pady=5, sticky="w")
        self.ent_eje2.grid(row=r_base+5, column=3, padx=5, pady=5, sticky="ew")

        self.frame_botones.grid(row=r_base+6, column=0, columnspan=6, pady=10)

        # El rótulo de potencia (y el sufijo "Opcional") depende del modo Y del sistema
        # de unidades, así que se delega en un único lugar en vez de fijarlo aquí.
        self.actualizar_etiquetas_unidades()

    # --- Factores de conversión métrico -> inglés (deben coincidir con el núcleo) ---
    MM_POR_PULGADA = 25.4
    KW_POR_HP      = 0.7457
    MPA_POR_PSI    = 0.0068947572932
    KGM3_POR_LBIN3 = 27679.9047

    def _es_sistema_ingles(self) -> bool:
        """Sistema de unidades activo según la tecnología seleccionada. Devuelve False de
        forma segura si se llama antes de que existan los combos (durante la construcción)."""
        try:
            if "Planas" in self.cmb_tecnologia.get():
                return "Inglés" in self.cmb_p_unidades.get()
            return "Inglés" in self.cmb_v_unidades.get()
        except Exception:
            return False

    def _convertir_valor_campo(self, entry, factor_metrico_a_ingles, a_ingles):
        """Reescala el contenido numérico de un campo al cambiar de sistema de unidades,
        para que el valor físico que el usuario ya escribió se conserve."""
        try:
            texto = entry.get().strip()
            if not texto:
                return
            valor = float(texto.replace(",", "."))
            nuevo = valor / factor_metrico_a_ingles if a_ingles else valor * factor_metrico_a_ingles
            entry.delete(0, tk.END)
            # Cifras significativas, no decimales fijos: una densidad en lb/pulg³ ronda
            # 0.0397 y con 4 decimales se perdería precisión al volver a métrico.
            entry.insert(0, f"{nuevo:.8g}")
        except (ValueError, AttributeError, tk.TclError):
            pass  # si no es numérico se deja tal cual

    def _reescalar_entradas(self, a_ingles: bool):
        """Convierte todos los campos dimensionales al nuevo sistema. Las rpm y el
        coeficiente de fricción no se tocan por ser invariantes/adimensionales."""
        MM, KW = self.MM_POR_PULGADA, self.KW_POR_HP
        longitudes = [self.ent_d1, self.ent_p_centros, self.ent_v_c1, self.ent_v_c2,
                      self.ent_eje1, self.ent_eje2, self.ent_pm_espesor, self.ent_pm_ancho]
        for ent in longitudes:
            self._convertir_valor_campo(ent, MM, a_ingles)
        self._convertir_valor_campo(self.ent_potencia,     KW, a_ingles)
        self._convertir_valor_campo(self.ent_pm_esfuerzo,  self.MPA_POR_PSI,    a_ingles)
        self._convertir_valor_campo(self.ent_pm_densidad,  self.KGM3_POR_LBIN3, a_ingles)

    def actualizar_etiquetas_unidades(self, event=None):
        tecnologia = self.cmb_tecnologia.get()
        es_planas = "Planas" in tecnologia
        is_ing = self._es_sistema_ingles()

        # Si el usuario cambió de sistema, se reescala lo que ya haya escrito para no
        # dejar números métricos bajo etiquetas inglesas (o al revés).
        anterior = getattr(self, "_ultimo_is_ing", None)
        if anterior is not None and anterior != is_ing:
            self._reescalar_entradas(a_ingles=is_ing)
        self._ultimo_is_ing = is_ing

        u_pot = "HP"        if is_ing else "kW"
        u_dim = "pulg"      if is_ing else "mm"
        u_esf = "psi"       if is_ing else "MPa"
        u_den = "lb/pulg³"  if is_ing else "kg/m³"

        # La potencia es opcional únicamente en el modo Manual / Académico de bandas planas
        opcional_pot = es_planas and "Manual" in self.cmb_p_modo.get()
        self.lbl_pot.config(text=f"Potencia Nominal ({u_pot}):" + (" (Opcional)" if opcional_pot else ""))

        self.lbl_d1.config(text=f"D1 Conductora ({u_dim}) (Opcional):")
        self.lbl_v6.config(text=f"Dist. Mínima / C1 ({u_dim}):")
        self.lbl_v7.config(text=f"Dist. Máxima / C2 ({u_dim}):")
        self.lbl_p4.config(text=f"Dist. Centros ({u_dim}) (Opcional):")
        self.lbl_eje1.config(text=f"Diámetro Eje Motor d1 ({u_dim}):")
        self.lbl_eje2.config(text=f"Diámetro Eje Conducida d2 ({u_dim}):")

        # Campos del modo Manual / Académico, que antes conservaban siempre el rótulo métrico
        self.lbl_pm_esfuerzo.config(text=f"Esfuerzo Admisible ({u_esf}):")
        self.lbl_pm_espesor.config(text=f"Espesor ({u_dim}):")
        self.lbl_pm_densidad.config(text=f"Densidad ({u_den}):")
        self.lbl_pm_ancho.config(text=f"Ancho de Banda ({u_dim}):")

    def actualizar_campos_centros_v(self, event=None):
        if "Planas" in self.cmb_tecnologia.get(): return
        modo = self.cmb_v_centros.get()
        is_ing = "Inglés" in self.cmb_v_unidades.get()
        u_dim = "pulg" if is_ing else "mm"

        if modo == "FIJO":
            self.lbl_v6.config(text=f"Dist. Fija de Centros ({u_dim}):")
            self.lbl_v6.grid(); self.ent_v_c1.grid()
            self.lbl_v7.grid_remove(); self.ent_v_c2.grid_remove()
        elif modo == "RANGO":
            self.lbl_v6.config(text=f"Dist. Mínima / C1 ({u_dim}):")
            self.lbl_v6.grid(); self.ent_v_c1.grid()
            self.lbl_v7.grid(); self.ent_v_c2.grid()
            self.lbl_v7.config(text=f"Dist. Máxima / C2 ({u_dim}):")
        else:
            self.lbl_v6.grid_remove(); self.ent_v_c1.grid_remove()
            self.lbl_v7.grid_remove(); self.ent_v_c2.grid_remove()

    def limpiar_datos(self):
        campos_entrada = [
            self.ent_potencia, self.ent_n1, self.ent_n2, self.ent_d1,
            self.ent_v_c1, self.ent_v_c2, self.ent_p_centros,
            self.ent_eje1, self.ent_eje2,
            self.ent_pm_esfuerzo, self.ent_pm_mu,
            self.ent_pm_espesor, self.ent_pm_densidad, self.ent_pm_ancho
        ]
        
        for ent in campos_entrada:
            try:
                ent.delete(0, tk.END)
            except Exception:
                pass
        
        self.chk_motor_electrico_var.set(True)
        self.chk_normalizar_var.set(True)

        self.txt_output.delete("1.0", tk.END)
        for etiqueta in (self.lbl_transmision, self.lbl_conductora, self.lbl_conducida):
            etiqueta._ruta_svg = None          # si no, el reajuste por resize los redibuja
            etiqueta.config(text="[ Sin Gráfico ]", image="")
            etiqueta.image = None
        
        messagebox.showinfo("Limpieza Exitosa", "Todos los campos han sido borrados. Listo para un nuevo problema.")

    def ejecutar_calculo(self):
        tecnologia = self.cmb_tecnologia.get()
        try:
            pot_val = self.ent_potencia.get().strip()
            pot = float(pot_val) if pot_val else None

            n1 = float(self.ent_n1.get())
            
            n2_val = self.ent_n2.get().strip()
            if n2_val:
                n2 = float(n2_val)
            else:
                n2 = n1 if "Planas" in tecnologia and "Manual" in self.cmb_p_modo.get() else 0.0

            d1_val = self.ent_d1.get().strip()
            d1_usr = float(d1_val) if d1_val else None

            if "Planas" in tecnologia:
                condicion_op = self.cmb_p_condicion.get()
                horas_rango = self.cmb_p_horas.get()
                tipo_par_sel = self.cmb_p_par.get()
                
                c_val_str = self.ent_p_centros.get().strip()
                c_val = float(c_val_str) if c_val_str else None

                d_eje1_usr = float(self.ent_eje1.get().strip()) if self.ent_eje1.get().strip() else None
                d_eje2_usr = float(self.ent_eje2.get().strip()) if self.ent_eje2.get().strip() else None
                is_ing = "Inglés" in self.cmb_p_unidades.get()

                modo_sel = self.cmb_p_modo.get()

                if "Catálogo" in modo_sel:
                    if not n2_val: raise ValueError("Para el modo Catálogo de Bandas Planas, la velocidad n2 es obligatoria.")
                    serie_texto = self.cmb_p_serie.get()
                    grupo_letra = serie_texto.split(" ")[1].replace("(", "").strip()
                    
                    resultados = nucleo_diseno_planas.ejecutar_diseno_bandas_planas(
                        potencia_in=pot, n_conductora=n1, n_conducida=n2,
                        condicion_operacion=condicion_op, horas_servicio=horas_rango,
                        tipo_par=tipo_par_sel, user_d_driver=d1_usr,
                        C_usuario=c_val, d_eje_1_in=d_eje1_usr, d_eje_2_in=d_eje2_usr,
                        grupo_correa_usuario=grupo_letra, is_ing=is_ing, ruta_excel="DATOS_SOFTWARE_planas.xlsx",
                        es_motor_electrico=self.chk_motor_electrico_var.get()
                    )
                else:
                    nombre_m = self.cmb_pm_nombre.get().strip()
                    esf_m = float(self.ent_pm_esfuerzo.get().strip()) if self.ent_pm_esfuerzo.get().strip() else 22.6
                    mu_m = float(self.ent_pm_mu.get().strip()) if self.ent_pm_mu.get().strip() else 0.8
                    esp_m = float(self.ent_pm_espesor.get().strip()) if self.ent_pm_espesor.get().strip() else 5.5
                    den_m = float(self.ent_pm_densidad.get().strip()) if self.ent_pm_densidad.get().strip() else 909.1
                    ancho_m = float(self.ent_pm_ancho.get().strip()) if self.ent_pm_ancho.get().strip() else None

                    resultados = nucleo_diseno_planas.ejecutar_diseno_bandas_planas(
                        potencia_in=pot, n_conductora=n1, n_conducida=n2,
                        condicion_operacion=condicion_op, horas_servicio=horas_rango,
                        tipo_par=tipo_par_sel, user_d_driver=d1_usr,
                        C_usuario=c_val, d_eje_1_in=d_eje1_usr, d_eje_2_in=d_eje2_usr,
                        grupo_correa_usuario="MANUAL", is_ing=is_ing, ruta_excel="DATOS_SOFTWARE_planas.xlsx",
                        user_nombre_correa=nombre_m, user_esfuerzo_adm=esf_m,
                        user_mu=mu_m, user_espesor=esp_m, user_densidad=den_m,
                        user_ancho_manual=ancho_m,
                        es_motor_electrico=self.chk_motor_electrico_var.get()
                    )

                informe = nucleo_diseno_planas.generar_informe_planas(resultados, is_ing=is_ing)
                self.txt_output.delete("1.0", tk.END)
                self.txt_output.insert(tk.END, informe)

                archivo_svg_1 = nucleo_diseno_planas.generar_svg_polea(
                    resultados, es_conductora=True, carpeta_salida=self.carpeta_temporal)
                archivo_svg_2 = nucleo_diseno_planas.generar_svg_polea(
                    resultados, es_conductora=False, carpeta_salida=self.carpeta_temporal)
                archivo_transmision, _ = nucleo_diseno_planas.generar_svg_transmision(
                    resultados, carpeta_salida=self.carpeta_temporal)

                self.cargar_grafica_en_etiqueta(archivo_transmision, self.lbl_transmision)
                self.cargar_grafica_en_etiqueta(archivo_svg_1, self.lbl_conductora)
                self.cargar_grafica_en_etiqueta(archivo_svg_2, self.lbl_conducida)

            else:
                if not n2_val: raise ValueError("Para Bandas en V, la velocidad n2 es obligatoria.")
                if pot is None: pot = 50.0
                motor = self.cmb_v_motor.get()
                horas = self.cmb_v_horas.get()
                modo_c = self.cmb_v_centros.get()
                fam = self.cmb_v_familia.get()
                trans = self.cmb_v_trans.get()

                # En FHP el parametro 'tipo_transmision' del nucleo transporta la MAQUINA
                # accionada, que es la unica entrada del factor de servicio combinado.
                if fam.strip().upper() == "SERVICIO_LIVIANO":
                    trans = self.cmb_fhp_maquina.get()

                c_val_1 = float(self.ent_v_c1.get().strip()) if self.ent_v_c1.get().strip() else None
                c_val_2 = float(self.ent_v_c2.get().strip()) if (self.ent_v_c2.get().strip() and modo_c != "FIJO") else None

                d_eje1_usr = float(self.ent_eje1.get().strip()) if self.ent_eje1.get().strip() else None
                d_eje2_usr = float(self.ent_eje2.get().strip()) if self.ent_eje2.get().strip() else None

                is_ing = "Inglés" in self.cmb_v_unidades.get()

                resultados = nucleo_diseno_correas.ejecutar_diseno_transmision(
                    potencia_in=pot, n1=n1, n2=n2, tipo_motor=motor, tipo_transmision=trans,
                    horas_operacion=horas, familia=fam, D1_usuario_in=d1_usr,
                    modo_centros=modo_c, c_valor_1=c_val_1, c_valor_2=c_val_2,
                    d_eje_1_in=d_eje1_usr, d_eje_2_in=d_eje2_usr, is_ing=is_ing,
                    ruta_excel="DATOS SOFTWARE.xlsx",
                    es_motor_electrico=self.chk_motor_electrico_var.get(),
                    normalizar_diametros=self.chk_normalizar_var.get()
                )

                rutas_planos = visualizacion_correas.exportar_planos_completos(
                    resultados, is_ing=is_ing, carpeta_salida=self.carpeta_temporal)
                informe = nucleo_diseno_correas.generar_informe_completo(resultados, is_ing=is_ing)
                
                self.txt_output.delete("1.0", tk.END)
                self.txt_output.insert(tk.END, informe)

                self.cargar_grafica_en_etiqueta(rutas_planos["transmision"], self.lbl_transmision)
                self.cargar_grafica_en_etiqueta(rutas_planos["conductora"], self.lbl_conductora)
                self.cargar_grafica_en_etiqueta(rutas_planos["conducida"], self.lbl_conducida)

        except Exception as e:
            messagebox.showerror("Error en el Cálculo", f"Ocurrió un error procesando los datos:\n{str(e)}")

    # Tamaño mínimo del área de dibujo (ancho, alto) en píxeles
    TAM_GRAFICO_MIN = (380, 360)

    def cargar_grafica_en_etiqueta(self, ruta_svg, label_widget):
        """Registra el plano asociado a la pestaña y lo dibuja ajustado al área visible."""
        label_widget._ruta_svg = ruta_svg if (ruta_svg and os.path.exists(ruta_svg)) else None
        if label_widget._ruta_svg is None:
            nombre = os.path.basename(ruta_svg) if ruta_svg else "(sin plantilla)"
            label_widget.config(text=f"[ Plano no generado: {nombre} ]", image="")
            label_widget.image = None
            return
        self._renderizar_svg(label_widget)

    def _renderizar_svg(self, label_widget):
        """Rasteriza el SVG RESPETANDO su relación de aspecto y lo encaja completo dentro
        del área disponible. Antes se forzaban 450x420 px, lo que deformaba el dibujo y
        recortaba las cotas que caían fuera de esa caja."""
        ruta = getattr(label_widget, "_ruta_svg", None)
        if not ruta:
            return
        try:
            ancho_caja, alto_caja = getattr(self, "_caja_grafico", self.TAM_GRAFICO_MIN)
            # Se fija SOLO el ancho de salida: cairosvg deduce el alto conservando la
            # proporción original del dibujo. Se rasteriza al doble para que al reducir
            # con LANCZOS las cotas se lean nítidas.
            # Se pasa el CONTENIDO del archivo y no su ruta: los planos viven ahora en la
            # carpeta temporal, con una ruta absoluta (en Windows, con letra de unidad y
            # espacios) que no conviene dejar a la interpretación de cairosvg como URL.
            with open(ruta, "rb") as f:
                contenido_svg = f.read()
            png_data = cairosvg.svg2png(bytestring=contenido_svg,
                                        output_width=max(1200, ancho_caja * 2))
            imagen_pil = Image.open(io.BytesIO(png_data))
            imagen_pil.thumbnail((ancho_caja, alto_caja), Image.LANCZOS)
            img_tk = ImageTk.PhotoImage(imagen_pil)
            label_widget.config(image=img_tk, text="")
            label_widget.image = img_tk
        except Exception as e:
            label_widget.config(text=f"[ Error renderizando gráfico ]\n{e}", image="")
            label_widget.image = None

    def _al_redimensionar_ventana(self, event=None):
        """El área de dibujo se recalcula a partir del tamaño de la VENTANA (nunca del
        tamaño de la imagen), de modo que no se realimenta a sí misma."""
        if event is not None and event.widget is not self:
            return
        tam = (self.winfo_width(), self.winfo_height())
        if tam == getattr(self, "_ultimo_tam_ventana", None):
            return
        self._ultimo_tam_ventana = tam
        if getattr(self, "_job_reajuste", None):
            self.after_cancel(self._job_reajuste)
        self._job_reajuste = self.after(250, self._reajustar_graficos)

    def _reajustar_graficos(self):
        self._job_reajuste = None
        ancho_v, alto_v = self.winfo_width(), self.winfo_height()
        self._caja_grafico = (
            max(self.TAM_GRAFICO_MIN[0], min(760, int(ancho_v * 0.34))),
            max(self.TAM_GRAFICO_MIN[1], int(alto_v * 0.45)),
        )
        for etiqueta in (self.lbl_transmision, self.lbl_conductora, self.lbl_conducida):
            if getattr(etiqueta, "_ruta_svg", None):
                self._renderizar_svg(etiqueta)

if __name__ == "__main__":
    app = AppDisenoCorreas()
    app.mainloop()