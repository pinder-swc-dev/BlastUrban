#!/usr/bin/env python3
"""Tk desktop UI for preparing a server-ready 3-D blastFoam case."""

from __future__ import annotations

import math
import platform
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, Optional

from blast_case_builder import (
    DEFAULT_TEMPLATE,
    CaseConfig,
    StlReport,
    analyse_stl,
    auto_charge_level,
    auto_domain,
    auto_surface_levels,
    charge_radius,
    create_case,
    foam_number,
    foam_vec,
    mesh_divisions,
    parse_probes,
    validate_config,
)


class BlastCaseUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("BlastUrban — 3-D blastFoam Case Builder")
        self.root.geometry("1120x790")
        self.root.minsize(980, 680)
        self.report: Optional[StlReport] = None
        self.busy = False
        self.variables: Dict[str, tk.Variable] = {}
        self._create_variables()
        self._configure_style()
        self._build_ui()
        self._set_status("พร้อมใช้งาน — เลือก STL แล้วกด ตรวจ Surface", "info")

    def _var(self, name: str, value: object, boolean: bool = False) -> tk.Variable:
        variable: tk.Variable
        variable = tk.BooleanVar(value=bool(value)) if boolean else tk.StringVar(value=str(value))
        self.variables[name] = variable
        return variable

    def _create_variables(self) -> None:
        default_stl = DEFAULT_TEMPLATE / "constant/triSurface/townBuildings.stl"
        default_output = DEFAULT_TEMPLATE / "generatedCases"
        defaults = {
            "stl": default_stl,
            "scale": 1,
            "horizontal_buffer": 20,
            "top_buffer": 20,
            "xmin": -20,
            "ymin": -20,
            "zmin": 0,
            "xmax": 90,
            "ymax": 95,
            "zmax": 55,
            "target_cell": 1.5,
            "nx": 74,
            "ny": 77,
            "nz": 37,
            "surface_min": 2,
            "surface_max": 3,
            "feature_level": 2,
            "snappy_cells": 6_000_000,
            "dynamic_cells": 8_000_000,
            "dynamic_levels": 2,
            "refine_interval": 5,
            "location_x": -10,
            "location_y": -10,
            "location_z": 1,
            "charge_x": 35,
            "charge_y": 20,
            "charge_z": 1,
            "mass": 10,
            "density": 1601,
            "charge_level": 6,
            "plane_x": 35,
            "plane_y": 20,
            "plane_z": 1,
            "end_time": 0.0125,
            "delta_t": 5e-8,
            "max_delta_t": 2.5e-7,
            "max_co": 0.3,
            "write_interval": 2.5e-5,
            "ambient_pressure": 101298,
            "iso_pressure": 110000,
            "mpi": 10,
            "case_name": "urbanBlast3D",
            "output": default_output,
        }
        for name, value in defaults.items():
            self._var(name, value)
        self._var("binary", True, boolean=True)
        self._var("archive", True, boolean=True)
        self._var("allow_surface_errors", False, boolean=True)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("TkDefaultFont", 16, "bold"))
        style.configure("Section.TLabel", font=("TkDefaultFont", 11, "bold"))
        style.configure("Danger.TLabel", foreground="#b42318")
        style.configure("Good.TLabel", foreground="#067647")

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=(16, 12, 16, 6))
        top.pack(fill="x")
        ttk.Label(top, text="BlastUrban 3-D Case Builder", style="Title.TLabel").pack(side="left")
        host_label = "macOS UI + Docker/Linux solver" if platform.system() == "Darwin" else "Linux/OpenFOAM workflow"
        ttk.Label(top, text=f"{host_label}  •  Server profile: 10 CPU / 64 GB RAM").pack(side="right")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=8)
        self.geometry_tab = ttk.Frame(self.notebook, padding=14)
        self.mesh_tab = ttk.Frame(self.notebook, padding=14)
        self.blast_tab = ttk.Frame(self.notebook, padding=14)
        self.outputs_tab = ttk.Frame(self.notebook, padding=14)
        self.export_tab = ttk.Frame(self.notebook, padding=14)
        self.notebook.add(self.geometry_tab, text="1  STL และ Surface")
        self.notebook.add(self.mesh_tab, text="2  Domain และ Mesh")
        self.notebook.add(self.blast_tab, text="3  จุดระเบิด")
        self.notebook.add(self.outputs_tab, text="4  Probes และเวลา")
        self.notebook.add(self.export_tab, text="5  ตรวจและ Export")
        self._geometry_ui()
        self._mesh_ui()
        self._blast_ui()
        self._outputs_ui()
        self._export_ui()

        bottom = ttk.Frame(self.root, padding=(14, 4, 14, 10))
        bottom.pack(fill="x")
        self.status_label = ttk.Label(bottom, text="", anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=180)
        self.progress.pack(side="right")

    def _entry(self, parent: tk.Widget, row: int, label: str, variable: str, column: int = 0, width: int = 15, help_text: str = "") -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(0, 8), pady=5)
        entry = ttk.Entry(parent, textvariable=self.variables[variable], width=width)
        entry.grid(row=row, column=column + 1, sticky="ew", padx=(0, 18), pady=5)
        if help_text:
            ttk.Label(parent, text=help_text, foreground="#667085").grid(row=row, column=column + 2, sticky="w", pady=5)
        return entry

    def _geometry_ui(self) -> None:
        tab = self.geometry_tab
        tab.columnconfigure(1, weight=1)
        ttk.Label(tab, text="นำเข้าและตรวจสอบโมเดล STL", style="Section.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))
        ttk.Label(tab, text="ไฟล์ STL").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(tab, textvariable=self.variables["stl"]).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 8))
        ttk.Button(tab, text="เลือกไฟล์…", command=self._browse_stl).grid(row=1, column=3)

        settings = ttk.Frame(tab)
        settings.grid(row=2, column=0, columnspan=4, sticky="ew", pady=8)
        self._entry(settings, 0, "Scale", "scale", 0, 12, "m=1, cm=0.01, mm=0.001")
        self._entry(settings, 0, "Buffer รอบอาคาร (m)", "horizontal_buffer", 3, 12)
        self._entry(settings, 0, "Buffer ด้านบน (m)", "top_buffer", 6, 12)
        ttk.Button(settings, text="ตรวจ Surface", command=self._check_surface).grid(row=0, column=9, padx=8)
        ttk.Button(settings, text="Auto Domain + Mesh", command=self._auto_domain_mesh).grid(row=0, column=10, padx=4)

        ttk.Label(
            tab,
            text="Internal checker อ่าน Binary/ASCII STL, bounds, open/non-manifold edges และ degenerate triangles; "
            "ถ้าพบ surfaceCheck ใน OpenFOAM จะเรียกตรวจซ้ำอัตโนมัติ",
            foreground="#475467",
            wraplength=1020,
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 8))
        self.surface_output = tk.Text(tab, height=25, wrap="word", font=("Menlo", 11))
        self.surface_output.grid(row=4, column=0, columnspan=4, sticky="nsew")
        tab.rowconfigure(4, weight=1)
        self.surface_output.tag_configure("error", foreground="#b42318", background="#fef3f2")
        self.surface_output.tag_configure("warning", foreground="#b54708", background="#fffaeb")
        self.surface_output.tag_configure("ok", foreground="#067647", background="#ecfdf3")

    def _mesh_ui(self) -> None:
        tab = self.mesh_tab
        for col in (1, 4, 7):
            tab.columnconfigure(col, weight=1)
        ttk.Label(tab, text="ขอบเขต Domain (เมตร)", style="Section.TLabel").grid(row=0, column=0, columnspan=9, sticky="w")
        labels = (("X min", "xmin", "X max", "xmax"), ("Y min", "ymin", "Y max", "ymax"), ("Z min / ground", "zmin", "Z max", "zmax"))
        for row, values in enumerate(labels, 1):
            self._entry(tab, row, values[0], values[1], 0)
            self._entry(tab, row, values[2], values[3], 3)

        ttk.Separator(tab).grid(row=4, column=0, columnspan=9, sticky="ew", pady=12)
        ttk.Label(tab, text="Base mesh", style="Section.TLabel").grid(row=5, column=0, columnspan=9, sticky="w")
        self._entry(tab, 6, "Target cell (m)", "target_cell", 0, help_text="ใช้คำนวณ Nx/Ny/Nz เมื่อกด Auto")
        self._entry(tab, 7, "Nx", "nx", 0)
        self._entry(tab, 7, "Ny", "ny", 3)
        self._entry(tab, 7, "Nz", "nz", 6)
        self._entry(tab, 8, "Wall level min", "surface_min", 0)
        self._entry(tab, 8, "Wall level max", "surface_max", 3)
        self._entry(tab, 8, "Feature level", "feature_level", 6)
        self._entry(tab, 9, "snappy max cells", "snappy_cells", 0)
        self._entry(tab, 9, "Dynamic max cells", "dynamic_cells", 3)
        self._entry(tab, 9, "Dynamic levels", "dynamic_levels", 6)
        self._entry(tab, 10, "Refine interval", "refine_interval", 0)

        ttk.Separator(tab).grid(row=11, column=0, columnspan=9, sticky="ew", pady=12)
        ttk.Label(tab, text="locationInMesh — ต้องอยู่ในอากาศ ไม่อยู่ในอาคาร", style="Section.TLabel").grid(row=12, column=0, columnspan=9, sticky="w")
        self._entry(tab, 13, "X", "location_x", 0)
        self._entry(tab, 13, "Y", "location_y", 3)
        self._entry(tab, 13, "Z", "location_z", 6)
        ttk.Button(tab, text="คำนวณ Mesh ใหม่จาก Domain", command=self._recalculate_mesh).grid(row=14, column=0, columnspan=2, sticky="w", pady=12)
        ttk.Button(tab, text="แสดงประมาณการทรัพยากร", command=self._show_estimate).grid(row=14, column=3, columnspan=2, sticky="w", pady=12)
        self.mesh_summary = ttk.Label(tab, text="", wraplength=1000, foreground="#344054")
        self.mesh_summary.grid(row=15, column=0, columnspan=9, sticky="w", pady=8)

    def _blast_ui(self) -> None:
        tab = self.blast_tab
        for col in (1, 4, 7):
            tab.columnconfigure(col, weight=1)
        ttk.Label(tab, text="C4 แบบทรงกลม 3D", style="Section.TLabel").grid(row=0, column=0, columnspan=9, sticky="w")
        self._entry(tab, 1, "Charge X (m)", "charge_x", 0)
        self._entry(tab, 1, "Charge Y (m)", "charge_y", 3)
        self._entry(tab, 1, "Charge Z (m)", "charge_z", 6)
        self._entry(tab, 2, "มวล C4 (kg)", "mass", 0)
        self._entry(tab, 2, "ความหนาแน่น (kg/m³)", "density", 3)
        self._entry(tab, 2, "Charge refine level", "charge_level", 6)
        ttk.Button(tab, text="Auto charge refinement", command=self._auto_charge_refinement).grid(row=3, column=0, columnspan=2, sticky="w", pady=10)
        ttk.Button(tab, text="ให้ระนาบผ่านจุดระเบิด", command=self._planes_at_charge).grid(row=3, column=3, columnspan=2, sticky="w", pady=10)
        self.charge_summary = ttk.Label(tab, text="", wraplength=1000)
        self.charge_summary.grid(row=4, column=0, columnspan=9, sticky="w")

        ttk.Separator(tab).grid(row=5, column=0, columnspan=9, sticky="ew", pady=15)
        ttk.Label(tab, text="จุดตัดระนาบผลลัพธ์ X/Y/Z", style="Section.TLabel").grid(row=6, column=0, columnspan=9, sticky="w")
        self._entry(tab, 7, "Plane X", "plane_x", 0)
        self._entry(tab, 7, "Plane Y", "plane_y", 3)
        self._entry(tab, 7, "Plane Z", "plane_z", 6)

        ttk.Label(
            tab,
            text="หมายเหตุ: ค่านี้ใช้ JWL/EOS ของ C4 จาก template หากเปลี่ยนชนิดวัตถุระเบิดต้องแก้ A, B, R1, R2, omega, E0 และ vDet จากข้อมูลวัสดุที่ตรวจสอบแล้ว",
            foreground="#b54708",
            wraplength=1000,
        ).grid(row=8, column=0, columnspan=9, sticky="w", pady=20)
        self._update_charge_summary()

    def _outputs_ui(self) -> None:
        tab = self.outputs_tab
        for col in (1, 4, 7):
            tab.columnconfigure(col, weight=1)
        ttk.Label(tab, text="ตำแหน่ง Pressure probes", style="Section.TLabel").grid(row=0, column=0, columnspan=9, sticky="w")
        ttk.Label(tab, text="หนึ่งจุดต่อบรรทัด รูปแบบ: x y z   (# ใช้เขียนหมายเหตุ)", foreground="#475467").grid(row=1, column=0, columnspan=9, sticky="w")
        self.probes_text = tk.Text(tab, height=11, width=80, font=("Menlo", 11))
        self.probes_text.grid(row=2, column=0, columnspan=9, sticky="nsew", pady=8)
        self.probes_text.insert("1.0", "35 15 1  # south\n40 20 1  # east\n35 25 1  # near wall\n")
        tab.rowconfigure(2, weight=1)

        ttk.Separator(tab).grid(row=3, column=0, columnspan=9, sticky="ew", pady=10)
        ttk.Label(tab, text="Simulation และ output", style="Section.TLabel").grid(row=4, column=0, columnspan=9, sticky="w")
        self._entry(tab, 5, "End time (s)", "end_time", 0)
        self._entry(tab, 5, "Initial deltaT (s)", "delta_t", 3)
        self._entry(tab, 5, "Max deltaT (s)", "max_delta_t", 6)
        self._entry(tab, 6, "Max Courant", "max_co", 0)
        self._entry(tab, 6, "Write interval (s)", "write_interval", 3)
        self._entry(tab, 6, "MPI ranks", "mpi", 6)
        self._entry(tab, 7, "Ambient p (Pa)", "ambient_pressure", 0)
        self._entry(tab, 7, "Pressure iso (Pa)", "iso_pressure", 3)
        ttk.Checkbutton(tab, text="เขียน full fields แบบ binary", variable=self.variables["binary"]).grid(row=7, column=6, columnspan=3, sticky="w")

    def _export_ui(self) -> None:
        tab = self.export_tab
        tab.columnconfigure(1, weight=1)
        ttk.Label(tab, text="ตรวจสอบและสร้าง Server package", style="Section.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))
        ttk.Label(tab, text="ชื่อ Case").grid(row=1, column=0, sticky="w")
        ttk.Entry(tab, textvariable=self.variables["case_name"], width=35).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Label(tab, text="Output folder").grid(row=2, column=0, sticky="w", pady=8)
        ttk.Entry(tab, textvariable=self.variables["output"]).grid(row=2, column=1, columnspan=2, sticky="ew", padx=8)
        ttk.Button(tab, text="เลือก…", command=self._browse_output).grid(row=2, column=3)
        ttk.Checkbutton(tab, text="สร้าง .tar.gz สำหรับส่งขึ้น server", variable=self.variables["archive"]).grid(row=3, column=1, sticky="w")
        ttk.Checkbutton(
            tab,
            text="อนุญาต Export แม้ STL มี open/non-manifold edges (ไม่แนะนำ)",
            variable=self.variables["allow_surface_errors"],
        ).grid(row=4, column=1, sticky="w")
        buttons = ttk.Frame(tab)
        buttons.grid(row=5, column=0, columnspan=4, sticky="w", pady=14)
        ttk.Button(buttons, text="ตรวจ Config", command=self._validate).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="สร้าง Case + Server Package", command=self._export).pack(side="left")

        self.validation_output = tk.Text(tab, height=24, wrap="word", font=("Menlo", 11))
        self.validation_output.grid(row=6, column=0, columnspan=4, sticky="nsew")
        self.validation_output.tag_configure("error", foreground="#b42318")
        self.validation_output.tag_configure("warning", foreground="#b54708")
        self.validation_output.tag_configure("ok", foreground="#067647")
        tab.rowconfigure(6, weight=1)

    def _browse_stl(self) -> None:
        path = filedialog.askopenfilename(title="เลือก STL", filetypes=[("STL model", "*.stl"), ("All files", "*")])
        if path:
            self.variables["stl"].set(path)
            self.report = None

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(title="เลือก parent folder สำหรับ case ใหม่")
        if path:
            self.variables["output"].set(path)

    def _float(self, name: str) -> float:
        try:
            value = float(self.variables[name].get())
        except ValueError as exc:
            raise ValueError(f"{name}: ต้องเป็นตัวเลข") from exc
        if not math.isfinite(value):
            raise ValueError(f"{name}: ต้องเป็นตัวเลข finite")
        return value

    def _int(self, name: str) -> int:
        try:
            value = int(str(self.variables[name].get()).replace(",", ""))
        except ValueError as exc:
            raise ValueError(f"{name}: ต้องเป็นจำนวนเต็ม") from exc
        return value

    def _vec(self, prefix: str):
        return (self._float(prefix + "_x"), self._float(prefix + "_y"), self._float(prefix + "_z"))

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        if busy:
            self.progress.start(10)
        else:
            self.progress.stop()
        if message:
            self._set_status(message, "info")

    def _set_status(self, text: str, kind: str) -> None:
        colors = {"error": "#b42318", "warning": "#b54708", "ok": "#067647", "info": "#344054"}
        self.status_label.configure(text=text, foreground=colors.get(kind, "#344054"))

    def _check_surface(self) -> None:
        if self.busy:
            return
        try:
            path = Path(str(self.variables["stl"].get())).expanduser()
            scale = self._float("scale")
        except ValueError as exc:
            messagebox.showerror("ข้อมูลไม่ถูกต้อง", str(exc))
            return
        self.surface_output.delete("1.0", "end")
        self.surface_output.insert("end", "กำลังอ่านและตรวจ STL…\n")
        self._set_busy(True, "กำลังตรวจ STL และเรียก surfaceCheck ถ้ามีใน environment…")

        def work() -> None:
            try:
                report = analyse_stl(path, scale, run_external=True)
                self.root.after(0, lambda: self._surface_done(report, None))
            except Exception as exc:  # shown in the UI with context
                self.root.after(0, lambda error=exc: self._surface_done(None, error))

        threading.Thread(target=work, daemon=True).start()

    def _surface_done(self, report: Optional[StlReport], error: Optional[Exception]) -> None:
        self._set_busy(False)
        self.surface_output.delete("1.0", "end")
        if error:
            self.report = None
            self.surface_output.insert("end", f"ERROR: {error}\n", "error")
            self._set_status("ตรวจ STL ไม่สำเร็จ", "error")
            return
        assert report is not None
        self.report = report
        tag = "error" if report.errors else ("warning" if report.warnings else "ok")
        self.surface_output.insert("end", report.readable_summary() + "\n", tag)
        if report.errors:
            self._set_status(f"STL มีข้อผิดพลาด {len(report.errors)} รายการ — ดูข้อความสีแดง", "error")
        elif report.warnings:
            self._set_status("ตรวจ STL ผ่านโดยมีคำเตือน", "warning")
        else:
            self._set_status("STL ผ่าน internal surface check", "ok")

    def _require_report(self) -> StlReport:
        path = str(Path(str(self.variables["stl"].get())).expanduser().resolve())
        scale = self._float("scale")
        if self.report is None or self.report.path != path or self.report.scale != scale:
            self.report = analyse_stl(Path(path), scale, run_external=False)
        return self.report

    def _auto_domain_mesh(self) -> None:
        try:
            report = self._require_report()
            domain = auto_domain(report.bounds, self._float("horizontal_buffer"), self._float("top_buffer"))
            names = ("xmin", "ymin", "zmin", "xmax", "ymax", "zmax")
            values = domain.minimum + domain.maximum
            for name, value in zip(names, values):
                self.variables[name].set(foam_number(value))
            clearance = max(0.5, min(1.0, domain.span[2] * 0.02))
            self.variables["location_x"].set(foam_number(domain.minimum[0] + self._float("horizontal_buffer") * 0.25))
            self.variables["location_y"].set(foam_number(domain.minimum[1] + self._float("horizontal_buffer") * 0.25))
            self.variables["location_z"].set(foam_number(domain.minimum[2] + clearance))
            self._recalculate_mesh()
            minimum, maximum = auto_surface_levels(self._float("target_cell"), report.bounds)
            self.variables["surface_min"].set(minimum)
            self.variables["surface_max"].set(maximum)
            self.variables["feature_level"].set(minimum)
            self._set_status("สร้าง Domain, locationInMesh และ wall refinement อัตโนมัติแล้ว", "ok")
            self.notebook.select(self.mesh_tab)
        except Exception as exc:
            messagebox.showerror("Auto Domain ไม่สำเร็จ", str(exc))

    def _domain_values(self):
        from blast_case_builder import Bounds
        return Bounds(
            (self._float("xmin"), self._float("ymin"), self._float("zmin")),
            (self._float("xmax"), self._float("ymax"), self._float("zmax")),
        )

    def _recalculate_mesh(self) -> None:
        try:
            divisions = mesh_divisions(self._domain_values(), self._float("target_cell"))
            for name, value in zip(("nx", "ny", "nz"), divisions):
                self.variables[name].set(value)
            self._show_estimate()
        except Exception as exc:
            messagebox.showerror("คำนวณ Mesh ไม่สำเร็จ", str(exc))

    def _auto_charge_refinement(self) -> None:
        try:
            level = auto_charge_level(self._float("target_cell"), self._float("mass"), self._float("density"), 6)
            self.variables["charge_level"].set(level)
            self._update_charge_summary()
            self._set_status("คำนวณ charge refinement สำหรับอย่างน้อยประมาณ 6 cells ต่อเส้นผ่านศูนย์กลางแล้ว", "ok")
        except Exception as exc:
            messagebox.showerror("คำนวณ Charge ไม่สำเร็จ", str(exc))

    def _planes_at_charge(self) -> None:
        for axis in "xyz":
            self.variables[f"plane_{axis}"].set(self.variables[f"charge_{axis}"].get())
        self._set_status("ย้ายระนาบ X/Y/Z ให้ผ่านจุดศูนย์กลางระเบิดแล้ว", "ok")

    def _update_charge_summary(self) -> None:
        try:
            radius = charge_radius(self._float("mass"), self._float("density"))
            cell = self._float("target_cell") / (2 ** self._int("charge_level"))
            across = 2 * radius / cell
            self.charge_summary.configure(
                text=f"รัศมีทฤษฎี {radius:.5g} m  •  cell รอบ charge ≈ {cell:.5g} m  •  ประมาณ {across:.1f} cells ต่อเส้นผ่านศูนย์กลาง"
            )
        except Exception:
            self.charge_summary.configure(text="กรอกมวล ความหนาแน่น และ refinement ให้ถูกต้อง")

    def _config(self) -> CaseConfig:
        return CaseConfig(
            case_name=str(self.variables["case_name"].get()),
            stl_path=str(Path(str(self.variables["stl"].get())).expanduser()),
            stl_scale=self._float("scale"),
            domain_min=(self._float("xmin"), self._float("ymin"), self._float("zmin")),
            domain_max=(self._float("xmax"), self._float("ymax"), self._float("zmax")),
            divisions=(self._int("nx"), self._int("ny"), self._int("nz")),
            surface_min_level=self._int("surface_min"),
            surface_max_level=self._int("surface_max"),
            feature_level=self._int("feature_level"),
            snappy_max_cells=self._int("snappy_cells"),
            dynamic_max_cells=self._int("dynamic_cells"),
            dynamic_max_refinement=self._int("dynamic_levels"),
            refine_interval=self._int("refine_interval"),
            location_in_mesh=self._vec("location"),
            charge_centre=self._vec("charge"),
            charge_mass=self._float("mass"),
            explosive_density=self._float("density"),
            charge_refinement_level=self._int("charge_level"),
            probes=parse_probes(self.probes_text.get("1.0", "end")),
            plane_point=self._vec("plane"),
            end_time=self._float("end_time"),
            initial_delta_t=self._float("delta_t"),
            max_delta_t=self._float("max_delta_t"),
            max_co=self._float("max_co"),
            write_interval=self._float("write_interval"),
            ambient_pressure=self._float("ambient_pressure"),
            pressure_iso_value=self._float("iso_pressure"),
            mpi_ranks=self._int("mpi"),
            output_binary=bool(self.variables["binary"].get()),
            allow_surface_errors=bool(self.variables["allow_surface_errors"].get()),
        )

    def _show_estimate(self) -> None:
        try:
            config = self._config()
            estimate = config.estimate()
            cell = config.actual_cell_size
            text = (
                f"Base cells: {config.base_cells:,}  •  cell จริง: {foam_vec(cell)} m  •  "
                f"output ≈ {int(estimate['frames']):,} frames  •  RAM ที่ dynamic cap ≈ "
                f"{estimate['ram_gib_at_dynamic_cap']:.1f} GiB  •  disk worst-case planning ≈ "
                f"{estimate['disk_gib_at_dynamic_cap']:.0f} GiB"
            )
            self.mesh_summary.configure(text=text)
            self._update_charge_summary()
        except Exception as exc:
            self.mesh_summary.configure(text=f"ข้อมูลยังไม่ครบ: {exc}")

    def _render_validation(self, errors, warnings, config: CaseConfig) -> None:
        self.validation_output.delete("1.0", "end")
        if errors:
            self.validation_output.insert("end", f"ERROR ({len(errors)} รายการ)\n", "error")
            for item in errors:
                self.validation_output.insert("end", f"  • {item}\n", "error")
        else:
            self.validation_output.insert("end", "CONFIG OK — พร้อมสร้าง case\n", "ok")
        if warnings:
            self.validation_output.insert("end", f"\nWARNING ({len(warnings)} รายการ)\n", "warning")
            for item in warnings:
                self.validation_output.insert("end", f"  • {item}\n", "warning")
        estimate = config.estimate()
        self.validation_output.insert(
            "end",
            "\nSUMMARY\n"
            f"  Domain: {foam_vec(config.domain_min)} → {foam_vec(config.domain_max)} m\n"
            f"  Mesh: {config.divisions} = {config.base_cells:,} base cells\n"
            f"  Charge: {config.charge_mass:g} kg, radius {config.theoretical_charge_radius:.5g} m at {foam_vec(config.charge_centre)}\n"
            f"  MPI: {config.mpi_ranks}; output frames ≈ {int(estimate['frames']):,}\n",
        )

    def _validate(self) -> None:
        if self.busy:
            return
        try:
            config = self._config()
            report = self._require_report()
        except Exception as exc:
            self.validation_output.delete("1.0", "end")
            self.validation_output.insert("end", f"ERROR: {exc}\n", "error")
            self._set_status("ตรวจ Config ไม่สำเร็จ", "error")
            return
        self._set_busy(True, "กำลังตรวจพิกัดกับผิว STL และตรวจ Config…")

        def work() -> None:
            try:
                result = validate_config(config, report, inspect_points=True)
                self.root.after(0, lambda: self._validation_done(config, result, None))
            except Exception as exc:
                self.root.after(0, lambda error=exc: self._validation_done(config, None, error))

        threading.Thread(target=work, daemon=True).start()

    def _validation_done(self, config: CaseConfig, result, error: Optional[Exception]) -> None:
        self._set_busy(False)
        if error:
            self.validation_output.delete("1.0", "end")
            self.validation_output.insert("end", f"ERROR: {error}\n", "error")
            self._set_status("ตรวจ Config ไม่สำเร็จ", "error")
            return
        errors, warnings = result
        self._render_validation(errors, warnings, config)
        self._set_status("Config มีข้อผิดพลาด" if errors else "Config ผ่านการตรวจ", "error" if errors else "ok")

    def _export(self) -> None:
        if self.busy:
            return
        try:
            config = self._config()
            report = self._require_report()
            output = Path(str(self.variables["output"].get())).expanduser()
            archive = bool(self.variables["archive"].get())
            # The inexpensive checks run immediately.  create_case performs the
            # full point-to-surface checks in the background before writing.
            errors, warnings = validate_config(config, report, inspect_points=False)
            self._render_validation(errors, warnings, config)
            if errors:
                self._set_status("ยัง Export ไม่ได้ — แก้ข้อความสีแดงก่อน", "error")
                return
        except Exception as exc:
            messagebox.showerror("ข้อมูลไม่ถูกต้อง", str(exc))
            return
        self._set_busy(True, "กำลังสร้าง case แยกและ package สำหรับ server…")

        def work() -> None:
            try:
                result = create_case(config, output, report, create_archive=archive)
                self.root.after(0, lambda: self._export_done(result, None))
            except Exception as exc:
                self.root.after(0, lambda error=exc: self._export_done(None, error))

        threading.Thread(target=work, daemon=True).start()

    def _export_done(self, result, error: Optional[Exception]) -> None:
        self._set_busy(False)
        if error:
            self.validation_output.insert("end", f"\nEXPORT ERROR: {error}\n", "error")
            self._set_status("สร้าง package ไม่สำเร็จ", "error")
            messagebox.showerror("Export ไม่สำเร็จ", str(error))
            return
        target, archive, warnings = result
        self.validation_output.insert("end", f"\nสร้าง Case สำเร็จ:\n  {target}\n", "ok")
        if archive:
            self.validation_output.insert("end", f"Server package:\n  {archive}\n", "ok")
        self.validation_output.insert("end", "คำสั่งและขั้นตอนอยู่ใน SERVER_COMMANDS.md\n", "ok")
        self._set_status("สร้าง case และ server package สำเร็จ โดยไม่แก้ template ต้นฉบับ", "ok")
        messagebox.showinfo("สำเร็จ", f"สร้าง case แล้ว:\n{target}" + (f"\n\nArchive:\n{archive}" if archive else ""))


def main() -> None:
    root = tk.Tk()
    BlastCaseUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
