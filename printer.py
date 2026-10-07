"""Přímý tisk na systémovou tiskárnu (GDI bitmapa) + legacy PDF tisk."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def list_printers() -> list[str]:
    """Seznam dostupných tiskáren (Windows / Linux)."""
    if sys.platform == "win32":
        try:
            import win32print  # type: ignore

            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            return [p[2] for p in win32print.EnumPrinters(flags)]
        except Exception:
            return []
    try:
        out = subprocess.check_output(["lpstat", "-a"], text=True, stderr=subprocess.DEVNULL)
        names = []
        for line in out.splitlines():
            parts = line.split()
            if parts:
                names.append(parts[0])
        return names
    except Exception:
        return []


def default_printer() -> str | None:
    if sys.platform == "win32":
        try:
            import win32print  # type: ignore

            return win32print.GetDefaultPrinter()
        except Exception:
            return None
    try:
        out = subprocess.check_output(
            ["lpstat", "-d"], text=True, stderr=subprocess.DEVNULL
        )
        if ":" in out:
            return out.split(":", 1)[1].strip() or None
    except Exception:
        return None
    return None


def print_bitmap(
    image,
    printer_name: str | None = None,
    *,
    page_width_mm: float = 215.0,
    page_height_mm: float = 304.0,
) -> None:
    """
    Odešle PIL Image přímo na tiskárnu přes Windows GDI (bez PDF).
    Na jiných platformách uloží PNG a použije lpr (fallback).
    """
    if sys.platform == "win32":
        _print_bitmap_windows(image, printer_name, page_width_mm, page_height_mm)
        return

    # Fallback mimo Windows: dočasný PNG + lpr
    fd, name = tempfile.mkstemp(prefix="stitky_", suffix=".png")
    os.close(fd)
    path = Path(name)
    try:
        image.save(path, format="PNG")
        if sys.platform == "darwin":
            cmd = ["lp", str(path)]
            if printer_name:
                cmd = ["lp", "-d", printer_name, str(path)]
        else:
            cmd = ["lpr", str(path)]
            if printer_name:
                cmd = ["lpr", "-P", printer_name, str(path)]
        subprocess.check_call(cmd)
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


def _apply_custom_page_devmode(
    printer_name: str,
    page_width_mm: float,
    page_height_mm: float,
):
    """
    Nastaví vlastní rozměr papíru v DEVMODE (0,1 mm).
    Phaser 6700 Tray 1: vodítka drží arch na středu dráhy — rozměr
    v ovladači musí odpovídat fyzickému archu, jinak vznikne L/R posun.
    """
    import win32con  # type: ignore
    import win32print  # type: ignore

    hprinter = win32print.OpenPrinter(printer_name)
    try:
        info = win32print.GetPrinter(hprinter, 2)
        devmode = info.get("pDevMode")
        if devmode is None:
            return None

        # DMPAPER_USER = 256 — vlastní šířka/délka
        paper_size_user = getattr(win32con, "DMPAPER_USER", 256)
        devmode.PaperSize = paper_size_user
        devmode.PaperWidth = int(round(page_width_mm * 10.0))
        devmode.PaperLength = int(round(page_height_mm * 10.0))
        devmode.Orientation = win32con.DMORIENT_PORTRAIT

        fields = int(getattr(devmode, "Fields", 0) or 0)
        fields |= (
            win32con.DM_PAPERSIZE
            | win32con.DM_PAPERWIDTH
            | win32con.DM_PAPERLENGTH
            | win32con.DM_ORIENTATION
        )

        # Boční / manuální podavač (Tray 1 u Phaser 6700)
        for bin_attr in ("DMBIN_MANUAL", "DMBIN_FORMSOURCE", "DMBIN_ONLYONE"):
            if hasattr(win32con, bin_attr):
                try:
                    devmode.DefaultSource = getattr(win32con, bin_attr)
                    fields |= win32con.DM_DEFAULTSOURCE
                    break
                except Exception:
                    pass

        devmode.Fields = fields
        return devmode
    finally:
        win32print.ClosePrinter(hprinter)


def _bake_print_scale(image, scale_x: float, scale_y: float):
    """
    Kompenzaci měřítka vložit do bitmapy (bílé okraje), ne do GDI dest.
    FinePrint / ovladač často znovu roztáhne úlohu na celou stránku a tím
    zruší menší dest — u výšky se chyba nasčítá přes 7 mezer mezi řádky.
    """
    from PIL import Image

    if image.mode != "RGB":
        image = image.convert("RGB")
    w, h = image.size
    nw = max(1, int(round(w * scale_x)))
    nh = max(1, int(round(h * scale_y)))
    if nw == w and nh == h:
        return image
    small = image.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    # Stejné zmenšení od středu → rozteče X i Y zůstanou po fit-to-page.
    canvas.paste(small, ((w - nw) // 2, (h - nh) // 2))
    return canvas


def _print_bitmap_windows(
    image,
    printer_name: str | None,
    page_width_mm: float,
    page_height_mm: float,
) -> None:
    import win32con  # type: ignore
    import win32print  # type: ignore
    import win32ui  # type: ignore
    from PIL import ImageWin

    from layout import PRINT_SCALE_X, PRINT_SCALE_Y

    name = printer_name or win32print.GetDefaultPrinter()
    if not name:
        raise RuntimeError("Není dostupná žádná tiskárna.")

    # Scale v bitmapě; na tiskárnu jde stránka 1:1 (mm → device px).
    image = _bake_print_scale(image, PRINT_SCALE_X, PRINT_SCALE_Y)

    devmode = None
    try:
        devmode = _apply_custom_page_devmode(name, page_width_mm, page_height_mm)
    except Exception:
        devmode = None

    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(name)
    try:
        if devmode is not None:
            try:
                hdc.ResetDC(devmode)
            except Exception:
                pass

        hdc.StartDoc("Štítky")
        hdc.StartPage()

        # (0,0) DC = levý horní roh tisknutelné oblasti.
        dpi_x = float(hdc.GetDeviceCaps(win32con.LOGPIXELSX))
        dpi_y = float(hdc.GetDeviceCaps(win32con.LOGPIXELSY))
        offset_x = int(hdc.GetDeviceCaps(win32con.PHYSICALOFFSETX))
        offset_y = int(hdc.GetDeviceCaps(win32con.PHYSICALOFFSETY))
        phys_w = int(hdc.GetDeviceCaps(win32con.PHYSICALWIDTH))
        phys_h = int(hdc.GetDeviceCaps(win32con.PHYSICALHEIGHT))

        page_w_px = int(round(page_width_mm * dpi_x / 25.4))
        page_h_px = int(round(page_height_mm * dpi_y / 25.4))

        # Phaser 6700 Tray 1: šířka na střed vodítek; výška od náběžné hrany.
        left = -offset_x + int(round((phys_w - page_w_px) / 2.0))
        top = -offset_y + int(round((phys_h - page_h_px) / 2.0)) if phys_h > 0 else -offset_y
        # Když ovladač hlásí stejnou výšku jako arch, stačí náběžná hrana.
        if abs(phys_h - page_h_px) <= 2:
            top = -offset_y
        dest = (left, top, left + page_w_px, top + page_h_px)

        dib = ImageWin.Dib(image)
        dib.draw(hdc.GetHandleOutput(), dest)

        hdc.EndPage()
        hdc.EndDoc()
    finally:
        hdc.DeleteDC()


def print_pdf(pdf_path: str | Path, printer_name: str | None = None) -> bool:
    """
    Odešle PDF na tiskárnu (Sumatra / ShellExecute).
    Vrací True, pokud je bezpečné soubor hned smazat (synchronní tisk).
    False = tisk běží asynchronně (Acrobat apod.) — soubor ještě nechat.
    """
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF neexistuje: {pdf_path}")

    if sys.platform == "win32":
        return _print_windows_pdf(pdf_path, printer_name)
    elif sys.platform == "darwin":
        cmd = ["lp", str(pdf_path)]
        if printer_name:
            cmd = ["lp", "-d", printer_name, str(pdf_path)]
        subprocess.check_call(cmd)
        return True
    else:
        cmd = ["lpr", str(pdf_path)]
        if printer_name:
            cmd = ["lpr", "-P", printer_name, str(pdf_path)]
        subprocess.check_call(cmd)
        return True


def _print_windows_pdf(pdf_path: Path, printer_name: str | None) -> bool:
    sumatra = _find_sumatra()
    if sumatra:
        cmd = [sumatra, "-print-to-default", "-silent", str(pdf_path)]
        if printer_name:
            cmd = [sumatra, "-print-to", printer_name, "-silent", str(pdf_path)]
        subprocess.check_call(cmd)
        return True

    try:
        import win32api  # type: ignore

        if printer_name:
            win32api.ShellExecute(0, "printto", str(pdf_path), f'"{printer_name}"', ".", 0)
        else:
            win32api.ShellExecute(0, "print", str(pdf_path), None, ".", 0)
        # ShellExecute jen spustí Acrobat — soubor nesmí zmizet.
        return False
    except Exception:
        pass

    ps = (
        f'Start-Process -FilePath "{pdf_path}" -Verb Print -WindowStyle Hidden'
        if not printer_name
        else (
            f'$p = Get-CimInstance Win32_Printer | Where-Object {{ $_.Name -eq "{printer_name}" }}; '
            f'if (-not $p) {{ throw "Tiskárna nenalezena" }}; '
            f'Start-Process -FilePath "{pdf_path}" -Verb PrintTo -ArgumentList "{printer_name}" '
            f'-WindowStyle Hidden'
        )
    )
    subprocess.check_call(
        ["powershell", "-NoProfile", "-Command", ps],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return False


def _find_sumatra() -> str | None:
    candidates = [
        shutil.which("SumatraPDF"),
        r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
        r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\SumatraPDF\SumatraPDF.exe"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None
