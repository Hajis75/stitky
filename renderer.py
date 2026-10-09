"""Vykreslení archu štítků do PDF (přesné mm)."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from reportlab.lib.colors import HexColor, black
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from layout import SheetLayout, cell_name

# ReportLab default fonts don't cover Czech diacritics well for Helvetica.
# Prefer Arial / DejaVu if available (regular + bold + italic).
_FONTS_READY = False
_FONT_FAMILY: dict[str, str] = {
    "regular": "Helvetica",
    "bold": "Helvetica-Bold",
    "italic": "Helvetica-Oblique",
    "bold_italic": "Helvetica-BoldOblique",
}


def _try_register(name: str, path: str) -> bool:
    if not Path(path).is_file():
        return False
    try:
        pdfmetrics.registerFont(TTFont(name, path))
        return True
    except Exception:
        return False


def _ensure_fonts() -> None:
    global _FONTS_READY, _FONT_FAMILY
    if _FONTS_READY:
        return

    families = [
        {
            "regular": ("LabelFont", "C:/Windows/Fonts/arial.ttf"),
            "bold": ("LabelFont-Bold", "C:/Windows/Fonts/arialbd.ttf"),
            "italic": ("LabelFont-Italic", "C:/Windows/Fonts/ariali.ttf"),
            "bold_italic": ("LabelFont-BoldItalic", "C:/Windows/Fonts/arialbi.ttf"),
        },
        {
            "regular": ("LabelFont", "C:/Windows/Fonts/calibri.ttf"),
            "bold": ("LabelFont-Bold", "C:/Windows/Fonts/calibrib.ttf"),
            "italic": ("LabelFont-Italic", "C:/Windows/Fonts/calibrii.ttf"),
            "bold_italic": ("LabelFont-BoldItalic", "C:/Windows/Fonts/calibriz.ttf"),
        },
        {
            "regular": ("LabelFont", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            "bold": ("LabelFont-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            "italic": (
                "LabelFont-Italic",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
            ),
            "bold_italic": (
                "LabelFont-BoldItalic",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
            ),
        },
    ]

    for family in families:
        registered: dict[str, str] = {}
        ok = True
        for key, (name, path) in family.items():
            if _try_register(name, path):
                registered[key] = name
            else:
                ok = False
                break
        if ok and len(registered) == 4:
            _FONT_FAMILY = registered
            break

    _FONTS_READY = True


def font_name(*, bold: bool = False, italic: bool = False) -> str:
    _ensure_fonts()
    if bold and italic:
        return _FONT_FAMILY["bold_italic"]
    if bold:
        return _FONT_FAMILY["bold"]
    if italic:
        return _FONT_FAMILY["italic"]
    return _FONT_FAMILY["regular"]


def _ensure_font() -> str:
    """Zpětná kompatibilita — běžný řez."""
    return font_name()


def parse_color(value: str | None):
    """Vrátí reportlab Color z #RRGGBB; při chybě černá."""
    if not value:
        return black
    s = value.strip()
    if not s.startswith("#"):
        s = "#" + s
    try:
        return HexColor(s)
    except Exception:
        return black


from richtext import (
    TextRun,
    line_height_pt,
    line_width,
    normalize_runs,
    rich_block_height_mm,
    runs_from_plain,
    runs_to_plain,
)


@dataclass
class LabelContent:
    text: str = ""
    image_path: str | None = None
    mode: str = "text"  # text | text_image | image
    font_size_pt: float = 11.0  # výchozí / fallback velikost
    padding_mm: float = 2.0
    image_max_ratio: float = 0.45
    align: str = "left"  # left | center | right
    bold: bool = False  # legacy (celý text)
    italic: bool = False
    underline: bool = False
    color: str = "#000000"
    runs: list[TextRun] | None = None  # rich-text běhy; pokud None → legacy

    def resolved_runs(self) -> list[TextRun]:
        if self.runs:
            return normalize_runs(self.runs, self.font_size_pt)
        return runs_from_plain(
            self.text,
            bold=self.bold,
            italic=self.italic,
            underline=self.underline,
            color=self.color,
            size=self.font_size_pt,
        )



@dataclass
class RenderOptions:
    show_outlines: bool = False
    show_cell_names: bool = False
    show_printable_area: bool = False


