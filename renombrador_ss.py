"""
Renombrador de PDFs - Seguridad Social
=======================================
Dos modos de funcionamiento:

  1. RLC / RNT  →  Detecta tipo de documento, extrae Razón Social y organiza
                   por carpetas de cliente.

  2. Notificaciones TGSS  →  Extrae Apellidos y Nombre/R.Social del campo
                              correspondiente y renombra como:
                              NotificacionTGSS_NombreCliente.pdf

En ambos modos el usuario puede elegir:
  - Renombrar en la carpeta de origen (los archivos se quedan donde están)
  - Mover a una carpeta de destino nueva (se crea si no existe)
  - Crear subcarpetas por cliente dentro del destino

Compatible con macOS y Windows.
Requiere: pdfplumber
"""

import os
import re
import sys
import shutil
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import pdfplumber
except ImportError:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Dependencia faltante",
        "No se encontró la librería 'pdfplumber'.\n\n"
        "Instálala ejecutando en Terminal:\n\n"
        "    pip3 install pdfplumber\n\n"
        "Luego vuelve a abrir la aplicación."
    )
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# PATRONES  –  RLC / RNT
# ─────────────────────────────────────────────────────────────────────────────
PATRONES_TIPO = {
    "RNT": [
        r"RELACI[OÓ]N\s+NOMINAL\s+DE\s+TRABAJADORES",
        r"[Rr]elaci[oó]n\s+[Nn]ominal\s+de\s+[Tt]rabajadores",
        r"relaci[oó]n\s+nominal",
    ],
    "RLC": [
        r"[Rr]ecibo\s+de\s+[Ll]iquidaci[oó]n\s+de\s+[Cc]otizaciones",
        r"RECIBO\s+DE\s+LIQUIDACI[OÓ]N",
        r"[Rr]ecibo\s+de\s+[Ll]iquidaci[oó]n",
    ],
}

PATRONES_RAZON_RLC = [
    r"Raz[oó]n\s+[Ss]ocial\s+([A-ZÁÉÍÓÚÜÑ][^\n]+?)\s{2,}",
    r"Raz[oó]n\s+[Ss]ocial:\s+([^\n]+?)\s+(?:N[uú]mero|C[oó]digo|Periodo|Entidad)",
    r"Raz[oó]n\s+[Ss]ocial[:\s]+(.+)",
]

# ─────────────────────────────────────────────────────────────────────────────
# PATRONES  –  Notificaciones TGSS  (cubre todos los formatos conocidos)
# ─────────────────────────────────────────────────────────────────────────────
# Los patrones se aplican en orden de prioridad (más específico primero).
# Cada uno captura el nombre/razón social en el grupo 1.
PATRONES_NOMBRE_NOTIF = [
    # Doc 3, 4: "Apellidos y nombre/R.Social: NOMBRE"  (con o sin espacio, mayúsculas/minúsculas)
    r"Apellidos\s+y\s+[Nn]ombre/R\.?[Ss]ocial:\s+([^\n]+)",
    # Doc 3, 4 (misma línea con NIF): "NIF/CIF: X  Apellidos y nombre/R.Social: NOMBRE"
    r"NIF/CIF:[^\n]+?Apellidos\s+y\s+[Nn]ombre/R\.?[Ss]ocial:\s+([^\n]+)",
    # Doc 7: "RAZÓN SOCIAL: NOMBRE" al inicio de línea
    r"^RAZ[ÓO]N\s+SOCIAL:\s+(.+)",
    # Doc 5: "Nombre o Razón Social" seguido de línea con el nombre
    r"Nombre\s+o\s+Raz[oó]n\s+Social\s*\n([^\n]+)",
    # Doc 1: "Régimen/C.C.C./Razón social\n0111 / 28 XXXXXX / NOMBRE"
    r"R[eé]gimen/C\.C\.C\./Raz[oó]n\s+social\s*\n[^\n]+/\s*([^\n]+)",
    # Doc 6: "Hola, NOMBRE:" al inicio del documento
    r"^Hola,\s+([^:]+):",
    # Genérico: "R.Social: NOMBRE" o "Razón Social: NOMBRE"
    r"R\.?[Ss]ocial:\s+([^\n]+)",
    r"Raz[oó]n\s+[Ss]ocial[:\s]+([A-ZÁÉÍÓÚÜÑ][^\n]+)",
]


# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES COMUNES
# ─────────────────────────────────────────────────────────────────────────────
def extraer_texto_pdf(ruta):
    texto = ""
    with pdfplumber.open(ruta) as pdf:
        for pagina in pdf.pages[:3]:
            t = pagina.extract_text()
            if t:
                texto += t + "\n"
    return texto


def limpiar_nombre(nombre):
    """Elimina caracteres no válidos para nombres de archivo/carpeta."""
    nombre = re.sub(r'[\\/:*?"<>|]', "_", nombre)
    return nombre.strip()[:80]


def nombre_unico(carpeta, base, ext):
    """Genera un nombre único añadiendo sufijo numérico si ya existe."""
    candidato = base + ext
    if not os.path.exists(os.path.join(carpeta, candidato)):
        return candidato
    n = 1
    while True:
        candidato = f"{base}_{n}{ext}"
        if not os.path.exists(os.path.join(carpeta, candidato)):
            return candidato
        n += 1


# ─────────────────────────────────────────────────────────────────────────────
# LÓGICA  –  RLC / RNT
# ─────────────────────────────────────────────────────────────────────────────
def detectar_tipo_rlc_rnt(texto):
    for tipo, patrones in PATRONES_TIPO.items():
        for patron in patrones:
            if re.search(patron, texto):
                return tipo
    return None


def detectar_razon_social(texto):
    for patron in PATRONES_RAZON_RLC:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            nombre = limpiar_nombre(m.group(1))
            if nombre:
                return nombre
    return None


# ─────────────────────────────────────────────────────────────────────────────
# LÓGICA  –  Notificaciones TGSS
# ─────────────────────────────────────────────────────────────────────────────
def detectar_nombre_notificacion(texto):
    for patron in PATRONES_NOMBRE_NOTIF:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            nombre = limpiar_nombre(m.group(1).strip())
            if nombre:
                return nombre
    return None


