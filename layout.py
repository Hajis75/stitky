"""Výpočet pozic štítků — fyzický arch vs. tisková stránka (vystředěno)."""

from __future__ import annotations

from dataclasses import dataclass


ROWS = "ABCDEFGH"  # max. 8 řádků (A–H)
COLS = 3  # výchozí počet sloupců (preset 3×8)

# Nepotisknutelný okraj tiskárny (informativní / náhledové rámečky).
DEFAULT_PRINTABLE_MARGIN_MM = 5.0

# GDI tisk: plný rámeček 70×36 vyšel na papíře 73×36,5 → zmenšit výstup.
PRINT_SCALE_X = 70.0 / 73.0
PRINT_SCALE_Y = 36.0 / 36.5

# Vzdálenosti středů (pravítko) pro výchozí arch 3×8: A1→A3 = 145, A1→H1 = 266.
CENTER_SPAN_X_A1_A3_MM = 145.0
CENTER_SPAN_Y_A1_H1_MM = 266.0


def _equal_split_center_spans(
    page_width_mm: float,
    page_height_mm: float,
    label_width_mm: float,
    label_height_mm: float,
    rows: int,
    cols: int,
) -> tuple[float, float]:
    """Výchozí rozteče středů při rovnoměrném rozdělení zbytků (okraje = mezery)."""
    leftover_x = page_width_mm - cols * label_width_mm
    pieces_x = 2 + max(cols - 1, 0)
    unit_x = leftover_x / pieces_x if pieces_x else 0.0
    pitch_x = label_width_mm + unit_x
    span_x = pitch_x * (cols - 1) if cols > 1 else 0.0

    leftover_y = page_height_mm - rows * label_height_mm
    pieces_y = 2 + max(rows - 1, 0)
    unit_y = leftover_y / pieces_y if pieces_y else 0.0
    pitch_y = label_height_mm + unit_y
    span_y = pitch_y * (rows - 1) if rows > 1 else 0.0
    return span_x, span_y


@dataclass(frozen=True)
class SheetPreset:
    """Předvolba archu samolepek."""

    id: str
    title: str
    page_width_mm: float
    page_height_mm: float
    print_width_mm: float
    print_height_mm: float
    label_width_mm: float
    label_height_mm: float
    rows: int
    cols: int
    span_x_mm: float
    span_y_mm: float

    @property
    def span_x_label(self) -> str:
        last_col = self.cols
        return f"A1→A{last_col} (středy)"

    @property
    def span_y_label(self) -> str:
        last_row = ROWS[self.rows - 1] if self.rows else "H"
        return f"A1→{last_row}1 (středy)"

    def short_info(self) -> str:
        return (
            f"Arch {self.page_width_mm:.0f}×{self.page_height_mm:.0f} mm, "
            f"tisk {self.print_width_mm:.0f}×{self.print_height_mm:.0f} (střed). "
            f"Štítek {self.label_width_mm:.0f}×{self.label_height_mm:.0f}, "
            f"mřížka {self.cols}×{self.rows}."
        )


# 2×8: štítek 102×36, arch 211×303,5
# Šířka: 2 + 102 + 3 + 102 + 2 = 211 → stretch A1→A2 = 105
# Výška: okraj 2 mm nahoře i dole, mezi řádky rovnoměrně
# → A1→H1 = 303,5 − 2 − 2 − 36 = 263,5 (středy)
_LABEL_W_2X8 = 102.0
_LABEL_H_2X8 = 36.0
_PAGE_W_2X8 = 211.0
_PAGE_H_2X8 = 303.5
_OUTER_2X8 = 2.0
_GAP_X_2X8 = 3.0
_SPAN_X_2X8 = _LABEL_W_2X8 + _GAP_X_2X8  # 105
_SPAN_Y_2X8 = _PAGE_H_2X8 - 2 * _OUTER_2X8 - _LABEL_H_2X8  # 263.5