def _wrap_lines(text: str, font_name_str: str, font_size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        words = paragraph.split(" ")
        current = ""
        for word in words:
            trial = word if not current else f"{current} {word}"
            if pdfmetrics.stringWidth(trial, font_name_str, font_size) <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                # příliš dlouhé slovo — zalom po znacích
                if pdfmetrics.stringWidth(word, font_name_str, font_size) > max_width:
                    chunk = ""
                    for ch in word:
                        t2 = chunk + ch
                        if pdfmetrics.stringWidth(t2, font_name_str, font_size) <= max_width:
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
    *,
    bold: bool = False,
    italic: bool = False,
) -> tuple[bool, list[str], float]:
    """Vrátí (vejde_se, řádky, potřebná_výška_mm)."""
    fname = font_name(bold=bold, italic=italic)
    max_w = (label_w_mm - 2 * padding_mm) * mm
    if max_w <= 0:
        return False, [], 0.0
    lines = _wrap_lines(text, fname, font_size_pt, max_w)
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
    *,
    bold: bool = False,
    italic: bool = False,
) -> float:
    lo, hi = min_pt, max_pt
    best = min_pt
    for _ in range(24):
        mid = (lo + hi) / 2
        ok, _, _ = text_fits(
            text,
            label_w_mm,
            label_h_mm,
            mid,
            padding_mm,
            reserved_image_h_mm,
            bold=bold,
            italic=italic,
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
    content: LabelContent | dict[tuple[int, int], LabelContent],
    output: str | Path | BytesIO,
    options: RenderOptions | None = None,
) -> None:
    options = options or RenderOptions()
    font = font_name()
    # PDF = tisková stránka (např. 215×304), ne fyzický arch (217×304)
    page_w = layout.print_width_mm * mm
    page_h = layout.print_height_mm * mm
    if isinstance(output, Path):
        output = str(output)
    c = canvas.Canvas(output, pagesize=(page_w, page_h))
    if layout.rotate_print_180:
        # Podavač tiskne od fyzického spodku → optický A1 by jinak vyšel dole.
        c.translate(page_w, page_h)
        c.rotate(180)

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
        if isinstance(content, dict):
            item = content.get((row, col))
            if item is None:
                continue
        else:
            item = content
        _draw_label(c, layout, row, col, item, page_h)

    c.save()


def _draw_rich_line(
    c: canvas.Canvas,
    line: list[TextRun],
    x_left,
    x_right,
    baseline_y,
    *,
    align: str,
) -> None:
    total_w = line_width(line, font_name)
    if align == "right":
        x = x_right - total_w
    elif align == "center":
        x = (x_left + x_right - total_w) / 2
    else:
        x = x_left
    for run in line:
        if not run.text:
            continue
        size = float(run.size or 11.0)
        fname = font_name(bold=run.bold, italic=run.italic)
        color = parse_color(run.color)
        c.setFillColor(color)
        c.setFont(fname, size)
        c.drawString(x, baseline_y, run.text)
        w = pdfmetrics.stringWidth(run.text, fname, size)
        if run.underline and run.text.strip():
            c.setStrokeColor(color)
            c.setLineWidth(max(0.6, size * 0.06))
            c.line(x, baseline_y - 1.2, x + w, baseline_y - 1.2)
        x += w


