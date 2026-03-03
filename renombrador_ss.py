"""
Renombrador de PDFs - Seguridad Social
=======================================
Detecta si el PDF es RLC (Recibo de Liquidación de Cotizaciones)
o RNT (Relación Nominal de Trabajadores), extrae la Razón Social
y renombra el archivo con el formato: RazonSocial_RLC.pdf / RazonSocial_RNT.pdf

Compatible con macOS y Windows.
Requiere: pdfplumber
"""

import os
import re
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import pdfplumber
except ImportError:
    # Si no está instalado, mostrar mensaje de error claro
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
# PATRONES DE DETECCIÓN (validados con PDFs reales de la SS española)
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

PATRONES_RAZON = [
    # "Razón social NOMBRE  Código..." (RNT: sin dos puntos, separado por espacios)
    r"Raz[oó]n\s+[Ss]ocial\s+([A-ZÁÉÍÓÚÜÑ][^\n]+?)\s{2,}",
    # "Razón Social: NOMBRE  Número..." (RLC: con dos puntos)
    r"Raz[oó]n\s+[Ss]ocial:\s+([^\n]+?)\s+(?:N[uú]mero|C[oó]digo|Periodo|Entidad)",
    # Fallback genérico
    r"Raz[oó]n\s+[Ss]ocial[:\s]+(.+)",
]


def extraer_texto_pdf(ruta):
    """Extrae el texto de las primeras 3 páginas del PDF."""
    texto = ""
    with pdfplumber.open(ruta) as pdf:
        for pagina in pdf.pages[:3]:
            t = pagina.extract_text()
            if t:
                texto += t + "\n"
    return texto


def detectar_tipo(texto):
    """Devuelve 'RLC', 'RNT' o None."""
    for tipo, patrones in PATRONES_TIPO.items():
        for patron in patrones:
            if re.search(patron, texto):
                return tipo
    return None


def detectar_razon_social(texto):
    """Extrae la razón social del texto o devuelve None."""
    for patron in PATRONES_RAZON:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            nombre = m.group(1).strip()
            # Limpiar caracteres no válidos para nombre de archivo
            nombre = re.sub(r'[\\/:*?"<>|]', "_", nombre)
            nombre = nombre.strip()
            if nombre:
                return nombre[:80]
    return None