SHEET_PRESETS: dict[str, SheetPreset] = {
    "3x8_70x36": SheetPreset(
        id="3x8_70x36",
        title="3×8 · 70×36 mm · arch 217×304",
        page_width_mm=217.0,
        page_height_mm=304.0,
        print_width_mm=215.0,
        print_height_mm=304.0,
        label_width_mm=70.0,
        label_height_mm=36.0,
        rows=8,
        cols=3,
        span_x_mm=CENTER_SPAN_X_A1_A3_MM,
        span_y_mm=CENTER_SPAN_Y_A1_H1_MM,
    ),
    "2x8_120x36": SheetPreset(
        id="2x8_120x36",
        title="2×8 · 102×36 mm · arch 211×303,5",
        page_width_mm=_PAGE_W_2X8,
        page_height_mm=_PAGE_H_2X8,
        # Stejné jako fyzický arch — Tray 1 (boční) drží papír vodítky
        # na středu; ovladač musí dostat přesně 211×303,5 (ne 215).
        print_width_mm=_PAGE_W_2X8,
        print_height_mm=_PAGE_H_2X8,
        label_width_mm=_LABEL_W_2X8,
        label_height_mm=_LABEL_H_2X8,
        rows=8,
        cols=2,
        span_x_mm=_SPAN_X_2X8,
        span_y_mm=_SPAN_Y_2X8,
    ),
}

DEFAULT_PRESET_ID = "3x8_70x36"


def get_preset(preset_id: str | None) -> SheetPreset:
    if preset_id == "2x8_12x36":
        preset_id = "2x8_120x36"  # stará chybná id → 120×36
    if preset_id and preset_id in SHEET_PRESETS:
        return SHEET_PRESETS[preset_id]
    return SHEET_PRESETS[DEFAULT_PRESET_ID]


def preset_choices() -> list[tuple[str, str]]:
    """[(id, title), ...] pro UI."""
    return [(p.id, p.title) for p in SHEET_PRESETS.values()]


