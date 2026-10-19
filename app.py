"""Actualizar Kardex — interfaz gráfica sencilla (Tkinter, incluido con Python en Windows)."""
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import flujo


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(flujo.NOMBRE)
        self.geometry("1150x720")
        self.cfg = flujo.cargar_config()
        self.cola = queue.Queue()
        self.ocupado = False
        self.acciones = []
        self._construir()
        self.after(150, self._bombear)

    # ------------------------------------------------------------ interfaz
    def _construir(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Enlace del KARDEX:").grid(row=0, column=0, sticky="w")
        self.url = tk.StringVar(value=self.cfg["url_kardex"])
        ttk.Entry(top, textvariable=self.url).grid(row=0, column=1, sticky="ew", padx=6)
        top.columnconfigure(1, weight=1)
        self.b_sesion = ttk.Button(top, text="1. Iniciar sesión", command=self.on_sesion)
        self.b_analizar = ttk.Button(top, text="2. Analizar", command=self.on_analizar)
        self.b_aplicar = ttk.Button(top, text="3. Escribir en el kardex", command=self.on_aplicar, state="disabled")
        self.b_copiar = ttk.Button(top, text="Copiar texto nuevo", command=self.on_copiar, state="disabled")
        for i, b in enumerate((self.b_sesion, self.b_analizar, self.b_aplicar, self.b_copiar), start=2):
            b.grid(row=0, column=i, padx=3)

        self.barra = ttk.Progressbar(self, mode="determinate")
        self.barra.pack(fill="x", padx=8)
        self.estado = tk.StringVar(value="Primero «Iniciar sesión» (solo la primera vez), luego «Analizar».")
        ttk.Label(self, textvariable=self.estado, padding=(8, 2)).pack(fill="x")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=4)
        self.t_acc = self._tabla("Qué hay que actualizar", ("sel", "tipo", "paciente", "campo", "detalle"),
                                 ("", "Acción", "Paciente", "Campo", "Detalle"), (30, 100, 260, 110, 520))
        self.t_sis = self._tabla("Encontré en el sistema", ("p", "h", "m", "f", "dx"),
                                 ("Paciente", "Habitación", "Médico", "Fecha", "Diagnóstico"), (260, 90, 160, 130, 420))
        self.t_kar = self._tabla("Encontré en el kardex", ("s", "p", "h", "dx"),
                                 ("Servicio", "Paciente", "Habitación", "DX actual"), (200, 260, 100, 440))
        self.t_acc.bind("<Button-1>", self._clic_acc)
        self.t_acc.bind("<<TreeviewSelect>>", self._mostrar_detalle)

        pie = ttk.Frame(self, padding=8)
        pie.pack(fill="both")
        self.actual = self._caja(pie, "Ahora en el kardex")
        self.nuevo = self._caja(pie, "Según el sistema (nuevo)")
        self.reg = tk.Text(self, height=5, state="disabled", background="#f4f4f4")
        self.reg.pack(fill="x", padx=8, pady=(0, 8))

    def _tabla(self, titulo, cols, textos, anchos):
        fr = ttk.Frame(self.nb)
        self.nb.add(fr, text=titulo)
        t = ttk.Treeview(fr, columns=cols, show="headings", selectmode="browse")
        for c, tx, an in zip(cols, textos, anchos):
            t.heading(c, text=tx)
            t.column(c, width=an, anchor="w")
        sb = ttk.Scrollbar(fr, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return t

    def _caja(self, padre, titulo):
        lf = ttk.LabelFrame(padre, text=titulo)
        lf.pack(side="left", fill="both", expand=True, padx=4)
        t = tk.Text(lf, height=7, wrap="word", state="disabled")
        t.pack(fill="both", expand=True)
        return t

    @staticmethod
    def _poner(caja, texto):
        caja.configure(state="normal")
        caja.delete("1.0", "end")
        caja.insert("1.0", texto)
        caja.configure(state="disabled")

    # ------------------------------------------------------------ hilos
    def _log(self, msg):
        self.cola.put(("log", msg))

    def _correr(self, tarea, al_terminar=None):
        if self.ocupado:
            return
        self.ocupado = True
        for b in (self.b_sesion, self.b_analizar, self.b_aplicar):
            b.configure(state="disabled")

        def run():
            try:
                self.cola.put(("fin", al_terminar, tarea()))
            except Exception as e:  # noqa: BLE001
                self.cola.put(("error", str(e)))
        threading.Thread(target=run, daemon=True).start()

    def _bombear(self):
        try:
            while True:
                m = self.cola.get_nowait()
                if m[0] == "log":
                    self.estado.set(m[1])
                    self.reg.configure(state="normal")
                    self.reg.insert("end", m[1] + "\n")
                    self.reg.see("end")
                    self.reg.configure(state="disabled")
                elif m[0] == "prog":
                    self.barra.configure(maximum=m[2], value=m[1])
                elif m[0] == "error":
                    self._libre()
                    self.estado.set("Error: " + m[1])
                    messagebox.showerror(flujo.NOMBRE, m[1])
                elif m[0] == "fin":
                    self._libre()
                    if m[1]:
                        m[1](m[2])
        except queue.Empty:
            pass
        self.after(150, self._bombear)

    def _libre(self):
        self.ocupado = False
        self.b_sesion.configure(state="normal")
        self.b_analizar.configure(state="normal")
        self.b_aplicar.configure(state="normal" if self.acciones else "disabled")

    # ------------------------------------------------------------ acciones
    def _guardar_url(self):
        self.cfg["url_kardex"] = self.url.get().strip()
        flujo.guardar_config(self.cfg)

    def on_sesion(self):
        self._guardar_url()
        self._correr(lambda: flujo.iniciar_sesion(self.cfg, self._log))

    def on_analizar(self):
        self._guardar_url()
        self.estado.set("Analizando… se abrirá el navegador; no lo cierres.")
        self._correr(lambda: flujo.analizar(self.cfg, self._log, lambda i, n: self.cola.put(("prog", i, n))),
                     self._mostrar)

    def _mostrar(self, res):
        sis, kar, self.acciones = res
        for t in (self.t_acc, self.t_sis, self.t_kar):
            t.delete(*t.get_children())
        for p in sis:
            self.t_sis.insert("", "end", values=(p.nombre, p.habitacion, p.medico, p.fecha, p.dx.replace("\n", " · ")))
        for f in kar:
            self.t_kar.insert("", "end", values=(f.servicio, f.nombre, f.habitacion, f.dx.replace("\n", " · ")))
        for i, a in enumerate(self.acciones):
            self.t_acc.insert("", "end", iid=str(i), values=(
                "☑" if a.marcada and a.automatica else ("☐" if a.automatica else ""),
                a.tipo, a.paciente, a.campo, a.detalle))
        auto = sum(1 for a in self.acciones if a.automatica)
        self.estado.set(f"Listo: {len(sis)} en el sistema, {len(kar)} en el kardex, "
                        f"{auto} celdas por actualizar, {len(self.acciones) - auto} avisos para revisar a mano.")
        self.b_aplicar.configure(state="normal" if auto else "disabled")
        self.b_copiar.configure(state="normal" if self.acciones else "disabled")
        self.nb.select(0)

    def _clic_acc(self, ev):
        if self.t_acc.identify_region(ev.x, ev.y) != "cell" or self.t_acc.identify_column(ev.x) != "#1":
            return
        iid = self.t_acc.identify_row(ev.y)
        if not iid:
            return
        a = self.acciones[int(iid)]
        if a.automatica:
            a.marcada = not a.marcada
            self.t_acc.set(iid, "sel", "☑" if a.marcada else "☐")

    def _mostrar_detalle(self, _=None):
        s = self.t_acc.selection()
        if not s:
            return
        a = self.acciones[int(s[0])]
        self._poner(self.actual, a.actual or "(vacío)")
        self._poner(self.nuevo, a.nuevo or a.detalle)

    def on_copiar(self):
        s = self.t_acc.selection()
        if s:
            self.clipboard_clear()
            self.clipboard_append(self.acciones[int(s[0])].nuevo)
            self.estado.set("Texto nuevo copiado: pégalo en la celda.")

    def on_aplicar(self):
        sel = [a for a in self.acciones if a.automatica and a.marcada]
        if not sel:
            messagebox.showinfo(flujo.NOMBRE, "No hay actualizaciones marcadas.")
            return
        if not messagebox.askyesno(flujo.NOMBRE, f"Se escribirán {len(sel)} celdas en el KARDEX.\n"
                                   "Puedes deshacer con Archivo → Historial de versiones.\n¿Continuar?"):
            return
        self._correr(lambda: flujo.aplicar(self.cfg, sel, self._log),
                     lambda r: messagebox.showinfo(flujo.NOMBRE, f"Escritas {r[0]} celdas." +
                                                   (f"\nOmitidas: {len(r[1])} (ver registro)" if r[1] else "")))


if __name__ == "__main__":
    App().mainloop()