def _draw_label(
    c: canvas.Canvas,
    layout: SheetLayout,
    row: int,
    col: int,
    content: LabelContent,
    page_h,
) -> None:
    # Obsah jen v průniku štítek ∩ tisknutelná zóna tiskárny
    x_mm, y_top_mm, w_mm, h_mm = layout.label_content_rect_print_mm(row, col)
    pad = content.padding_mm
    inner_x = (x_mm + pad) * mm
    inner_w = (w_mm - 2 * pad) * mm
    inner_h_mm = h_mm - 2 * pad
    y_bottom = page_h - (y_top_mm + h_mm) * mm
    inner_y = y_bottom + pad * mm

    mode = content.mode
    runs = content.resolved_runs()
    plain = runs_to_plain(runs)
    has_text = mode in ("text", "text_image") and plain.strip()
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
        usable_h = h_mm - 2 * pad - reserved
        lines, need_mm = rich_block_height_mm(runs, w_mm, pad, font_name)

        # nouzově zmenši všechny velikosti proporcionálně, když se nevejde
        if need_mm > usable_h + 0.05 and need_mm > 0:
            scale = max(0.35, usable_h / need_mm)
            runs = [
                TextRun(
                    r.text,
                    r.bold,
                    r.italic,
                    r.underline,
                    r.color,
                    max(6.0, round(float(r.size) * scale, 1)),
                )
                for r in runs
            ]
            lines, need_mm = rich_block_height_mm(runs, w_mm, pad, font_name)

        align = content.align if content.align in ("left", "center", "right") else "left"
        text_block_h = need_mm * mm
        if mode == "text_image" and has_image:
            top_of_text = inner_y + (inner_h_mm - image_h_mm - 1.0) * mm
            text_area_h = (inner_h_mm - image_h_mm - 1.0) * mm
        else:
            top_of_text = inner_y + inner_h_mm * mm
            text_area_h = inner_h_mm * mm

        # baseline prvního řádku
        first_size = max((float(r.size) for r in lines[0]), default=11.0) if lines else 11.0
        y = top_of_text - (text_area_h - text_block_h) / 2 - first_size
        x_right = inner_x + inner_w
        for line in lines:
            _draw_rich_line(c, line, inner_x, x_right, y, align=align)
            y -= line_height_pt(line)

def _is_svg_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in (".svg", ".svgz")


def _load_svg_drawing(path: str | Path):
    from svglib.svglib import svg2rlg

    drawing = svg2rlg(str(path))
    if drawing is None:
        raise ValueError(f"SVG se nepodařilo načíst: {path}")
    return drawing


def _scale_drawing_to_fit(drawing, max_w: float, max_h: float):
    """Škáluje drawing in-place do max_w × max_h; vrací (dw, dh)."""
    iw = float(drawing.width or 1.0)
    ih = float(drawing.height or 1.0)
    if iw <= 0 or ih <= 0:
        return max_w, max_h
    scale = min(max_w / iw, max_h / ih)
    drawing.width = iw * scale
    drawing.height = ih * scale
    drawing.scale(scale, scale)
    return drawing.width, drawing.height


_SVG_RASTER_CACHE: dict[tuple, object] = {}
_SVG_RASTER_CACHE_MAX = 64


def open_label_image(path: str | Path, *, max_px: int | None = None):
    """
    Načte rastr nebo SVG jako PIL RGBA.
    max_px = delší strana (pro náhled); None = nativní / po škálování SVG.
    """
    from PIL import Image as PILImage

    path = Path(path)
    if _is_svg_path(path):
        from reportlab.graphics import renderPM

        px = int(max_px) if max_px else 0
        try:
            key = (str(path.resolve()), path.stat().st_mtime_ns, px)
        except OSError:
            key = None
        if key is not None and key in _SVG_RASTER_CACHE:
            return _SVG_RASTER_CACHE[key].copy()
        drawing = _load_svg_drawing(path)
        if px > 0:
            _scale_drawing_to_fit(drawing, float(px), float(px))
        im = renderPM.drawToPIL(drawing).convert("RGBA")
        if key is not None:
            if len(_SVG_RASTER_CACHE) >= _SVG_RASTER_CACHE_MAX:
                _SVG_RASTER_CACHE.pop(next(iter(_SVG_RASTER_CACHE)))
            _SVG_RASTER_CACHE[key] = im.copy()
        return im

    im = PILImage.open(path).convert("RGBA")
    if max_px is not None and max_px > 0:
        w, h = im.size
        longest = max(w, h)
        if longest > max_px:
            scale = max_px / longest
            im = im.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                PILImage.Resampling.LANCZOS,
            )
    return im


def _draw_image(c: canvas.Canvas, path: str, x, y, max_w, max_h) -> None:
    try:
        if _is_svg_path(path):
            from reportlab.graphics import renderPDF

            drawing = _load_svg_drawing(path)
            dw, dh = _scale_drawing_to_fit(drawing, max_w, max_h)
            renderPDF.draw(drawing, c, x + (max_w - dw) / 2, y + (max_h - dh) / 2)
            return

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