@dataclass
class SheetLayout:
    """
    Fyzický arch vs. tisková stránka — mřížka i tisk vystředěné.
    Pozice z roztečí středů; mezery = pitch − velikost štítku; okraje = zbytek / 2.
    """

    # Fyzický arch (pravítko na papíře)
    page_width_mm: float = 217.0
    page_height_mm: float = 304.0

    # Ovladač / PDF (max. šířka Phaseru)
    print_width_mm: float = 215.0
    print_height_mm: float = 304.0

    label_width_mm: float = 70.0
    label_height_mm: float = 36.0
    rows: int = 8
    cols: int = 3

    printable_margin_left_mm: float = DEFAULT_PRINTABLE_MARGIN_MM
    printable_margin_right_mm: float = DEFAULT_PRINTABLE_MARGIN_MM
    printable_margin_top_mm: float = DEFAULT_PRINTABLE_MARGIN_MM
    printable_margin_bottom_mm: float = DEFAULT_PRINTABLE_MARGIN_MM

    # Ze středů: pitch X=72,5 Y=38 → mezery 2,5 / 2,0; okraje 1 mm.
    outer_margin_x_mm: float | None = 1.0
    outer_margin_y_mm: float | None = 1.0

    # Padding obsahu uvnitř štítku (horní, pravý, dolní, levý). 0 0 0 0 = celý 70×36.
    content_pad_top_mm: float = 0.0
    content_pad_right_mm: float = 0.0
    content_pad_bottom_mm: float = 0.0
    content_pad_left_mm: float = 0.0

    nudge_x_mm: float = 0.0
    nudge_y_mm: float = 0.0

    rotate_print_180: bool = False

    def print_offset_mm(self) -> tuple[float, float]:
        """
        Posun tiskové stránky vůči fyzickému archu — vždy vystředěno.
        Střed mřížky štítků = střed archu; větší/menší okraj stránky střed nemění.
        """
        ox = (self.page_width_mm - self.print_width_mm) / 2.0
        oy = (self.page_height_mm - self.print_height_mm) / 2.0
        return ox, oy

    def resolved_outer_margins(self) -> tuple[float, float]:
        """Vnější okraje mřížky od kraje fyzického papíru (symetrické)."""
        if self.outer_margin_x_mm is not None:
            ox = self.outer_margin_x_mm
        else:
            leftover = self.page_width_mm - self.cols * self.label_width_mm
            pieces = 2 + max(self.cols - 1, 0)
            ox = leftover / pieces if pieces else 0.0

        if self.outer_margin_y_mm is not None:
            oy = self.outer_margin_y_mm
        else:
            leftover = self.page_height_mm - self.rows * self.label_height_mm
            pieces = 2 + max(self.rows - 1, 0)
            oy = leftover / pieces if pieces else 0.0

        return ox, oy

    def gap_x_mm(self) -> float:
        ox, _ = self.resolved_outer_margins()
        denom = self.cols - 1
        if denom <= 0:
            return 0.0
        return (self.page_width_mm - 2 * ox - self.cols * self.label_width_mm) / denom

    def gap_y_mm(self) -> float:
        _, oy = self.resolved_outer_margins()
        denom = self.rows - 1
        if denom <= 0:
            return 0.0
        return (self.page_height_mm - 2 * oy - self.rows * self.label_height_mm) / denom

    def content_width_mm(self) -> float:
        return self.cols * self.label_width_mm + (self.cols - 1) * self.gap_x_mm()

    def content_height_mm(self) -> float:
        return self.rows * self.label_height_mm + (self.rows - 1) * self.gap_y_mm()

    def resolved_margins(self) -> tuple[float, float]:
        return self.resolved_outer_margins()

    def printable_rect_physical_mm(self) -> tuple[float, float, float, float]:
        """
        Tisknutelná oblast ve FYZICKÝCH souřadnicích archu.
        = tisková stránka (zleva od 0) minus vnitřní printable margins.
        """
        off_x, off_y = self.print_offset_mm()
        x = off_x + self.printable_margin_left_mm
        y = off_y + self.printable_margin_top_mm
        w = (
            self.print_width_mm
            - self.printable_margin_left_mm
            - self.printable_margin_right_mm
        )
        h = (
            self.print_height_mm
            - self.printable_margin_top_mm
            - self.printable_margin_bottom_mm
        )
        return x, y, w, h

    def printable_rect_mm(self) -> tuple[float, float, float, float]:
        """Alias — fyzické souřadnice (pro varování / náhled na archu)."""
        return self.printable_rect_physical_mm()

    def label_rect_mm(self, row: int, col: int) -> tuple[float, float, float, float]:
        """(x, y, w, h) ve FYZICKÝCH mm od levého horního rohu archu."""
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            raise ValueError(f"Pozice mimo rozsah: řádek={row}, sloupec={col}")
        left, top = self.resolved_margins()
        gx, gy = self.gap_x_mm(), self.gap_y_mm()
        x = left + col * (self.label_width_mm + gx)
        y = top + row * (self.label_height_mm + gy)
        return x, y, self.label_width_mm, self.label_height_mm

    def label_rect_print_mm(self, row: int, col: int) -> tuple[float, float, float, float]:
        """(x, y, w, h) v mm na TISKOVÉ stránce (215×304), včetně nudge."""
        x, y, w, h = self.label_rect_mm(row, col)
        off_x, off_y = self.print_offset_mm()
        return (
            x - off_x + self.nudge_x_mm,
            y - off_y + self.nudge_y_mm,
            w,
            h,
        )

    def printable_rect_print_mm(self) -> tuple[float, float, float, float]:
        """Tisknutelná oblast v souřadnicích tiskové stránky (bez nudge)."""
        return (
            self.printable_margin_left_mm,
            self.printable_margin_top_mm,
            self.print_width_mm
            - self.printable_margin_left_mm
            - self.printable_margin_right_mm,
            self.print_height_mm
            - self.printable_margin_top_mm
            - self.printable_margin_bottom_mm,
        )

    def content_insets_mm(self, row: int, col: int) -> tuple[float, float, float, float]:
        """
        Padding obsahu uvnitř štítku: (horní, pravý, dolní, levý).
        Stejné pro všechny pozice — nastavitelné v UI (např. 0 0 0 0 nebo 10 5 10 5).
        """
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            raise ValueError(f"Pozice mimo rozsah: řádek={row}, sloupec={col}")
        return (
            float(self.content_pad_top_mm),
            float(self.content_pad_right_mm),
            float(self.content_pad_bottom_mm),
            float(self.content_pad_left_mm),
        )

    def label_content_rect_print_mm(
        self,
        row: int,
        col: int,
        *,
        pad_mm: float = 0.0,
    ) -> tuple[float, float, float, float]:
        """
        Vnitřní plnitelná oblast = štítek 70×36 minus content_insets (+ volitelný pad).
        """
        lx, ly, lw, lh = self.label_rect_print_mm(row, col)
        top, right, bottom, left = self.content_insets_mm(row, col)
        x0 = lx + left + pad_mm
        y0 = ly + top + pad_mm
        w = lw - left - right - 2 * pad_mm
        h = lh - top - bottom - 2 * pad_mm
        if w < 0.5 or h < 0.5:
            pad = max(pad_mm, 1.0)
            return (lx + pad, ly + pad, max(0.5, lw - 2 * pad), max(0.5, lh - 2 * pad))
        return x0, y0, w, h

    def pitch_x_mm(self) -> float:
        """Rozteč sloupců (levá hrana → levá hrana sousedního štítku)."""
        return self.label_width_mm + self.gap_x_mm()

    def pitch_y_mm(self) -> float:
        """Rozteč řádků (horní hrana → horní hrana sousedního štítku)."""
        return self.label_height_mm + self.gap_y_mm()

    def apply_measured_pitches(
        self,
        *,
        span_x_a1_a3_mm: float | None = None,
        span_y_a1_h1_mm: float | None = None,
    ) -> dict[str, float]:
        """
        Z naměřené vzdálenosti A1→A3 (levé hrany) a A1→H1 (horní hrany)
        nastaví vnější okraje tak, aby mezery odpovídaly fyzické rozteči.

        Vrací dict s novými hodnotami (gap_x, gap_y, outer_x, outer_y, pitch_x, pitch_y).
        """
        result: dict[str, float] = {}

        if span_x_a1_a3_mm is not None:
            if self.cols < 2:
                raise ValueError("Pro kalibraci X jsou potřeba alespoň 2 sloupce.")
            pitch_x = float(span_x_a1_a3_mm) / (self.cols - 1)
            gap_x = pitch_x - self.label_width_mm
            # page = 2*outer + cols*label + (cols-1)*gap
            outer_x = (
                self.page_width_mm
                - self.cols * self.label_width_mm
                - (self.cols - 1) * gap_x
            ) / 2.0
            self.outer_margin_x_mm = outer_x
            result.update(
                {
                    "pitch_x": pitch_x,
                    "gap_x": gap_x,
                    "outer_x": outer_x,
                }
            )

        if span_y_a1_h1_mm is not None:
            if self.rows < 2:
                raise ValueError("Pro kalibraci Y jsou potřeba alespoň 2 řádky.")
            pitch_y = float(span_y_a1_h1_mm) / (self.rows - 1)
            gap_y = pitch_y - self.label_height_mm
            outer_y = (
                self.page_height_mm
                - self.rows * self.label_height_mm
                - (self.rows - 1) * gap_y
            ) / 2.0
            self.outer_margin_y_mm = outer_y
            result.update(
                {
                    "pitch_y": pitch_y,
                    "gap_y": gap_y,
                    "outer_y": outer_y,
                }
            )

        if not result:
            raise ValueError("Zadejte alespoň jedno měření (A1→A3 nebo A1→H1).")
        return result

    def apply_a1_shift(self, dx_mm: float = 0.0, dy_mm: float = 0.0) -> tuple[float, float]:
        """
        Posun křížku A1 oproti středu fyzického štítku (mm).
        Kladné X = tisk je vpravo od středu → nudge doleva.
        Kladné Y = tisk je níž → nudge nahoru.
        Vrací nové (nudge_x, nudge_y).
        """
        self.nudge_x_mm = self.nudge_x_mm - float(dx_mm)
        self.nudge_y_mm = self.nudge_y_mm - float(dy_mm)
        return self.nudge_x_mm, self.nudge_y_mm

    def fit_warnings(self) -> list[str]:
        """Všechna upozornění (zobrazují se v UI)."""
        return self._fit_warnings(blocking_only=False)

    def fit_blocking_warnings(self) -> list[str]:
        """Jen závažné problémy, které mají vyžadovat potvrzení před tiskem/PDF."""
        return self._fit_warnings(blocking_only=True)

    def _fit_warnings(self, *, blocking_only: bool) -> list[str]:
        warnings: list[str] = []
        ox, oy = self.resolved_outer_margins()
        gx, gy = self.gap_x_mm(), self.gap_y_mm()
        off_x, off_y = self.print_offset_mm()

        if self.print_width_mm > self.page_width_mm + 0.05:
            warnings.append(
                f"Tisková šířka ({self.print_width_mm:.1f} mm) je větší než "
                f"fyzický arch ({self.page_width_mm:.1f} mm)."
            )
        if self.print_height_mm > self.page_height_mm + 0.05:
            warnings.append(
                f"Tisková výška ({self.print_height_mm:.1f} mm) je větší než "
                f"fyzický arch ({self.page_height_mm:.1f} mm)."
            )

        if gx < -0.05 or gy < -0.05:
            msg = (
                f"Štítky se nevejdou při vnějších okrajích {ox:.1f}/{oy:.1f} mm "
                f"(mezery {gx:.2f}/{gy:.2f} mm)."
            )
            # Mírně záporné mezery z kalibrace (rozteč < nominální šířka) jsou OK.
            if gx < -2.0 or gy < -2.0 or not blocking_only:
                warnings.append(msg)

        if blocking_only:
            return warnings

        # Informativní — tisková stránka jiná než fyzický arch (vystředěno).
        if abs(off_x) > 0.05 or abs(self.page_width_mm - self.print_width_mm) > 0.05:
            warnings.append(
                f"Tisková stránka {self.print_width_mm:.0f} mm je na archu "
                f"{self.page_width_mm:.0f} mm vystředěná "
                f"(offset X {off_x:+.2f} mm) — okraje archu mimo tisk se oříznou."
            )
        if abs(off_y) > 0.05:
            warnings.append(
                f"Tisková výška offset Y {off_y:.2f} mm vůči fyzickému archu."
            )

        if gx >= -0.05 and gy >= -0.05 and (gx < 0.5 or gy < 0.5):
            warnings.append(
                f"Velmi malé rozestupy ({gx:.2f}×{gy:.2f} mm)."
            )

        left, top = self.resolved_margins()
        right = left + self.content_width_mm()
        bottom = top + self.content_height_mm()
        pr_x, pr_y, pr_w, pr_h = self.printable_rect_physical_mm()
        pr_right = pr_x + pr_w
        pr_bottom = pr_y + pr_h

        if left < pr_x - 0.05 or top < pr_y - 0.05 or right > pr_right + 0.05 or bottom > pr_bottom + 0.05:
            warnings.append(
                "Fyzické štítky sahají k okraji archu (mimo tisknutelnou zónu tiskárny) — "
                "očekávané. Obsah se kreslí jen do průniku štítek ∩ tisknutelná oblast."
            )

        return warnings

    def summary_text(self) -> str:
        ox, oy = self.resolved_outer_margins()
        gx, gy = self.gap_x_mm(), self.gap_y_mm()
        off_x, off_y = self.print_offset_mm()
        span_x = self.pitch_x_mm() * max(self.cols - 1, 0)
        span_y = self.pitch_y_mm() * max(self.rows - 1, 0)
        last_col = self.cols
        last_row = ROWS[self.rows - 1] if 0 < self.rows <= len(ROWS) else "?"
        return (
            f"Fyzický arch: {self.page_width_mm:.0f}×{self.page_height_mm:.0f} mm "
            f"(štítky {self.label_width_mm:.0f}×{self.label_height_mm:.0f}, "
            f"mřížka {self.cols}×{self.rows})\n"
            f"Tisková stránka: {self.print_width_mm:.0f}×{self.print_height_mm:.0f} mm "
            f"(offset {off_x:.2f}/{off_y:.2f} mm; "
            f"vpravo ořez {self.page_width_mm - self.print_width_mm - off_x:.2f} mm)\n"
            f"Rozteč středů (hlavní): A1→A{last_col}={span_x:.1f}, "
            f"A1→{last_row}1={span_y:.1f} mm "
            f"(pitch {self.pitch_x_mm():.2f}/{self.pitch_y_mm():.2f})\n"
            f"Mezery mezi štítky (= pitch − štítek): {gx:.2f} / {gy:.2f} mm\n"
            f"Okraje archu (vystředění): {ox:.2f} / {oy:.2f} mm\n"
            f"Padding obsahu T R B L: "
            f"{self.content_pad_top_mm:.1f} {self.content_pad_right_mm:.1f} "
            f"{self.content_pad_bottom_mm:.1f} {self.content_pad_left_mm:.1f} mm\n"
            f"Nudge X/Y: {self.nudge_x_mm:+.2f} / {self.nudge_y_mm:+.2f} mm"
        )