# ─────────────────────────────────────────────────────────────────────────────
# WIDGET REUTILIZABLE: Panel de carpeta
# ─────────────────────────────────────────────────────────────────────────────
class PanelCarpeta(tk.Frame):
    """
    Panel con:
      - Selector de carpeta de origen
      - Opción de destino: misma carpeta / carpeta nueva
      - Checkbox: crear subcarpetas por cliente
    """
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg="#f0f2f5", **kwargs)
        self._origen = tk.StringVar()
        self._destino = tk.StringVar()
        self._modo_destino = tk.StringVar(value="origen")  # "origen" | "nueva"
        self._crear_subcarpetas = tk.BooleanVar(value=False)
        self._build()

    def _build(self):
        # ── Carpeta origen ────────────────────────────────────────────────────
        tk.Label(self, text="Carpeta con los PDFs:",
                 font=("Helvetica", 10, "bold"),
                 bg="#f0f2f5", anchor="w").pack(fill="x", pady=(0, 3))

        row1 = tk.Frame(self, bg="#f0f2f5")
        row1.pack(fill="x", pady=(0, 10))
        self._entry_origen = tk.Entry(row1, textvariable=self._origen,
                                      font=("Helvetica", 10), state="readonly",
                                      bg="white", relief="solid", bd=1)
        self._entry_origen.pack(side="left", fill="x", expand=True, ipady=4)
        tk.Button(row1, text="Examinar…", command=self._sel_origen,
                  bg="#e8eef7", relief="solid", bd=1,
                  font=("Helvetica", 10), padx=8).pack(side="left", padx=(5, 0), ipady=4)

        # ── Destino ───────────────────────────────────────────────────────────
        tk.Label(self, text="¿Dónde guardar los archivos renombrados?",
                 font=("Helvetica", 10, "bold"),
                 bg="#f0f2f5", anchor="w").pack(fill="x", pady=(0, 3))

        rb_frame = tk.Frame(self, bg="#f0f2f5")
        rb_frame.pack(fill="x", pady=(0, 4))
        tk.Radiobutton(rb_frame, text="En la misma carpeta de origen",
                       variable=self._modo_destino, value="origen",
                       command=self._toggle_destino,
                       bg="#f0f2f5", activebackground="#f0f2f5",
                       font=("Helvetica", 10)).pack(side="left")
        tk.Radiobutton(rb_frame, text="En una carpeta nueva:",
                       variable=self._modo_destino, value="nueva",
                       command=self._toggle_destino,
                       bg="#f0f2f5", activebackground="#f0f2f5",
                       font=("Helvetica", 10)).pack(side="left", padx=(16, 0))

        row2 = tk.Frame(self, bg="#f0f2f5")
        row2.pack(fill="x", pady=(0, 10))
        self._entry_destino = tk.Entry(row2, textvariable=self._destino,
                                       font=("Helvetica", 10), state="disabled",
                                       bg="#e0e0e0", relief="solid", bd=1)
        self._entry_destino.pack(side="left", fill="x", expand=True, ipady=4)
        self._btn_destino = tk.Button(row2, text="Examinar…",
                                      command=self._sel_destino,
                                      bg="#e8eef7", relief="solid", bd=1,
                                      font=("Helvetica", 10), padx=8,
                                      state="disabled")
        self._btn_destino.pack(side="left", padx=(5, 0), ipady=4)

        # ── Subcarpetas ───────────────────────────────────────────────────────
        tk.Checkbutton(self,
                       text="Crear subcarpeta por cliente con todos sus documentos",
                       variable=self._crear_subcarpetas,
                       font=("Helvetica", 10),
                       bg="#f0f2f5", anchor="w",
                       activebackground="#f0f2f5").pack(fill="x", pady=(0, 6))

    def _sel_origen(self):
        c = filedialog.askdirectory(title="Seleccionar carpeta con PDFs")
        if c:
            self._origen.set(c)

    def _sel_destino(self):
        c = filedialog.askdirectory(title="Seleccionar carpeta de destino")
        if c:
            self._destino.set(c)

    def _toggle_destino(self):
        if self._modo_destino.get() == "nueva":
            self._entry_destino.config(state="normal", bg="white")
            self._btn_destino.config(state="normal")
        else:
            self._entry_destino.config(state="disabled", bg="#e0e0e0")
            self._btn_destino.config(state="disabled")

    # ── Propiedades públicas ──────────────────────────────────────────────────
    @property
    def carpeta_origen(self):
        return self._origen.get()

    @property
    def carpeta_destino(self):
        if self._modo_destino.get() == "origen":
            return self._origen.get()
        return self._destino.get()

    @property
    def crear_subcarpetas(self):
        return self._crear_subcarpetas.get()

    def valido(self):
        if not self._origen.get():
            return False, "Selecciona la carpeta de origen."
        if self._modo_destino.get() == "nueva" and not self._destino.get():
            return False, "Selecciona la carpeta de destino o elige 'misma carpeta de origen'."
        return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# WIDGET REUTILIZABLE: Panel de log + progreso
