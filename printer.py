"""Přímý tisk PDF na systémovou tiskárnu."""

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
    # Linux / macOS
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
        # "system default destination: Name"
        if ":" in out:
            return out.split(":", 1)[1].strip() or None
    except Exception:
        return None
    return None


def print_pdf(pdf_path: str | Path, printer_name: str | None = None) -> None:
    """
    Odešle PDF přímo na tiskárnu.
    Windows: win32api ShellExecute('print') / PowerShell.
    Linux: lpr.
    """
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF neexistuje: {pdf_path}")

    if sys.platform == "win32":
        _print_windows(pdf_path, printer_name)
    elif sys.platform == "darwin":
        cmd = ["lp", str(pdf_path)]
        if printer_name:
            cmd = ["lp", "-d", printer_name, str(pdf_path)]
        subprocess.check_call(cmd)
    else:
        cmd = ["lpr", str(pdf_path)]
        if printer_name:
            cmd = ["lpr", "-P", printer_name, str(pdf_path)]
        subprocess.check_call(cmd)


def _print_windows(pdf_path: Path, printer_name: str | None) -> None:
    # 1) Prefer SumatraPDF if installed (spolehlivý tichý tisk)
    sumatra = _find_sumatra()
    if sumatra:
        cmd = [sumatra, "-print-to-default", "-silent", str(pdf_path)]
        if printer_name:
            cmd = [sumatra, "-print-to", printer_name, "-silent", str(pdf_path)]
        subprocess.check_call(cmd)
        return

    # 2) win32api ShellExecute printto / print
    try:
        import win32api  # type: ignore

        if printer_name:
            win32api.ShellExecute(0, "printto", str(pdf_path), f'"{printer_name}"', ".", 0)
        else:
            win32api.ShellExecute(0, "print", str(pdf_path), None, ".", 0)
        return
    except Exception:
        pass

    # 3) PowerShell Start-Process -Verb Print
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


def print_pdf_bytes(pdf_bytes: bytes, printer_name: str | None = None) -> Path:
    """Uloží PDF do dočasného souboru a vytiskne. Vrací cestu (pro případné smazání)."""
    fd, name = tempfile.mkstemp(prefix="stitky_", suffix=".pdf")
    os.close(fd)
    path = Path(name)
    path.write_bytes(pdf_bytes)
    print_pdf(path, printer_name)
    return path