def parse_cell(token: str, *, cols: int = COLS, rows: int = 8) -> tuple[int, int]:
    """'A1' -> (0, 0), 'H3' -> (7, 2). Písmeno = řádek, číslo = sloupec."""
    token = token.strip().upper()
    if len(token) < 2:
        raise ValueError(f"Neplatná pozice: {token!r}")
    row_letter = token[0]
    col_part = token[1:]
    allowed_rows = ROWS[:rows]
    if row_letter not in allowed_rows:
        raise ValueError(f"Řádek musí být {allowed_rows[0]}–{allowed_rows[-1]}, dostáno: {row_letter!r}")
    if not col_part.isdigit():
        raise ValueError(f"Sloupec musí být číslo 1–{cols}, dostáno: {col_part!r}")
    col = int(col_part)
    if not (1 <= col <= cols):
        raise ValueError(f"Sloupec musí být 1–{cols}, dostáno: {col}")
    return ROWS.index(row_letter), col - 1


def parse_range(
    spec: str, *, cols: int = COLS, rows: int = 8
) -> list[tuple[int, int]]:
    spec = spec.strip().upper().replace(" ", "")
    if not spec:
        raise ValueError("Zadejte alespoň jednu pozici (např. A1 nebo A1-B2).")

    cells: set[tuple[int, int]] = set()
    for part in spec.split(","):
        if not part:
            continue
        if "-" in part or ":" in part:
            sep = "-" if "-" in part else ":"
            a, b = part.split(sep, 1)
            r1, c1 = parse_cell(a, cols=cols, rows=rows)
            r2, c2 = parse_cell(b, cols=cols, rows=rows)
            for r in range(min(r1, r2), max(r1, r2) + 1):
                for c in range(min(c1, c2), max(c1, c2) + 1):
                    cells.add((r, c))
        else:
            cells.add(parse_cell(part, cols=cols, rows=rows))

    return sorted(cells)


