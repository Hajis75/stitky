"""Rich-text běhy pro editor (tk.Text) a PDF — včetně velikosti písma po znacích."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from reportlab.pdfbase import pdfmetrics

DEFAULT_SIZE = 11.0


@dataclass
class TextRun:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: str = "#000000"
    size: float = DEFAULT_SIZE

    def style_key(self) -> tuple:
        return (
            self.bold,
            self.italic,
            self.underline,
            (self.color or "#000000").lower(),
            round(float(self.size or DEFAULT_SIZE), 1),
        )


def runs_to_plain(runs: list[TextRun] | None) -> str:
    if not runs:
        return ""
    return "".join(r.text for r in runs)


def runs_from_plain(
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    color: str = "#000000",
    size: float = DEFAULT_SIZE,
) -> list[TextRun]:
    if not text:
        return []
    return [
        TextRun(
            text=text,
            bold=bold,
            italic=italic,
            underline=underline,
            color=color or "#000000",
            size=float(size or DEFAULT_SIZE),
        )
    ]


def normalize_runs(raw: Any, default_size: float = DEFAULT_SIZE) -> list[TextRun]:
    """Z JSON / dictů udělá list TextRun; sloučí sousední se stejným stylem."""
    if not raw:
        return []
    out: list[TextRun] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, TextRun):
                run = TextRun(
                    text=item.text,
                    bold=item.bold,
                    italic=item.italic,
                    underline=item.underline,
                    color=item.color or "#000000",
                    size=float(item.size or default_size),
                )
            elif isinstance(item, dict):
                run = TextRun(
                    text=str(item.get("text") or ""),
                    bold=bool(item.get("bold", False)),
                    italic=bool(item.get("italic", False)),
                    underline=bool(item.get("underline", False)),
                    color=str(item.get("color") or "#000000"),
                    size=float(item.get("size") or default_size),
                )
            else:
                continue
            if not run.text:
                continue
            if out and out[-1].style_key() == run.style_key():
                out[-1].text += run.text
            else:
                out.append(run)
    return out


def runs_to_json(runs: list[TextRun]) -> list[dict]:
    return [asdict(r) for r in normalize_runs(runs)]


def max_run_size(runs: list[TextRun], fallback: float = DEFAULT_SIZE) -> float:
    if not runs:
        return fallback
    return max((float(r.size or fallback) for r in runs), default=fallback)


def _color_from_tags(tags: tuple[str, ...]) -> str:
    for t in tags:
        if t.startswith("fg_"):
            return "#" + t[3:]
    return "#000000"


def _size_from_tags(tags: tuple[str, ...], fallback: float) -> float:
    for t in tags:
        if t.startswith("sz_"):
            try:
                return float(t[3:].replace("_", "."))
            except ValueError:
                continue
    return fallback


def size_tag_name(size: float) -> str:
    # tk tag names: tečka → podtržítko
    return "sz_" + f"{float(size):.1f}".replace(".", "_")


def dump_text_runs(widget, default_size: float = DEFAULT_SIZE) -> list[TextRun]:
    """Přečte styly znak po znaku z tk.Text tagů."""
    plain = widget.get("1.0", "end-1c")
    if not plain:
        return []
    runs: list[TextRun] = []
    cur: TextRun | None = None
    for i, ch in enumerate(plain):
        idx = f"1.0+{i}c"
        tags = widget.tag_names(idx)
        style = TextRun(
            text=ch,
            bold="bold" in tags or "bold_italic" in tags,
            italic="italic" in tags or "bold_italic" in tags,
            underline="underline" in tags,
            color=_color_from_tags(tags),
            size=_size_from_tags(tags, default_size),
        )
        if cur and cur.style_key() == style.style_key():
            cur.text += ch
        else:
            if cur:
                runs.append(cur)
            cur = style
    if cur:
        runs.append(cur)
    return runs


def clear_format_tags(widget) -> None:
    for tag in list(widget.tag_names()):
        if tag in ("bold", "italic", "underline", "bold_italic") or tag.startswith(
            ("fg_", "sz_")
        ):
            try:
                widget.tag_remove(tag, "1.0", "end")
            except Exception:
                pass
            if tag.startswith(("fg_", "sz_")):
                try:
                    widget.tag_delete(tag)
                except Exception:
                    pass


def _font(size: int, *, bold: bool = False, italic: bool = False):
    import tkinter.font as tkfont

    kw: dict[str, Any] = {"family": "Segoe UI", "size": max(6, int(size))}
    if bold:
        kw["weight"] = "bold"
    if italic:
        kw["slant"] = "italic"
    return tkfont.Font(**kw)


def ensure_format_tags(widget, size: int = 12) -> None:
    widget.tag_configure("bold", font=_font(size, bold=True))
    widget.tag_configure("italic", font=_font(size, italic=True))
    widget.tag_configure("bold_italic", font=_font(size, bold=True, italic=True))
    widget.tag_configure("underline", underline=True)
    widget.configure(font=_font(size))


def _ensure_fg_tag(widget, color: str) -> str:
    c = (color or "#000000").strip()
    if not c.startswith("#"):
        c = "#" + c
    tag = "fg_" + c[1:].lower()
    if tag not in widget.tag_names():
        try:
            widget.tag_configure(tag, foreground=c)
        except Exception:
            widget.tag_configure(tag, foreground="#000000")
            return "fg_000000"
    return tag


def _ensure_size_tag(widget, size: float, *, bold: bool = False, italic: bool = False) -> str:
    """Tag velikosti nese i font (velikost); bold/italic řeší samostatné tagy s vyšší prioritou."""
    tag = size_tag_name(size)
    pt = max(6, int(round(float(size))))
    if tag not in widget.tag_names():
        widget.tag_configure(tag, font=_font(pt))
    # kombinované fonty pro konkrétní velikost
    bi = f"{tag}_bi"
    b = f"{tag}_b"
    i = f"{tag}_i"
    if b not in widget.tag_names():
        widget.tag_configure(b, font=_font(pt, bold=True))
    if i not in widget.tag_names():
        widget.tag_configure(i, font=_font(pt, italic=True))
    if bi not in widget.tag_names():
        widget.tag_configure(bi, font=_font(pt, bold=True, italic=True))
    return tag


def apply_runs_to_text(widget, runs: list[TextRun], *, default_size: float = DEFAULT_SIZE) -> None:
    """Nahradí obsah widgetu plain textem + tagy podle běhů."""
    ensure_format_tags(widget, int(round(default_size)))
    clear_format_tags(widget)
    widget.delete("1.0", "end")
    runs = normalize_runs(runs, default_size)
    if not runs:
        widget.edit_modified(False)
        return
    for run in runs:
        start = widget.index("end-1c")
        widget.insert("end", run.text)
        end = widget.index("end-1c")
        _apply_style_tags(widget, start, end, run)
    widget.edit_modified(False)


def _apply_style_tags(widget, start: str, end: str, run: TextRun) -> None:
    size = float(run.size or DEFAULT_SIZE)
    sz = _ensure_size_tag(widget, size)
    widget.tag_add(sz, start, end)
    # font podle řezu + velikosti (přepíše základní sz font)
    pt = max(6, int(round(size)))
    if run.bold and run.italic:
        tag = f"{sz}_bi"
        widget.tag_configure(tag, font=_font(pt, bold=True, italic=True))
        widget.tag_add(tag, start, end)
        widget.tag_add("bold", start, end)
        widget.tag_add("italic", start, end)
    elif run.bold:
        tag = f"{sz}_b"
        widget.tag_configure(tag, font=_font(pt, bold=True))
        widget.tag_add(tag, start, end)
        widget.tag_add("bold", start, end)
    elif run.italic:
        tag = f"{sz}_i"
        widget.tag_configure(tag, font=_font(pt, italic=True))
        widget.tag_add(tag, start, end)
        widget.tag_add("italic", start, end)
    if run.underline:
        widget.tag_add("underline", start, end)
    if run.color and run.color.lower() not in ("#000000", "black"):
        widget.tag_add(_ensure_fg_tag(widget, run.color), start, end)


def _range_has_tag(widget, tag: str, start: str, end: str) -> bool:
    try:
        if widget.compare(start, ">=", end):
            return False
    except Exception:
        return False
    idx = start
    while widget.compare(idx, "<", end):
        if tag not in widget.tag_names(idx):
            return False
        idx = widget.index(f"{idx}+1c")
    return True


def toggle_tag_on_range(widget, tag: str, start: str, end: str) -> bool:
    fully = _range_has_tag(widget, tag, start, end)
    if fully:
        widget.tag_remove(tag, start, end)
        # sundej i velikostní varianty řezu
        for t in list(widget.tag_names()):
            if t.endswith("_b") or t.endswith("_i") or t.endswith("_bi"):
                if tag == "bold" and (t.endswith("_b") or t.endswith("_bi")):
                    widget.tag_remove(t, start, end)
                if tag == "italic" and (t.endswith("_i") or t.endswith("_bi")):
                    widget.tag_remove(t, start, end)
        return False
    widget.tag_add(tag, start, end)
    _refresh_face_fonts_on_range(widget, start, end)
    return True


def _refresh_face_fonts_on_range(widget, start: str, end: str) -> None:
    """Po změně bold/italic znovu nastav font tag podle velikosti každého znaku."""
    idx = start
    while widget.compare(idx, "<", end):
        tags = widget.tag_names(idx)
        size = _size_from_tags(tags, DEFAULT_SIZE)
        bold = "bold" in tags or "bold_italic" in tags
        italic = "italic" in tags or "bold_italic" in tags
        sz = _ensure_size_tag(widget, size)
        nxt = widget.index(f"{idx}+1c")
        # sundej staré face tagy na tomto znaku
        for t in tags:
            if t.endswith("_b") or t.endswith("_i") or t.endswith("_bi"):
                widget.tag_remove(t, idx, nxt)
        pt = max(6, int(round(size)))
        if bold and italic:
            tag = f"{sz}_bi"
            widget.tag_configure(tag, font=_font(pt, bold=True, italic=True))
            widget.tag_add(tag, idx, nxt)
        elif bold:
            tag = f"{sz}_b"
            widget.tag_configure(tag, font=_font(pt, bold=True))
            widget.tag_add(tag, idx, nxt)
        elif italic:
            tag = f"{sz}_i"
            widget.tag_configure(tag, font=_font(pt, italic=True))
            widget.tag_add(tag, idx, nxt)
        idx = nxt


def apply_color_on_range(widget, color: str, start: str, end: str) -> None:
    idx = start
    seen: set[str] = set()
    while widget.compare(idx, "<", end):
        for t in widget.tag_names(idx):
            if t.startswith("fg_"):
                seen.add(t)
        idx = widget.index(f"{idx}+1c")
    for t in seen:
        widget.tag_remove(t, start, end)
    c = (color or "#000000").strip()
    if c.lower() in ("#000000", "black"):
        return
    widget.tag_add(_ensure_fg_tag(widget, c), start, end)


def apply_size_on_range(widget, size: float, start: str, end: str) -> None:
    size = float(size)
    idx = start
    seen: set[str] = set()
    while widget.compare(idx, "<", end):
        for t in widget.tag_names(idx):
            if t.startswith("sz_"):
                seen.add(t)
        idx = widget.index(f"{idx}+1c")
    for t in seen:
        widget.tag_remove(t, start, end)
    sz = _ensure_size_tag(widget, size)
    widget.tag_add(sz, start, end)
    _refresh_face_fonts_on_range(widget, start, end)


def style_at_index(widget, index: str = "insert", default_size: float = DEFAULT_SIZE) -> dict:
    tags = widget.tag_names(index)
    return {
        "bold": "bold" in tags or "bold_italic" in tags,
        "italic": "italic" in tags or "bold_italic" in tags,
        "underline": "underline" in tags,
        "color": _color_from_tags(tags),
        "size": _size_from_tags(tags, default_size),
    }


# --- PDF ---

FontNameFn = Callable[..., str]


def run_width(text: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(text, font, size)


def wrap_rich_runs(
    runs: list[TextRun],
    max_width: float,
    font_name_fn: FontNameFn,
) -> list[list[TextRun]]:
    """Zalomí rich běhy do řádků (každý běh má vlastní size). max_width v PDF bodech."""
    lines: list[list[TextRun]] = []
    cur_line: list[TextRun] = []
    cur_w = 0.0

    def flush_line() -> None:
        nonlocal cur_line, cur_w
        lines.append(cur_line)
        cur_line = []
        cur_w = 0.0

    def push(piece: TextRun) -> None:
        nonlocal cur_w
        if not piece.text:
            return
        if cur_line and cur_line[-1].style_key() == piece.style_key():
            cur_line[-1].text += piece.text
        else:
            cur_line.append(
                TextRun(
                    piece.text,
                    piece.bold,
                    piece.italic,
                    piece.underline,
                    piece.color,
                    piece.size,
                )
            )
        fname = font_name_fn(bold=piece.bold, italic=piece.italic)
        cur_w += run_width(piece.text, fname, float(piece.size))

    def add_piece(piece: TextRun) -> None:
        nonlocal cur_w
        if not piece.text:
            return
        fname = font_name_fn(bold=piece.bold, italic=piece.italic)
        size = float(piece.size)
        w = run_width(piece.text, fname, size)
        if cur_line and cur_w + w > max_width + 0.01 and piece.text != " ":
            _append_fitting(piece, fname, size)
        else:
            push(piece)

    def _append_fitting(piece: TextRun, fname: str, size: float) -> None:
        nonlocal cur_w
        parts: list[str] = []
        buf = ""
        for ch in piece.text:
            if ch == " ":
                if buf:
                    parts.append(buf)
                    buf = ""
                parts.append(" ")
            else:
                buf += ch
        if buf:
            parts.append(buf)

        for part in parts:
            pw = run_width(part, fname, size)
            if cur_line and cur_w + pw > max_width + 0.01 and part != " ":
                flush_line()
            if pw > max_width and part.strip():
                chunk = ""
                for ch in part:
                    tw = run_width(chunk + ch, fname, size)
                    if chunk and tw > max_width + 0.01:
                        push(
                            TextRun(
                                chunk,
                                piece.bold,
                                piece.italic,
                                piece.underline,
                                piece.color,
                                piece.size,
                            )
                        )
                        flush_line()
                        chunk = ch
                    else:
                        chunk += ch
                if chunk:
                    push(
                        TextRun(
                            chunk,
                            piece.bold,
                            piece.italic,
                            piece.underline,
                            piece.color,
                            piece.size,
                        )
                    )
            else:
                push(
                    TextRun(
                        part,
                        piece.bold,
                        piece.italic,
                        piece.underline,
                        piece.color,
                        piece.size,
                    )
                )

    for run in normalize_runs(runs):
        chunks = run.text.split("\n")
        for i, chunk in enumerate(chunks):
            if i > 0:
                flush_line()
            add_piece(
                TextRun(chunk, run.bold, run.italic, run.underline, run.color, run.size)
            )

    if cur_line or not lines:
        flush_line()
    return lines


def line_width(line: list[TextRun], font_name_fn: FontNameFn) -> float:
    total = 0.0
    for run in line:
        fname = font_name_fn(bold=run.bold, italic=run.italic)
        total += run_width(run.text, fname, float(run.size))
    return total


def line_height_pt(line: list[TextRun], fallback: float = DEFAULT_SIZE) -> float:
    if not line:
        return fallback * 1.25
    return max(float(r.size or fallback) for r in line) * 1.25


def rich_block_height_mm(
    runs: list[TextRun],
    label_w_mm: float,
    padding_mm: float,
    font_name_fn: FontNameFn,
) -> tuple[list[list[TextRun]], float]:
    from reportlab.lib.units import mm

    max_w = (label_w_mm - 2 * padding_mm) * mm
    if max_w <= 0:
        return [], 0.0
    lines = wrap_rich_runs(runs, max_w, font_name_fn)
    h_pt = sum(line_height_pt(line) for line in lines)
    return lines, h_pt * 25.4 / 72.0