def render_calibration_pdf(
    layout: SheetLayout,
    output: str | Path | BytesIO,
) -> None:
    """
    Kalibrační arch (vše červené):
    - plný rámeček = štítek 70×36
    - čárkovaný = vnitřní obsah (inset)
    - křížek = střed obsahu
    """
    font = font_name()
    page_w = layout.print_width_mm * mm
    page_h = layout.print_height_mm * mm
    if isinstance(output, Path):
        output = str(output)
    c = canvas.Canvas(output, pagesize=(page_w, page_h))
    if layout.rotate_print_180:
        c.translate(page_w, page_h)
        c.rotate(180)

    red = (0.85, 0.05, 0.05)
    off_x, off_y = layout.print_offset_mm()
    # Obrys fyzického archu na tiskové stránce (vystředěný)
    phys_x = -off_x * mm
    phys_y = page_h - (-off_y + layout.page_height_mm) * mm
    c.setStrokeColorRGB(0.75, 0.75, 0.75)
    c.setDash(1, 2)
    c.setLineWidth(0.5)
    c.rect(
        phys_x,
        phys_y,
        layout.page_width_mm * mm,
        layout.page_height_mm * mm,
        stroke=1,
        fill=0,
    )
    c.setDash()

    span_x = layout.pitch_x_mm() * max(layout.cols - 1, 0)
    span_y = layout.pitch_y_mm() * max(layout.rows - 1, 0)
    last_col = layout.cols
    last_row = cell_name(layout.rows - 1, 0)[0] if layout.rows else "?"
    ml, mr, mt, mb = layout.margins_lrtb_mm()
    # Text dole — nahoře by překrýval A1 při malých okrajích
    c.setFillColorRGB(*red)
    c.setFont(font, 7.5)
    c.drawString(
        8,
        14,
        f"KALIBRACE — štítek {layout.label_width_mm:.0f}×{layout.label_height_mm:.0f} mm | "
        f"arch {layout.page_width_mm:.0f}×{layout.page_height_mm:.0f} vystředěn na "
        f"tisk {layout.print_width_mm:.0f}×{layout.print_height_mm:.0f}",
    )
    c.drawString(
        8,
        4,
        f"Středy A1→A{last_col}={span_x:.1f} A1→{last_row}1={span_y:.1f} | "
        f"mezery {layout.gap_x_mm():.2f}/{layout.gap_y_mm():.2f} | "
        f"okraje L/P/H/D {ml:.1f}/{mr:.1f}/{mt:.1f}/{mb:.1f}",
    )

    for r in range(layout.rows):
        for col in range(layout.cols):
            x_mm, y_top_mm, w_mm, h_mm = layout.label_rect_print_mm(r, col)
            x = x_mm * mm
            w = w_mm * mm
            h = h_mm * mm
            y = page_h - (y_top_mm + h_mm) * mm

            # vnější = štítek (plná čára)
            c.setStrokeColorRGB(*red)
            c.setDash()
            c.setLineWidth(0.8)
            c.rect(x, y, w, h, stroke=1, fill=0)

            cx_mm, cy_top_mm, cw_mm, ch_mm = layout.label_content_rect_print_mm(r, col)
            cx = cx_mm * mm
            cw = cw_mm * mm
            ch = ch_mm * mm
            cy = page_h - (cy_top_mm + ch_mm) * mm

            # vnitřní = obsah (čárkovaná)
            c.setStrokeColorRGB(*red)
            c.setDash(3, 2)
            c.setLineWidth(0.7)
            c.rect(cx, cy, cw, ch, stroke=1, fill=0)
            c.setDash()

            mid_x = cx + cw / 2
            mid_y = cy + ch / 2
            arm = min(cw, ch) * 0.22
            c.setStrokeColorRGB(*red)
            c.setLineWidth(0.9)
            c.line(mid_x - arm, mid_y, mid_x + arm, mid_y)
            c.line(mid_x, mid_y - arm, mid_x, mid_y + arm)
            c.setFillColorRGB(*red)
            c.circle(mid_x, mid_y, 1.2, stroke=0, fill=1)

            c.setFillColorRGB(*red)
            c.setFont(font, 9)
            c.drawString(cx + 3, cy + ch - 11, cell_name(r, col))
            if r == 0 and col == 0:
                c.setFont(font, 7)
                c.drawString(
                    x + 3,
                    y + 4,
                    f"{layout.label_width_mm:.0f}×{layout.label_height_mm:.0f} mm",
                )

    c.save()


# --- Bitmapový render (přímý tisk přes GDI, bez PDF) ---

_MM_PER_INCH = 25.4
_PIL_FONT_CACHE: dict[tuple[str, int], object] = {}


