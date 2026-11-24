"""Unit tests for scripts/export.py. Run: make test"""

import io
import json
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import export

TABLE = {
    "Id": 1,
    "Nombre": "Tabla",
    "Ultima_Modificacion": "Fri Nov 13 09:00:00 CET 2026",
}


def quiet():
    return mock.patch("builtins.print")


class LastModified(unittest.TestCase):
    def test_epoch_ms(self):
        # Real values from the last export before the API change (tables 50902, 24077).
        self.assertEqual(export.last_modified(1749798000000), "2025-06-13")
        self.assertEqual(export.last_modified(1791961200000.0), "2026-10-14")

    def test_java_strings_match_old_epoch_ms(self):
        # 1749798000000 is 2025-06-13 07:00 UTC, i.e. 09:00 CEST.
        self.assertEqual(
            export.last_modified("Fri Jun 13 09:00:00 CEST 2025"), "2025-06-13"
        )
        self.assertEqual(
            export.last_modified("Fri Nov 13 09:00:00 CET 2026"), "2026-11-13"
        )

    def test_utc_date_crosses_midnight(self):
        self.assertEqual(
            export.last_modified("Thu Jan 01 00:30:00 CET 2026"), "2025-12-31"
        )
        self.assertEqual(
            export.last_modified("Mon Jun 01 01:30:00 CEST 2026"), "2026-05-31"
        )

    def test_missing(self):
        for value in (None, "", "null"):
            self.assertEqual(export.last_modified(value), "Desconocido")

    def test_unexpected_values_are_shown_raw(self):
        for value in (
            "2026-11-13",
            "Fri Nov 13 09:00:00 PST 2026",
            "Fri Feb 30 09:00:00 CET 2026",
            float("inf"),
            [1],
        ):
            with quiet():
                self.assertEqual(export.last_modified(value), str(value))

    def test_readme(self):
        self.assertIn("**Última Modificación**: 2026-11-13", export.readme(TABLE))
        self.assertIn("**Última Modificación**: Desconocido", export.readme({"Id": 1}))


class Retry(unittest.TestCase):
    def call(self, *errors):
        """Run retry() over a fn raising `errors` in turn, then returning "ok"."""
        fn = mock.Mock(side_effect=[*errors, "ok"])
        with mock.patch("time.sleep"), quiet():
            try:
                return export.retry(fn, "x"), fn.call_count
            except Exception as e:  # noqa: BLE001
                return e, fn.call_count

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


class TempOutput(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)
        for name, value in (("OUT", self.out), ("TABLES", self.out / "tablas")):
            patcher = mock.patch.object(export, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def steps(self, data=None, series=None):
        noop = mock.Mock()
        return (
            mock.patch.object(export, "export_data", data or noop),
            mock.patch.object(export, "export_series", series or noop),
        )


class ExportTable(TempOutput):
    def run_table(self, table=TABLE, deadline=float("inf"), **steps):
        data, series = self.steps(**steps)
        with data, series:
            return export.export_table(table, deadline)

    def test_ok(self):
        self.assertEqual(self.run_table(), {})
        self.assertTrue((self.out / "tablas/1/README.md").exists())
        self.assertTrue((self.out / "tablas/1/metadata.json").exists())

    def test_readme_error_still_exports_data(self):
        data = mock.Mock()
        with mock.patch.object(export, "readme", side_effect=TypeError("boom")):
            self.assertEqual(self.run_table(data=data), {"readme": "TypeError: boom"})
        data.assert_called_once()

    def test_step_errors_are_recorded(self):
        fail = mock.Mock(side_effect=export.Unavailable("nope"))
        self.assertEqual(
            self.run_table(data=fail, series=fail),
            {"datos": "Unavailable: nope", "metadatos_series": "Unavailable: nope"},
        )

    def test_past_deadline_is_skipped(self):
        data = mock.Mock()
        self.assertIsNone(self.run_table(deadline=0, data=data))
        data.assert_not_called()
        self.assertFalse((self.out / "tablas/1").exists())


class ExportData(TempOutput):
    def test_html_instead_of_csv_is_a_clear_error(self):
        # INE answers 202 + its HTML home page while it prepares a CSV.
        response = io.BytesIO(b"<!DOCTYPE html><html>INEbase</html>")
        response.status, response.headers = 202, Message()
        response.headers["Content-Type"] = "text/html;utf-8=;charset=UTF-8"
        directory = self.out / "1"
        directory.mkdir()
        with (
            mock.patch.object(export, "urlopen", return_value=response),
            self.assertRaisesRegex(RuntimeError, "HTTP 202 HTML, not the CSV"),
        ):
            export.export_data(1, directory)
        self.assertEqual(list(directory.iterdir()), [])


class Main(TempOutput):
    """main() end to end with the network mocked out."""

    def run_main(self, failing=(), skipped=()):
        tables = [{"Id": i} for i in range(1, 11)]
        real_export_table = export.export_table

        def export_table(table, deadline):
            return (
                None if table["Id"] in skipped else real_export_table(table, deadline)
            )

        def data(table_id, directory):
            if table_id in failing:
                raise export.Unavailable("no")

        data_patch, series_patch = self.steps(data=data)
        with (
            data_patch,
            series_patch,
            mock.patch.object(export, "export_base", return_value=tables),
            mock.patch.object(export, "export_table", export_table),
            mock.patch.object(sys, "argv", ["export.py", "--workers", "2"]),
            quiet(),
        ):
            try:
                export.main()
                code = None
            except SystemExit as e:
                code = e.code
        return code, json.loads((self.out / "failures.json").read_text("utf-8"))

    def test_ten_percent_failing_is_ok(self):
        code, failures = self.run_main(failing={1})
        self.assertIsNone(code)
        self.assertEqual(failures, {"1": {"datos": "Unavailable: no"}})

    def test_over_ten_percent_failing_fails(self):
        code, failures = self.run_main(failing={1, 2})
        self.assertEqual(
            code, "2 of 10 tables failed (see ine/failures.json), something is broken"
        )
        self.assertEqual(set(failures), {"1", "2"})

    def test_skipped_tables_are_not_failures(self):
        # Running out of time must not stop the finished tables from being uploaded.
        code, failures = self.run_main(skipped={6, 7, 8, 9, 10})
        self.assertIsNone(code)
        self.assertEqual(failures, {})

    def test_threshold_counts_attempted_tables_only(self):
        code, _ = self.run_main(failing={1}, skipped={6, 7, 8, 9, 10})
        self.assertEqual(
            code, "1 of 5 tables failed (see ine/failures.json), something is broken"
        )


if __name__ == "__main__":
    unittest.main()