# ─────────────────────────────────────────────────────────────────────────────
class PanelLog(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg="#f0f2f5", **kwargs)
        self._build()

    def _build(self):
        self._prog_label = tk.Label(self, text="", font=("Helvetica", 9),
                                    bg="#f0f2f5", fg="#555", anchor="w")
        self._prog_label.pack(fill="x")
        self._prog = ttk.Progressbar(self, mode="determinate")
        self._prog.pack(fill="x", pady=(2, 10))

        tk.Label(self, text="Registro de operaciones:",
                 font=("Helvetica", 10, "bold"),
                 bg="#f0f2f5", anchor="w").pack(fill="x", pady=(0, 3))

        frame = tk.Frame(self, bg="#f0f2f5")
        frame.pack(fill="both", expand=True)

        self._txt = tk.Text(frame, height=10, state="disabled",
                            font=("Menlo" if sys.platform == "darwin" else "Consolas", 9),
                            bg="#f4f7fb", relief="solid", bd=1, wrap="word")
        self._txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(frame, command=self._txt.yview)
        sb.pack(side="right", fill="y")
        self._txt.config(yscrollcommand=sb.set)

        self._txt.tag_config("ok",      foreground="#1a7a3c")
        self._txt.tag_config("carpeta", foreground="#1a56a0")
        self._txt.tag_config("skip",    foreground="#7a6a1a")
        self._txt.tag_config("error",   foreground="#b22222")
        self._txt.tag_config("info",    foreground="#444444")

    def limpiar(self):
        self._txt.config(state="normal")
        self._txt.delete("1.0", "end")
        self._txt.config(state="disabled")
        self._prog["value"] = 0
        self._prog_label.config(text="")

    def log(self, msg, tag="info"):
        self._txt.config(state="normal")
        self._txt.insert("end", msg + "\n", tag)
        self._txt.see("end")
        self._txt.config(state="disabled")

    def progreso(self, valor, texto=""):
        self._prog["value"] = valor
        self._prog_label.config(text=texto)


# ─────────────────────────────────────────────────────────────────────────────
# PESTAÑA 1: RLC / RNT
# ─────────────────────────────────────────────────────────────────────────────
class TabRLCRNT(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg="#f0f2f5", **kwargs)
        self._build()

    def _build(self):
        pad = {"padx": 20, "pady": 10}

        tk.Label(self,
                 text="Renombra documentos RLC y RNT de la Seguridad Social\n"
                      "extrayendo automáticamente la Razón Social.",
                 font=("Helvetica", 10), bg="#f0f2f5", fg="#444",
                 justify="left").pack(anchor="w", padx=20, pady=(14, 6))

        self._panel_carpeta = PanelCarpeta(self)
        self._panel_carpeta.pack(fill="x", padx=20)

        self._btn = tk.Button(
            self, text="▶  Renombrar y Organizar PDFs",
            command=self._iniciar,
            bg="#e8a000", fg="white",
            font=("Helvetica", 12, "bold"),
            relief="flat", pady=10,
            activebackground="#c78800", activeforeground="white",
            cursor="hand2"
        )
        self._btn.pack(fill="x", padx=20, pady=(6, 4))

        self._panel_log = PanelLog(self)
        self._panel_log.pack(fill="both", expand=True, padx=20, pady=(0, 14))

    def _iniciar(self):
        ok, msg = self._panel_carpeta.valido()
        if not ok:
            messagebox.showwarning("Atención", msg)
            return
        self._btn.config(state="disabled")
        self._panel_log.limpiar()
        threading.Thread(target=self._procesar, daemon=True).start()

    def _procesar(self):
        origen = self._panel_carpeta.carpeta_origen
        destino = self._panel_carpeta.carpeta_destino
        subcarpetas = self._panel_carpeta.crear_subcarpetas

        pdfs = [f for f in os.listdir(origen)
                if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(origen, f))]

        if not pdfs:
            self._panel_log.log("No se encontraron archivos PDF en la carpeta.", "skip")
            self._btn.config(state="normal")
            return

        total = len(pdfs)
        ok = skip = errores = 0
        carpetas_creadas = set()

        for i, nombre_archivo in enumerate(pdfs, 1):
            ruta_origen = os.path.join(origen, nombre_archivo)
            self._panel_log.progreso((i / total) * 100, f"Procesando {i} de {total}…")
            self._panel_log.log(f"Procesando: {nombre_archivo}", "info")

            try:
                texto = extraer_texto_pdf(ruta_origen)
                tipo = detectar_tipo_rlc_rnt(texto)
                razon = detectar_razon_social(texto)

                if not tipo:
                    self._panel_log.log("  ⚠ No se detectó tipo (RLC/RNT) → omitido", "skip")
                    skip += 1
                    continue
                if not razon:
                    self._panel_log.log("  ⚠ No se encontró Razón Social → omitido", "skip")
                    skip += 1
                    continue

                # Carpeta destino final
                if subcarpetas:
                    carpeta_final = os.path.join(destino, razon)
                    if not os.path.exists(carpeta_final):
                        os.makedirs(carpeta_final)
                        carpetas_creadas.add(razon)
                        self._panel_log.log(f"  📁 Carpeta creada: {razon}", "carpeta")
                else:
                    carpeta_final = destino
                    if not os.path.exists(carpeta_final):
                        os.makedirs(carpeta_final)

                nuevo_base = f"{razon}_{tipo}"
                nuevo_nombre = nombre_unico(carpeta_final, nuevo_base, ".pdf")
                ruta_destino = os.path.join(carpeta_final, nuevo_nombre)

                if ruta_origen == ruta_destino:
                    self._panel_log.log("  ✓ Ya tiene el nombre correcto → sin cambios", "skip")
                    skip += 1
                    continue

                shutil.move(ruta_origen, ruta_destino)
                rel = os.path.relpath(ruta_destino, origen)
                self._panel_log.log(f"  ✓ {nombre_archivo}  →  {rel}", "ok")
                ok += 1

            except Exception as e:
                self._panel_log.log(f"  ✗ Error: {e}", "error")
                errores += 1

        self._panel_log.progreso(100, "Proceso completado.")
        extra = f"  📁 Carpetas creadas: {len(carpetas_creadas)}\n" if subcarpetas else ""
        self._panel_log.log(
            f"\n{'─'*50}\n"
            f"  ✓ Procesados: {ok}   ⚠ Omitidos: {skip}   ✗ Errores: {errores}\n"
            f"{extra}{'─'*50}", "info"
        )
        self._btn.config(state="normal")


