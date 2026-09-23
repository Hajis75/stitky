"""Vykreslení archu štítků do PDF (přesné mm)."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from layout import SheetLayout, cell_name

# ReportLab default fonts don't cover Czech diacritics well for Helvetica.
# Prefer DejaVu if available on the system.
_FONT_REGISTERED = False
_FONT_NAME = "Helvetica"


def _ensure_font() -> str:
    global _FONT_REGISTERED, _FONT_NAME
    if _FONT_REGISTERED:
        return _FONT_NAME
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            try:
                pdfmetrics.registerFont(TTFont("LabelFont", path))
                _FONT_NAME = "LabelFont"
                break
            except Exception:
                continue
    _FONT_REGISTERED = True
    return _FONT_NAME


@dataclass
class LabelContent:
    text: str = ""
    image_path: str | None = None
    mode: str = "text"  # text | text_image | image
    font_size_pt: float = 11.0
    padding_mm: float = 2.0
    image_max_ratio: float = 0.45  # podíl výšky štítku pro obrázek u text+obrázek


@dataclass
class RenderOptions:
    show_outlines: bool = False
    show_cell_names: bool = False
    show_printable_area: bool = False


def _wrap_lines(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        words = paragraph.split(" ")
        current = ""
        for word in words:
            trial = word if not current else f"{current} {word}"
            if pdfmetrics.stringWidth(trial, font_name, font_size) <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                # příliš dlouhé slovo — zalom po znacích
                if pdfmetrics.stringWidth(word, font_name, font_size) > max_width:
                    chunk = ""
                    for ch in word:
                        t2 = chunk + ch
                        if pdfmetrics.stringWidth(t2, font_name, font_size) <= max_width:
                            chunk = t2
                        else:
                            if chunk:
                                lines.append(chunk)
                            chunk = ch
                    current = chunk
                else:
                    current = word
        if current or paragraph == "":
            lines.append(current)
    return lines


def text_fits(
    text: str,
    label_w_mm: float,
    label_h_mm: float,
    font_size_pt: float,
    padding_mm: float = 2.0,
    reserved_image_h_mm: float = 0.0,
) -> tuple[bool, list[str], float]:
    """Vrátí (vejde_se, řádky, potřebná_výška_mm)."""
    font = _ensure_font()
    max_w = (label_w_mm - 2 * padding_mm) * mm
    if max_w <= 0:
        return False, [], 0.0
    lines = _wrap_lines(text, font, font_size_pt, max_w)
    line_h = font_size_pt * 1.25
    text_h_pt = len(lines) * line_h if lines else 0
    text_h_mm = text_h_pt * 25.4 / 72.0
    usable_h = label_h_mm - 2 * padding_mm - reserved_image_h_mm
    return text_h_mm <= usable_h + 0.05, lines, text_h_mm


def max_fitting_font_size(
    text: str,
    label_w_mm: float,
    label_h_mm: float,
    padding_mm: float = 2.0,
    reserved_image_h_mm: float = 0.0,
    min_pt: float = 6.0,
    max_pt: float = 28.0,
) -> float:
    lo, hi = min_pt, max_pt
    best = min_pt
    for _ in range(24):
        mid = (lo + hi) / 2
        ok, _, _ = text_fits(
            text, label_w_mm, label_h_mm, mid, padding_mm, reserved_image_h_mm
        )
        if ok:
            best = mid
            lo = mid
        else:
            hi = mid
    return round(best, 1)


def render_sheet_pdf(
    layout: SheetLayout,
    positions: list[tuple[int, int]],
    content: LabelContent,
    output: str | Path | BytesIO,
    options: RenderOptions | None = None,
) -> None:
    options = options or RenderOptions()
    font = _ensure_font()
    # PDF = tisková stránka (např. 215×304), ne fyzický arch (217×304)
    page_w = layout.print_width_mm * mm
    page_h = layout.print_height_mm * mm
    if isinstance(output, Path):
        output = str(output)
    c = canvas.Canvas(output, pagesize=(page_w, page_h))

    if options.show_printable_area:
        # V tiskových souřadnicích: okraje od kraje tiskové stránky
        px = layout.printable_margin_left_mm
        py = layout.printable_margin_top_mm
        pw = (
            layout.print_width_mm
            - layout.printable_margin_left_mm
            - layout.printable_margin_right_mm
        )
        ph = (
            layout.print_height_mm
            - layout.printable_margin_top_mm
            - layout.printable_margin_bottom_mm
        )
        y = page_h - (py + ph) * mm
        c.setStrokeColorRGB(0.85, 0.35, 0.15)
        c.setDash(3, 2)
        c.setLineWidth(0.6)
        c.rect(px * mm, y, pw * mm, ph * mm, stroke=1, fill=0)
        c.setDash()
        c.setFillColorRGB(0.85, 0.35, 0.15)
        c.setFont(font, 7)
        c.drawString(px * mm + 2, y + ph * mm - 9, "tisknutelná oblast")

    if options.show_outlines:
        for r in range(layout.rows):
            for col in range(layout.cols):
                x_mm, y_top_mm, w_mm, h_mm = layout.label_rect_print_mm(r, col)
                y = page_h - (y_top_mm + h_mm) * mm
                c.setStrokeColorRGB(0.75, 0.75, 0.75)
                c.setDash(1, 2)
                c.rect(x_mm * mm, y, w_mm * mm, h_mm * mm, stroke=1, fill=0)
                c.setDash()
                if options.show_cell_names:
                    c.setFillColorRGB(0.7, 0.7, 0.7)
                    c.setFont(font, 7)
                    c.drawString(x_mm * mm + 2, y + h_mm * mm - 10, cell_name(r, col))

    for row, col in positions:
        _draw_label(c, layout, row, col, content, font, page_h)

    c.save()


def _draw_label(
    c: canvas.Canvas,
    layout: SheetLayout,
    row: int,
    col: int,
    content: LabelContent,
    font: str,
    page_h,
) -> None:
    x_mm, y_top_mm, w_mm, h_mm = layout.label_rect_print_mm(row, col)
    pad = content.padding_mm
    inner_x = (x_mm + pad) * mm
    inner_w = (w_mm - 2 * pad) * mm
    inner_h_mm = h_mm - 2 * pad
    y_bottom = page_h - (y_top_mm + h_mm) * mm
    inner_y = y_bottom + pad * mm

    mode = content.mode
    has_text = mode in ("text", "text_image") and content.text.strip()
    has_image = mode in ("image", "text_image") and content.image_path

    image_h_mm = 0.0
    if has_image and mode == "text_image":
        image_h_mm = h_mm * content.image_max_ratio
    elif has_image and mode == "image":
        image_h_mm = inner_h_mm

    if has_image:
        _draw_image(
            c,
            content.image_path,
            inner_x,
            inner_y + (inner_h_mm - image_h_mm) * mm if mode == "text_image" else inner_y,
            inner_w,
            image_h_mm * mm,
        )

    if has_text:
        reserved = image_h_mm + (1.0 if has_image and mode == "text_image" else 0.0)
        ok, lines, _ = text_fits(
            content.text, w_mm, h_mm, content.font_size_pt, pad, reserved
        )
        if not ok:
            # nouzově zmenši font, ať se nic neořízne
            size = max_fitting_font_size(content.text, w_mm, h_mm, pad, reserved)
            _, lines, _ = text_fits(content.text, w_mm, h_mm, size, pad, reserved)
        else:
            size = content.font_size_pt

        c.setFillColorRGB(0, 0, 0)
        c.setFont(font, size)
        line_h = size * 1.25
        text_block_h = len(lines) * line_h
        # text nahoře v textové oblasti (pod obrázkem u text_image je obrázek nahoře)
        if mode == "text_image" and has_image:
            top_of_text = inner_y + (inner_h_mm - image_h_mm - 1.0) * mm
        else:
            top_of_text = inner_y + inner_h_mm * mm
        # vertikálně vycentrovat text v dostupné oblasti
        text_area_h = (
            (inner_h_mm - image_h_mm - 1.0) * mm
            if mode == "text_image" and has_image
            else inner_h_mm * mm
        )
        start_y = top_of_text - (text_area_h - text_block_h) / 2 - size
        for i, line in enumerate(lines):
            c.drawCentredString(
                inner_x + inner_w / 2,
                start_y - i * line_h,
                line,
            )


def _draw_image(c: canvas.Canvas, path: str, x, y, max_w, max_h) -> None:
    try:
        img = ImageReader(path)
        iw, ih = img.getSize()
        if iw <= 0 or ih <= 0:
            return
        scale = min(max_w / iw, max_h / ih)
        dw, dh = iw * scale, ih * scale
        c.drawImage(
            img,
            x + (max_w - dw) / 2,
            y + (max_h - dh) / 2,
            width=dw,
            height=dh,
            preserveAspectRatio=True,
            mask="auto",
        )
    except Exception:
        c.setStrokeColorRGB(0.8, 0.2, 0.2)
        c.rect(x, y, max_w, max_h, stroke=1, fill=0)