def cell_name(row: int, col: int) -> str:
    return f"{ROWS[row]}{col + 1}"


def layout_from_center_spans(
    span_x_mm: float = CENTER_SPAN_X_A1_A3_MM,
    span_y_mm: float = CENTER_SPAN_Y_A1_H1_MM,
    *,
    page_width_mm: float = 217.0,
    page_height_mm: float = 304.0,
    print_width_mm: float | None = None,
    print_height_mm: float | None = None,
    label_width_mm: float = 70.0,
    label_height_mm: float = 36.0,
    rows: int = 8,
    cols: int = 3,
    content_pad_top_mm: float = 0.0,
    content_pad_right_mm: float = 0.0,
    content_pad_bottom_mm: float = 0.0,
    content_pad_left_mm: float = 0.0,
) -> SheetLayout:
    """
    Mezery a okraje z vzdáleností středů prvního→posledního sloupce / řádku.
    pitch = span / (n−1), mezera = pitch − štítek, okraj = zbytek / 2.
    """
    if cols < 2 or rows < 2:
        raise ValueError("Pro rozteče středů jsou potřeba alespoň 2×2 štítky.")
    pitch_x = float(span_x_mm) / (cols - 1)
    pitch_y = float(span_y_mm) / (rows - 1)
    gap_x = pitch_x - label_width_mm
    gap_y = pitch_y - label_height_mm
    outer_x = (
        page_width_mm - cols * label_width_mm - (cols - 1) * gap_x
    ) / 2.0
    outer_y = (
        page_height_mm - rows * label_height_mm - (rows - 1) * gap_y
    ) / 2.0
    pw = page_width_mm if print_width_mm is None else float(print_width_mm)
    ph = page_height_mm if print_height_mm is None else float(print_height_mm)
    return SheetLayout(
        page_width_mm=page_width_mm,
        page_height_mm=page_height_mm,
        print_width_mm=pw,
        print_height_mm=ph,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
        rows=rows,
        cols=cols,
        outer_margin_x_mm=outer_x,
        outer_margin_y_mm=outer_y,
        content_pad_top_mm=content_pad_top_mm,
        content_pad_right_mm=content_pad_right_mm,
        content_pad_bottom_mm=content_pad_bottom_mm,
        content_pad_left_mm=content_pad_left_mm,
    )


