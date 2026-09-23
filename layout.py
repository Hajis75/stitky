"""Výpočet pozic štítků — fyzický arch vs. tisková stránka (centrovaně)."""

from __future__ import annotations

from dataclasses import dataclass


ROWS = "ABCDEFGH"  # 8 řádků
COLS = 3

# Typický vnitřní nepotisknutelný okraj uvnitř tiskové stránky.
DEFAULT_PRINTABLE_MARGIN_MM = 4.0


@dataclass
class SheetLayout:
    """
    Fyzický arch (např. 217×304) nese štítky.
    Tiskárna přijme jen užší formát (např. 215×304) — tisková stránka
    je na fyzickém archu vždy centrovaná, okraje (1+1 mm) se nevytisknou.

    Štítky se počítají ve fyzických souřadnicích; do PDF se posunou o offset.
    """

    # Fyzický arch (pravítko na papíře)
    page_width_mm: float = 217.0
    page_height_mm: float = 304.0

    # Co nastavíte v ovladači / co má PDF (max. šířka Phaseru ≈ 215,9 mm)
    print_width_mm: float = 215.0
    print_height_mm: float = 304.0

    label_width_mm: float = 70.0
    label_height_mm: float = 36.0
    rows: int = 8
    cols: int = 3

    # Nepotisknutelný okraj uvnitř tiskové stránky (od kraje 215mm stránky)
    printable_margin_left_mm: float = DEFAULT_PRINTABLE_MARGIN_MM
    printable_margin_right_mm: float = DEFAULT_PRINTABLE_MARGIN_MM
    printable_margin_top_mm: float = DEFAULT_PRINTABLE_MARGIN_MM
    printable_margin_bottom_mm: float = DEFAULT_PRINTABLE_MARGIN_MM

    # Vnější okraj mřížky od kraje FYZICKÉHO papíru (None = auto rovnoměrně)
    outer_margin_x_mm: float | None = None
    outer_margin_y_mm: float | None = None

    # Jemné doladění posunu tisku (mm). Kladné X = doprava na papíře.
    nudge_x_mm: float = 0.0
    nudge_y_mm: float = 0.0

    def print_offset_mm(self) -> tuple[float, float]:
        """
        Posun levého horního rohu tiskové stránky vůči fyzickému archu.
        Centrovaně: (217-215)/2 = 1 mm zleva i zprava.
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
        = tisková stránka (centrovaná) minus vnitřní printable margins.
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

    def fit_warnings(self) -> list[str]:
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

        if abs(off_x) > 0.05 or abs(off_y) > 0.05:
            warnings.append(
                f"Tisková stránka {self.print_width_mm:.0f}×{self.print_height_mm:.0f} mm "
                f"je na archu {self.page_width_mm:.0f}×{self.page_height_mm:.0f} mm "
                f"centrovaná (přesah {off_x:.2f} / {off_y:.2f} mm na každé straně) — "
                f"tyto okraje se nevytisknou."
            )

        if gx < -0.05 or gy < -0.05:
            warnings.append(
                f"Štítky se nevejdou při vnějších okrajích {ox:.1f}/{oy:.1f} mm "
                f"(mezery {gx:.2f}/{gy:.2f} mm)."
            )
        elif gx < 0.5 or gy < 0.5:
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
                "Mřížka štítků zasahuje mimo vnitřní tisknutelnou oblast "
                "(tisková stránka minus tisknutelná hranice). "
                "Text u krajních štítků může být oříznutý — doladíte nudge / okraje."
            )

        return warnings

    def summary_text(self) -> str:
        ox, oy = self.resolved_outer_margins()
        gx, gy = self.gap_x_mm(), self.gap_y_mm()
        off_x, off_y = self.print_offset_mm()
        return (
            f"Fyzický arch: {self.page_width_mm:.0f}×{self.page_height_mm:.0f} mm\n"
            f"Tisková stránka: {self.print_width_mm:.0f}×{self.print_height_mm:.0f} mm "
            f"(offset {off_x:.2f}/{off_y:.2f} mm)\n"
            f"Vnější okraje: {ox:.2f} / {oy:.2f} mm · mezery {gx:.2f} / {gy:.2f} mm\n"
            f"Nudge X/Y: {self.nudge_x_mm:+.2f} / {self.nudge_y_mm:+.2f} mm"
        )


def parse_cell(token: str) -> tuple[int, int]:
    """'A1' -> (0, 0), 'H3' -> (7, 2). Písmeno = řádek, číslo = sloupec."""
    token = token.strip().upper()
    if len(token) < 2:
        raise ValueError(f"Neplatná pozice: {token!r}")
    row_letter = token[0]
    col_part = token[1:]
    if row_letter not in ROWS:
        raise ValueError(f"Řádek musí být A–H, dostáno: {row_letter!r}")
    if not col_part.isdigit():
        raise ValueError(f"Sloupec musí být číslo 1–{COLS}, dostáno: {col_part!r}")
    col = int(col_part)
    if not (1 <= col <= COLS):
        raise ValueError(f"Sloupec musí být 1–{COLS}, dostáno: {col}")
    return ROWS.index(row_letter), col - 1


def parse_range(spec: str) -> list[tuple[int, int]]:
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
            r1, c1 = parse_cell(a)
            r2, c2 = parse_cell(b)
            for r in range(min(r1, r2), max(r1, r2) + 1):
                for c in range(min(c1, c2), max(c1, c2) + 1):
                    cells.add((r, c))
        else:
            cells.add(parse_cell(part))

    return sorted(cells)


def cell_name(row: int, col: int) -> str:
    return f"{ROWS[row]}{col + 1}"