# ─────────────────────────────────────────────────────────────────────────────
# PESTAÑA 2: Notificaciones TGSS
# ─────────────────────────────────────────────────────────────────────────────
class TabNotificaciones(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg="#f0f2f5", **kwargs)
        self._build()

    def _build(self):
        tk.Label(self,
                 text="Renombra notificaciones de la TGSS con el formato:\n"
                      "NotificacionTGSS_NombreCliente.pdf",
                 font=("Helvetica", 10), bg="#f0f2f5", fg="#444",
                 justify="left").pack(anchor="w", padx=20, pady=(14, 6))

        self._panel_carpeta = PanelCarpeta(self)
        self._panel_carpeta.pack(fill="x", padx=20)

        self._btn = tk.Button(
            self, text="▶  Renombrar Notificaciones TGSS",
            command=self._iniciar,
            bg="#e8a000", fg="white",
            font=("Helvetica", 12, "bold"),
            relief="flat", pady=10,
            activebackground="#c78800", activeforeground="white",
            cursor="hand2"
        )
        self._btn.pack(fill="x", padx=20, pady=(6, 4))

        self._panel_log = PanelLog(self)
        self._panel_log.pack(fill="both", expand=True, padx=20, pady=(0, 14))

    def _iniciar(self):
        ok, msg = self._panel_carpeta.valido()
        if not ok:
            messagebox.showwarning("Atención", msg)
            return
        self._btn.config(state="disabled")
        self._panel_log.limpiar()
        threading.Thread(target=self._procesar, daemon=True).start()

    def _procesar(self):
        origen = self._panel_carpeta.carpeta_origen
        destino = self._panel_carpeta.carpeta_destino
        subcarpetas = self._panel_carpeta.crear_subcarpetas

        pdfs = [f for f in os.listdir(origen)
                if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(origen, f))]

        if not pdfs:
            self._panel_log.log("No se encontraron archivos PDF en la carpeta.", "skip")
            self._btn.config(state="normal")
            return

        total = len(pdfs)
        ok = skip = errores = 0
        carpetas_creadas = set()

        for i, nombre_archivo in enumerate(pdfs, 1):
            ruta_origen = os.path.join(origen, nombre_archivo)
            self._panel_log.progreso((i / total) * 100, f"Procesando {i} de {total}…")
            self._panel_log.log(f"Procesando: {nombre_archivo}", "info")

            try:
                texto = extraer_texto_pdf(ruta_origen)
                nombre_cliente = detectar_nombre_notificacion(texto)

                if not nombre_cliente:
                    self._panel_log.log(
                        "  ⚠ No se encontró nombre de cliente → omitido", "skip")
                    skip += 1
                    continue

                # Carpeta destino final
                if subcarpetas:
                    carpeta_final = os.path.join(destino, nombre_cliente)
                    if not os.path.exists(carpeta_final):
                        os.makedirs(carpeta_final)
                        carpetas_creadas.add(nombre_cliente)
                        self._panel_log.log(
                            f"  📁 Carpeta creada: {nombre_cliente}", "carpeta")
                else:
                    carpeta_final = destino
                    if not os.path.exists(carpeta_final):
                        os.makedirs(carpeta_final)

                nuevo_base = f"NotificacionTGSS_{nombre_cliente}"
                nuevo_nombre = nombre_unico(carpeta_final, nuevo_base, ".pdf")
                ruta_destino = os.path.join(carpeta_final, nuevo_nombre)

                if ruta_origen == ruta_destino:
                    self._panel_log.log("  ✓ Ya tiene el nombre correcto → sin cambios", "skip")
                    skip += 1
                    continue

                shutil.move(ruta_origen, ruta_destino)
                rel = os.path.relpath(ruta_destino, origen)
                self._panel_log.log(f"  ✓ {nombre_archivo}  →  {rel}", "ok")
                ok += 1

            except Exception as e:
                self._panel_log.log(f"  ✗ Error: {e}", "error")
                errores += 1

        self._panel_log.progreso(100, "Proceso completado.")
        extra = f"  📁 Carpetas creadas: {len(carpetas_creadas)}\n" if subcarpetas else ""
        self._panel_log.log(
            f"\n{'─'*50}\n"
            f"  ✓ Procesados: {ok}   ⚠ Omitidos: {skip}   ✗ Errores: {errores}\n"
            f"{extra}{'─'*50}", "info"
        )
        self._btn.config(state="normal")


