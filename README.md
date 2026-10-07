# Tisk štítků 3×8

Samolepicí štítky pro Xerox Phaser 6700 — arch **217 × 304 mm**, tisk **215 × 304 mm**.

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

V ovladači Phaseru 6700 zvolte vlastní formát podle archu
(**215 × 304** u 3×8, **211 × 303,5** u 2×8). Boční Tray 1: vodítka
k okrajům, tisková strana dolů, dolní hrana do tiskárny.

## Rozměry

| Co | mm |
|----|-----|
| Fyzický arch | 217 × 304 |
| Tisková stránka (ovladač) | 215 × 304 |
| Štítek | 70 × 36 (od kraje do kraje) |
| Mřížka | 3 × 8 (A1–H3) |
| Žluté mezery X / Y | ≈3,5 / ≈2,29 |
| Tisknutelný okraj tiskárny | 5 |

Tisk jde **přímo na tiskárnu** (Windows GDI, bez PDF). PDF zůstává jen pro náhled/export. Layout je v `layout.py`.
