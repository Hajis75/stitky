#!/usr/bin/env python3
"""
Tisk adresních štítků 3×8 na arch 217×304 mm.
Podporuje přímý tisk na tiskárnu i export do PDF.
"""

from __future__ import annotations

import sys
import tempfile
import tkinter as tk
from io import BytesIO
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from layout import ROWS, SheetLayout, cell_name, parse_range
from printer import default_printer, list_printers, print_pdf
from renderer import (
    LabelContent,
    RenderOptions,
    max_fitting_font_size,
    render_sheet_pdf,
    text_fits,
)

APP_TITLE = "Tisk štítků 3×8"
MODES = {
    "Jen text": "text",
    "Text + obrázek": "text_image",
    "Jen obrázek": "image",
}


class LabelApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(920, 720)
        self.image_path: str | None = None
        self._build_ui()
        self._refresh_printers()
        self._update_layout_info()
        self._on_text_change()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(root)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right = ttk.Frame(root, width=320)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))

        # --- Rozměry ---
        dims = ttk.LabelFrame(right, text="Rozměry (mm)", padding=8)
        dims.pack(fill=tk.X)
        self.var_page_w = tk.DoubleVar(value=217.0)
        self.var_page_h = tk.DoubleVar(value=304.0)
        self.var_print_w = tk.DoubleVar(value=215.0)
        self.var_print_h = tk.DoubleVar(value=304.0)
        self.var_label_w = tk.DoubleVar(value=70.0)
        self.var_label_h = tk.DoubleVar(value=36.0)
        self.var_print_margin = tk.DoubleVar(value=4.0)
        self.var_outer_x = tk.StringVar(value="")
        self.var_outer_y = tk.StringVar(value="")
        self.var_nudge_x = tk.DoubleVar(value=0.0)
        self.var_nudge_y = tk.DoubleVar(value=0.0)

        rows_spec = [
            ("Fyzická šířka archu", self.var_page_w),
            ("Fyzická výška archu", self.var_page_h),
            ("Tisková šířka (ovladač)", self.var_print_w),
            ("Tisková výška (ovladač)", self.var_print_h),
            ("Šířka štítku", self.var_label_w),
            ("Výška štítku", self.var_label_h),
            ("Tisknutelná hranice", self.var_print_margin),
            ("Nudge X (doladění)", self.var_nudge_x),
            ("Nudge Y (doladění)", self.var_nudge_y),
        ]
        for i, (label, var) in enumerate(rows_spec):
            ttk.Label(dims, text=label).grid(row=i, column=0, sticky=tk.W, pady=2)
            e = ttk.Entry(dims, textvariable=var, width=10)
            e.grid(row=i, column=1, sticky=tk.E, pady=2)
            e.bind("<KeyRelease>", lambda _e: self._update_layout_info())
            e.bind("<FocusOut>", lambda _e: self._update_layout_info())

        ttk.Label(dims, text="Vnější okraj X (auto)").grid(
            row=9, column=0, sticky=tk.W, pady=2
        )
        e_ox = ttk.Entry(dims, textvariable=self.var_outer_x, width=10)
        e_ox.grid(row=9, column=1, sticky=tk.E, pady=2)
        e_ox.bind("<KeyRelease>", lambda _e: self._update_layout_info())
        e_ox.bind("<FocusOut>", lambda _e: self._update_layout_info())

        ttk.Label(dims, text="Vnější okraj Y (auto)").grid(
            row=10, column=0, sticky=tk.W, pady=2
        )
        e_oy = ttk.Entry(dims, textvariable=self.var_outer_y, width=10)
        e_oy.grid(row=10, column=1, sticky=tk.E, pady=2)
        e_oy.bind("<KeyRelease>", lambda _e: self._update_layout_info())
        e_oy.bind("<FocusOut>", lambda _e: self._update_layout_info())

        ttk.Label(
            dims,
            text="Arch 217 mm, tisk 215 mm = centrovaný přesah 1 mm.\n"
            "V ovladači zvolte vlastní formát 215×304 mm.\n"
            "Nudge: jemné posunutí tisku při doladění.",
            wraplength=280,
            foreground="#555",
        ).grid(row=11, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))

        self.layout_info = tk.StringVar(value="")
        ttk.Label(dims, textvariable=self.layout_info, wraplength=280, foreground="#333").grid(
            row=12, column=0, columnspan=2, sticky=tk.W, pady=(6, 0)
        )

        # --- Pozice ---
        pos = ttk.LabelFrame(right, text="Pozice štítků", padding=8)
        pos.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(pos, text="Např. A1  |  A1-B2  |  A1,C3,H1").pack(anchor=tk.W)
        self.var_positions = tk.StringVar(value="A1")
        ttk.Entry(pos, textvariable=self.var_positions).pack(fill=tk.X, pady=4)

        grid = ttk.Frame(pos)
        grid.pack(fill=tk.X, pady=4)
        self.cell_vars: dict[tuple[int, int], tk.BooleanVar] = {}
        for r, letter in enumerate(ROWS):
            ttk.Label(grid, text=letter, width=2).grid(row=r + 1, column=0)
            for c in range(3):
                if r == 0:
                    ttk.Label(grid, text=str(c + 1), width=3).grid(row=0, column=c + 1)
                var = tk.BooleanVar(value=(r == 0 and c == 0))
                self.cell_vars[(r, c)] = var
                cb = ttk.Checkbutton(
                    grid, variable=var, command=self._sync_positions_from_grid
                )
                cb.grid(row=r + 1, column=c + 1)

        ttk.Button(pos, text="Vybrat vše", command=self._select_all).pack(fill=tk.X, pady=2)
        ttk.Button(pos, text="Zrušit výběr", command=self._select_none).pack(fill=tk.X)

        # --- Tiskárna ---
        prn = ttk.LabelFrame(right, text="Tiskárna", padding=8)
        prn.pack(fill=tk.X, pady=(10, 0))
        self.var_printer = tk.StringVar(value="")
        self.cmb_printer = ttk.Combobox(prn, textvariable=self.var_printer, state="readonly")
        self.cmb_printer.pack(fill=tk.X)
        ttk.Button(prn, text="Obnovit seznam", command=self._refresh_printers).pack(
            fill=tk.X, pady=4
        )

        # --- Obsah vlevo ---
        mode_fr = ttk.LabelFrame(left, text="Obsah štítku", padding=8)
        mode_fr.pack(fill=tk.X)
        self.var_mode = tk.StringVar(value="Jen text")
        for label in MODES:
            ttk.Radiobutton(
                mode_fr,
                text=label,
                value=label,
                variable=self.var_mode,
                command=self._on_mode_change,
            ).pack(anchor=tk.W)

        img_fr = ttk.Frame(mode_fr)
        img_fr.pack(fill=tk.X, pady=4)
        ttk.Button(img_fr, text="Vybrat obrázek…", command=self._pick_image).pack(
            side=tk.LEFT
        )
        self.var_image_label = tk.StringVar(value="(žádný obrázek)")
        ttk.Label(img_fr, textvariable=self.var_image_label).pack(side=tk.LEFT, padx=8)

        text_fr = ttk.LabelFrame(left, text="Text adresy", padding=8)
        text_fr.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.txt = tk.Text(text_fr, height=10, wrap=tk.WORD, font=("Segoe UI", 12))
        self.txt.pack(fill=tk.BOTH, expand=True)
        self.txt.insert(
            "1.0",
            "Jan Novák\nUlice 123\n110 00 Praha 1",
        )
        self.txt.bind("<<Modified>>", self._on_text_modified)

        font_fr = ttk.Frame(text_fr)
        font_fr.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(font_fr, text="Velikost písma (pt):").pack(side=tk.LEFT)
        self.var_font = tk.DoubleVar(value=11.0)
        self.spn_font = ttk.Spinbox(
            font_fr,
            from_=6,
            to=28,
            increment=0.5,
            textvariable=self.var_font,
            width=6,
            command=self._on_font_change,
        )
        self.spn_font.pack(side=tk.LEFT, padx=6)
        self.spn_font.bind("<KeyRelease>", lambda _e: self._on_font_change())
        ttk.Button(font_fr, text="Automaticky vejít", command=self._autofit_font).pack(
            side=tk.LEFT, padx=4
        )

        self.status_var = tk.StringVar(value="")
        ttk.Label(text_fr, textvariable=self.status_var, foreground="#0a5").pack(
            anchor=tk.W, pady=(6, 0)
        )

        opts = ttk.Frame(left)
        opts.pack(fill=tk.X, pady=(8, 0))
        self.var_outlines = tk.BooleanVar(value=True)
        self.var_names = tk.BooleanVar(value=True)
        self.var_printable = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opts, text="Náhledové rámečky štítků (jen pro zkoušku)", variable=self.var_outlines
        ).pack(anchor=tk.W)
        ttk.Checkbutton(opts, text="Zobrazit kódy pozic A1…", variable=self.var_names).pack(
            anchor=tk.W
        )
        ttk.Checkbutton(
            opts,
            text="Zobrazit tisknutelnou oblast",
            variable=self.var_printable,
        ).pack(anchor=tk.W)

        btns = ttk.Frame(left)
        btns.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btns, text="Náhled PDF…", command=self._preview).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(btns, text="Uložit PDF…", command=self._save_pdf).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(btns, text="Tisknout na tiskárnu", command=self._print).pack(
            side=tk.LEFT
        )

    # --- helpers ---

    def _layout(self) -> SheetLayout:
        def opt_float(s: str) -> float | None:
            s = s.strip().replace(",", ".")
            if not s:
                return None
            return float(s)

        pm = float(self.var_print_margin.get())
        return SheetLayout(
            page_width_mm=float(self.var_page_w.get()),
            page_height_mm=float(self.var_page_h.get()),
            print_width_mm=float(self.var_print_w.get()),
            print_height_mm=float(self.var_print_h.get()),
            label_width_mm=float(self.var_label_w.get()),
            label_height_mm=float(self.var_label_h.get()),
            printable_margin_left_mm=pm,
            printable_margin_right_mm=pm,
            printable_margin_top_mm=pm,
            printable_margin_bottom_mm=pm,
            outer_margin_x_mm=opt_float(self.var_outer_x.get()),
            outer_margin_y_mm=opt_float(self.var_outer_y.get()),
            nudge_x_mm=float(self.var_nudge_x.get()),
            nudge_y_mm=float(self.var_nudge_y.get()),
        )

    def _update_layout_info(self) -> None:
        try:
            lay = self._layout()
            msg = lay.summary_text()
            warns = lay.fit_warnings()
            if warns:
                msg += "\n⚠ " + " ".join(warns)
            self.layout_info.set(msg)
            self._on_text_change()
        except Exception as exc:
            self.layout_info.set(f"Chyba rozměrů: {exc}")

    def _refresh_printers(self) -> None:
        printers = list_printers()
        self.cmb_printer["values"] = printers
        d = default_printer()
        if d and d in printers:
            self.var_printer.set(d)
        elif printers:
            self.var_printer.set(printers[0])
        else:
            self.var_printer.set("")

    def _sync_positions_from_grid(self) -> None:
        selected = [
            cell_name(r, c) for (r, c), v in sorted(self.cell_vars.items()) if v.get()
        ]
        self.var_positions.set(",".join(selected) if selected else "")

    def _select_all(self) -> None:
        for v in self.cell_vars.values():
            v.set(True)
        self._sync_positions_from_grid()

    def _select_none(self) -> None:
        for v in self.cell_vars.values():
            v.set(False)
        self.var_positions.set("")

    def _pick_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Vyberte obrázek",
            filetypes=[
                ("Obrázky", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                ("Vše", "*.*"),
            ],
        )
        if path:
            self.image_path = path
            self.var_image_label.set(Path(path).name)
            self._on_text_change()

    def _on_mode_change(self) -> None:
        self._on_text_change()

    def _on_text_modified(self, _event=None) -> None:
        if self.txt.edit_modified():
            self.txt.edit_modified(False)
            self._on_text_change()

    def _reserved_image_h(self, lay: SheetLayout) -> float:
        mode = MODES[self.var_mode.get()]
        if mode == "text_image" and self.image_path:
            return lay.label_height_mm * 0.45 + 1.0
        return 0.0

    def _on_text_change(self) -> None:
        try:
            lay = self._layout()
            text = self.txt.get("1.0", "end-1c")
            mode = MODES[self.var_mode.get()]
            if mode == "image":
                self.status_var.set("Režim jen obrázek — text se netiskne.")
                return
            if not text.strip():
                self.status_var.set("Text je prázdný.")
                return
            size = float(self.var_font.get())
            reserved = self._reserved_image_h(lay)
            ok, lines, need = text_fits(
                text,
                lay.label_width_mm,
                lay.label_height_mm,
                size,
                2.0,
                reserved,
            )
            usable = lay.label_height_mm - 4.0 - reserved
            if ok:
                self.status_var.set(
                    f"OK — {len(lines)} řádků, výška textu {need:.1f} mm "
                    f"(limit {usable:.1f} mm)."
                )
            else:
                max_sz = max_fitting_font_size(
                    text, lay.label_width_mm, lay.label_height_mm, 2.0, reserved
                )
                self.status_var.set(
                    f"Text se nevejde při {size} pt. Max. vhodná velikost: {max_sz} pt."
                )
        except Exception as exc:
            self.status_var.set(f"Kontrola textu: {exc}")

    def _on_font_change(self) -> None:
        try:
            lay = self._layout()
            text = self.txt.get("1.0", "end-1c")
            size = float(self.var_font.get())
            reserved = self._reserved_image_h(lay)
            ok, _, _ = text_fits(
                text, lay.label_width_mm, lay.label_height_mm, size, 2.0, reserved
            )
            if not ok and text.strip() and MODES[self.var_mode.get()] != "image":
                max_sz = max_fitting_font_size(
                    text, lay.label_width_mm, lay.label_height_mm, 2.0, reserved
                )
                if size > max_sz:
                    self.var_font.set(max_sz)
                    messagebox.showwarning(
                        "Písmo moc velké",
                        f"Při velikosti {size} pt se text nevejde na štítek "
                        f"{lay.label_width_mm:.0f}×{lay.label_height_mm:.0f} mm.\n"
                        f"Nastaveno na maximum {max_sz} pt.",
                    )
            self._on_text_change()
        except Exception:
            self._on_text_change()

    def _autofit_font(self) -> None:
        lay = self._layout()
        text = self.txt.get("1.0", "end-1c")
        reserved = self._reserved_image_h(lay)
        size = max_fitting_font_size(
            text, lay.label_width_mm, lay.label_height_mm, 2.0, reserved
        )
        self.var_font.set(size)
        self._on_text_change()

    def _positions(self) -> list[tuple[int, int]]:
        # Prefer text field (podporuje rozsahy); synchronizuj checkboxy
        positions = parse_range(self.var_positions.get())
        for key, var in self.cell_vars.items():
            var.set(key in set(positions))
        return positions

    def _content(self) -> LabelContent:
        mode = MODES[self.var_mode.get()]
        if mode in ("image", "text_image") and not self.image_path:
            raise ValueError("Vyberte obrázek, nebo přepněte na režim „Jen text“.")
        return LabelContent(
            text=self.txt.get("1.0", "end-1c"),
            image_path=self.image_path,
            mode=mode,
            font_size_pt=float(self.var_font.get()),
        )

    def _options(self) -> RenderOptions:
        return RenderOptions(
            show_outlines=self.var_outlines.get(),
            show_cell_names=self.var_names.get(),
            show_printable_area=self.var_printable.get(),
        )

    def _build_pdf_bytes(self) -> bytes:
        lay = self._layout()
        warns = lay.fit_warnings()
        if warns:
            if not messagebox.askyesno(
                "Upozornění k rozměrům",
                "\n\n".join(warns) + "\n\nPokračovat i tak?",
            ):
                raise RuntimeError("Zrušeno uživatelem")
        positions = self._positions()
        if not positions:
            raise ValueError("Vyberte alespoň jednu pozici štítku.")
        content = self._content()
        # finální pojistka velikosti textu
        if content.mode != "image" and content.text.strip():
            reserved = self._reserved_image_h(lay)
            ok, _, _ = text_fits(
                content.text,
                lay.label_width_mm,
                lay.label_height_mm,
                content.font_size_pt,
                2.0,
                reserved,
            )
            if not ok:
                content.font_size_pt = max_fitting_font_size(
                    content.text,
                    lay.label_width_mm,
                    lay.label_height_mm,
                    2.0,
                    reserved,
                )
                self.var_font.set(content.font_size_pt)

        buf = BytesIO()
        render_sheet_pdf(lay, positions, content, buf, self._options())
        return buf.getvalue()

    def _save_pdf(self) -> None:
        try:
            data = self._build_pdf_bytes()
        except RuntimeError:
            return
        except Exception as exc:
            messagebox.showerror("Chyba", str(exc))
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile="stitky.pdf",
        )
        if not path:
            return
        Path(path).write_bytes(data)
        messagebox.showinfo("Uloženo", f"PDF uloženo:\n{path}")

    def _preview(self) -> None:
        try:
            data = self._build_pdf_bytes()
        except RuntimeError:
            return
        except Exception as exc:
            messagebox.showerror("Chyba", str(exc))
            return
        fd, name = tempfile.mkstemp(prefix="stitky_nahled_", suffix=".pdf")
        import os

        os.close(fd)
        path = Path(name)
        path.write_bytes(data)
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", str(path)])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showinfo("Náhled", f"PDF: {path}\n({exc})")

    def _print(self) -> None:
        try:
            data = self._build_pdf_bytes()
        except RuntimeError:
            return
        except Exception as exc:
            messagebox.showerror("Chyba", str(exc))
            return

        printer = self.var_printer.get().strip() or None
        fd, name = tempfile.mkstemp(prefix="stitky_tisk_", suffix=".pdf")
        import os

        os.close(fd)
        path = Path(name)
        path.write_bytes(data)
        try:
            # Pro ostrý tisk vypnout rámečky — zeptáme se, pokud jsou zapnuté
            if self.var_outlines.get() or self.var_names.get() or self.var_printable.get():
                if messagebox.askyesno(
                    "Náhledové značky",
                    "Máte zapnuté náhledové rámečky / kódy / tisknutelnou oblast.\n"
                    "Pro ostrý tisk na štítky je vypnout?\n\n"
                    "Ano = vytisknout bez značek\nNe = vytisknout jak je",
                ):
                    self.var_outlines.set(False)
                    self.var_names.set(False)
                    self.var_printable.set(False)
                    data = self._build_pdf_bytes()
                    path.write_bytes(data)

            print_pdf(path, printer)
            messagebox.showinfo(
                "Tisk",
                f"Úloha odeslána na tiskárnu"
                + (f" „{printer}“." if printer else " (výchozí)."),
            )
        except Exception as exc:
            messagebox.showerror(
                "Tisk selhal",
                f"{exc}\n\nTip: na Windows pomůže nainstalovaný SumatraPDF "
                "nebo výchozí prohlížeč PDF s podporou tisku.\n"
                "Můžete také použít „Uložit PDF…“ a vytisknout ručně.",
            )


def main() -> None:
    app = LabelApp()
    app.mainloop()


if __name__ == "__main__":
    main()