def _mm_to_px(mm_val: float, dpi: float) -> float:
    return mm_val / _MM_PER_INCH * dpi


def _pt_to_px(pt: float, dpi: float) -> float:
    return pt / 72.0 * dpi


def _pil_font(*, bold: bool = False, italic: bool = False, size_pt: float = 11.0, dpi: float = 300.0):
    from PIL import ImageFont

    px = max(6, int(round(_pt_to_px(size_pt, dpi))))
    paths = []
    if bold and italic:
        paths = [
            "C:/Windows/Fonts/arialbi.ttf",
            "C:/Windows/Fonts/calibri.ttf",
        ]
    elif bold:
        paths = ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/calibrib.ttf"]
    elif italic:
        paths = ["C:/Windows/Fonts/ariali.ttf", "C:/Windows/Fonts/calibrii.ttf"]
    else:
        paths = ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/calibri.ttf"]
    key = (paths[0] if paths else "default", px, bold, italic)
    cached = _PIL_FONT_CACHE.get(key)  # type: ignore[arg-type]
    if cached is not None:
        return cached
    for p in paths:
        try:
            if Path(p).is_file():
                f = ImageFont.truetype(p, px)
                _PIL_FONT_CACHE[key] = f  # type: ignore[index]
                return f
        except Exception:
            continue
    f = ImageFont.load_default()
    _PIL_FONT_CACHE[key] = f  # type: ignore[index]
    return f


def _hex_rgb(value: str | None) -> tuple[int, int, int]:
    if not value:
        return (0, 0, 0)
    s = value.strip().lstrip("#")
    if len(s) != 6:
        return (0, 0, 0)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except Exception:
        return (0, 0, 0)


def _dashed_rect(draw, box, fill, *, dash=(6, 4), width: int = 2) -> None:
    """Jednoduchý čárkovaný obdélník (x0,y0,x1,y1)."""
    x0, y0, x1, y1 = box
    segs = [
        ((x0, y0), (x1, y0)),
        ((x1, y0), (x1, y1)),
        ((x1, y1), (x0, y1)),
        ((x0, y1), (x0, y0)),
    ]
    on, off = dash
    for (ax, ay), (bx, by) in segs:
        length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        if length < 1:
            continue
        dx, dy = (bx - ax) / length, (by - ay) / length
        pos = 0.0
        draw_on = True
        while pos < length:
            step = on if draw_on else off
            end = min(pos + step, length)
            if draw_on:
                draw.line(
                    (
                        ax + dx * pos,
                        ay + dy * pos,
                        ax + dx * end,
                        ay + dy * end,
                    ),
                    fill=fill,
                    width=width,
                )
            pos = end
            draw_on = not draw_on


