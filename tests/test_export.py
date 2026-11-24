"""Unit tests for scripts/export.py. Run: uv run --locked python -m unittest discover -s tests -v"""

import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import export


class ParseIneDate(unittest.TestCase):
    def test_epoch_ms_int_and_float(self):
        # Real values from the last good export (tables 50902 and 24077).
        self.assertEqual(
            export.parse_ine_date(1749798000000),
            datetime(2025, 6, 13, 7, 0, tzinfo=UTC),
        )
        self.assertEqual(
            export.parse_ine_date(1791961200000.0),
            datetime(2026, 10, 14, 7, 0, tzinfo=UTC),
        )

    def test_epoch_ms_as_string(self):
        self.assertEqual(
            export.parse_ine_date("1749798000000"),
            datetime(2025, 6, 13, 7, 0, tzinfo=UTC),
        )

    def test_java_string_cet(self):
        self.assertEqual(
            export.parse_ine_date("Fri Nov 13 09:00:00 CET 2026"),
            datetime(2026, 11, 13, 8, 0, tzinfo=UTC),
        )

    def test_java_string_cest(self):
        self.assertEqual(
            export.parse_ine_date("Fri Jun 13 09:00:00 CEST 2025"),
            datetime(2025, 6, 13, 7, 0, tzinfo=UTC),
        )

    def test_same_instant_in_both_formats(self):
        self.assertEqual(
            export.parse_ine_date("Fri Jun 13 09:00:00 CEST 2025"),
            export.parse_ine_date(1749798000000),
        )

    def test_utc_date_crosses_midnight(self):
        # 00:30 CET is the previous day in UTC, matching the old ms behaviour.
        self.assertEqual(
            export.format_ine_date("Thu Jan 01 00:30:00 CET 2026"), "2025-12-31"
        )

    def test_missing(self):
        for value in (None, "", "null", "  "):
            self.assertIsNone(export.parse_ine_date(value))
            self.assertEqual(export.format_ine_date(value), "Desconocido")

    def test_epoch_zero_is_not_missing(self):
        self.assertEqual(export.format_ine_date(0), "1970-01-01")

    def test_unknown_formats_raise(self):
        for value in ("2026-11-13", "Fri Nov 13 09:00:00 PST 2026", "garbage"):
            with self.assertRaises(ValueError):
                export.parse_ine_date(value)
        for value in (True, [1], {"a": 1}):
            with self.assertRaises(TypeError):
                export.parse_ine_date(value)

    def test_format_falls_back_to_raw_value(self):
        with mock.patch("builtins.print"):
            self.assertEqual(export.format_ine_date("garbage"), "garbage")
            self.assertEqual(export.format_ine_date(True), "True")


TABLE = {
    "Id": 1,
    "Nombre": "Tabla",
    "Codigo": "T",
    "Ultima_Modificacion": "Fri Nov 13 09:00:00 CET 2026",
}


class Readme(unittest.TestCase):
    def test_both_formats(self):
        for value in ("Fri Nov 13 09:00:00 CET 2026", 1794556800000):
            text = export.readme({**TABLE, "Ultima_Modificacion": value})
            self.assertIn("**Última Modificación**: 2026-11-13", text)

    def test_missing(self):
        text = export.readme({"Id": 1})
        self.assertIn("**Última Modificación**: Desconocido", text)


class ExportTable(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(export, "TABLES", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tables = Path(tmp.name)

    def run_table(self, table, data=None, series=None):
        noop = lambda table_id, directory: None
        with (
            mock.patch.object(export, "export_data", data or noop),
            mock.patch.object(export, "export_series", series or noop),
        ):
            return export.export_table(table)

    def test_ok(self):
        self.assertEqual(self.run_table(TABLE), (1, {}))
        self.assertTrue((self.tables / "1" / "README.md").exists())
        self.assertTrue((self.tables / "1" / "metadata.json").exists())

    def test_readme_error_still_exports_data(self):
        calls = []
        with mock.patch.object(export, "readme", side_effect=TypeError("boom")):
            table_id, errors = self.run_table(
                TABLE, data=lambda *a: calls.append("datos")
            )
        self.assertEqual(table_id, 1)
        self.assertEqual(errors, {"readme": "TypeError: boom"})
        self.assertEqual(calls, ["datos"])
        self.assertTrue((self.tables / "1" / "metadata.json").exists())

    def test_unexpected_error_does_not_raise(self):
        # No "Id" at all: export_table must still return instead of raising.
        table_id, errors = self.run_table({"Nombre": "x"})
        self.assertIsNone(table_id)
        self.assertIn("table", errors)


if __name__ == "__main__":
    unittest.main()