def layout_from_preset(
    preset: SheetPreset | str,
    *,
    span_x_mm: float | None = None,
    span_y_mm: float | None = None,
    content_pad_top_mm: float = 0.0,
    content_pad_right_mm: float = 0.0,
    content_pad_bottom_mm: float = 0.0,
    content_pad_left_mm: float = 0.0,
) -> SheetLayout:
    p = get_preset(preset) if isinstance(preset, str) else preset
    return layout_from_center_spans(
        span_x_mm if span_x_mm is not None else p.span_x_mm,
        span_y_mm if span_y_mm is not None else p.span_y_mm,
        page_width_mm=p.page_width_mm,
        page_height_mm=p.page_height_mm,
        print_width_mm=p.print_width_mm,
        print_height_mm=p.print_height_mm,
        label_width_mm=p.label_width_mm,
        label_height_mm=p.label_height_mm,
        rows=p.rows,
        cols=p.cols,
        content_pad_top_mm=content_pad_top_mm,
        content_pad_right_mm=content_pad_right_mm,
        content_pad_bottom_mm=content_pad_bottom_mm,
        content_pad_left_mm=content_pad_left_mm,
    )


def default_sheet_layout() -> SheetLayout:
    """Výchozí layout — preset 3×8 ze středů A1→A3=145, A1→H1=266."""
    return layout_from_preset(DEFAULT_PRESET_ID)