def render_sheet_image(
    layout: SheetLayout,
    positions: list[tuple[int, int]],
    content: LabelContent | dict[tuple[int, int], LabelContent],
    *,
    dpi: float = 300.0,
    options: RenderOptions | None = None,
    calibration: bool = False,
):
    """
    Vykreslí tiskovou stránku do PIL Image (RGB) — pro přímý GDI tisk bez PDF.
    Souřadnice: horní levý roh = (0,0), Y dolů (jako obrazovka).
    """
    from PIL import Image, ImageDraw

    options = options or RenderOptions()
    page_w_mm = layout.print_width_mm
    page_h_mm = layout.print_height_mm
    w_px = max(1, int(round(_mm_to_px(page_w_mm, dpi))))
    h_px = max(1, int(round(_mm_to_px(page_h_mm, dpi))))
    img = Image.new("RGB", (w_px, h_px), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    def to_xy(x_mm: float, y_mm: float) -> tuple[float, float]:
        return _mm_to_px(x_mm, dpi), _mm_to_px(y_mm, dpi)

    def to_box(x_mm: float, y_mm: float, w_mm: float, h_mm: float):
        x0, y0 = to_xy(x_mm, y_mm)
        return (x0, y0, x0 + _mm_to_px(w_mm, dpi), y0 + _mm_to_px(h_mm, dpi))

    if layout.rotate_print_180:
        # Vykreslíme normálně a na konci otočíme obrázek
        pass

    if options.show_printable_area and not calibration:
        pr = layout.printable_rect_print_mm()
        box = to_box(*pr)
        _dashed_rect(draw, box, (220, 90, 40), dash=(8, 5), width=2)

    if options.show_outlines and not calibration:
        for r in range(layout.rows):
            for col in range(layout.cols):
                box = to_box(*layout.label_rect_print_mm(r, col))
                _dashed_rect(draw, box, (190, 190, 190), dash=(4, 4), width=1)
                if options.show_cell_names:
                    font = _pil_font(size_pt=7, dpi=dpi)
                    draw.text((box[0] + 3, box[1] + 2), cell_name(r, col), fill=(180, 180, 180), font=font)

    if calibration:
        red = (220, 20, 20)
        header = _pil_font(size_pt=8, dpi=dpi)
        draw.text(
            (8, 6),
            f"KALIBRACE — ŠTÍTEK = {layout.label_width_mm:.0f}×{layout.label_height_mm:.0f} mm "
            f"(plný rámeček), ne rozteč {layout.pitch_x_mm():.2f}×{layout.pitch_y_mm():.2f}!",
            fill=red,
            font=header,
        )
        span_x = layout.pitch_x_mm() * max(layout.cols - 1, 0)
        span_y = layout.pitch_y_mm() * max(layout.rows - 1, 0)
        last_col = layout.cols
        last_row = cell_name(layout.rows - 1, 0)[0] if layout.rows else "?"
        ml, mr, mt, mb = layout.margins_lrtb_mm()
        draw.text(
            (8, 6 + int(_pt_to_px(10, dpi))),
            f"Středy A1→A{last_col}={span_x:.1f} A1→{last_row}1={span_y:.1f} | "
            f"mezery {layout.gap_x_mm():.2f}/{layout.gap_y_mm():.2f} | "
            f"okraje L/P/H/D {ml:.1f}/{mr:.1f}/{mt:.1f}/{mb:.1f}",
            fill=red,
            font=header,
        )
        for r in range(layout.rows):
            for col in range(layout.cols):
                box = to_box(*layout.label_rect_print_mm(r, col))
                draw.rectangle(box, outline=red, width=2)
                cbox = to_box(*layout.label_content_rect_print_mm(r, col))
                _dashed_rect(draw, cbox, red, dash=(6, 4), width=2)
                mx = (cbox[0] + cbox[2]) / 2
                my = (cbox[1] + cbox[3]) / 2
                arm = min(cbox[2] - cbox[0], cbox[3] - cbox[1]) * 0.22
                draw.line((mx - arm, my, mx + arm, my), fill=red, width=2)
                draw.line((mx, my - arm, mx, my + arm), fill=red, width=2)
                rdot = max(2, int(_mm_to_px(0.4, dpi)))
                draw.ellipse((mx - rdot, my - rdot, mx + rdot, my + rdot), fill=red)
                font = _pil_font(size_pt=9, dpi=dpi)
                draw.text((cbox[0] + 3, cbox[1] + 2), cell_name(r, col), fill=red, font=font)
                if r == 0 and col == 0:
                    small = _pil_font(size_pt=7, dpi=dpi)
                    draw.text(
                        (box[0] + 3, box[3] - _pt_to_px(9, dpi)),
                        f"{layout.label_width_mm:.0f}×{layout.label_height_mm:.0f} mm",
                        fill=red,
                        font=small,
                    )
    else:
        for row, col in positions:
            if isinstance(content, dict):
                item = content.get((row, col))
                if item is None:
                    continue
            else:
                item = content
            _draw_label_image(draw, img, layout, row, col, item, dpi)

    if layout.rotate_print_180:
        img = img.rotate(180, expand=False)

    return img


def _draw_label_image(draw, img, layout: SheetLayout, row: int, col: int, content: LabelContent, dpi: float) -> None:
    from PIL import Image as PILImage

    x_mm, y_mm, w_mm, h_mm = layout.label_content_rect_print_mm(row, col)
    pad = content.padding_mm
    ix = x_mm + pad
    iy = y_mm + pad
    iw = w_mm - 2 * pad
    ih = h_mm - 2 * pad
    if iw <= 0.5 or ih <= 0.5:
        return

    mode = content.mode
    runs = content.resolved_runs()
    plain = runs_to_plain(runs)
    has_text = mode in ("text", "text_image") and plain.strip()
    has_image = mode in ("image", "text_image") and content.image_path

    image_h_mm = 0.0
    if has_image and mode == "text_image":
        image_h_mm = h_mm * content.image_max_ratio
    elif has_image and mode == "image":
        image_h_mm = ih

    if has_image and content.image_path:
        try:
            max_w = _mm_to_px(iw, dpi)
            max_h = _mm_to_px(image_h_mm, dpi)
            if _is_svg_path(content.image_path):
                im = open_label_image(content.image_path, max_px=max(max_w, max_h))
                if im.width > max_w or im.height > max_h:
                    scale = min(max_w / im.width, max_h / im.height)
                    im = im.resize(
                        (max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                        PILImage.Resampling.LANCZOS,
                    )
            else:
                im = PILImage.open(content.image_path).convert("RGBA")
                scale = min(max_w / im.width, max_h / im.height)
                dw, dh = int(im.width * scale), int(im.height * scale)
                im = im.resize((max(1, dw), max(1, dh)), PILImage.Resampling.LANCZOS)
            if mode == "text_image":
                top_y = _mm_to_px(iy + ih - image_h_mm, dpi)
            else:
                top_y = _mm_to_px(iy, dpi)
            left_x = _mm_to_px(ix, dpi) + (max_w - im.width) / 2
            img.paste(im, (int(left_x), int(top_y + (max_h - im.height) / 2)), im)
        except Exception:
            box = (
                _mm_to_px(ix, dpi),
                _mm_to_px(iy, dpi),
                _mm_to_px(ix + iw, dpi),
                _mm_to_px(iy + image_h_mm, dpi),
            )
            draw.rectangle(box, outline=(200, 40, 40), width=2)

    if not has_text:
        return

    reserved = image_h_mm + (1.0 if has_image and mode == "text_image" else 0.0)
    usable_h = h_mm - 2 * pad - reserved
    lines, need_mm = rich_block_height_mm(runs, w_mm, pad, font_name)
    if need_mm > usable_h + 0.05 and need_mm > 0:
        scale = max(0.35, usable_h / need_mm)
        runs = [
            TextRun(
                r.text,
                r.bold,
                r.italic,
                r.underline,
                r.color,
                max(6.0, round(float(r.size) * scale, 1)),
            )
            for r in runs
        ]
        lines, need_mm = rich_block_height_mm(runs, w_mm, pad, font_name)

    align = content.align if content.align in ("left", "center", "right") else "left"
    if mode == "text_image" and has_image:
        text_top_mm = iy
        text_h_mm = ih - image_h_mm - 1.0
    else:
        text_top_mm = iy
        text_h_mm = ih

    # vertikální centrovaní bloku
    y_mm_cursor = text_top_mm + max(0.0, (text_h_mm - need_mm) / 2)
    x_left_px = _mm_to_px(ix, dpi)
    x_right_px = _mm_to_px(ix + iw, dpi)

    for line in lines:
        # šířka řádku v px přes reportlab metriku (pt → px)
        total_pt = line_width(line, font_name)  # reportlab body body
        total_px = total_pt / 72.0 * dpi
        if align == "right":
            x = x_right_px - total_px
        elif align == "center":
            x = (x_left_px + x_right_px - total_px) / 2
        else:
            x = x_left_px
        first_size = max((float(r.size) for r in line), default=11.0)
        # baseline ≈ top + font size
        baseline = _mm_to_px(y_mm_cursor, dpi) + _pt_to_px(first_size, dpi)
        for run in line:
            if not run.text:
                continue
            size = float(run.size or 11.0)
            fnt = _pil_font(bold=run.bold, italic=run.italic, size_pt=size, dpi=dpi)
            color = _hex_rgb(run.color)
            draw.text((x, baseline - _pt_to_px(size, dpi)), run.text, fill=color, font=fnt)
            # šířka runu
            run_w_px = pdfmetrics.stringWidth(run.text, font_name(bold=run.bold, italic=run.italic), size) / 72.0 * dpi
            if run.underline and run.text.strip():
                uy = baseline + 1
                draw.line((x, uy, x + run_w_px, uy), fill=color, width=max(1, int(size * 0.06)))
            x += run_w_px
        y_mm_cursor += line_height_pt(line) * 25.4 / 72.0


def render_calibration_image(layout: SheetLayout, *, dpi: float = 300.0):
    """Kalibrační bitmapa pro přímý tisk."""
    return render_sheet_image(
        layout,
        [],
        {},
        dpi=dpi,
        options=RenderOptions(),
        calibration=True,
    )
