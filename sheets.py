"""Definice archů (verze 2.0) — vše zadatelné uživatelem, uložené v sheets.json."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from layout import PRINT_SCALE_X, PRINT_SCALE_Y, ROWS, SheetLayout

SHEETS_FILE_VERSION = 1

# Režimy rozložení jedné osy (sloupce = X, řádky = Y)
AXIS_INTERPOLATE = "interpolate"  # okraj začátek + okraj konec → mezera dopočtena
AXIS_GAP = "gap"  # pevná mezera mezi štítky
AXIS_PITCH = "pitch"  # pevná rozteč (vzdálenost sousedních středů)
AXIS_MODES = (AXIS_INTERPOLATE, AXIS_GAP, AXIS_PITCH)

AXIS_MODE_TITLES = {
    AXIS_INTERPOLATE: "Interpolovat mezi okraji",
    AXIS_GAP: "Pevná mezera",
    AXIS_PITCH: "Pevná rozteč středů",
}


@dataclass
class AxisSpec:
    """Rozložení štítků v jedné ose."""

    mode: str = AXIS_INTERPOLATE
    margin_start_mm: float = 2.0  # vlevo / nahoře
    margin_end_mm: float = 2.0  # vpravo / dole (jen interpolace)
    gap_mm: float = 3.0  # jen „pevná mezera“
    pitch_mm: float = 105.0  # jen „pevná rozteč“
    center: bool = True  # u pevné mezery/rozteče: vystředit místo okraje začátku

    def resolve(self, page_mm: float, label_mm: float, count: int) -> tuple[float, float]:
        """Vrátí (okraj_začátek, mezera) v mm."""
        n = max(int(count), 1)
        if self.mode == AXIS_INTERPOLATE:
            start = float(self.margin_start_mm)
            if n <= 1:
                return start, 0.0
            free = page_mm - start - float(self.margin_end_mm) - n * label_mm
            return start, free / (n - 1)

        if self.mode == AXIS_PITCH:
            gap = float(self.pitch_mm) - label_mm
        else:
            gap = float(self.gap_mm)
        if n <= 1:
            gap = 0.0
        content = n * label_mm + (n - 1) * gap
        if self.center:
            start = (page_mm - content) / 2.0
        else:
            start = float(self.margin_start_mm)
        return start, gap

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None, default: "AxisSpec | None" = None) -> "AxisSpec":
        base = default or cls()
        if not isinstance(data, dict):
            return replace(base)
        mode = str(data.get("mode", base.mode))
        if mode not in AXIS_MODES:
            mode = base.mode
        return cls(
            mode=mode,
            margin_start_mm=_f(data.get("margin_start_mm"), base.margin_start_mm),
            margin_end_mm=_f(data.get("margin_end_mm"), base.margin_end_mm),
            gap_mm=_f(data.get("gap_mm"), base.gap_mm),
            pitch_mm=_f(data.get("pitch_mm"), base.pitch_mm),
            center=bool(data.get("center", base.center)),
        )


def _f(value, default: float) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return float(default)


@dataclass
class SheetDefinition:
    """Kompletní popis archu samolepek."""

    id: str
    name: str
    page_width_mm: float
    page_height_mm: float
    label_width_mm: float
    label_height_mm: float
    cols: int
    rows: int
    x: AxisSpec = field(default_factory=AxisSpec)
    y: AxisSpec = field(default_factory=AxisSpec)
    # Formát v ovladači tiskárny; None = stejný jako arch.
    print_width_mm: float | None = None
    print_height_mm: float | None = None
    # Korekce tisku (100 % = beze změny).
    print_scale_x_pct: float = 100.0
    print_scale_y_pct: float = 100.0
    nudge_x_mm: float = 0.0
    nudge_y_mm: float = 0.0
    builtin: bool = False

    # --- kompatibilita s SheetPreset (UI) ---
    @property
    def title(self) -> str:
        return self.name

    @property
    def effective_print_width_mm(self) -> float:
        return float(self.print_width_mm) if self.print_width_mm else float(self.page_width_mm)

    @property
    def effective_print_height_mm(self) -> float:
        return float(self.print_height_mm) if self.print_height_mm else float(self.page_height_mm)

    def short_info(self) -> str:
        return (
            f"Arch {self.page_width_mm:g}×{self.page_height_mm:g} mm, "
            f"tisk {self.effective_print_width_mm:g}×{self.effective_print_height_mm:g}. "
            f"Štítek {self.label_width_mm:g}×{self.label_height_mm:g}, "
            f"mřížka {self.cols}×{self.rows}. "
            f"X: {AXIS_MODE_TITLES[self.x.mode].lower()}, "
            f"Y: {AXIS_MODE_TITLES[self.y.mode].lower()}."
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.page_width_mm <= 0 or self.page_height_mm <= 0:
            errors.append("Rozměr archu musí být kladný.")
        if self.label_width_mm <= 0 or self.label_height_mm <= 0:
            errors.append("Rozměr štítku musí být kladný.")
        if not (1 <= self.cols <= 26):
            errors.append("Počet sloupců musí být 1–26.")
        if not (1 <= self.rows <= len(ROWS)):
            errors.append(f"Počet řádků musí být 1–{len(ROWS)}.")
        if self.print_scale_x_pct <= 0 or self.print_scale_y_pct <= 0:
            errors.append("Měřítko tisku musí být kladné.")
        if not self.name.strip():
            errors.append("Zadejte název archu.")
        return errors

    def to_layout(
        self,
        *,
        content_pad_top_mm: float = 0.0,
        content_pad_right_mm: float = 0.0,
        content_pad_bottom_mm: float = 0.0,
        content_pad_left_mm: float = 0.0,
    ) -> SheetLayout:
        left, gap_x = self.x.resolve(self.page_width_mm, self.label_width_mm, self.cols)
        top, gap_y = self.y.resolve(self.page_height_mm, self.label_height_mm, self.rows)
        return SheetLayout(
            page_width_mm=float(self.page_width_mm),
            page_height_mm=float(self.page_height_mm),
            print_width_mm=self.effective_print_width_mm,
            print_height_mm=self.effective_print_height_mm,
            label_width_mm=float(self.label_width_mm),
            label_height_mm=float(self.label_height_mm),
            rows=int(self.rows),
            cols=int(self.cols),
            margin_left_mm=left,
            margin_top_mm=top,
            gap_x_fixed_mm=gap_x,
            gap_y_fixed_mm=gap_y,
            content_pad_top_mm=content_pad_top_mm,
            content_pad_right_mm=content_pad_right_mm,
            content_pad_bottom_mm=content_pad_bottom_mm,
            content_pad_left_mm=content_pad_left_mm,
            nudge_x_mm=float(self.nudge_x_mm),
            nudge_y_mm=float(self.nudge_y_mm),
            print_scale_x=float(self.print_scale_x_pct) / 100.0,
            print_scale_y=float(self.print_scale_y_pct) / 100.0,
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["x"] = self.x.to_dict()
        data["y"] = self.y.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict, default: "SheetDefinition | None" = None) -> "SheetDefinition":
        if not isinstance(data, dict):
            raise ValueError("Neplatná definice archu.")
        base = default
        sid = str(data.get("id") or (base.id if base else "")).strip()
        if not sid:
            raise ValueError("Definice archu nemá id.")

        def num(key: str, fallback: float) -> float:
            return _f(data.get(key), fallback)

        def opt(key: str, fallback: float | None) -> float | None:
            v = data.get(key, fallback)
            if v is None or v == "":
                return None
            return _f(v, fallback or 0.0)

        return cls(
            id=sid,
            name=str(data.get("name") or (base.name if base else sid)),
            page_width_mm=num("page_width_mm", base.page_width_mm if base else 210.0),
            page_height_mm=num("page_height_mm", base.page_height_mm if base else 297.0),
            label_width_mm=num("label_width_mm", base.label_width_mm if base else 70.0),
            label_height_mm=num("label_height_mm", base.label_height_mm if base else 36.0),
            cols=int(num("cols", base.cols if base else 3)),
            rows=int(num("rows", base.rows if base else 8)),
            x=AxisSpec.from_dict(data.get("x"), base.x if base else None),
            y=AxisSpec.from_dict(data.get("y"), base.y if base else None),
            print_width_mm=opt("print_width_mm", base.print_width_mm if base else None),
            print_height_mm=opt("print_height_mm", base.print_height_mm if base else None),
            print_scale_x_pct=num("print_scale_x_pct", base.print_scale_x_pct if base else 100.0),
            print_scale_y_pct=num("print_scale_y_pct", base.print_scale_y_pct if base else 100.0),
            nudge_x_mm=num("nudge_x_mm", base.nudge_x_mm if base else 0.0),
            nudge_y_mm=num("nudge_y_mm", base.nudge_y_mm if base else 0.0),
            builtin=bool(base.builtin) if base else False,
        )

    def copy(self, **changes) -> "SheetDefinition":
        return replace(self, x=replace(self.x), y=replace(self.y), **changes)


# --- Vestavěné archy (původní presety verze 1) ---

_SCALE_X_PCT = round(PRINT_SCALE_X * 100.0, 3)
_SCALE_Y_PCT = round(PRINT_SCALE_Y * 100.0, 3)


def builtin_sheets() -> list[SheetDefinition]:
    return [
        SheetDefinition(
            id="3x8_70x36",
            name="3×8 · 70×36 mm · arch 217×304",
            page_width_mm=217.0,
            page_height_mm=304.0,
            label_width_mm=70.0,
            label_height_mm=36.0,
            cols=3,
            rows=8,
            # A1→A3 = 145, A1→H1 = 266 (středy), vystředěno
            x=AxisSpec(mode=AXIS_PITCH, pitch_mm=72.5, center=True, margin_start_mm=1.0,
                       margin_end_mm=1.0, gap_mm=2.5),
            y=AxisSpec(mode=AXIS_PITCH, pitch_mm=38.0, center=True, margin_start_mm=1.0,
                       margin_end_mm=1.0, gap_mm=2.0),
            print_width_mm=215.0,
            print_height_mm=304.0,
            print_scale_x_pct=_SCALE_X_PCT,
            print_scale_y_pct=_SCALE_Y_PCT,
            builtin=True,
        ),
        SheetDefinition(
            id="2x8_120x36",
            name="2×8 · 102×36 mm · arch 211×303,5",
            page_width_mm=211.0,
            page_height_mm=303.5,
            label_width_mm=102.0,
            label_height_mm=36.0,
            cols=2,
            rows=8,
            # 2 + 102 + 3 + 102 + 2 = 211; nahoře/dole 2 mm, řádky interpolovat
            x=AxisSpec(mode=AXIS_INTERPOLATE, margin_start_mm=2.0, margin_end_mm=2.0,
                       gap_mm=3.0, pitch_mm=105.0),
            y=AxisSpec(mode=AXIS_INTERPOLATE, margin_start_mm=2.0, margin_end_mm=2.0,
                       gap_mm=1.64, pitch_mm=37.64),
            print_width_mm=None,
            print_height_mm=None,
            print_scale_x_pct=_SCALE_X_PCT,
            print_scale_y_pct=_SCALE_Y_PCT,
            builtin=True,
        ),
    ]


DEFAULT_SHEET_ID = "3x8_70x36"
_LEGACY_IDS = {"2x8_12x36": "2x8_120x36"}


def builtin_by_id(sheet_id: str) -> SheetDefinition | None:
    for s in builtin_sheets():
        if s.id == sheet_id:
            return s
    return None


class SheetStore:
    """Seznam archů: vestavěné (s případnými úpravami) + vlastní."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.sheets: list[SheetDefinition] = []
        self.load()

    # --- načtení / uložení ---
    def load(self) -> None:
        overrides: dict[str, dict] = {}
        custom: list[dict] = []
        if self.path is not None and self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
                for item in raw.get("sheets", []):
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    if builtin_by_id(str(item["id"])) is not None:
                        overrides[str(item["id"])] = item
                    else:
                        custom.append(item)
            except Exception:
                overrides, custom = {}, []

        sheets: list[SheetDefinition] = []
        for b in builtin_sheets():
            if b.id in overrides:
                try:
                    sheets.append(SheetDefinition.from_dict(overrides[b.id], b))
                    continue
                except Exception:
                    pass
            sheets.append(b)
        for item in custom:
            try:
                sheets.append(SheetDefinition.from_dict(item))
            except Exception:
                continue
        self.sheets = sheets

    def save(self) -> None:
        if self.path is None:
            return
        items: list[dict] = []
        for s in self.sheets:
            if s.builtin:
                default = builtin_by_id(s.id)
                if default is not None and default.to_dict() == s.to_dict():
                    continue  # neupravený vestavěný arch neukládat
            items.append(s.to_dict())
        payload = {"version": SHEETS_FILE_VERSION, "app": "stitky", "sheets": items}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    # --- dotazy ---
    def get(self, sheet_id: str | None) -> SheetDefinition:
        sid = _LEGACY_IDS.get(str(sheet_id or ""), str(sheet_id or ""))
        for s in self.sheets:
            if s.id == sid:
                return s
        for s in self.sheets:
            if s.id == DEFAULT_SHEET_ID:
                return s
        return self.sheets[0]

    def has(self, sheet_id: str) -> bool:
        sid = _LEGACY_IDS.get(sheet_id, sheet_id)
        return any(s.id == sid for s in self.sheets)

    def choices(self) -> list[tuple[str, str]]:
        return [(s.id, s.name) for s in self.sheets]

    def replace_all(self, sheets: list[SheetDefinition]) -> None:
        self.sheets = [s.copy() for s in sheets]

    def upsert(self, sheet: SheetDefinition) -> None:
        for i, s in enumerate(self.sheets):
            if s.id == sheet.id:
                self.sheets[i] = sheet
                return
        self.sheets.append(sheet)

    def new_id(self, base: str = "arch") -> str:
        existing = {s.id for s in self.sheets}
        i = 1
        while f"{base}_{i}" in existing:
            i += 1
        return f"{base}_{i}"
