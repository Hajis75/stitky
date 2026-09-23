"""Jednoduché testy layoutu a renderu bez GUI."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from layout import SheetLayout, cell_name, parse_range
from renderer import LabelContent, RenderOptions, max_fitting_font_size, render_sheet_pdf, text_fits


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
        lay = SheetLayout(page_width_mm=217, print_width_mm=215, page_height_mm=304, print_height_mm=304)
        off_x, off_y = lay.print_offset_mm()
        self.assertAlmostEqual(off_x, 1.0, places=3)
        self.assertAlmostEqual(off_y, 0.0, places=3)

    def test_auto_gaps_fit_physical_page(self) -> None:
        lay = SheetLayout()
        ox, oy = lay.resolved_outer_margins()
        self.assertAlmostEqual(lay.content_height_mm() + 2 * oy, 304.0, places=2)
        self.assertAlmostEqual(lay.content_width_mm() + 2 * ox, 217.0, places=2)
        self.assertAlmostEqual(ox, lay.gap_x_mm(), places=4)

    def test_label_print_coords(self) -> None:
        lay = SheetLayout(outer_margin_x_mm=0.5, outer_margin_y_mm=2.0)
        x_phys, y_phys, w, h = lay.label_rect_mm(0, 0)
        x_print, y_print, _, _ = lay.label_rect_print_mm(0, 0)
        self.assertAlmostEqual(x_phys, 0.5, places=2)
        self.assertAlmostEqual(x_print, 0.5 - 1.0, places=2)  # − offset 1 mm
        self.assertAlmostEqual(y_print, y_phys, places=2)

    def test_nudge(self) -> None:
        lay = SheetLayout(nudge_x_mm=0.5, nudge_y_mm=-0.3)
        x0, y0, _, _ = SheetLayout().label_rect_print_mm(0, 0)
        x1, y1, _, _ = lay.label_rect_print_mm(0, 0)
        self.assertAlmostEqual(x1 - x0, 0.5, places=3)
        self.assertAlmostEqual(y1 - y0, -0.3, places=3)


class RenderTests(unittest.TestCase):
    def test_text_fit_and_pdf(self) -> None:
        text = "Jan Novák\nUlice 1\n110 00 Praha"
        ok, lines, _ = text_fits(text, 70, 36, 11)
        self.assertTrue(ok)
        size = max_fitting_font_size(text, 70, 36)
        self.assertGreaterEqual(size, 6)

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
            raw = path.read_bytes()
            self.assertIn(b"/MediaBox", raw)


if __name__ == "__main__":
    unittest.main()
