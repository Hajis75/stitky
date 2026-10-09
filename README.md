# Tisk štítků 2.0

Samolepicí štítky na libovolný arch — vyzkoušeno na Xerox Phaser 6700.

Repo: https://github.com/Hajis75/stitky

## Instalace do `c:\GitHub\stitky`

```powershell
git clone https://github.com/Hajis75/stitky.git c:\GitHub\stitky
c:\GitHub\stitky\dist\StitkyTisk.exe
```

Nebo spusťte `Nainstalovat_do_c_GitHub_stitky.bat`.

## Spuštění

| Způsob | Soubor |
|--------|--------|
| Hotové .exe | `dist\StitkyTisk.exe` |
| Python | `Spustit.bat` |
| Znovu sestavit .exe | `build_exe.bat` |

## Správa archů

Tlačítko **Správa archů…** v hlavním okně otevře okno, kde se pro každý arch zadává:

- rozměr archu (šířka × délka) a formát v ovladači tiskárny,
- rozměr štítku, počet sloupců a řádků (až 26 × 26),
- zvlášť pro sloupce a pro řádky jeden z režimů:
  - **Interpolovat mezi okraji** — zadáte okraj na začátku a na konci, mezery se dopočítají,
  - **Pevná mezera** — zadáte mezeru, okraj buď zadáte, nebo se mřížka vystředí,
  - **Pevná rozteč středů** — zadáte vzdálenost sousedních středů, okraj zadáte nebo vystředíte,
- korekce tisku: měřítko X/Y v % a posun X/Y v mm.

Dopočtené hodnoty se zobrazují šedě přímo v polích, vpravo je náhled mřížky a souhrn okrajů.
Archy se ukládají do `Dokumenty\Stitky\sheets.json`. Vestavěné archy (3×8 · 70×36 a
2×8 · 102×36) lze upravit a tlačítkem *Obnovit výchozí hodnoty* vrátit. Uložený dokument
nese celou definici archu, takže jde otevřít i na jiném počítači.

## Phaser 6700, boční Tray 1

V ovladači zvolte vlastní formát podle archu (u 2×8 **211 × 303,5**). Vodítka k okrajům,
tisková strana dolů, dolní hrana do tiskárny.

Tisk jde **přímo na tiskárnu** (Windows GDI, bez PDF). PDF zůstává pro náhled/export.