# ─────────────────────────────────────────────────────────────────────────────
# VENTANA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Renombrador de PDFs – Seguridad Social")
        self.resizable(False, False)
        self.configure(bg="#f0f2f5")
        self.geometry("720x680")
        self._build_ui()

    def _build_ui(self):
        # ── Cabecera ──────────────────────────────────────────────────────────
        header = tk.Frame(self, bg="#1a56a0", pady=16)
        header.pack(fill="x")
        tk.Label(header, text="📄  Renombrador de PDFs – Seguridad Social",
                 font=("Helvetica", 15, "bold"),
                 bg="#1a56a0", fg="white").pack()
        tk.Label(header, text="RLC · RNT · Notificaciones TGSS  ·  Organización automática por cliente",
                 font=("Helvetica", 9),
                 bg="#1a56a0", fg="#c8d9f0").pack()

        # ── Pestañas ──────────────────────────────────────────────────────────
        style = ttk.Style()
        style.configure("TNotebook.Tab", font=("Helvetica", 10, "bold"), padding=[14, 6])

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=0, pady=0)

        tab1 = TabRLCRNT(nb)
        tab2 = TabNotificaciones(nb)

        nb.add(tab1, text="  📋  RLC / RNT  ")
        nb.add(tab2, text="  🔔  Notificaciones TGSS  ")


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