def nombre_unico(carpeta, base, ext):
    """Genera un nombre de archivo único añadiendo sufijo numérico si es necesario."""
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
# INTERFAZ GRÁFICA
# ─────────────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Renombrador de PDFs – Seguridad Social")
        self.resizable(False, False)
        self.configure(bg="#f0f2f5")

        # En macOS, usar un tamaño más compacto
        self.geometry("680x560")

        self._carpeta = tk.StringVar()
        self._build_ui()

    def _build_ui(self):
        # ── Cabecera ──────────────────────────────────────────────────────────
        header = tk.Frame(self, bg="#1a56a0", pady=18)
        header.pack(fill="x")
        tk.Label(
            header, text="📄  Renombrador de PDFs",
            font=("Helvetica", 16, "bold"),
            bg="#1a56a0", fg="white"
        ).pack()
        tk.Label(
            header, text="Seguridad Social  ·  RLC y RNT  ·  Extrae Razón Social automáticamente",
            font=("Helvetica", 10),
            bg="#1a56a0", fg="#c8d9f0"
        ).pack()

        # ── Cuerpo ────────────────────────────────────────────────────────────
        body = tk.Frame(self, bg="#f0f2f5", padx=24, pady=20)
        body.pack(fill="both", expand=True)

        # Selección de carpeta
        tk.Label(
            body, text="Carpeta con los PDFs:",
            font=("Helvetica", 11, "bold"),
            bg="#f0f2f5", anchor="w"
        ).pack(fill="x", pady=(0, 4))

        row = tk.Frame(body, bg="#f0f2f5")
        row.pack(fill="x", pady=(0, 16))

        self._entry = tk.Entry(
            row, textvariable=self._carpeta,
            font=("Helvetica", 10), state="readonly",
            bg="white", relief="solid", bd=1
        )
        self._entry.pack(side="left", fill="x", expand=True, ipady=5)

        tk.Button(
            row, text="Examinar…",
            command=self._seleccionar_carpeta,
            bg="#e8eef7", relief="solid", bd=1,
            font=("Helvetica", 10), padx=10
        ).pack(side="left", padx=(6, 0), ipady=5)

        # Botón principal
        self._btn = tk.Button(
            body, text="▶  Renombrar PDFs",
            command=self._iniciar_proceso,
            state="disabled",
            bg="#1a56a0", fg="white",
            font=("Helvetica", 12, "bold"),
            relief="flat", pady=10,
            activebackground="#154480", activeforeground="white",
            cursor="hand2"
        )
        self._btn.pack(fill="x", pady=(0, 14))

        # Barra de progreso
        self._prog_label = tk.Label(
            body, text="", font=("Helvetica", 9),
            bg="#f0f2f5", fg="#555", anchor="w"
        )
        self._prog_label.pack(fill="x")
        self._prog = ttk.Progressbar(body, mode="determinate")
        self._prog.pack(fill="x", pady=(2, 14))

        # Log
        tk.Label(
            body, text="Registro de operaciones:",
            font=("Helvetica", 10, "bold"),
            bg="#f0f2f5", anchor="w"
        ).pack(fill="x", pady=(0, 4))

        log_frame = tk.Frame(body, bg="#f0f2f5")
        log_frame.pack(fill="both", expand=True)

        self._log = tk.Text(
            log_frame, height=12, state="disabled",
            font=("Menlo" if sys.platform == "darwin" else "Consolas", 9),
            bg="#f4f7fb", relief="solid", bd=1,
            wrap="word"
        )
        self._log.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(log_frame, command=self._log.yview)
        sb.pack(side="right", fill="y")
        self._log.config(yscrollcommand=sb.set)

        # Colores del log
        self._log.tag_config("ok",    foreground="#1a7a3c")
        self._log.tag_config("skip",  foreground="#7a6a1a")
        self._log.tag_config("error", foreground="#b22222")
        self._log.tag_config("info",  foreground="#444444")

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _seleccionar_carpeta(self):
        carpeta = filedialog.askdirectory(title="Seleccionar carpeta con PDFs")
        if carpeta:
            self._carpeta.set(carpeta)
            self._btn.config(state="normal")
            self._limpiar_log()
            self._prog["value"] = 0
            self._prog_label.config(text="")

    def _limpiar_log(self):
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")

    def _log_msg(self, msg, tag="info"):
        self._log.config(state="normal")
        self._log.insert("end", msg + "\n", tag)
        self._log.see("end")
        self._log.config(state="disabled")

    def _iniciar_proceso(self):
        self._btn.config(state="disabled")
        self._limpiar_log()
        self._prog["value"] = 0
        # Ejecutar en hilo separado para no bloquear la UI
        t = threading.Thread(target=self._procesar, daemon=True)
        t.start()

    def _procesar(self):
        carpeta = self._carpeta.get()
        pdfs = [f for f in os.listdir(carpeta) if f.lower().endswith(".pdf")]

        if not pdfs:
            self._log_msg("No se encontraron archivos PDF en la carpeta.", "skip")
            self._btn.config(state="normal")
            return

        total = len(pdfs)
        ok = skip = errores = 0

        for i, nombre_archivo in enumerate(pdfs, 1):
            ruta = os.path.join(carpeta, nombre_archivo)
            self._prog_label.config(text=f"Procesando {i} de {total}…")
            self._prog["value"] = (i / total) * 100
            self.update_idletasks()

            self._log_msg(f"Procesando: {nombre_archivo}", "info")

            try:
                texto = extraer_texto_pdf(ruta)
                tipo = detectar_tipo(texto)
                razon = detectar_razon_social(texto)

                if not tipo:
                    self._log_msg(f"  ⚠ No se detectó tipo (RLC/RNT) → omitido", "skip")
                    skip += 1
                    continue

                if not razon:
                    self._log_msg(f"  ⚠ No se encontró Razón Social → omitido", "skip")
                    skip += 1
                    continue

                nuevo_base = f"{razon}_{tipo}"
                nuevo_nombre = nombre_unico(carpeta, nuevo_base, ".pdf")

                if nuevo_nombre == nombre_archivo:
                    self._log_msg(f"  ✓ Ya tiene el nombre correcto → sin cambios", "skip")
                    skip += 1
                    continue

                nueva_ruta = os.path.join(carpeta, nuevo_nombre)
                os.rename(ruta, nueva_ruta)
                self._log_msg(f"  ✓ {nombre_archivo}  →  {nuevo_nombre}", "ok")
                ok += 1

            except Exception as e:
                self._log_msg(f"  ✗ Error: {e}", "error")
                errores += 1

        self._prog["value"] = 100
        self._prog_label.config(text="Proceso completado.")
        self._log_msg(
            f"\n{'─'*50}\n"
            f"  ✓ Renombrados: {ok}   ⚠ Omitidos: {skip}   ✗ Errores: {errores}\n"
            f"{'─'*50}",
            "info"
        )
        self._btn.config(state="normal")


# ─────────────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
