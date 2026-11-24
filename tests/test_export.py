"""Unit tests for scripts/export.py. Run: uv run --locked python -m unittest discover -s tests -v"""

import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

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
        for value in (
            "2026-11-13",
            "Fri Nov 13 09:00:00 PST 2026",
            "Fri Foo 13 09:00:00 CET 2026",
            "garbage",
        ):
            with self.assertRaises(ValueError):
                export.parse_ine_date(value)
        for value in (True, [1], {"a": 1}):
            with self.assertRaises(TypeError):
                export.parse_ine_date(value)

    def test_format_falls_back_to_raw_value(self):
        with mock.patch("builtins.print"):
            self.assertEqual(export.format_ine_date("garbage"), "garbage")
            self.assertEqual(
                export.format_ine_date("Fri Feb 30 09:00:00 CET 2026"),
                "Fri Feb 30 09:00:00 CET 2026",
            )
            self.assertEqual(export.format_ine_date(float("inf")), "inf")
            self.assertEqual(export.format_ine_date(True), "True")


class Retry(unittest.TestCase):
    def call(self, *errors):
        """Run retry() over a fn raising `errors` in turn, then returning "ok"."""
        errors = list(errors)
        calls = []

        def fn():
            calls.append(1)
            if errors:
                raise errors.pop(0)
            return "ok"

        with mock.patch("time.sleep"), mock.patch("builtins.print"):
            try:
                return export.retry(fn, "x"), len(calls)
            except Exception as e:  # noqa: BLE001
                return e, len(calls)

    def http(self, code):
        return HTTPError("u", code, "msg", None, None)

    def test_retries_transient_errors(self):
        self.assertEqual(
            self.call(OSError(), self.http(503), self.http(429)), ("ok", 4)
        )

    def test_gives_up_after_attempts(self):
        result, calls = self.call(*[OSError()] * export.ATTEMPTS)
        self.assertIsInstance(result, OSError)
        self.assertEqual(calls, export.ATTEMPTS)

    def test_no_retry_on_client_error_or_unavailable(self):
        for error in (self.http(404), export.Unavailable()):
            self.assertEqual(self.call(error), (error, 1))


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

    def test_step_errors_are_recorded(self):
        def fail(table_id, directory):
            raise export.Unavailable("nope")

        _, errors = self.run_table(TABLE, data=fail, series=fail)
        self.assertEqual(
            errors,
            {"datos": "Unavailable: nope", "metadatos_series": "Unavailable: nope"},
        )

    def test_unexpected_error_does_not_raise(self):
        # No "Id" at all: export_table must still return instead of raising.
        table_id, errors = self.run_table({"Nombre": "x"})
        self.assertIsNone(table_id)
        self.assertIn("table", errors)


class MainThresholds(unittest.TestCase):
    """main() end to end with mocked network: thresholds and failures.json shape."""

    def run_main(self, data, readme_fails=()):
        tables = [{"Id": i} for i in range(1, 11)]

        def fake_readme(table):
            if table["Id"] in readme_fails:
                raise ValueError("bad readme")
            return "ok"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with (
                mock.patch.object(export, "OUT", out),
                mock.patch.object(export, "TABLES", out / "tablas"),
                mock.patch.object(export, "export_base", return_value=tables),
                mock.patch.object(export, "export_data", data),
                mock.patch.object(export, "export_series", lambda *a: None),
                mock.patch.object(export, "readme", fake_readme),
                mock.patch.object(sys, "argv", ["export.py", "--workers", "1"]),
                mock.patch("time.sleep"),
                mock.patch("builtins.print"),
            ):
                try:
                    export.main()
                    code = None
                except SystemExit as e:
                    code = e.code
            return code, json.loads((out / "failures.json").read_text("utf-8"))

    @staticmethod
    def data_failing_for(*ids):
        def data(table_id, directory):
            if table_id in ids:
                raise export.Unavailable("no")
            (directory / "datos.parquet").write_bytes(b"ok")

        return data

    def test_ten_percent_without_datos_is_ok(self):
        code, failures = self.run_main(self.data_failing_for(1))
        self.assertIsNone(code)
        self.assertEqual(failures, {"1": {"datos": "Unavailable: no"}})

    def test_over_ten_percent_without_datos_fails(self):
        code, failures = self.run_main(self.data_failing_for(1, 2))
        self.assertIn("Too many tables failed", code)
        self.assertEqual(set(failures), {"1", "2"})

    def test_over_ten_percent_readme_errors_fails(self):
        code, failures = self.run_main(self.data_failing_for(), readme_fails=(1, 2))
        self.assertIn("2 with readme/table errors", code)
        self.assertEqual(failures["1"], {"readme": "ValueError: bad readme"})


if __name__ == "__main__":
    unittest.main()
