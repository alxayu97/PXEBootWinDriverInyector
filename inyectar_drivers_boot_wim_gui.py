import os
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import ctypes
import tempfile
import shutil
from pathlib import Path


class DismDriverInjectorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Inyector de drivers en boot.wim - WDS / WinPE")
        self.root.geometry("850x620")

        self.wim_path = tk.StringVar()
        self.drivers_path = tk.StringVar()
        self.mount_path = tk.StringVar(value=r"E:\Mount")
        self.index_value = tk.StringVar(value="2")
        self.backup_enabled = tk.BooleanVar(value=True)

        self.build_ui()

    def build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Inyectar drivers .INF en boot.wim", font=("Segoe UI", 14, "bold")).pack(anchor="w")

        self.add_file_row(main, "boot.wim:", self.wim_path, self.select_wim)
        self.add_folder_row(main, "Carpeta drivers .INF:", self.drivers_path, self.select_drivers)
        self.add_folder_row(main, "Carpeta montaje:", self.mount_path, self.select_mount)

        index_frame = ttk.Frame(main)
        index_frame.pack(fill="x", pady=6)
        ttk.Label(index_frame, text="Índice WIM:", width=22).pack(side="left")
        ttk.Entry(index_frame, textvariable=self.index_value, width=8).pack(side="left")
        ttk.Label(index_frame, text="Normalmente 2 = Windows Setup").pack(side="left", padx=10)

        ttk.Checkbutton(
            main,
            text="Crear copia de seguridad del boot.wim antes de modificarlo",
            variable=self.backup_enabled
        ).pack(anchor="w", pady=6)

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=10)

        ttk.Button(btn_frame, text="Ver índices del WIM", command=self.thread_get_indexes).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Inyectar drivers", command=self.thread_inject_drivers).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Desmontar SIN guardar", command=self.thread_discard_mount).pack(side="left", padx=4)

        ttk.Label(main, text="Salida:").pack(anchor="w")

        self.output = tk.Text(main, height=24, wrap="word")
        self.output.pack(fill="both", expand=True)

        scroll = ttk.Scrollbar(self.output, command=self.output.yview)
        self.output.configure(yscrollcommand=scroll.set)

    def add_file_row(self, parent, label, variable, command):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=6)
        ttk.Label(frame, text=label, width=22).pack(side="left")
        ttk.Entry(frame, textvariable=variable).pack(side="left", fill="x", expand=True)
        ttk.Button(frame, text="Buscar", command=command).pack(side="left", padx=6)

    def add_folder_row(self, parent, label, variable, command):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=6)
        ttk.Label(frame, text=label, width=22).pack(side="left")
        ttk.Entry(frame, textvariable=variable).pack(side="left", fill="x", expand=True)
        ttk.Button(frame, text="Buscar", command=command).pack(side="left", padx=6)

    def select_wim(self):
        path = filedialog.askopenfilename(
            title="Selecciona boot.wim",
            filetypes=[("WIM files", "*.wim"), ("Todos los archivos", "*.*")]
        )
        if path:
            self.wim_path.set(path)

    def select_drivers(self):
        path = filedialog.askdirectory(title="Selecciona carpeta con drivers .INF")
        if path:
            self.drivers_path.set(path)

    def select_mount(self):
        path = filedialog.askdirectory(title="Selecciona carpeta de montaje")
        if path:
            self.mount_path.set(path)

    def log(self, text):
        self.output.insert("end", text + "\n")
        self.output.see("end")
        self.root.update_idletasks()

    def run_command(self, args):
        self.log("\n> " + " ".join(f'"{a}"' if " " in a else a for a in args))

        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False
        )

        for line in process.stdout:
            self.log(line.rstrip())

        process.wait()

        if process.returncode != 0:
            raise RuntimeError(f"El comando terminó con código {process.returncode}")

    def validate_paths(self):
        wim = Path(self.wim_path.get())
        drivers = Path(self.drivers_path.get())
        mount = Path(self.mount_path.get())

        if not wim.is_file():
            raise ValueError("Selecciona un boot.wim válido.")

        if not drivers.is_dir():
            raise ValueError("Selecciona una carpeta de drivers válida.")

        infs = list(drivers.rglob("*.inf"))
        if not infs:
            raise ValueError("No se encontraron archivos .inf dentro de la carpeta de drivers.")

        if not mount.exists():
            mount.mkdir(parents=True, exist_ok=True)

        if any(mount.iterdir()):
            raise ValueError("La carpeta de montaje debe estar vacía.")

        try:
            index = int(self.index_value.get())
            if index < 1:
                raise ValueError()
        except Exception:
            raise ValueError("El índice debe ser un número válido, normalmente 2.")

        return wim, drivers, mount, str(index)

    def is_admin(self):
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            return False

    def thread_get_indexes(self):
        threading.Thread(target=self.get_indexes, daemon=True).start()

    def thread_inject_drivers(self):
        threading.Thread(target=self.inject_drivers, daemon=True).start()

    def thread_discard_mount(self):
        threading.Thread(target=self.discard_mount, daemon=True).start()

    def get_indexes(self):
        try:
            wim = Path(self.wim_path.get())
            if not wim.is_file():
                raise ValueError("Selecciona un boot.wim válido.")

            self.run_command(["dism", "/Get-WimInfo", f"/WimFile:{wim}"])

        except Exception as ex:
            messagebox.showerror("Error", str(ex))

    def inject_drivers(self):
        mounted = False
        try:
            if not self.is_admin():
                raise PermissionError("Ejecuta este programa como Administrador.")

            wim, drivers, mount, index = self.validate_paths()

            # Quitar atributo solo lectura por si viene de ISO/copias.
            subprocess.run(["attrib", "-r", str(wim)], shell=False)

            if self.backup_enabled.get():
                backup = wim.with_suffix(".backup.wim")
                self.log(f"Creando copia de seguridad: {backup}")
                shutil.copy2(wim, backup)

            self.log("Montando imagen...")
            self.run_command([
                "dism",
                "/Mount-Wim",
                f"/WimFile:{wim}",
                f"/Index:{index}",
                f"/MountDir:{mount}"
            ])
            mounted = True

            self.log("Añadiendo drivers...")
            self.run_command([
                "dism",
                f"/Image:{mount}",
                "/Add-Driver",
                f"/Driver:{drivers}",
                "/Recurse"
            ])

            self.log("Mostrando drivers instalados...")
            self.run_command([
                "dism",
                f"/Image:{mount}",
                "/Get-Drivers"
            ])

            self.log("Guardando cambios...")
            self.run_command([
                "dism",
                "/Unmount-Wim",
                f"/MountDir:{mount}",
                "/Commit"
            ])
            mounted = False

            messagebox.showinfo(
                "Completado",
                "Drivers inyectados correctamente.\n\nAhora elimina la Boot Image antigua en WDS y añade este boot.wim modificado."
            )

        except Exception as ex:
            self.log(f"ERROR: {ex}")
            if mounted:
                self.log("La imagen ha quedado montada. Puedes usar 'Desmontar SIN guardar' o ejecutar DISM manualmente.")
            messagebox.showerror("Error", str(ex))

    def discard_mount(self):
        try:
            mount = Path(self.mount_path.get())
            if not mount.exists():
                raise ValueError("La carpeta de montaje no existe.")

            self.run_command([
                "dism",
                "/Unmount-Wim",
                f"/MountDir:{mount}",
                "/Discard"
            ])

            messagebox.showinfo("Completado", "Imagen desmontada sin guardar cambios.")

        except Exception as ex:
            messagebox.showerror("Error", str(ex))


if __name__ == "__main__":
    root = tk.Tk()
    app = DismDriverInjectorApp(root)
    root.mainloop()
