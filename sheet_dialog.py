"""Modální okno „Správa archů“ — zadání rozměrů, roztečí a mezer."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from layout import ROWS, cell_name
from sheets import (
    AXIS_GAP,
    AXIS_INTERPOLATE,
    AXIS_MODE_TITLES,
    AXIS_MODES,
    AXIS_PITCH,
    AxisSpec,
    SheetDefinition,
    SheetStore,
    builtin_by_id,
)


def _fmt(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _num(raw: str, what: str) -> float:
    s = (raw or "").strip().replace(",", ".")
    if not s:
        raise ValueError(f"Chybí hodnota: {what}.")
    try:
        return float(s)
    except ValueError as exc:
        raise ValueError(f"Neplatné číslo u „{what}“: {raw!r}") from exc


class _AxisForm:
    """Formulář pro jednu osu (sloupce / řádky)."""

    def __init__(
        self,
        parent: ttk.Frame,
        title: str,
        start_label: str,
        end_label: str,
        on_change,
    ) -> None:
        self.frame = ttk.LabelFrame(parent, text=title, padding=6)
        self.start_label = start_label
        self.end_label = end_label
        self.var_mode = tk.StringVar(value=AXIS_INTERPOLATE)
        self.var_start = tk.StringVar()
        self.var_end = tk.StringVar()
        self.var_gap = tk.StringVar()
        self.var_pitch = tk.StringVar()
        self.var_center = tk.BooleanVar(value=True)

        modes = ttk.Frame(self.frame)
        modes.grid(row=0, column=0, columnspan=4, sticky=tk.W)
        for i, mode in enumerate(AXIS_MODES):
            ttk.Radiobutton(
                modes,
                text=AXIS_MODE_TITLES[mode],
                value=mode,
                variable=self.var_mode,
                command=on_change,
            ).grid(row=0, column=i, sticky=tk.W, padx=(0, 10))

        self.e_start = self._field(1, 0, start_label, self.var_start)
        self.e_end = self._field(1, 2, end_label, self.var_end)
        self.e_gap = self._field(2, 0, "Mezera", self.var_gap)
        self.e_pitch = self._field(2, 2, "Rozteč středů", self.var_pitch)
        self.cb_center = ttk.Checkbutton(
            self.frame,
            text="Vystředit na arch (okraje dopočítat)",
            variable=self.var_center,
            command=on_change,
        )
        self.cb_center.grid(row=3, column=0, columnspan=4, sticky=tk.W, pady=(4, 0))

        for var in (self.var_start, self.var_end, self.var_gap, self.var_pitch):
            var.trace_add("write", lambda *_: on_change())

    def _field(self, row: int, col: int, label: str, var: tk.StringVar) -> ttk.Entry:
        ttk.Label(self.frame, text=f"{label} (mm)").grid(
            row=row, column=col, sticky=tk.W, pady=2, padx=(0, 4)
        )
        e = ttk.Entry(self.frame, textvariable=var, width=9)
        e.grid(row=row, column=col + 1, sticky=tk.W, pady=2, padx=(0, 12))
        return e

    # --- data ---
    def load(self, spec: AxisSpec) -> None:
        self.var_mode.set(spec.mode)
        self.var_start.set(_fmt(spec.margin_start_mm))
        self.var_end.set(_fmt(spec.margin_end_mm))
        self.var_gap.set(_fmt(spec.gap_mm))
        self.var_pitch.set(_fmt(spec.pitch_mm))
        self.var_center.set(bool(spec.center))

    def editable(self) -> dict[str, bool]:
        mode = self.var_mode.get()
        center = bool(self.var_center.get())
        return {
            "start": mode == AXIS_INTERPOLATE or not center,
            "end": mode == AXIS_INTERPOLATE,
            "gap": mode == AXIS_GAP,
            "pitch": mode == AXIS_PITCH,
            "center": mode != AXIS_INTERPOLATE,
        }

    def read(self, previous: AxisSpec) -> AxisSpec:
        """Načte jen editovatelná pole; dopočítaná pole drží předchozí hodnotu."""
        ed = self.editable()
        spec = AxisSpec(
            mode=self.var_mode.get(),
            margin_start_mm=previous.margin_start_mm,
            margin_end_mm=previous.margin_end_mm,
            gap_mm=previous.gap_mm,
            pitch_mm=previous.pitch_mm,
            center=bool(self.var_center.get()),
        )
        if ed["start"]:
            spec.margin_start_mm = _num(self.var_start.get(), self.start_label)
        if ed["end"]:
            spec.margin_end_mm = _num(self.var_end.get(), self.end_label)
        if ed["gap"]:
            spec.gap_mm = _num(self.var_gap.get(), "Mezera")
        if ed["pitch"]:
            spec.pitch_mm = _num(self.var_pitch.get(), "Rozteč středů")
        return spec

    def show_computed(self, start: float, end: float, gap: float, pitch: float) -> None:
        """Do needitovatelných polí zapíše dopočtené hodnoty."""
        ed = self.editable()
        pairs = (
            ("start", self.e_start, self.var_start, start),
            ("end", self.e_end, self.var_end, end),
            ("gap", self.e_gap, self.var_gap, gap),
            ("pitch", self.e_pitch, self.var_pitch, pitch),
        )
        for key, entry, var, value in pairs:
            if ed[key]:
                entry.configure(state=tk.NORMAL)
            else:
                entry.configure(state=tk.NORMAL)
                var.set(_fmt(round(value, 3)))
                entry.configure(state="readonly")
        self.cb_center.configure(state=tk.NORMAL if ed["center"] else tk.DISABLED)


class SheetManagerDialog(tk.Toplevel):
    """Správa archů. Po zavření: `result_id` = zvolený arch (nebo None = zrušeno)."""

    PREVIEW_W = 250
    PREVIEW_H = 340

    def __init__(self, master: tk.Misc, store: SheetStore, current_id: str) -> None:
        super().__init__(master)
        self.title("Správa archů")
        self.transient(master)
        self.resizable(True, True)
        self.store = store
        self.work: list[SheetDefinition] = [s.copy() for s in store.sheets]
        self.result_id: str | None = None
        self.changed = False
        self._index = 0
        self._updating = False

        self._build()
        idx = next((i for i, s in enumerate(self.work) if s.id == current_id), 0)
        self._select(idx)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self._grab()
        self.update_idletasks()
        try:
            x = master.winfo_rootx() + 40
            y = master.winfo_rooty() + 30
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _grab(self) -> None:
        try:
            self.grab_set()
        except tk.TclError:
            # okno ještě není zobrazené
            self.after(50, self._grab)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        # Seznam archů
        left = ttk.Frame(root)
        left.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(left, text="Archy").pack(anchor=tk.W)
        self.listbox = tk.Listbox(left, width=44, height=18, exportselection=False)
        self.listbox.pack(fill=tk.Y, expand=True, pady=(2, 6))
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)
        ttk.Button(left, text="Nový arch", command=self._new).pack(fill=tk.X)
        ttk.Button(left, text="Duplikovat", command=self._duplicate).pack(fill=tk.X, pady=2)
        self.btn_delete = ttk.Button(left, text="Smazat", command=self._delete)
        self.btn_delete.pack(fill=tk.X)
        self.btn_reset = ttk.Button(
            left, text="Obnovit výchozí hodnoty", command=self._reset_builtin
        )
        self.btn_reset.pack(fill=tk.X, pady=(2, 0))

        # Formulář
        form = ttk.Frame(root)
        form.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))
        self.var_name = tk.StringVar()
        self.var_page_w = tk.StringVar()
        self.var_page_h = tk.StringVar()
        self.var_print_same = tk.BooleanVar(value=True)
        self.var_print_w = tk.StringVar()
        self.var_print_h = tk.StringVar()
        self.var_label_w = tk.StringVar()
        self.var_label_h = tk.StringVar()
        self.var_cols = tk.StringVar()
        self.var_rows = tk.StringVar()
        self.var_scale_x = tk.StringVar()
        self.var_scale_y = tk.StringVar()
        self.var_nudge_x = tk.StringVar()
        self.var_nudge_y = tk.StringVar()

        gen = ttk.LabelFrame(form, text="Arch", padding=6)
        gen.pack(fill=tk.X)
        ttk.Label(gen, text="Název").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(gen, textvariable=self.var_name, width=40).grid(
            row=0, column=1, columnspan=3, sticky=tk.W + tk.E, pady=2
        )
        self._pair(gen, 1, "Šířka archu", self.var_page_w, "Délka archu", self.var_page_h)
        ttk.Checkbutton(
            gen,
            text="Formát v ovladači tiskárny = rozměr archu",
            variable=self.var_print_same,
            command=self._on_change,
        ).grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(4, 0))
        self.e_print_w, self.e_print_h = self._pair(
            gen, 3, "Šířka v ovladači", self.var_print_w, "Délka v ovladači", self.var_print_h
        )

        lab = ttk.LabelFrame(form, text="Štítek a mřížka", padding=6)
        lab.pack(fill=tk.X, pady=(8, 0))
        self._pair(lab, 0, "Šířka štítku", self.var_label_w, "Výška štítku", self.var_label_h)
        ttk.Label(lab, text="Sloupců").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Spinbox(lab, from_=1, to=26, textvariable=self.var_cols, width=7).grid(
            row=1, column=1, sticky=tk.W, pady=2, padx=(0, 12)
        )
        ttk.Label(lab, text="Řádků").grid(row=1, column=2, sticky=tk.W, pady=2)
        ttk.Spinbox(lab, from_=1, to=len(ROWS), textvariable=self.var_rows, width=7).grid(
            row=1, column=3, sticky=tk.W, pady=2
        )

        self.axis_x = _AxisForm(form, "Vodorovně (sloupce)", "Okraj vlevo", "Okraj vpravo",
                                self._on_change)
        self.axis_x.frame.pack(fill=tk.X, pady=(8, 0))
        self.axis_y = _AxisForm(form, "Svisle (řádky)", "Okraj nahoře", "Okraj dole",
                                self._on_change)
        self.axis_y.frame.pack(fill=tk.X, pady=(8, 0))

        cor = ttk.LabelFrame(form, text="Korekce tisku", padding=6)
        cor.pack(fill=tk.X, pady=(8, 0))
        self._pair(cor, 0, "Měřítko X (%)", self.var_scale_x, "Měřítko Y (%)", self.var_scale_y,
                   unit="")
        self._pair(cor, 1, "Posun X", self.var_nudge_x, "Posun Y", self.var_nudge_y)
        ttk.Label(
            cor,
            text="Měřítko 100 % = beze změny. Posun + = doprava / dolů.",
            foreground="#555",
        ).grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(2, 0))

        for var in (
            self.var_name, self.var_page_w, self.var_page_h, self.var_print_w,
            self.var_print_h, self.var_label_w, self.var_label_h, self.var_cols,
            self.var_rows, self.var_scale_x, self.var_scale_y, self.var_nudge_x,
            self.var_nudge_y,
        ):
            var.trace_add("write", lambda *_: self._on_change())

        # Náhled + výsledek
        side = ttk.Frame(root)
        side.pack(side=tk.LEFT, fill=tk.Y, padx=(12, 0))
        ttk.Label(side, text="Náhled").pack(anchor=tk.W)
        self.preview = tk.Canvas(
            side, width=self.PREVIEW_W, height=self.PREVIEW_H, background="#f4f4f4",
            highlightthickness=1, highlightbackground="#bbb",
        )
        self.preview.pack(pady=(2, 8))
        self.var_summary = tk.StringVar()
        self.lbl_summary = ttk.Label(
            side, textvariable=self.var_summary, wraplength=self.PREVIEW_W, justify=tk.LEFT
        )
        self.lbl_summary.pack(anchor=tk.W)

        btns = ttk.Frame(side)
        btns.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        ttk.Button(btns, text="Uložit a použít", command=self._save_and_use).pack(fill=tk.X)
        ttk.Button(btns, text="Uložit", command=self._save).pack(fill=tk.X, pady=2)
        ttk.Button(btns, text="Zavřít bez uložení", command=self._cancel).pack(fill=tk.X)

    def _pair(self, parent, row, l1, v1, l2, v2, unit=" (mm)"):
        ttk.Label(parent, text=f"{l1}{unit}").grid(row=row, column=0, sticky=tk.W, pady=2)
        e1 = ttk.Entry(parent, textvariable=v1, width=9)
        e1.grid(row=row, column=1, sticky=tk.W, pady=2, padx=(0, 12))
        ttk.Label(parent, text=f"{l2}{unit}").grid(row=row, column=2, sticky=tk.W, pady=2)
        e2 = ttk.Entry(parent, textvariable=v2, width=9)
        e2.grid(row=row, column=3, sticky=tk.W, pady=2)
        return e1, e2

    # ------------------------------------------------------------ seznam
    def _refresh_list(self) -> None:
        self.listbox.delete(0, tk.END)
        for s in self.work:
            mark = " (vestavěný)" if s.builtin else ""
            self.listbox.insert(tk.END, f"{s.name}{mark}")
        self.listbox.selection_clear(0, tk.END)
        if self.work:
            self.listbox.selection_set(self._index)
            self.listbox.see(self._index)

    def _on_list_select(self, _event=None) -> None:
        sel = self.listbox.curselection()
        if not sel or sel[0] == self._index:
            return
        self._select(sel[0])

    def _select(self, idx: int) -> None:
        self._index = max(0, min(idx, len(self.work) - 1))
        self._load_form(self.work[self._index])
        self._refresh_list()
        self._on_change()

    def _current(self) -> SheetDefinition:
        return self.work[self._index]

    def _new(self) -> None:
        base = self._current()
        sheet = base.copy(id=self._new_id(), name="Nový arch", builtin=False)
        self.work.append(sheet)
        self.changed = True
        self._select(len(self.work) - 1)

    def _duplicate(self) -> None:
        base = self._current()
        sheet = base.copy(id=self._new_id(), name=f"{base.name} (kopie)", builtin=False)
        self.work.append(sheet)
        self.changed = True
        self._select(len(self.work) - 1)

    def _delete(self) -> None:
        s = self._current()
        if s.builtin:
            return
        if not messagebox.askyesno("Smazat arch", f"Smazat arch „{s.name}“?", parent=self):
            return
        del self.work[self._index]
        self.changed = True
        self._select(min(self._index, len(self.work) - 1))

    def _reset_builtin(self) -> None:
        s = self._current()
        default = builtin_by_id(s.id) if s.builtin else None
        if default is None:
            return
        self.work[self._index] = default
        self.changed = True
        self._select(self._index)

    def _new_id(self) -> str:
        existing = {s.id for s in self.work}
        i = 1
        while f"arch_{i}" in existing:
            i += 1
        return f"arch_{i}"

    # ------------------------------------------------------------ formulář
    def _load_form(self, s: SheetDefinition) -> None:
        self._updating = True
        try:
            self.var_name.set(s.name)
            self.var_page_w.set(_fmt(s.page_width_mm))
            self.var_page_h.set(_fmt(s.page_height_mm))
            self.var_print_same.set(s.print_width_mm is None and s.print_height_mm is None)
            self.var_print_w.set(_fmt(s.effective_print_width_mm))
            self.var_print_h.set(_fmt(s.effective_print_height_mm))
            self.var_label_w.set(_fmt(s.label_width_mm))
            self.var_label_h.set(_fmt(s.label_height_mm))
            self.var_cols.set(str(s.cols))
            self.var_rows.set(str(s.rows))
            self.axis_x.load(s.x)
            self.axis_y.load(s.y)
            self.var_scale_x.set(_fmt(s.print_scale_x_pct))
            self.var_scale_y.set(_fmt(s.print_scale_y_pct))
            self.var_nudge_x.set(_fmt(s.nudge_x_mm))
            self.var_nudge_y.set(_fmt(s.nudge_y_mm))
        finally:
            self._updating = False
        self.btn_delete.configure(state=tk.DISABLED if s.builtin else tk.NORMAL)
        self.btn_reset.configure(state=tk.NORMAL if s.builtin else tk.DISABLED)

    def _read_form(self) -> SheetDefinition:
        prev = self._current()
        cols = int(_num(self.var_cols.get(), "Sloupců"))
        rows = int(_num(self.var_rows.get(), "Řádků"))
        same = bool(self.var_print_same.get())
        sheet = SheetDefinition(
            id=prev.id,
            name=self.var_name.get().strip(),
            page_width_mm=_num(self.var_page_w.get(), "Šířka archu"),
            page_height_mm=_num(self.var_page_h.get(), "Délka archu"),
            label_width_mm=_num(self.var_label_w.get(), "Šířka štítku"),
            label_height_mm=_num(self.var_label_h.get(), "Výška štítku"),
            cols=cols,
            rows=rows,
            x=self.axis_x.read(prev.x),
            y=self.axis_y.read(prev.y),
            print_width_mm=None if same else _num(self.var_print_w.get(), "Šířka v ovladači"),
            print_height_mm=None if same else _num(self.var_print_h.get(), "Délka v ovladači"),
            print_scale_x_pct=_num(self.var_scale_x.get(), "Měřítko X"),
            print_scale_y_pct=_num(self.var_scale_y.get(), "Měřítko Y"),
            nudge_x_mm=_num(self.var_nudge_x.get(), "Posun X"),
            nudge_y_mm=_num(self.var_nudge_y.get(), "Posun Y"),
            builtin=prev.builtin,
        )
        errors = sheet.validate()
        if errors:
            raise ValueError(" ".join(errors))
        return sheet

    def _on_change(self) -> None:
        if self._updating:
            return
        same = bool(self.var_print_same.get())
        for e in (self.e_print_w, self.e_print_h):
            e.configure(state="readonly" if same else tk.NORMAL)
        try:
            sheet = self._read_form()
        except ValueError as exc:
            self.var_summary.set(f"⚠ {exc}")
            self.lbl_summary.configure(foreground="#b00")
            self.preview.delete("all")
            return

        if sheet.to_dict() != self._current().to_dict():
            self.changed = True
        self.work[self._index] = sheet
        lay = sheet.to_layout()
        ml, mr, mt, mb = lay.margins_lrtb_mm()
        gx, gy = lay.gap_x_mm(), lay.gap_y_mm()

        self._updating = True
        try:
            if same:
                self.var_print_w.set(_fmt(sheet.page_width_mm))
                self.var_print_h.set(_fmt(sheet.page_height_mm))
            self.axis_x.show_computed(ml, mr, gx, lay.pitch_x_mm())
            self.axis_y.show_computed(mt, mb, gy, lay.pitch_y_mm())
        finally:
            self._updating = False

        # název v seznamu
        mark = " (vestavěný)" if sheet.builtin else ""
        self.listbox.delete(self._index)
        self.listbox.insert(self._index, f"{sheet.name}{mark}")
        self.listbox.selection_set(self._index)

        last_col = sheet.cols
        last_row = ROWS[sheet.rows - 1]
        lines = [
            f"Mezera X / Y: {gx:.2f} / {gy:.2f} mm",
            f"Rozteč X / Y: {lay.pitch_x_mm():.2f} / {lay.pitch_y_mm():.2f} mm",
            f"Středy A1→A{last_col}: {lay.pitch_x_mm() * (sheet.cols - 1):.2f} mm",
            f"Středy A1→{last_row}1: {lay.pitch_y_mm() * (sheet.rows - 1):.2f} mm",
            f"Okraje L / P: {ml:.2f} / {mr:.2f} mm",
            f"Okraje H / D: {mt:.2f} / {mb:.2f} mm",
        ]
        warns = [w for w in lay.fit_warnings() if "Tisková" not in w and "tisknutelnou" not in w]
        if warns:
            lines.append("")
            lines.extend(f"⚠ {w}" for w in warns)
        self.var_summary.set("\n".join(lines))
        self.lbl_summary.configure(foreground="#b00" if warns else "#222")
        self._draw_preview(lay)

    def _draw_preview(self, lay) -> None:
        c = self.preview
        c.delete("all")
        pad = 10
        sw = (self.PREVIEW_W - 2 * pad) / max(lay.page_width_mm, lay.print_width_mm)
        sh = (self.PREVIEW_H - 2 * pad) / max(lay.page_height_mm, lay.print_height_mm)
        s = min(sw, sh)
        ox = (self.PREVIEW_W - lay.page_width_mm * s) / 2
        oy = (self.PREVIEW_H - lay.page_height_mm * s) / 2

        c.create_rectangle(ox, oy, ox + lay.page_width_mm * s, oy + lay.page_height_mm * s,
                           fill="white", outline="#444")
        off_x, off_y = lay.print_offset_mm()
        if abs(off_x) > 0.05 or abs(off_y) > 0.05:
            px, py = ox + off_x * s, oy + off_y * s
            c.create_rectangle(px, py, px + lay.print_width_mm * s, py + lay.print_height_mm * s,
                               outline="#d07020", dash=(3, 2))
        for r in range(lay.rows):
            for col in range(lay.cols):
                x, y, w, h = lay.label_rect_mm(r, col)
                fill = "#ffe9b0" if (r, col) == (0, 0) else "#fff6dc"
                c.create_rectangle(ox + x * s, oy + y * s, ox + (x + w) * s, oy + (y + h) * s,
                                   fill=fill, outline="#c33")
                if lay.rows * lay.cols <= 60:
                    c.create_text(ox + x * s + 3, oy + y * s + 2, text=cell_name(r, col),
                                  anchor=tk.NW, fill="#933", font=("Segoe UI", 7))

    # ------------------------------------------------------------ uložení
    def _commit(self) -> bool:
        try:
            self.work[self._index] = self._read_form()
        except ValueError as exc:
            messagebox.showerror("Chyba v zadání", str(exc), parent=self)
            return False
        self.store.replace_all(self.work)
        try:
            self.store.save()
        except Exception as exc:
            messagebox.showerror("Uložení selhalo", str(exc), parent=self)
            return False
        self.changed = False
        return True

    def _save(self) -> None:
        if self._commit():
            self.result_id = self._current().id

    def _save_and_use(self) -> None:
        if self._commit():
            self.result_id = self._current().id
            self._close()

    def _cancel(self) -> None:
        if self.changed and not messagebox.askyesno(
            "Neuložené změny", "Zahodit neuložené změny archů?", parent=self
        ):
            return
        self._close()

    def _close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
