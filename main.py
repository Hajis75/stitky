#!/usr/bin/env python3
"""
Tisk samolepicích štítků na libovolný arch (verze 2.0).
Archy (rozměry, rozteče, mezery) se definují v okně „Správa archů“.
Podporuje přímý tisk na tiskárnu i export do PDF.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import tkinter as tk
from io import BytesIO
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from layout import (
    ROWS,
    SheetLayout,
    cell_name,
    parse_cell,
    parse_range,
)
from printer import default_printer, list_printers, print_bitmap
from sheet_dialog import SheetManagerDialog
from sheet_preview import SheetPreview
from sheets import DEFAULT_SHEET_ID, SheetDefinition, SheetStore
from richtext import (
    apply_color_on_range,
    apply_runs_to_text,
    apply_size_on_range,
    dump_text_runs,
    ensure_format_tags,
    max_run_size,
    normalize_runs,
    rich_block_height_mm,
    runs_from_plain,
    runs_to_json,
    runs_to_plain,
    style_at_index,
    toggle_tag_on_range,
)
from renderer import (
    LabelContent,
    RenderOptions,
    font_name,
    open_label_image,
    render_calibration_image,
    render_calibration_pdf,
    render_sheet_image,
    render_sheet_pdf,
)

APP_VERSION = "2.0"
APP_TITLE = f"Tisk štítků {APP_VERSION}"
DOC_VERSION = 6
ALIGN_LEFT = "left"
ALIGN_CENTER = "center"
ALIGN_RIGHT = "right"
DOC_FILETYPES = [
    ("JSON (obsah + nastavení)", "*.json"),
    ("Štítek (.stitky)", "*.stitky"),
    ("Všechny soubory", "*.*"),
]
SESSION_FILENAME = "last_session.json"
SHEETS_FILENAME = "sheets.json"


def _documents_dir() -> Path:
    """Složka pro uložené projekty (vytvoří se při potřebě)."""
    base = Path.home() / "Documents" / "Stitky"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        base = Path.cwd()
    return base


def _session_path() -> Path:
    return _documents_dir() / SESSION_FILENAME


def _session_enabled() -> bool:
    """Testy mohou vypnout session přes STITKY_NO_SESSION=1."""
    return os.environ.get("STITKY_NO_SESSION", "").strip() != "1"


def _sheets_path() -> Path | None:
    """Uložené definice archů; bez session (testy) jen v paměti."""
    if not _session_enabled():
        return None
    return _documents_dir() / SHEETS_FILENAME


MODES = {
    "Jen text": "text",
    "Text + obrázek": "text_image",
    "Jen obrázek": "image",
}
MODE_BY_VALUE = {v: k for k, v in MODES.items()}


class LabelApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(1240, 720)
        try:
            w = min(1560, self.winfo_screenwidth() - 40)
            h = min(920, self.winfo_screenheight() - 80)
            self.geometry(f"{w}x{h}+10+10")
        except Exception:
            pass
        self.image_path: str | None = None
        self.doc_path: Path | None = None
        self.active_cell: tuple[int, int] = (0, 0)
        self.label_states: dict[str, dict] = {}
        self.sheet_store = SheetStore(_sheets_path())
        self._loading_editor = False
        self._session_save_after_id: str | None = None
        self._init_styles()
        self._build_ui()
        self._init_default_labels()
        self._refresh_printers()
        self._restore_session()
        self._on_text_change()
        self._bind_shortcuts()
        self._update_title()
        self._update_active_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_styles(self) -> None:
        style = ttk.Style(self)
        base = ("Segoe UI", 9)
        style.configure("Title.TLabel", font=("Segoe UI", 14, "bold"), foreground="#1565c0")
        style.configure("Hint.TLabel", font=("Segoe UI", 8), foreground="#666")
        style.configure("Ok.TLabel", font=base, foreground="#1b7a3a")
        style.configure("Bad.TLabel", font=base, foreground="#b00020")
        style.configure("Warn.TLabel", font=("Segoe UI", 8), foreground="#b26a00")
        style.configure("Count.TLabel", font=("Segoe UI", 9, "bold"), foreground="#2e7d32")
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(8, 6))
        style.configure("Status.TLabel", font=base, foreground="#333", background="#e9e9e9")

    def _set_status(self, message: str) -> None:
        """Krátká zpráva do stavového řádku (místo vyskakovacího okna)."""
        if hasattr(self, "app_status"):
            self.app_status.set(message)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(root)
        left.pack(side=tk.LEFT, fill=tk.Y)

        # --- Náhled celého archu (prostřední sloupec) ---
        sheet_fr = ttk.LabelFrame(root, text="Arch", padding=6)
        sheet_fr.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))

        sel_bar = ttk.Frame(sheet_fr)
        sel_bar.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(sel_bar, text="Tisknout:").pack(side=tk.LEFT)
        ttk.Button(sel_bar, text="Vše", width=6, command=self._select_all).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        ttk.Button(sel_bar, text="Vyplněné", command=self._select_filled).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        ttk.Button(sel_bar, text="Nic", width=6, command=self._select_none).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        self.var_selection_count = tk.StringVar(value="")
        ttk.Label(sel_bar, textvariable=self.var_selection_count, style="Count.TLabel").pack(
            side=tk.RIGHT
        )

        self.sheet_preview = SheetPreview(
            sheet_fr,
            on_select=self._on_preview_select,
            on_toggle=self._toggle_print_cell,
        )
        self.sheet_preview.pack(fill=tk.BOTH, expand=True)
        legend = ttk.Frame(sheet_fr)
        legend.pack(fill=tk.X, pady=(4, 0))
        tk.Label(legend, text="■ upravuje se", foreground="#1565c0").pack(side=tk.LEFT)
        tk.Label(legend, text="■ ✓ tiskne se", foreground="#2e7d32").pack(
            side=tk.LEFT, padx=(10, 0)
        )
        ttk.Label(
            legend,
            text="klik = upravit · pravý klik = tisk ano/ne · Alt+šipky = další štítek",
            style="Hint.TLabel",
        ).pack(side=tk.RIGHT)

        # Pravý panel se scrollem — ať je výběr archu vždy dostupný.
        right_wrap = ttk.Frame(root, width=340)
        right_wrap.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0), before=left)
        right_wrap.pack_propagate(False)
        right_canvas = tk.Canvas(right_wrap, highlightthickness=0, width=320)
        right_scroll = ttk.Scrollbar(
            right_wrap, orient=tk.VERTICAL, command=right_canvas.yview
        )
        right_canvas.configure(yscrollcommand=right_scroll.set)
        right_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        right_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right = ttk.Frame(right_canvas)
        right_window = right_canvas.create_window((0, 0), window=right, anchor=tk.NW)

        def _sync_right_scroll(_event=None) -> None:
            right_canvas.configure(scrollregion=right_canvas.bbox("all"))
            right_canvas.itemconfigure(right_window, width=right_canvas.winfo_width())

        right.bind("<Configure>", _sync_right_scroll)
        right_canvas.bind("<Configure>", _sync_right_scroll)

        def _on_right_mousewheel(event) -> str | None:
            right_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        for w in (right_canvas, right, right_wrap):
            w.bind("<Enter>", lambda _e: right_canvas.bind_all(
                "<MouseWheel>", _on_right_mousewheel
            ))
            w.bind("<Leave>", lambda _e: right_canvas.unbind_all("<MouseWheel>"))

        # --- Výběr archu (nahoře, výrazně) ---
        preset0 = self.sheet_store.get(DEFAULT_SHEET_ID)
        self.var_preset_id = tk.StringVar(value=preset0.id)
        self.var_preset = tk.StringVar(value=preset0.title)

        # 1) Arch
        arch = ttk.LabelFrame(right, text="1  Arch", padding=8)
        arch.pack(fill=tk.X)
        self.cmb_sheet = ttk.Combobox(
            arch, textvariable=self.var_preset, state="readonly", width=40
        )
        self.cmb_sheet.pack(fill=tk.X)
        self.cmb_sheet.bind("<<ComboboxSelected>>", lambda _e: self._on_sheet_combo())
        self._refresh_sheet_choices()
        self.var_sheet_info = tk.StringVar(value=preset0.short_info())
        ttk.Label(
            arch, textvariable=self.var_sheet_info, wraplength=290, style="Hint.TLabel"
        ).pack(anchor=tk.W, pady=(4, 0))
        ttk.Button(
            arch, text="Správa archů… (rozměry, rozteče, mezery)",
            command=self._open_sheet_manager,
        ).pack(fill=tk.X, pady=(6, 0))

        # 2) Tisk
        prn = ttk.LabelFrame(right, text="2  Tisk", padding=8)
        prn.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(prn, text="Tiskárna").pack(anchor=tk.W)
        prn_row = ttk.Frame(prn)
        prn_row.pack(fill=tk.X)
        self.var_printer = tk.StringVar(value="")
        self.cmb_printer = ttk.Combobox(
            prn_row, textvariable=self.var_printer, state="readonly"
        )
        self.cmb_printer.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(prn_row, text="↻", width=3, command=self._refresh_printers).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        ttk.Label(prn, text="Pozice k tisku (např. A1-B2, H1)").pack(
            anchor=tk.W, pady=(8, 0)
        )
        self.var_positions = tk.StringVar(value="A1")
        ttk.Entry(prn, textvariable=self.var_positions).pack(fill=tk.X)
        self.var_positions.trace_add("write", lambda *_: self._on_positions_typed())
        self.cell_vars: dict[tuple[int, int], tk.BooleanVar] = {}

        pads = ttk.Frame(prn)
        pads.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(pads, text="Okraj obsahu uvnitř štítku (mm)").grid(
            row=0, column=0, columnspan=4, sticky=tk.W
        )
        self.var_pad_trbl = tk.StringVar(value="0 0 0 0")
        self._pad_vars: list[tk.StringVar] = []
        self._syncing_pads = False
        for i, name in enumerate(("nahoře", "vpravo", "dole", "vlevo")):
            v = tk.StringVar(value="0")
            self._pad_vars.append(v)
            cell = ttk.Frame(pads)
            cell.grid(row=1, column=i, sticky=tk.W, padx=(0, 6))
            ttk.Spinbox(cell, from_=0, to=50, increment=0.5, width=5, textvariable=v).pack()
            ttk.Label(cell, text=name, style="Hint.TLabel").pack()
            v.trace_add("write", lambda *_: self._on_pad_field_changed())
        self.var_pad_trbl.trace_add("write", lambda *_: self._on_pad_trbl_changed())

        self.btn_print = ttk.Button(
            prn, text="Tisknout", style="Primary.TButton", command=self._print
        )
        self.btn_print.pack(fill=tk.X, pady=(10, 4))
        pdf_row = ttk.Frame(prn)
        pdf_row.pack(fill=tk.X)
        pdf_row.columnconfigure((0, 1), weight=1)
        ttk.Button(pdf_row, text="Náhled PDF…", command=self._preview).grid(
            row=0, column=0, sticky=tk.EW, padx=(0, 4)
        )
        ttk.Button(pdf_row, text="Uložit PDF…", command=self._save_pdf).grid(
            row=0, column=1, sticky=tk.EW
        )
        self.var_outlines = tk.BooleanVar(value=True)
        self.var_names = tk.BooleanVar(value=True)
        self.var_printable = tk.BooleanVar(value=True)
        ttk.Label(prn, text="Do náhledu PDF kreslit:", style="Hint.TLabel").pack(
            anchor=tk.W, pady=(6, 0)
        )
        pdf_opts = ttk.Frame(prn)
        pdf_opts.pack(fill=tk.X)
        for text, var in (
            ("rámečky", self.var_outlines),
            ("kódy A1…", self.var_names),
            ("tisknutelnou oblast", self.var_printable),
        ):
            ttk.Checkbutton(pdf_opts, text=text, variable=var).pack(side=tk.LEFT, padx=(0, 6))

        # 3) Soubor
        doc = ttk.LabelFrame(right, text="3  Soubor", padding=8)
        doc.pack(fill=tk.X, pady=(10, 0))
        doc.columnconfigure((0, 1, 2), weight=1)
        for i, (text, cmd) in enumerate((
            ("Otevřít…", self._load_document),
            ("Uložit", self._save_document),
            ("Uložit jako…", self._save_document_as),
        )):
            ttk.Button(doc, text=text, command=cmd).grid(
                row=0, column=i, sticky=tk.EW, padx=(0, 4) if i < 2 else 0
            )
        ttk.Label(doc, text="Ctrl+O · Ctrl+S · Ctrl+P = tisk", style="Hint.TLabel").grid(
            row=1, column=0, columnspan=3, sticky=tk.W, pady=(4, 0)
        )

        # 4) Kalibrace a technické údaje
        cal = ttk.LabelFrame(right, text="Kalibrace", padding=8)
        cal.pack(fill=tk.X, pady=(10, 0))
        cal.columnconfigure((0, 1), weight=1)
        ttk.Button(cal, text="Náhled…", command=self._preview_calibration).grid(
            row=0, column=0, sticky=tk.EW, padx=(0, 4)
        )
        ttk.Button(cal, text="Tisknout kalibraci", command=self._print_calibration).grid(
            row=0, column=1, sticky=tk.EW
        )
        self.var_details_shown = tk.BooleanVar(value=False)
        self.btn_details = ttk.Checkbutton(
            cal,
            text="Zobrazit technické údaje",
            variable=self.var_details_shown,
            command=self._toggle_layout_details,
        )
        self.btn_details.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))
        self.layout_summary = tk.StringVar(value="")
        self.lbl_layout_summary = ttk.Label(
            cal, textvariable=self.layout_summary, wraplength=290, style="Hint.TLabel"
        )
        self.var_layout_warning = tk.StringVar(value="")
        ttk.Label(
            cal, textvariable=self.var_layout_warning, wraplength=290, style="Warn.TLabel"
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W)

        # --- Editor aktivního štítku (vlevo) ---
        head = ttk.Frame(left)
        head.pack(fill=tk.X)
        ttk.Button(head, text="◀", width=3, command=lambda: self._move_active(0, -1)).pack(
            side=tk.LEFT
        )
        self.var_active_label = tk.StringVar(value="Štítek A1")
        ttk.Label(head, textvariable=self.var_active_label, style="Title.TLabel").pack(
            side=tk.LEFT, padx=8
        )
        ttk.Button(head, text="▶", width=3, command=lambda: self._move_active(0, 1)).pack(
            side=tk.LEFT
        )
        self.var_active_state = tk.StringVar(value="")
        ttk.Label(head, textvariable=self.var_active_state, style="Hint.TLabel").pack(
            side=tk.RIGHT
        )

        self.mode_fr = ttk.LabelFrame(left, text="Obsah", padding=8)
        self.mode_fr.pack(fill=tk.X, pady=(8, 0))
        self.var_mode = tk.StringVar(value="Jen text")
        modes_row = ttk.Frame(self.mode_fr)
        modes_row.pack(fill=tk.X)
        for label in MODES:
            ttk.Radiobutton(
                modes_row,
                text=label,
                value=label,
                variable=self.var_mode,
                command=self._on_mode_change,
            ).pack(side=tk.LEFT, padx=(0, 8))

        img_fr = ttk.Frame(self.mode_fr)
        img_fr.pack(fill=tk.X, pady=(6, 0))
        self._preview_photo = None
        self.img_preview = ttk.Label(img_fr)
        self.img_preview.pack(side=tk.LEFT, padx=(0, 8))
        img_info = ttk.Frame(img_fr)
        img_info.pack(side=tk.LEFT, fill=tk.X, expand=True)
        img_btns = ttk.Frame(img_info)
        img_btns.pack(anchor=tk.W)
        ttk.Button(img_btns, text="Logo / obrázek…", command=self._pick_image).pack(
            side=tk.LEFT
        )
        self.btn_remove_image = ttk.Button(
            img_btns, text="Odebrat", command=self._remove_image
        )
        self.btn_remove_image.pack(side=tk.LEFT, padx=(4, 0))
        self.var_image_label = tk.StringVar(value="(žádný obrázek)")
        ttk.Label(
            img_info, textvariable=self.var_image_label, style="Hint.TLabel", wraplength=260
        ).pack(anchor=tk.W, pady=(2, 0))

        text_fr = ttk.LabelFrame(left, text="Text", padding=8)
        text_fr.pack(fill=tk.X, pady=(10, 0))

        fmt = ttk.Frame(text_fr)
        fmt.pack(fill=tk.X, pady=(0, 2))
        fmt2 = ttk.Frame(text_fr)
        fmt2.pack(fill=tk.X, pady=(0, 6))

        self.var_align = tk.StringVar(value=ALIGN_LEFT)
        self.var_bold = tk.BooleanVar(value=False)
        self.var_italic = tk.BooleanVar(value=False)
        self.var_underline = tk.BooleanVar(value=False)
        self.var_color = tk.StringVar(value="#000000")
        self._syncing_toolbar = False

        align_fr = ttk.Frame(fmt)
        align_fr.pack(side=tk.LEFT)
        for value, label in (
            (ALIGN_LEFT, "Vlevo"),
            (ALIGN_CENTER, "Střed"),
            (ALIGN_RIGHT, "Vpravo"),
        ):
            ttk.Radiobutton(
                align_fr,
                text=label,
                value=value,
                variable=self.var_align,
                command=self._on_align_change,
            ).pack(side=tk.LEFT, padx=(0, 4))

        ttk.Separator(fmt, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Checkbutton(
            fmt, text="Tučné", variable=self.var_bold, command=self._toggle_bold
        ).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Checkbutton(
            fmt, text="Kurzíva", variable=self.var_italic, command=self._toggle_italic
        ).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Checkbutton(
            fmt,
            text="Podtržené",
            variable=self.var_underline,
            command=self._toggle_underline,
        ).pack(side=tk.LEFT, padx=(0, 2))

        self.btn_color = ttk.Button(fmt2, text="Barva…", command=self._pick_color)
        self.btn_color.pack(side=tk.LEFT)
        self.lbl_color = tk.Label(
            fmt2, text="  ", width=3, relief=tk.GROOVE, background="#000000"
        )
        self.lbl_color.pack(side=tk.LEFT, padx=(4, 0))

        ttk.Separator(fmt2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Label(fmt2, text="Velikost:").pack(side=tk.LEFT)
        self.var_font = tk.DoubleVar(value=11.0)
        self.spn_font = ttk.Spinbox(
            fmt2,
            from_=6,
            to=28,
            increment=0.5,
            textvariable=self.var_font,
            width=5,
            command=self._apply_font_size_to_selection,
        )
        self.spn_font.pack(side=tk.LEFT, padx=4)
        self.spn_font.bind("<Return>", lambda _e: self._apply_font_size_to_selection())
        self.spn_font.bind("<FocusOut>", lambda _e: self._apply_font_size_to_selection())
        ttk.Button(fmt2, text="Na výběr", command=self._apply_font_size_to_selection).pack(
            side=tk.LEFT, padx=(0, 4)
        )

        self.txt = tk.Text(text_fr, height=6, width=40, wrap=tk.WORD, undo=True)
        self.txt.pack(fill=tk.X)
        ensure_format_tags(self.txt, 12)
        self.txt.tag_configure("body", justify=tk.LEFT)
        self.txt.insert("1.0", "Jan Novák\nUlice 123\n110 00 Praha 1")
        apply_size_on_range(self.txt, 11.0, "1.0", "end-1c")
        self.txt.bind("<<Modified>>", self._on_text_modified)
        self.txt.bind("<<Selection>>", lambda _e: self._sync_format_toolbar())
        self.txt.bind("<KeyRelease>", lambda _e: self._sync_format_toolbar())
        self.txt.bind("<ButtonRelease-1>", lambda _e: self._sync_format_toolbar())

        ttk.Label(
            text_fr,
            text="Formát (tučné, barva, velikost…) platí na označený text, "
            "bez výběru na řádek s kurzorem.",
            wraplength=360,
            style="Hint.TLabel",
        ).pack(anchor=tk.W, pady=(4, 0))

        self.status_var = tk.StringVar(value="")
        self.lbl_fit = ttk.Label(
            text_fr, textvariable=self.status_var, style="Ok.TLabel", wraplength=360
        )
        self.lbl_fit.pack(anchor=tk.W, pady=(4, 0))

        acts = ttk.LabelFrame(left, text="Tento štítek", padding=8)
        acts.pack(fill=tk.X, pady=(10, 0))
        acts.columnconfigure((0, 1), weight=1)
        for i, (text, cmd) in enumerate((
            ("Nakopírovat všude", self._copy_content_everywhere),
            ("Nakopírovat na vybrané", self._copy_content_to_selected),
            ("Na první volný", self._duplicate_to_first_free),
            ("Vymazat", self._clear_active_box),
        )):
            ttk.Button(acts, text=text, command=cmd).grid(
                row=i // 2, column=i % 2, sticky=tk.EW,
                padx=(0, 4) if i % 2 == 0 else 0, pady=(0, 4),
            )

        self.app_status = tk.StringVar(value="Připraveno.")
        ttk.Label(
            self, textvariable=self.app_status, style="Status.TLabel", anchor=tk.W,
            padding=(10, 3),
        ).pack(side=tk.BOTTOM, fill=tk.X, before=root)

        self._rebuild_cell_vars(preset0)
        self._on_layout_settings_changed()

    # --- helpers ---

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-s>", lambda _e: self._save_document())
        self.bind("<Control-S>", lambda _e: self._save_document())
        self.bind("<Control-o>", lambda _e: self._load_document())
        self.bind("<Control-O>", lambda _e: self._load_document())
        self.bind("<Control-Shift-S>", lambda _e: self._save_document_as())
        self.bind("<Control-p>", lambda _e: self._print())
        self.bind("<Control-P>", lambda _e: self._print())
        for key, (dr, dc) in {
            "<Alt-Left>": (0, -1), "<Alt-Right>": (0, 1),
            "<Alt-Up>": (-1, 0), "<Alt-Down>": (1, 0),
        }.items():
            self.bind_all(key, lambda _e, d=(dr, dc): (self._move_active(*d), "break")[1])

    def _move_active(self, dr: int, dc: int) -> None:
        """Přejde na sousední štítek; vodorovně v pořadí čtení (A1, A2, B1…)."""
        p = self._current_preset()
        r, c = self.active_cell
        if dc:
            idx = max(0, min(p.rows * p.cols - 1, r * p.cols + c + dc))
            key = divmod(idx, p.cols)
        else:
            key = (max(0, min(p.rows - 1, r + dr)), c)
        if key != self.active_cell:
            self._on_preview_select(key)

    def _on_preview_select(self, key: tuple[int, int]) -> None:
        self._switch_active_cell(key)
        try:
            self.txt.focus_set()
        except Exception:
            pass

    def _select_filled(self) -> None:
        for key, var in self.cell_vars.items():
            var.set(not self._is_empty_state(self.label_states.get(cell_name(*key))))
        self._sync_positions_from_grid()

    def _remove_image(self) -> None:
        if not self.image_path:
            return
        self.image_path = None
        self.var_image_label.set("(žádný obrázek)")
        if self.var_mode.get() != "Jen text":
            self.var_mode.set("Jen text")
        self._refresh_image_preview()
        self._capture_editor_to_active()
        self._on_text_change()
        self._update_active_ui()
        self._schedule_session_save()
        self._set_status("Obrázek odebrán.")

    def _on_pad_field_changed(self) -> None:
        if self._syncing_pads:
            return
        parts = [(v.get() or "0").strip().replace(",", ".") for v in self._pad_vars]
        self._syncing_pads = True
        try:
            self.var_pad_trbl.set(" ".join(parts))
        finally:
            self._syncing_pads = False
        self._on_layout_settings_changed()

    def _on_pad_trbl_changed(self) -> None:
        """Programové nastavení (session/dokument) → čtyři pole."""
        if self._syncing_pads:
            return
        try:
            values = self._parse_pad_trbl(self.var_pad_trbl.get())
        except ValueError:
            return
        self._syncing_pads = True
        try:
            for var, val in zip(self._pad_vars, values):
                var.set(f"{val:g}")
        finally:
            self._syncing_pads = False
        self._on_layout_settings_changed()

    def _toggle_layout_details(self) -> None:
        if self.var_details_shown.get():
            self.lbl_layout_summary.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))
        else:
            self.lbl_layout_summary.grid_remove()

    def _update_selection_count(self) -> None:
        if not hasattr(self, "var_selection_count") or not hasattr(self, "btn_print"):
            return
        n = sum(1 for v in self.cell_vars.values() if v.get())
        total = len(self.cell_vars)
        self.var_selection_count.set(f"Tiskne se {n} z {total}")
        if n == 0:
            text = "Tisknout (nic není vybráno)"
        else:
            word = "štítek" if n == 1 else ("štítky" if 2 <= n <= 4 else "štítků")
            text = f"Tisknout {n} {word}"
        self.btn_print.configure(text=text)

    def _update_title(self) -> None:
        if self.doc_path:
            self.title(f"{APP_TITLE} — {self.doc_path.name}")
        else:
            self.title(APP_TITLE)

    def _default_label_state(self) -> dict:
        return {
            "text": "",
            "runs": [],
            "mode": "text",
            "font_size_pt": 11.0,
            "image_path": None,
            "align": ALIGN_LEFT,
        }

    def _init_default_labels(self) -> None:
        sample = self._default_label_state()
        sample["text"] = "Jan Novák\nUlice 123\n110 00 Praha 1"
        sample["runs"] = runs_to_json(runs_from_plain(sample["text"], size=11.0))
        self.label_states = {"A1": sample}
        self.active_cell = (0, 0)
        self._load_editor_from_state(sample)
        self._update_active_ui()

    def _snapshot_editor(self) -> dict:
        try:
            default_size = float(self.var_font.get())
        except Exception:
            default_size = 11.0
        runs = dump_text_runs(self.txt, default_size)
        plain = runs_to_plain(runs) if runs else self.txt.get("1.0", "end-1c")
        return {
            "text": plain,
            "runs": runs_to_json(runs) if runs else runs_to_json(
                runs_from_plain(plain, size=default_size)
            ),
            "mode": MODES[self.var_mode.get()],
            "font_size_pt": max_run_size(runs, default_size) if runs else default_size,
            "image_path": self.image_path,
            "align": self.var_align.get(),
        }

    def _capture_editor_to_active(self) -> None:
        if self._loading_editor:
            return
        key = cell_name(*self.active_cell)
        self.label_states[key] = self._snapshot_editor()

    def _load_editor_from_state(self, state: dict) -> None:
        self._loading_editor = True
        try:
            mode_raw = state.get("mode", "text")
            if mode_raw in MODE_BY_VALUE:
                mode_label = MODE_BY_VALUE[mode_raw]
            elif mode_raw in MODES:
                mode_label = mode_raw
            else:
                mode_label = "Jen text"
            self.var_mode.set(mode_label)

            default_size = float(state.get("font_size_pt") or 11.0)
            self.var_font.set(default_size)

            runs = normalize_runs(state.get("runs"), default_size)
            if not runs:
                text = state.get("text", "")
                if not isinstance(text, str):
                    text = ""
                # legacy: celý text jedním stylem
                runs = runs_from_plain(
                    text,
                    bold=bool(state.get("bold", False)),
                    italic=bool(state.get("italic", False)),
                    underline=bool(state.get("underline", False)),
                    color=str(state.get("color") or "#000000"),
                    size=default_size,
                )
            apply_runs_to_text(self.txt, runs, default_size=default_size)

            img = state.get("image_path")
            if img:
                img_path = Path(str(img))
                if img_path.is_file():
                    self.image_path = str(img_path)
                    self.var_image_label.set(img_path.name)
                else:
                    self.image_path = str(img)
                    self.var_image_label.set(f"{img_path.name} (nenalezen)")
            else:
                self.image_path = None
                self.var_image_label.set("(žádný obrázek)")
            self._refresh_image_preview()

            align = str(state.get("align", ALIGN_LEFT))
            if align not in (ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT):
                align = ALIGN_LEFT
            self.var_align.set(align)
            self._apply_align_tag()
            self._sync_format_toolbar()
        finally:
            self._loading_editor = False

    def _state_for_cell(self, key: tuple[int, int]) -> dict:
        name = cell_name(*key)
        state = self.label_states.get(name)
        if state is None:
            state = self._default_label_state()
            self.label_states[name] = state
        return state

    def _switch_active_cell(self, key: tuple[int, int]) -> None:
        if key == self.active_cell:
            self._update_active_ui()
            return
        self._capture_editor_to_active()
        self.active_cell = key
        self._load_editor_from_state(self._state_for_cell(key))
        self._update_active_ui()
        self._on_text_change()

    def _update_active_ui(self) -> None:
        self.var_active_label.set(f"Štítek {cell_name(*self.active_cell)}")
        self._update_active_state()
        self._refresh_sheet_preview()

    def _update_active_state(self) -> None:
        if not hasattr(self, "var_active_state"):
            return
        var = self.cell_vars.get(self.active_cell)
        printed = bool(var and var.get())
        self.var_active_state.set(
            "✓ tiskne se" if printed else "netiskne se (pravý klik v náhledu)"
        )
        if hasattr(self, "btn_remove_image"):
            self.btn_remove_image.state(["!disabled"] if self.image_path else ["disabled"])

    def _selected_cells(self) -> set[tuple[int, int]]:
        return {key for key, var in self.cell_vars.items() if var.get()}

    def _toggle_print_cell(self, key: tuple[int, int]) -> None:
        var = self.cell_vars.get(key)
        if var is None:
            return
        var.set(not var.get())
        self._sync_positions_from_grid()

    def _preview_contents(self) -> dict[tuple[int, int], LabelContent]:
        """Obsah všech vyplněných štítků (i nevybraných k tisku)."""
        self._capture_editor_to_active()
        result: dict[tuple[int, int], LabelContent] = {}
        p = self._current_preset()
        for r in range(p.rows):
            for c in range(p.cols):
                state = self.label_states.get(cell_name(r, c))
                if self._is_empty_state(state):
                    continue
                try:
                    result[(r, c)] = self._content_from_state(state)
                except Exception:
                    continue
        return result

    def _refresh_sheet_preview(self) -> None:
        if not hasattr(self, "sheet_preview") or self._loading_editor:
            return
        try:
            lay = self._layout()
        except Exception:
            return
        self.sheet_preview.set_data(
            lay, self._preview_contents(), self.active_cell, self._selected_cells()
        )

    def _refresh_sheet_marks(self) -> None:
        self._update_selection_count()
        self._update_active_state()
        if hasattr(self, "sheet_preview"):
            self.sheet_preview.set_marks(self.active_cell, self._selected_cells())

    def _current_preset(self) -> SheetDefinition:
        pid = (self.var_preset_id.get() or "").strip() or DEFAULT_SHEET_ID
        return self.sheet_store.get(pid)

    def _refresh_sheet_choices(self) -> None:
        choices = self.sheet_store.choices()
        self._sheet_name_to_id = {name: sid for sid, name in choices}
        self.cmb_sheet["values"] = [name for _sid, name in choices]
        self.var_preset.set(self._current_preset().title)

    def _on_sheet_combo(self) -> None:
        sid = self._sheet_name_to_id.get(self.var_preset.get())
        if not sid or sid == self.var_preset_id.get():
            return
        self.var_preset_id.set(sid)
        self._on_preset_changed()

    def _open_sheet_manager(self) -> None:
        old = self._current_preset()
        old_dict = old.to_dict()
        dlg = SheetManagerDialog(self, self.sheet_store, old.id)
        self.wait_window(dlg)
        if dlg.result_id:
            self.var_preset_id.set(dlg.result_id)
        elif not self.sheet_store.has(old.id):
            self.var_preset_id.set(DEFAULT_SHEET_ID)
        self.var_preset_id.set(self._current_preset().id)
        self._refresh_sheet_choices()
        new = self._current_preset()
        if new.id != old.id or (new.cols, new.rows) != (old.cols, old.rows):
            self._on_preset_changed()
        elif new.to_dict() != old_dict:
            self.var_sheet_info.set(new.short_info())
            self._on_layout_settings_changed()

    def _parse_positions(self, raw: str) -> list[tuple[int, int]]:
        p = self._current_preset()
        return parse_range(raw, cols=p.cols, rows=p.rows)

    def _rebuild_cell_vars(self, preset: SheetDefinition) -> None:
        """Stav „tisknout“ pro každou pozici; zobrazuje ho náhled archu."""
        self.cell_vars.clear()
        for r in range(preset.rows):
            for c in range(preset.cols):
                self.cell_vars[(r, c)] = tk.BooleanVar(value=(r == 0 and c == 0))
        self._update_selection_count()

    def _on_preset_changed(self) -> None:
        preset = self._current_preset()
        self.var_preset.set(preset.title)
        self.var_sheet_info.set(preset.short_info())
        self._rebuild_cell_vars(preset)
        # aktivní buňka musí zůstat v rozsahu
        ar, ac = self.active_cell
        if ar >= preset.rows or ac >= preset.cols:
            self.active_cell = (0, 0)
            self._load_editor_from_state(self._state_for_cell(self.active_cell))
        self.var_positions.set("A1")
        self._update_active_ui()
        self._on_layout_settings_changed()

    def _on_positions_typed(self) -> None:
        # nevolat při programovém nastavení přes sync — kontrolujeme shodu
        try:
            selected = set(self._parse_positions(self.var_positions.get()))
        except Exception:
            return
        current = {
            key for key, var in self.cell_vars.items() if var.get()
        }
        if selected == current:
            return
        for key, var in self.cell_vars.items():
            var.set(key in selected)
        self._refresh_sheet_marks()

    def _copy_content_everywhere(self) -> None:
        self._capture_editor_to_active()
        src = self._snapshot_editor()
        cells = self._all_cells_order()
        for key in cells:
            self.label_states[cell_name(*key)] = dict(src)
        self._update_active_ui()
        self._set_status(
            f"✓ Obsah štítku {cell_name(*self.active_cell)} nakopírován na všech "
            f"{len(cells)} pozic."
        )

    def _copy_content_to_selected(self) -> None:
        self._capture_editor_to_active()
        src = self._snapshot_editor()
        selected = [
            key for key, var in sorted(self.cell_vars.items()) if var.get()
        ]
        if not selected:
            self._set_status(
                "Nic není vybráno k tisku — pravým klikem v náhledu označte pozice."
            )
            return
        for key in selected:
            self.label_states[cell_name(*key)] = dict(src)
        self._update_active_ui()
        self._set_status(
            f"✓ Nakopírováno na {len(selected)} vybraných pozic: "
            + ", ".join(cell_name(*k) for k in selected)
        )

    def _is_empty_state(self, state: dict | None) -> bool:
        if not state:
            return True
        return not (state.get("text") or "").strip() and not state.get("image_path")

    def _all_cells_order(self) -> list[tuple[int, int]]:
        p = self._current_preset()
        return [(r, c) for r in range(p.rows) for c in range(p.cols)]

    def _clear_active_box(self) -> None:
        name = cell_name(*self.active_cell)
        empty = self._default_label_state()
        self.label_states[name] = empty
        self._load_editor_from_state(empty)
        self._update_active_ui()
        self._on_text_change()
        self._set_status(f"Štítek {name} vymazán. (Ctrl+Z v textu vrátí text)")

    def _find_first_free_cell(self) -> tuple[int, int] | None:
        """První prázdná pozice na archu (od A1 směrem k H3)."""
        self._capture_editor_to_active()
        for key in self._all_cells_order():
            name = cell_name(*key)
            state = self.label_states.get(name)
            if self._is_empty_state(state):
                return key
        return None

    def _duplicate_to_first_free(self) -> None:
        self._capture_editor_to_active()
        src = self._snapshot_editor()
        if self._is_empty_state(src):
            self._dialog_parent()
            messagebox.showwarning(
                "Prázdný štítek",
                "Aktivní box nemá co duplikovat — nejdřív vyplňte obsah.",
                parent=self,
            )
            return
        target = self._find_first_free_cell()
        if target is None:
            self._dialog_parent()
            messagebox.showwarning(
                "Arch plný",
                "Není volná pozice — všechny boxy už mají obsah.",
                parent=self,
            )
            return
        self.label_states[cell_name(*target)] = dict(src)
        self.cell_vars[target].set(True)
        self._sync_positions_from_grid()
        self._switch_active_cell(target)
        self._set_status(f"✓ Duplikováno na {cell_name(*target)} (první volná pozice).")

    def _export_state(self) -> dict:
        self._capture_editor_to_active()
        labels: dict[str, dict] = {}
        for name, state in self.label_states.items():
            if (
                name == cell_name(*self.active_cell)
                or (state.get("text") or "").strip()
                or state.get("image_path")
                or state.get("runs")
            ):
                labels[name] = dict(state)
        active = cell_name(*self.active_cell)
        active_state = labels.get(active, self._snapshot_editor())
        return {
            "version": DOC_VERSION,
            "app": "stitky",
            "labels": labels,
            "active": active,
            # zpětná kompatibilita / rychlý náhled aktivního štítku
            "text": active_state.get("text", ""),
            "runs": active_state.get("runs", []),
            "mode": active_state.get("mode", "text"),
            "font_size_pt": active_state.get("font_size_pt", 11.0),
            "image_path": active_state.get("image_path"),
            "align": active_state.get("align", ALIGN_LEFT),
            # nastavení aplikace (layout je pevný default v kódu)
            "positions": self.var_positions.get().strip(),
            "show_outlines": bool(self.var_outlines.get()),
            "show_cell_names": bool(self.var_names.get()),
            "show_printable_area": bool(self.var_printable.get()),
            "printer": self.var_printer.get().strip(),
            "sheet_preset": self._current_preset().id,
            # celá definice — dokument jde otevřít i na jiném PC
            "sheet_definition": self._current_preset().to_dict(),
            "content_pad_trbl": self.var_pad_trbl.get().strip(),
        }

    def _apply_state(self, data: dict) -> None:
        if not isinstance(data, dict):
            raise ValueError("Soubor neobsahuje platný obsah štítku.")

        if "show_outlines" in data:
            self.var_outlines.set(bool(data["show_outlines"]))
        if "show_cell_names" in data:
            self.var_names.set(bool(data["show_cell_names"]))
        if "show_printable_area" in data:
            self.var_printable.set(bool(data["show_printable_area"]))

        preset_id = str(data.get("sheet_preset") or DEFAULT_SHEET_ID)
        embedded = data.get("sheet_definition")
        if isinstance(embedded, dict) and not self.sheet_store.has(preset_id):
            # Arch z jiného PC — přidat mezi vlastní archy.
            try:
                imported = SheetDefinition.from_dict(embedded)
                imported.builtin = False
                self.sheet_store.upsert(imported)
                self.sheet_store.save()
                preset_id = imported.id
            except Exception:
                pass
        self.var_preset_id.set(preset_id)
        preset = self._current_preset()
        self.var_preset_id.set(preset.id)
        self._refresh_sheet_choices()
        self.var_sheet_info.set(preset.short_info())
        self._rebuild_cell_vars(preset)

        if "content_pad_trbl" in data:
            self.var_pad_trbl.set(str(data["content_pad_trbl"]))

        printer = data.get("printer")
        if printer:
            printers = list(self.cmb_printer["values"] or ())
            if printer in printers:
                self.var_printer.set(printer)

        positions = str(data.get("positions", "A1") or "")
        self.var_positions.set(positions)
        try:
            selected = set(self._parse_positions(positions))
        except Exception:
            selected = {(0, 0)}
        for key, var in self.cell_vars.items():
            var.set(key in selected)

        labels_raw = data.get("labels")
        self.label_states = {}
        if isinstance(labels_raw, dict) and labels_raw:
            for name, state in labels_raw.items():
                if not isinstance(state, dict):
                    continue
                try:
                    parse_cell(str(name), cols=preset.cols, rows=preset.rows)
                except Exception:
                    continue
                merged = self._default_label_state()
                merged.update(state)
                self.label_states[str(name).upper()] = merged
        else:
            # starý formát — jeden obsah
            legacy = self._default_label_state()
            if isinstance(data.get("text"), str):
                legacy["text"] = data["text"]
            if "mode" in data:
                legacy["mode"] = data["mode"]
            if "font_size_pt" in data:
                legacy["font_size_pt"] = float(data["font_size_pt"])
            if "image_path" in data:
                legacy["image_path"] = data["image_path"]
            if "align" in data:
                legacy["align"] = data["align"]
            if "bold" in data:
                legacy["bold"] = bool(data["bold"])
            if "italic" in data:
                legacy["italic"] = bool(data["italic"])
            if "underline" in data:
                legacy["underline"] = bool(data["underline"])
            if "color" in data:
                legacy["color"] = data["color"]
            if "runs" in data:
                legacy["runs"] = data["runs"]
            targets = selected or {(0, 0)}
            for key in targets:
                self.label_states[cell_name(*key)] = dict(legacy)

        active_name = str(data.get("active") or next(iter(self.label_states), "A1")).upper()
        try:
            self.active_cell = parse_cell(
                active_name, cols=preset.cols, rows=preset.rows
            )
        except Exception:
            self.active_cell = (0, 0)
        self._load_editor_from_state(self._state_for_cell(self.active_cell))
        self._update_active_ui()
        self._on_layout_settings_changed()
        self._on_text_change()

    def _write_document(self, path: Path) -> None:
        path = Path(path)
        if path.suffix.lower() not in (".json", ".stitky"):
            path = path.with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._export_state(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.doc_path = path
        self._update_title()
        self._schedule_session_save()

    def _read_document(self, path: Path) -> None:
        path = Path(path)
        raw = path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Soubor neobsahuje JSON objekt s nastavením.")
        self._apply_state(data)
        self.doc_path = path
        self._update_title()

    def _save_document(self) -> None:
        """Ctrl+S — přepsat aktuální soubor, jinak Uložit jako."""
        if self.doc_path is not None:
            try:
                self._write_document(self.doc_path)
            except Exception as exc:
                with self._with_app_on_top():
                    messagebox.showerror("Uložení selhalo", str(exc), parent=self)
                return
            self._set_status(f"✓ Uloženo: {self.doc_path}")
            return
        self._save_document_as()

    def _save_document_as(self) -> None:
        initial_dir = (
            str(self.doc_path.parent)
            if self.doc_path is not None
            else str(_documents_dir())
        )
        initial = self.doc_path.name if self.doc_path else "stitky.json"
        with self._with_app_on_top():
            path = filedialog.asksaveasfilename(
                parent=self,
                title="Uložit obsah a nastavení (JSON)",
                defaultextension=".json",
                filetypes=DOC_FILETYPES,
                initialdir=initial_dir,
                initialfile=initial,
            )
        if not path:
            return
        try:
            self._write_document(Path(path))
        except Exception as exc:
            with self._with_app_on_top():
                messagebox.showerror("Uložení selhalo", str(exc), parent=self)
            return
        self._set_status(f"✓ Uloženo: {path}")

    def _load_document(self) -> None:
        initial_dir = (
            str(self.doc_path.parent)
            if self.doc_path is not None
            else str(_documents_dir())
        )
        with self._with_app_on_top():
            path = filedialog.askopenfilename(
                parent=self,
                title="Načíst obsah a nastavení (JSON)",
                filetypes=DOC_FILETYPES,
                initialdir=initial_dir,
            )
        if not path:
            return
        try:
            self._read_document(Path(path))
        except Exception as exc:
            with self._with_app_on_top():
                messagebox.showerror("Načtení selhalo", str(exc), parent=self)
            return
        self._set_status(f"✓ Načteno: {path}")

    def _parse_mm(self, raw: str, default: float) -> float:
        s = (raw or "").strip().replace(",", ".")
        if not s:
            return default
        return float(s)

    def _parse_pad_trbl(self, raw: str) -> tuple[float, float, float, float]:
        parts = (raw or "").replace(",", ".").split()
        if len(parts) == 0:
            return 0.0, 0.0, 0.0, 0.0
        if len(parts) == 1:
            v = float(parts[0])
            return v, v, v, v
        if len(parts) == 2:
            v, h = float(parts[0]), float(parts[1])
            return v, h, v, h
        if len(parts) == 3:
            t, h, b = float(parts[0]), float(parts[1]), float(parts[2])
            return t, h, b, h
        if len(parts) == 4:
            return float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
        raise ValueError("Padding zadejte jako T R B L (např. 0 0 0 0 nebo 10 5 10 5).")

    def _layout(self) -> SheetLayout:
        preset = self._current_preset()
        top, right, bottom, left = self._parse_pad_trbl(self.var_pad_trbl.get())
        return preset.to_layout(
            content_pad_top_mm=top,
            content_pad_right_mm=right,
            content_pad_bottom_mm=bottom,
            content_pad_left_mm=left,
        )

    def _on_layout_settings_changed(self) -> None:
        try:
            lay = self._layout()
            msg = lay.summary_text()
            info = [w for w in lay.fit_warnings() if w not in lay.fit_blocking_warnings()]
            if info:
                msg += "\n" + " ".join(info)
            self.layout_summary.set(msg)
            blocking = lay.fit_blocking_warnings()
            self.var_layout_warning.set("⚠ " + " ".join(blocking) if blocking else "")
            self._on_text_change()
            self._schedule_session_save()
        except Exception as exc:
            self.layout_summary.set("")
            self.var_layout_warning.set(f"⚠ Chyba rozměrů: {exc}")

    def _build_calibration_pdf_bytes(self) -> bytes:
        buf = BytesIO()
        render_calibration_pdf(self._layout(), buf)
        return buf.getvalue()

    def _preview_calibration(self) -> None:
        try:
            data = self._build_calibration_pdf_bytes()
        except Exception as exc:
            with self._with_app_on_top():
                messagebox.showerror("Chyba", str(exc), parent=self)
            return
        fd, name = tempfile.mkstemp(prefix="stitky_kalibrace_", suffix=".pdf")
        import os

        os.close(fd)
        path = Path(name)
        path.write_bytes(data)
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            with self._with_app_on_top():
                messagebox.showinfo("Náhled", f"PDF: {path}\n({exc})", parent=self)

    def _print_calibration(self) -> None:
        try:
            lay = self._layout()
            image = render_calibration_image(lay, dpi=300)
            printer = self.var_printer.get().strip() or None
            print_bitmap(
                image,
                printer,
                page_width_mm=lay.print_width_mm,
                page_height_mm=lay.print_height_mm,
                scale_x=lay.print_scale_x,
                scale_y=lay.print_scale_y,
            )
            self.status_var.set("Kalibrační arch odeslán přímo na tiskárnu.")
            with self._with_app_on_top():
                messagebox.showinfo(
                    "Tisk kalibrace",
                    "Kalibrace odeslána (vše červené).\n\n"
                    "Phaser 6700 · boční Tray 1:\n"
                    f"• vlastní formát {lay.print_width_mm:.1f}×{lay.print_height_mm:.1f} mm "
                    "(stejný jako arch),\n"
                    "• vodítka těsně k okrajům (arch na středu dráhy),\n"
                    "• tisková strana dolů, dolní hrana archu do tiskárny.\n\n"
                    "Plný rámeček = štítek, čárkovaný = obsah, křížek = střed.",
                    parent=self,
                )
        except Exception as exc:
            with self._with_app_on_top():
                messagebox.showerror(
                    "Tisk selhal",
                    f"{exc}\n\nTip: můžete použít „Náhled kalibrace…“ (PDF) "
                    "a vytisknout ručně.",
                    parent=self,
                )

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
        if selected and len(selected) == len(self.cell_vars):
            p = self._current_preset()
            self.var_positions.set(f"A1-{cell_name(p.rows - 1, p.cols - 1)}")
        else:
            self.var_positions.set(",".join(selected))
        self._refresh_sheet_marks()

    def _select_all(self) -> None:
        for v in self.cell_vars.values():
            v.set(True)
        self._sync_positions_from_grid()

    def _select_none(self) -> None:
        for v in self.cell_vars.values():
            v.set(False)
        self.var_positions.set("")
        self._refresh_sheet_marks()

    def _pick_image(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Vyberte obrázek / SVG logo",
            filetypes=[
                ("Obrázky a SVG", "*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg *.svgz"),
                ("SVG (křivky)", "*.svg *.svgz"),
                ("Rastrové obrázky", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                ("Vše", "*.*"),
            ],
        )
        if not path:
            return
        self.image_path = path
        self.var_image_label.set(Path(path).name)
        # Bez režimu s obrázkem se logo vůbec nerenderuje ani netiskne.
        if self.var_mode.get() == "Jen text":
            plain = self.txt.get("1.0", "end-1c").strip()
            self.var_mode.set("Text + obrázek" if plain else "Jen obrázek")
        self._refresh_image_preview()
        self._capture_editor_to_active()
        self._on_text_change()
        self._update_active_state()
        self._schedule_session_save()

    def _refresh_image_preview(self) -> None:
        """Malý náhled vybraného PNG/JPG/SVG v panelu obsahu."""
        if not hasattr(self, "img_preview"):
            return
        path = self.image_path
        if not path or not Path(path).is_file():
            self._preview_photo = None
            self.img_preview.configure(image="", text="")
            return
        try:
            from PIL import ImageTk

            im = open_label_image(path, max_px=72)
            # bílý podklad kvůli průhlednosti
            from PIL import Image as PILImage

            bg = PILImage.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[3] if im.mode == "RGBA" else None)
            self._preview_photo = ImageTk.PhotoImage(bg)
            self.img_preview.configure(image=self._preview_photo, text="")
        except Exception as exc:
            self._preview_photo = None
            self.img_preview.configure(image="", text=f"(náhled selhal: {exc})")

    def _on_mode_change(self) -> None:
        self._capture_editor_to_active()
        self._on_text_change()
        self._schedule_session_save()

    def _format_range(self) -> tuple[str, str]:
        """Výběr, nebo aktuální řádek (když nic není vybráno)."""
        try:
            start = self.txt.index("sel.first")
            end = self.txt.index("sel.last")
            if self.txt.compare(start, "<", end):
                return start, end
        except tk.TclError:
            pass
        return self.txt.index("insert linestart"), self.txt.index("insert lineend")

    def _pick_color(self) -> None:
        self._dialog_parent()
        result = colorchooser.askcolor(
            color=self.var_color.get() or "#000000",
            title="Barva textu (pro výběr)",
            parent=self,
        )
        if not result or not result[1]:
            return
        self.var_color.set(result[1])
        start, end = self._format_range()
        if self.txt.compare(start, "<", end):
            apply_color_on_range(self.txt, result[1], start, end)
        try:
            self.lbl_color.configure(background=result[1])
        except Exception:
            pass
        self._on_text_change()

    def _toggle_bold(self) -> None:
        if self._syncing_toolbar:
            return
        start, end = self._format_range()
        if self.txt.compare(start, ">=", end):
            return
        want = bool(self.var_bold.get())
        on = toggle_tag_on_range(self.txt, "bold", start, end)
        # checkbox už změnil var — srovnej se skutečným tagem / požadovaným stavem
        if on != want:
            toggle_tag_on_range(self.txt, "bold", start, end)
        self._on_text_change()

    def _toggle_italic(self) -> None:
        if self._syncing_toolbar:
            return
        start, end = self._format_range()
        if self.txt.compare(start, ">=", end):
            return
        want = bool(self.var_italic.get())
        on = toggle_tag_on_range(self.txt, "italic", start, end)
        if on != want:
            toggle_tag_on_range(self.txt, "italic", start, end)
        self._on_text_change()

    def _toggle_underline(self) -> None:
        if self._syncing_toolbar:
            return
        start, end = self._format_range()
        if self.txt.compare(start, ">=", end):
            return
        want = bool(self.var_underline.get())
        on = toggle_tag_on_range(self.txt, "underline", start, end)
        if on != want:
            toggle_tag_on_range(self.txt, "underline", start, end)
        self._on_text_change()

    def _apply_font_size_to_selection(self) -> None:
        if self._syncing_toolbar or self._loading_editor:
            return
        try:
            size = float(self.var_font.get())
        except Exception:
            return
        size = max(6.0, min(28.0, size))
        start, end = self._format_range()
        if self.txt.compare(start, ">=", end):
            return
        apply_size_on_range(self.txt, size, start, end)
        self._on_text_change()

    def _on_align_change(self) -> None:
        self._apply_align_tag()
        self._on_text_change()

    def _apply_align_tag(self) -> None:
        self.txt.tag_configure(
            "body",
            justify={
                ALIGN_LEFT: tk.LEFT,
                ALIGN_CENTER: tk.CENTER,
                ALIGN_RIGHT: tk.RIGHT,
            }.get(self.var_align.get(), tk.LEFT),
        )
        self.txt.tag_add("body", "1.0", "end")

    def _sync_format_toolbar(self) -> None:
        if self._loading_editor:
            return
        try:
            default_size = float(self.var_font.get())
        except Exception:
            default_size = 11.0
        try:
            style = style_at_index(self.txt, "insert", default_size)
        except Exception:
            return
        self._syncing_toolbar = True
        try:
            self.var_bold.set(bool(style["bold"]))
            self.var_italic.set(bool(style["italic"]))
            self.var_underline.set(bool(style["underline"]))
            color = style.get("color") or "#000000"
            self.var_color.set(color)
            self.var_font.set(float(style.get("size") or default_size))
            try:
                self.lbl_color.configure(background=color)
            except Exception:
                pass
        finally:
            self._syncing_toolbar = False

    def _on_text_modified(self, _event=None) -> None:
        if self.txt.edit_modified():
            self.txt.edit_modified(False)
            self.txt.tag_add("body", "1.0", "end")
            self._on_text_change()
            self._schedule_session_save()

    def _reserved_image_h(self, lay: SheetLayout) -> float:
        mode = MODES[self.var_mode.get()]
        if mode == "text_image" and self.image_path:
            _, _, _, ch = lay.label_content_rect_print_mm(*self.active_cell)
            return ch * 0.45 + 1.0
        return 0.0

    def _on_text_change(self) -> None:
        self._refresh_sheet_preview()
        if hasattr(self, "lbl_fit"):
            self.lbl_fit.configure(style="Hint.TLabel")
        try:
            lay = self._layout()
            mode = MODES[self.var_mode.get()]
            if mode == "image":
                self.status_var.set("Režim jen obrázek — text se netiskne.")
                return
            try:
                default_size = float(self.var_font.get())
            except Exception:
                default_size = 11.0
            runs = dump_text_runs(self.txt, default_size)
            plain = runs_to_plain(runs)
            if not plain.strip():
                self.status_var.set("Text je prázdný.")
                return
            _, _, cw, ch = lay.label_content_rect_print_mm(*self.active_cell)
            reserved = self._reserved_image_h(lay)
            lines, need = rich_block_height_mm(runs, cw, 2.0, font_name)
            usable = ch - 4.0 - reserved
            fits = need <= usable + 0.05
            self.lbl_fit.configure(style="Ok.TLabel" if fits else "Bad.TLabel")
            if fits:
                self.status_var.set(
                    f"✓ Vejde se — {len(lines)} ř., {need:.1f} z {usable:.1f} mm výšky."
                )
            else:
                self.status_var.set(
                    f"✗ Nevejde se ({need:.1f} > {usable:.1f} mm) — zmenšete písmo, "
                    f"jinak se při tisku zmenší automaticky."
                )
        except Exception as exc:
            self.status_var.set(f"Kontrola textu: {exc}")

    def _positions(self) -> list[tuple[int, int]]:
        positions = self._parse_positions(self.var_positions.get())
        for key, var in self.cell_vars.items():
            var.set(key in set(positions))
        return positions

    def _content_from_state(self, state: dict) -> LabelContent:
        mode_raw = state.get("mode", "text")
        if mode_raw in MODE_BY_VALUE:
            mode = mode_raw
        elif mode_raw in MODES:
            mode = MODES[mode_raw]
        else:
            mode = "text"
        align = str(state.get("align", ALIGN_LEFT))
        if align not in (ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT):
            align = ALIGN_LEFT
        image_path = state.get("image_path")
        if mode in ("image", "text_image") and not image_path:
            raise ValueError(
                "Štítek v režimu s obrázkem nemá vybraný obrázek "
                "(nebo přepněte na „Jen text“)."
            )
        default_size = float(state.get("font_size_pt") or 11.0)
        runs = normalize_runs(state.get("runs"), default_size)
        if not runs:
            runs = runs_from_plain(
                str(state.get("text") or ""),
                bold=bool(state.get("bold", False)),
                italic=bool(state.get("italic", False)),
                underline=bool(state.get("underline", False)),
                color=str(state.get("color") or "#000000"),
                size=default_size,
            )
        return LabelContent(
            text=runs_to_plain(runs),
            image_path=str(image_path) if image_path else None,
            mode=mode,
            font_size_pt=default_size,
            align=align,
            runs=runs,
        )

    def _content(self) -> LabelContent:
        return self._content_from_state(self._snapshot_editor())

    def _contents_map(self, positions: list[tuple[int, int]]) -> dict[tuple[int, int], LabelContent]:
        self._capture_editor_to_active()
        result: dict[tuple[int, int], LabelContent] = {}
        for key in positions:
            name = cell_name(*key)
            state = self.label_states.get(name) or self._default_label_state()
            if self._is_empty_state(state):
                continue
            result[key] = self._content_from_state(state)
        return result

    def _render_options(self) -> RenderOptions:
        return RenderOptions(
            show_outlines=self.var_outlines.get(),
            show_cell_names=self.var_names.get(),
            show_printable_area=self.var_printable.get(),
        )

    def _dialog_parent(self) -> None:
        """Zvedni hlavní okno, ať systémové dialogy nejsou za ním."""
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
            self.update_idletasks()
        except Exception:
            pass

    def _with_app_on_top(self):
        """Dočasně topmost během dialogu (Windows často schová filedialog za app)."""

        class _Ctx:
            def __init__(self, app: "LabelApp") -> None:
                self.app = app
                self._was = False

            def __enter__(self):
                try:
                    self.app.lift()
                    self.app.attributes("-topmost", True)
                    self.app.update_idletasks()
                except Exception:
                    pass
                return self.app

            def __exit__(self, *_exc):
                try:
                    self.app.attributes("-topmost", False)
                    self.app.lift()
                except Exception:
                    pass

        return _Ctx(self)

    def _build_pdf_bytes(self, *, for_print: bool = False) -> bytes:
        lay = self._layout()
        # Upozornění k rozměrům zůstávají v panelu vpravo — nikdy neblokují
        # náhled/tisk/uložení (dialog za oknem vypadal jako „nic nefunguje“).
        positions = self._positions()
        if not positions:
            raise ValueError("Vyberte alespoň jednu pozici štítku.")
        contents = self._contents_map(positions)
        if not contents:
            raise ValueError(
                "Vybrané pozice nemají žádný obsah. "
                "Vyplňte text/obrázek, nebo použijte „Nakopírovat…“."
            )

        options = self._render_options()
        if for_print:
            # Ostrý tisk bez náhledových značek (bez dalšího dialogu).
            options = RenderOptions(
                show_outlines=False,
                show_cell_names=False,
                show_printable_area=False,
            )

        buf = BytesIO()
        render_sheet_pdf(lay, positions, contents, buf, options)
        return buf.getvalue()

    def _save_pdf(self) -> None:
        try:
            data = self._build_pdf_bytes()
        except RuntimeError:
            return
        except Exception as exc:
            with self._with_app_on_top():
                messagebox.showerror("Chyba", str(exc), parent=self)
            return

        with self._with_app_on_top():
            path = filedialog.asksaveasfilename(
                parent=self,
                title="Uložit PDF",
                defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf"), ("Všechny soubory", "*.*")],
                initialfile="stitky.pdf",
            )
        if not path:
            return
        try:
            Path(path).write_bytes(data)
        except Exception as exc:
            with self._with_app_on_top():
                messagebox.showerror("Uložení selhalo", str(exc), parent=self)
            return
        self._set_status(f"✓ PDF uloženo: {path}")

    def _preview(self) -> None:
        try:
            data = self._build_pdf_bytes()
        except RuntimeError:
            return
        except Exception as exc:
            with self._with_app_on_top():
                messagebox.showerror("Chyba", str(exc), parent=self)
            return
        fd, name = tempfile.mkstemp(prefix="stitky_nahled_", suffix=".pdf")
        import os

        os.close(fd)
        path = Path(name)
        path.write_bytes(data)
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", str(path)])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            with self._with_app_on_top():
                messagebox.showinfo("Náhled", f"PDF: {path}\n({exc})", parent=self)

    def _print(self) -> None:
        try:
            lay = self._layout()
            positions = self._positions()
            if not positions:
                raise ValueError("Vyberte alespoň jednu pozici štítku.")
            contents = self._contents_map(positions)
            if not contents:
                raise ValueError(
                    "Vybrané pozice nemají žádný obsah. "
                    "Vyplňte text/obrázek, nebo použijte „Nakopírovat…“."
                )
            printer = self.var_printer.get().strip() or None
            has_svg = any(
                c.image_path and Path(c.image_path).suffix.lower() in (".svg", ".svgz")
                for c in contents.values()
            )
            # Přímý GDI tisk (SVG se vyrastrová ve vysokém DPI).
            # Křivky SVG zůstanou v „Náhled PDF…“ / „Uložit PDF…“.
            image = render_sheet_image(
                lay,
                positions,
                contents,
                dpi=300,
                options=RenderOptions(
                    show_outlines=False,
                    show_cell_names=False,
                    show_printable_area=False,
                ),
            )
            print_bitmap(
                image,
                printer,
                page_width_mm=lay.print_width_mm,
                page_height_mm=lay.print_height_mm,
                scale_x=lay.print_scale_x,
                scale_y=lay.print_scale_y,
            )
            self._schedule_session_save()
            self._set_status(
                f"✓ Odesláno {len(contents)} štítků na tiskárnu "
                + (f"„{printer}“." if printer else "(výchozí).")
                + (" SVG vyrastrováno; křivky jsou v PDF exportu." if has_svg else "")
            )
        except Exception as exc:
            with self._with_app_on_top():
                messagebox.showerror(
                    "Tisk selhal",
                    f"{exc}\n\nTip: použijte „Uložit PDF…“ a vytiskněte ručně.",
                    parent=self,
                )

    def _schedule_session_save(self) -> None:
        if not _session_enabled():
            return
        if self._session_save_after_id is not None:
            try:
                self.after_cancel(self._session_save_after_id)
            except Exception:
                pass
        self._session_save_after_id = self.after(800, self._save_session)

    def _save_session(self) -> None:
        self._session_save_after_id = None
        if not _session_enabled():
            return
        try:
            self._capture_editor_to_active()
            path = _session_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = self._export_state()
            if self.doc_path is not None:
                payload["doc_path"] = str(self.doc_path)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass

    def _restore_session(self) -> None:
        if not _session_enabled():
            return
        path = _session_path()
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or data.get("app") != "stitky":
                return
            self._apply_state(data)
            doc = data.get("doc_path")
            if doc:
                p = Path(str(doc))
                if p.is_file():
                    self.doc_path = p
            self._set_status("Obnovena předchozí práce.")
        except Exception:
            pass

    def _on_close(self) -> None:
        try:
            if self._session_save_after_id is not None:
                self.after_cancel(self._session_save_after_id)
                self._session_save_after_id = None
            self._save_session()
        except Exception:
            pass
        self.destroy()


def main() -> None:
    app = LabelApp()
    app.mainloop()


if __name__ == "__main__":
    main()
