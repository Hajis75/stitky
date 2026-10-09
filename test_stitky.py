"""Jednoduché testy layoutu, rich-textu a renderu bez GUI."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

# Nesmí přepisovat uživatelský last_session.json ani ho načítat.
os.environ["STITKY_NO_SESSION"] = "1"

from layout import SheetLayout, cell_name, parse_range
from renderer import (
    LabelContent,
    RenderOptions,
    font_name,
    render_calibration_image,
    render_calibration_pdf,
    render_sheet_image,
    render_sheet_pdf,
)
from richtext import (
    TextRun,
    apply_size_on_range,
    dump_text_runs,
    normalize_runs,
    runs_to_plain,
    toggle_tag_on_range,
    wrap_rich_runs,
)


class LayoutTests(unittest.TestCase):
    def test_parse_range(self) -> None:
        self.assertEqual(parse_range("A1"), [(0, 0)])
        self.assertEqual(parse_range("H3"), [(7, 2)])
        self.assertEqual(
            parse_range("A1-B2"),
            [(0, 0), (0, 1), (1, 0), (1, 1)],
        )

    def test_cell_name(self) -> None:
        self.assertEqual(cell_name(0, 0), "A1")
        self.assertEqual(cell_name(7, 2), "H3")

    def test_print_offset_centered(self) -> None:
        lay = SheetLayout(
            page_width_mm=217, print_width_mm=215, page_height_mm=304, print_height_mm=304
        )
        off_x, off_y = lay.print_offset_mm()
        self.assertAlmostEqual(off_x, 1.0, places=3)
        self.assertAlmostEqual(off_y, 0.0, places=3)

    def test_edge_to_edge_gaps(self) -> None:
        from layout import default_sheet_layout

        lay = default_sheet_layout()
        ox, oy = lay.resolved_outer_margins()
        self.assertAlmostEqual(ox, 1.0, places=3)
        self.assertAlmostEqual(oy, 1.0, places=3)
        self.assertAlmostEqual(lay.gap_x_mm(), 2.5, places=3)
        self.assertAlmostEqual(lay.gap_y_mm(), 2.0, places=3)
        self.assertAlmostEqual(lay.pitch_x_mm(), 72.5, places=3)
        self.assertAlmostEqual(lay.pitch_y_mm(), 38.0, places=3)
        # vzdálenosti středů
        self.assertAlmostEqual(lay.pitch_x_mm() * 2, 145.0, places=2)
        self.assertAlmostEqual(lay.pitch_y_mm() * 7, 266.0, places=2)
        # úhlopříčka středů A1→H3
        diag = ((lay.pitch_x_mm() * 2) ** 2 + (lay.pitch_y_mm() * 7) ** 2) ** 0.5
        self.assertAlmostEqual(diag, 303.0, places=1)

    def test_preset_2x8_120x36(self) -> None:
        from layout import get_preset, layout_from_preset, parse_range

        p = get_preset("2x8_120x36")
        self.assertEqual(p.cols, 2)
        self.assertEqual(p.rows, 8)
        self.assertAlmostEqual(p.label_width_mm, 102.0)
        self.assertAlmostEqual(p.span_x_mm, 105.0)
        self.assertAlmostEqual(p.span_y_mm, 263.5)
        self.assertAlmostEqual(p.page_width_mm, 211.0)
        self.assertAlmostEqual(p.page_height_mm, 303.5)
        self.assertAlmostEqual(p.print_width_mm, 211.0)
        self.assertAlmostEqual(p.print_height_mm, 303.5)
        lay = layout_from_preset(p)
        self.assertEqual(lay.cols, 2)
        # 2 | 102 | 3 | 102 | 2
        self.assertAlmostEqual(lay.gap_x_mm(), 3.0, places=2)
        ox, oy = lay.resolved_outer_margins()
        self.assertAlmostEqual(ox, 2.0, places=2)
        self.assertAlmostEqual(oy, 2.0, places=2)
        self.assertAlmostEqual(lay.pitch_x_mm(), 105.0, places=2)
        self.assertAlmostEqual(lay.pitch_y_mm() * 7, 263.5, places=2)
        a1 = lay.label_rect_mm(0, 0)
        h1 = lay.label_rect_mm(7, 0)
        self.assertAlmostEqual(a1[1], 2.0, places=2)
        self.assertAlmostEqual(h1[1] + h1[3], 303.5 - 2.0, places=2)
        # tisk = fyzický arch → bez offsetu
        off_x, off_y = lay.print_offset_mm()
        self.assertAlmostEqual(off_x, 0.0, places=3)
        self.assertAlmostEqual(off_y, 0.0, places=3)
        # na tiskové stránce levá = pravá mezera (211 i 215 — střed)
        a1p = lay.label_rect_print_mm(0, 0)
        a2p = lay.label_rect_print_mm(0, 1)
        h1p = lay.label_rect_print_mm(7, 0)
        left_gap = a1p[0]
        right_gap = lay.print_width_mm - (a2p[0] + a2p[2])
        top_gap = a1p[1]
        bottom_gap = lay.print_height_mm - (h1p[1] + h1p[3])
        self.assertAlmostEqual(left_gap, right_gap, places=3)
        self.assertAlmostEqual(top_gap, bottom_gap, places=3)
        self.assertEqual(parse_range("H2", cols=2), [(7, 1)])
        with self.assertRaises(ValueError):
            parse_range("A3", cols=2)

    def test_content_insets(self) -> None:
        from layout import default_sheet_layout, layout_from_center_spans

        lay = default_sheet_layout()
        # výchozí: 0 0 0 0 — celý štítek 70×36
        for row, col in ((0, 0), (0, 1), (0, 2), (2, 1), (7, 0), (7, 2)):
            self.assertEqual(lay.content_insets_mm(row, col), (0.0, 0.0, 0.0, 0.0))
            _, _, w, h = lay.label_content_rect_print_mm(row, col)
            self.assertAlmostEqual(w, 70.0, places=2)
            self.assertAlmostEqual(h, 36.0, places=2)

        padded = layout_from_center_spans(
            content_pad_top_mm=10,
            content_pad_right_mm=5,
            content_pad_bottom_mm=10,
            content_pad_left_mm=5,
        )
        self.assertEqual(padded.content_insets_mm(2, 1), (10.0, 5.0, 10.0, 5.0))
        _, _, w, h = padded.label_content_rect_print_mm(2, 1)
        self.assertAlmostEqual(w, 60.0, places=2)
        self.assertAlmostEqual(h, 16.0, places=2)

    def test_label_print_coords(self) -> None:
        lay = SheetLayout(outer_margin_x_mm=0.5, outer_margin_y_mm=2.0)
        x_phys, y_phys, w, h = lay.label_rect_mm(0, 0)
        x_print, y_print, _, _ = lay.label_rect_print_mm(0, 0)
        off_x, off_y = lay.print_offset_mm()
        self.assertAlmostEqual(x_phys, 0.5, places=2)
        # tisk vystředěn vůči archu → print = physical − offset
        self.assertAlmostEqual(x_print, x_phys - off_x, places=2)
        self.assertAlmostEqual(y_print, y_phys - off_y, places=2)

    def test_nudge(self) -> None:
        lay = SheetLayout(nudge_x_mm=0.5, nudge_y_mm=-0.3)
        x0, y0, _, _ = SheetLayout().label_rect_print_mm(0, 0)
        x1, y1, _, _ = lay.label_rect_print_mm(0, 0)
        self.assertAlmostEqual(x1 - x0, 0.5, places=3)
        self.assertAlmostEqual(y1 - y0, -0.3, places=3)

    def test_default_warnings_are_informational(self) -> None:
        lay = SheetLayout()
        self.assertEqual(lay.fit_blocking_warnings(), [])
        self.assertTrue(lay.fit_warnings())

    def test_apply_measured_pitches(self) -> None:
        lay = SheetLayout()
        default_py = lay.pitch_y_mm()
        span_y = (default_py - 0.5) * 7
        span_x = (lay.pitch_x_mm() - 0.3) * 2
        result = lay.apply_measured_pitches(
            span_x_a1_a3_mm=span_x,
            span_y_a1_h1_mm=span_y,
        )
        self.assertAlmostEqual(lay.pitch_y_mm(), default_py - 0.5, places=3)
        self.assertAlmostEqual(lay.pitch_x_mm(), result["pitch_x"], places=3)
        _, y0, _, _ = lay.label_rect_mm(0, 0)
        _, y7, _, _ = lay.label_rect_mm(7, 0)
        self.assertAlmostEqual(y7 - y0, span_y, places=3)
        x0, _, _, _ = lay.label_rect_mm(0, 0)
        x2, _, _, _ = lay.label_rect_mm(0, 2)
        self.assertAlmostEqual(x2 - x0, span_x, places=3)

    def test_apply_a1_shift(self) -> None:
        lay = SheetLayout(nudge_x_mm=1.0, nudge_y_mm=2.0)
        nx, ny = lay.apply_a1_shift(dx_mm=0.5, dy_mm=-0.25)
        self.assertAlmostEqual(nx, 0.5, places=3)
        self.assertAlmostEqual(ny, 2.25, places=3)


class CalibrationRenderTests(unittest.TestCase):
    def test_calibration_pdf(self) -> None:
        lay = SheetLayout()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cal.pdf"
            render_calibration_pdf(lay, path)
            self.assertGreater(path.stat().st_size, 500)
            self.assertIn(b"/MediaBox", path.read_bytes())

    def test_calibration_and_sheet_bitmap(self) -> None:
        lay = SheetLayout()
        cal = render_calibration_image(lay, dpi=72)
        self.assertEqual(cal.mode, "RGB")
        self.assertGreater(cal.size[0], 100)
        self.assertGreater(cal.size[1], 100)
        content = LabelContent(text="Test\nAdresa", mode="text", font_size_pt=11)
        sheet = render_sheet_image(
            lay,
            [(0, 0)],
            content,
            dpi=72,
            options=RenderOptions(),
        )
        self.assertEqual(sheet.mode, "RGB")
        self.assertAlmostEqual(
            sheet.size[0] / sheet.size[1],
            lay.print_width_mm / lay.print_height_mm,
            places=2,
        )


class RichTextTests(unittest.TestCase):
    def test_normalize_and_size(self) -> None:
        runs = normalize_runs(
            [
                {"text": "A", "bold": True, "size": 14},
                {"text": "B", "bold": True, "size": 14},
                {"text": "C", "italic": True, "size": 9, "color": "#ff0000"},
            ]
        )
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0].text, "AB")
        self.assertEqual(runs[0].size, 14)
        self.assertTrue(runs[1].italic)
        self.assertEqual(runs[1].size, 9)

    def test_wrap_mixed_sizes(self) -> None:
        runs = [
            TextRun("Hello ", size=11),
            TextRun("BIG", bold=True, size=18),
            TextRun(" world", size=11),
        ]
        lines = wrap_rich_runs(runs, 200, font_name)
        self.assertTrue(lines)
        plain = "".join(r.text for line in lines for r in line)
        self.assertIn("BIG", plain)


class RenderTests(unittest.TestCase):
    def test_text_fit_and_pdf(self) -> None:
        text = "Jan Novák\nUlice 1\n110 00 Praha"
        lay = SheetLayout()
        content = LabelContent(text=text, mode="text", font_size_pt=11)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.pdf"
            render_sheet_pdf(
                lay,
                [(0, 0), (0, 1)],
                content,
                path,
                RenderOptions(
                    show_outlines=True,
                    show_cell_names=True,
                    show_printable_area=True,
                ),
            )
            self.assertGreater(path.stat().st_size, 500)

    def test_styled_pdf(self) -> None:
        lay = SheetLayout()
        content = LabelContent(
            text="x",
            mode="text",
            font_size_pt=11,
            align="right",
            runs=[
                TextRun("Tučný\n", bold=True, size=14),
                TextRun("kurziva\n", italic=True, size=10, color="#003366"),
                TextRun("podtrh", underline=True, size=12),
                TextRun("X", size=20, color="#cc0000"),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "styled.pdf"
            render_sheet_pdf(lay, [(0, 0)], content, path, RenderOptions())
            self.assertGreater(path.stat().st_size, 500)

    def test_svg_logo_pdf_and_bitmap(self) -> None:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40" '
            'viewBox="0 0 120 40">'
            '<rect x="1" y="1" width="118" height="38" fill="none" '
            'stroke="#003366" stroke-width="2"/>'
            '<text x="60" y="26" text-anchor="middle" font-size="14" '
            'font-family="Arial" fill="#003366">firma.cz</text>'
            "</svg>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            svg_path = Path(tmp) / "logo.svg"
            svg_path.write_text(svg, encoding="utf-8")
            lay = SheetLayout()
            content = LabelContent(
                text="",
                mode="image",
                image_path=str(svg_path),
            )
            pdf_path = Path(tmp) / "svg.pdf"
            render_sheet_pdf(lay, [(0, 0)], content, pdf_path, RenderOptions())
            self.assertGreater(pdf_path.stat().st_size, 500)
            img = render_sheet_image(
                lay, [(0, 0)], content, dpi=150, options=RenderOptions()
            )
            self.assertEqual(img.mode, "RGB")
            self.assertGreater(img.width, 100)


class SheetDefinitionTests(unittest.TestCase):
    def test_builtin_2x8_matches_measurement(self) -> None:
        from sheets import builtin_by_id

        lay = builtin_by_id("2x8_120x36").to_layout()
        ml, mr, mt, mb = lay.margins_lrtb_mm()
        self.assertAlmostEqual(ml, 2.0, places=3)
        self.assertAlmostEqual(mr, 2.0, places=3)
        self.assertAlmostEqual(mt, 2.0, places=3)
        self.assertAlmostEqual(mb, 2.0, places=3)
        self.assertAlmostEqual(lay.gap_x_mm(), 3.0, places=3)
        self.assertAlmostEqual(lay.pitch_y_mm() * 7, 263.5, places=3)
        self.assertAlmostEqual(lay.print_width_mm, 211.0)

    def test_builtin_3x8_same_as_v1(self) -> None:
        from layout import layout_from_preset
        from sheets import builtin_by_id

        old = layout_from_preset("3x8_70x36")
        new = builtin_by_id("3x8_70x36").to_layout()
        for r, c in ((0, 0), (3, 1), (7, 2)):
            for a, b in zip(old.label_rect_print_mm(r, c), new.label_rect_print_mm(r, c)):
                self.assertAlmostEqual(a, b, places=3)

    def test_axis_modes(self) -> None:
        from sheets import AXIS_GAP, AXIS_INTERPOLATE, AXIS_PITCH, AxisSpec

        # interpolace: 300 − 5 − 7 − 8×36 = 0 → mezera 0
        start, gap = AxisSpec(AXIS_INTERPOLATE, 5, 7).resolve(300, 36, 8)
        self.assertAlmostEqual(start, 5)
        self.assertAlmostEqual(gap, 0)
        # pevná mezera, vystředěno: 2×100 + 4 = 204 → okraj 3,5
        start, gap = AxisSpec(AXIS_GAP, gap_mm=4, center=True).resolve(211, 100, 2)
        self.assertAlmostEqual(start, 3.5)
        self.assertAlmostEqual(gap, 4)
        # pevná mezera od okraje
        start, gap = AxisSpec(AXIS_GAP, margin_start_mm=1, gap_mm=4, center=False).resolve(
            211, 100, 2
        )
        self.assertAlmostEqual(start, 1)
        # pevná rozteč
        start, gap = AxisSpec(AXIS_PITCH, pitch_mm=38, center=True).resolve(304, 36, 8)
        self.assertAlmostEqual(gap, 2)
        self.assertAlmostEqual(start, 1)
        # jeden štítek
        start, gap = AxisSpec(AXIS_GAP, gap_mm=4, center=True).resolve(100, 60, 1)
        self.assertAlmostEqual(start, 20)
        self.assertAlmostEqual(gap, 0)

    def test_asymmetric_margins_layout(self) -> None:
        from sheets import AXIS_INTERPOLATE, AxisSpec, SheetDefinition

        s = SheetDefinition(
            id="t", name="t", page_width_mm=210, page_height_mm=297,
            label_width_mm=100, label_height_mm=30, cols=2, rows=9,
            x=AxisSpec(AXIS_INTERPOLATE, 3, 1), y=AxisSpec(AXIS_INTERPOLATE, 6, 3),
            print_scale_x_pct=100, print_scale_y_pct=100,
        )
        lay = s.to_layout()
        ml, mr, mt, mb = lay.margins_lrtb_mm()
        self.assertAlmostEqual((ml, mr), (3, 1))
        self.assertAlmostEqual(mt, 6)
        self.assertAlmostEqual(mb, 3)
        self.assertAlmostEqual(lay.gap_x_mm(), 6)
        self.assertEqual(lay.print_scale_x, 1.0)
        self.assertEqual(lay.label_rect_mm(8, 1)[1] + 30, 297 - 3)

    def test_store_roundtrip(self) -> None:
        from sheets import SheetStore, builtin_by_id

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sheets.json"
            store = SheetStore(path)
            b = store.get("2x8_120x36").copy(page_height_mm=300.0)
            store.upsert(b)
            custom = b.copy(id="arch_1", name="Můj arch", builtin=False, cols=1)
            store.upsert(custom)
            store.save()

            again = SheetStore(path)
            self.assertAlmostEqual(again.get("2x8_120x36").page_height_mm, 300.0)
            self.assertTrue(again.get("2x8_120x36").builtin)
            self.assertEqual(again.get("arch_1").name, "Můj arch")
            self.assertEqual(again.get("arch_1").cols, 1)
            # neupravený vestavěný arch se do souboru neukládá
            again.upsert(builtin_by_id("2x8_120x36"))
            again.save()
            self.assertNotIn('"2x8_120x36"', path.read_text(encoding="utf-8"))
            # neznámé id → výchozí arch
            self.assertEqual(again.get("neexistuje").id, "3x8_70x36")

    def test_dialog_smoke(self) -> None:
        import tkinter as tk

        from sheet_dialog import SheetManagerDialog
        from sheets import AXIS_GAP, SheetStore

        root = tk.Tk()
        root.withdraw()
        try:
            store = SheetStore(None)
            dlg = SheetManagerDialog(root, store, "2x8_120x36")
            dlg.withdraw()
            # interpolace → mezera dopočtena do needitovatelného pole
            self.assertEqual(dlg.axis_x.var_gap.get(), "3")
            dlg.axis_x.var_mode.set(AXIS_GAP)
            dlg._on_change()
            dlg.axis_x.var_gap.set("5")
            self.assertEqual(dlg.axis_x.var_start.get(), "1")  # (211 − 209) / 2
            dlg._new()
            self.assertEqual(len(dlg.work), 3)
            dlg.var_name.set("Test arch")
            dlg._save_and_use()
            self.assertEqual(store.get(dlg.result_id).name, "Test arch")
            self.assertAlmostEqual(store.get("2x8_120x36").x.gap_mm, 5.0)
        finally:
            root.destroy()


class SheetPreviewTests(unittest.TestCase):
    def test_preview_click_and_toggle(self) -> None:
        from main import LabelApp

        app = LabelApp()
        app.withdraw()
        try:
            app.update()
            app.sheet_preview.render_now()
            self.assertIn((0, 0), app.sheet_preview._contents)
            x0, y0, x1, y1 = app.sheet_preview._cell_box((1, 1))
            event = type("E", (), {"x": (x0 + x1) / 2, "y": (y0 + y1) / 2})()
            app.sheet_preview._on_left(event)
            self.assertEqual(app.active_cell, (1, 1))
            self.assertFalse(app.cell_vars[(1, 1)].get())
            app.sheet_preview._on_right(event)
            self.assertTrue(app.cell_vars[(1, 1)].get())
            self.assertIn("B2", app.var_positions.get())
            self.assertIn((1, 1), app.sheet_preview._selected)
        finally:
            app.destroy()


class DocumentTests(unittest.TestCase):
    def test_sheet_definition_embedded(self) -> None:
        from main import LabelApp

        app = LabelApp()
        app.withdraw()
        try:
            state = app._export_state()
            self.assertEqual(state["sheet_definition"]["id"], state["sheet_preset"])
            foreign = dict(state["sheet_definition"], id="cizi_arch", name="Cizí", cols=1)
            state["sheet_preset"] = "cizi_arch"
            state["sheet_definition"] = foreign
            state["positions"] = "A1"
            app._apply_state(state)
            self.assertEqual(app._current_preset().id, "cizi_arch")
            self.assertEqual(app._layout().cols, 1)
        finally:
            app.destroy()

    def test_export_apply_roundtrip(self) -> None:
        from main import LabelApp

        app = LabelApp()
        app.withdraw()
        try:
            app.txt.delete("1.0", "end")
            app.txt.insert("1.0", "Marie Svobodová\nNáměstí 5\n602 00 Brno")
            apply_size_on_range(app.txt, 12.5, "1.0", "end-1c")
            app.var_mode.set("Jen text")
            app.var_positions.set("A1,B2")
            app.var_align.set("left")

            state = app._export_state()
            self.assertEqual(state["text"].splitlines()[0], "Marie Svobodová")
            self.assertTrue(state.get("runs"))

            app.txt.delete("1.0", "end")
            app.var_positions.set("H3")
            app._apply_state(state)

            self.assertIn("Marie Svobodová", app.txt.get("1.0", "end-1c"))
            self.assertEqual(app.var_positions.get(), "A1,B2")
            self.assertEqual(app.var_align.get(), "left")
        finally:
            app.destroy()

    def test_rich_selection_roundtrip(self) -> None:
        from main import LabelApp

        app = LabelApp()
        app.withdraw()
        try:
            app.txt.delete("1.0", "end")
            app.txt.insert("1.0", "ABC\nDEF")
            apply_size_on_range(app.txt, 11, "1.0", "end-1c")
            toggle_tag_on_range(app.txt, "bold", "1.0", "1.3")
            apply_size_on_range(app.txt, 16, "1.0", "1.3")
            toggle_tag_on_range(app.txt, "italic", "2.0", "2.3")
            runs = dump_text_runs(app.txt, 11)
            self.assertTrue(any(r.bold and r.size == 16 for r in runs))
            self.assertTrue(any(r.italic for r in runs))
            snap = app._snapshot_editor()
            app._load_editor_from_state(snap)
            runs2 = dump_text_runs(app.txt, 11)
            self.assertEqual(runs_to_plain(runs2), "ABC\nDEF")
            self.assertTrue(any(r.bold and abs(r.size - 16) < 0.1 for r in runs2))
        finally:
            app.destroy()

    def test_clear_and_duplicate_to_last_free(self) -> None:
        from main import LabelApp

        app = LabelApp()
        app.withdraw()
        try:
            app.txt.delete("1.0", "end")
            app.txt.insert("1.0", "Adresa jedna")
            app._capture_editor_to_active()
            self.assertEqual(app.active_cell, (0, 0))

            app._duplicate_to_first_free()
            # A1 má obsah → první volná je A2
            self.assertEqual(app.active_cell, (0, 1))
            self.assertIn("Adresa jedna", app.label_states["A2"]["text"])
            self.assertTrue(app.cell_vars[(0, 1)].get())

            app._clear_active_box()
            self.assertEqual(app.txt.get("1.0", "end-1c").strip(), "")
            self.assertTrue(app._is_empty_state(app.label_states.get("A2")))
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
