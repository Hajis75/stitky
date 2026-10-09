"""Živý náhled celého archu s obsahem štítků — klik = editace, pravý klik = tisk ano/ne."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from layout import SheetLayout, cell_name
from renderer import LabelContent, RenderOptions, render_sheet_image

ACTIVE_COLOR = "#1565c0"
PRINT_COLOR = "#2e7d32"


class SheetPreview(ttk.Frame):
    def __init__(self, master, *, on_select, on_toggle) -> None:
        super().__init__(master)
        self.on_select = on_select
        self.on_toggle = on_toggle
        self.canvas = tk.Canvas(self, background="#dcdcdc", highlightthickness=0,
                                width=380, height=540)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.schedule())
        self.canvas.bind("<Button-1>", self._on_left)
        self.canvas.bind("<Button-3>", self._on_right)
        self.canvas.bind("<Motion>", self._on_motion)

        self._layout: SheetLayout | None = None
        self._contents: dict[tuple[int, int], LabelContent] = {}
        self._active: tuple[int, int] = (0, 0)
        self._selected: set[tuple[int, int]] = set()
        self._photo = None
        self._scale = 1.0  # px na mm
        self._origin = (0.0, 0.0)
        self._after_id: str | None = None
        self.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, event) -> None:
        if event.widget is self and self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    # ------------------------------------------------------------ API
    def set_data(
        self,
        layout: SheetLayout,
        contents: dict[tuple[int, int], LabelContent],
        active: tuple[int, int],
        selected: set[tuple[int, int]],
    ) -> None:
        self._layout = layout
        self._contents = contents
        self._active = active
        self._selected = set(selected)
        self.schedule()

    def set_marks(self, active: tuple[int, int], selected: set[tuple[int, int]]) -> None:
        """Jen přebarví rámečky (bez nového renderu obsahu)."""
        self._active = active
        self._selected = set(selected)
        self._draw_marks()

    def schedule(self, delay_ms: int = 250) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = self.after(delay_ms, self.render_now)

    # ------------------------------------------------------------ render
    def render_now(self) -> None:
        self._after_id = None
        lay = self._layout
        if lay is None:
            return
        from PIL import Image, ImageTk

        cw = max(self.canvas.winfo_width(), 50)
        ch = max(self.canvas.winfo_height(), 50)
        if cw <= 50 or ch <= 50:
            cw, ch = int(self.canvas["width"]), int(self.canvas["height"])
        pad = 8
        pw, ph = lay.print_width_mm, lay.print_height_mm
        s = min((cw - 2 * pad) / pw, (ch - 2 * pad) / ph)
        if s <= 0:
            return
        out_w, out_h = max(1, int(pw * s)), max(1, int(ph * s))
        # 2× převzorkování kvůli čitelnosti malého textu
        dpi = max(40.0, min(220.0, s * 25.4 * 2.0))
        try:
            img = render_sheet_image(
                lay,
                list(self._contents.keys()),
                self._contents,
                dpi=dpi,
                options=RenderOptions(show_outlines=True, show_cell_names=False),
            )
            img = img.resize((out_w, out_h), Image.Resampling.LANCZOS)
        except Exception:
            img = Image.new("RGB", (out_w, out_h), (255, 255, 255))

        self._scale = s
        self._origin = ((cw - out_w) / 2.0, (ch - out_h) / 2.0)
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        ox, oy = self._origin
        self.canvas.create_rectangle(ox - 1, oy - 1, ox + out_w, oy + out_h,
                                     outline="#777", fill="")
        self.canvas.create_image(ox, oy, image=self._photo, anchor=tk.NW)
        self._draw_marks()

    def _cell_box(self, key: tuple[int, int]) -> tuple[float, float, float, float]:
        assert self._layout is not None
        x, y, w, h = self._layout.label_rect_print_mm(*key)
        ox, oy = self._origin
        s = self._scale
        return ox + x * s, oy + y * s, ox + (x + w) * s, oy + (y + h) * s

    def _draw_marks(self) -> None:
        lay = self._layout
        self.canvas.delete("mark")
        if lay is None:
            return
        for r in range(lay.rows):
            for c in range(lay.cols):
                key = (r, c)
                x0, y0, x1, y1 = self._cell_box(key)
                printed = key in self._selected
                if key == self._active:
                    self.canvas.create_rectangle(x0 + 1, y0 + 1, x1 - 1, y1 - 1,
                                                 outline=ACTIVE_COLOR, width=3, tags="mark")
                elif printed:
                    self.canvas.create_rectangle(x0 + 1, y0 + 1, x1 - 1, y1 - 1,
                                                 outline=PRINT_COLOR, width=2, tags="mark")
                label = cell_name(r, c) + ("  ✓" if printed else "")
                self.canvas.create_text(
                    x0 + 4, y0 + 3, text=label, anchor=tk.NW, tags="mark",
                    fill=ACTIVE_COLOR if key == self._active
                    else (PRINT_COLOR if printed else "#999"),
                    font=("Segoe UI", 7, "bold" if printed or key == self._active else "normal"),
                )

    # ------------------------------------------------------------ myš
    def _hit(self, event) -> tuple[int, int] | None:
        lay = self._layout
        if lay is None:
            return None
        for r in range(lay.rows):
            for c in range(lay.cols):
                x0, y0, x1, y1 = self._cell_box((r, c))
                if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                    return r, c
        return None

    def _on_left(self, event) -> None:
        key = self._hit(event)
        if key is not None:
            self.on_select(key)

    def _on_right(self, event) -> None:
        key = self._hit(event)
        if key is not None:
            self.on_toggle(key)

    def _on_motion(self, event) -> None:
        self.canvas.configure(cursor="hand2" if self._hit(event) else "")
