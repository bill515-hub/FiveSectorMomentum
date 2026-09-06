from __future__ import annotations

import os
import unittest

import pandas as pd

from five_sector_momentum.v6_1.canonical import table_hash
from five_sector_momentum.v6_1.probe_errors import call_with_evidence, classify_exception


class ProbeClassificationTests(unittest.TestCase):
    def test_windows_socket_permissions_is_network_blocked(self):
        exc = ConnectionError("WinError 10013: socket access forbidden by its access permissions")
        evidence = classify_exception(exc, "ft_limit")
        self.assertEqual(evidence.classification, "NETWORK_BLOCKED")
        self.assertNotEqual(evidence.classification, "APPLICATION_NO_PERMISSION")

    def test_generic_connection_error_is_transport(self):
        evidence = classify_exception(ConnectionError("temporary connection failure"), "fut_settle")
        self.assertEqual(evidence.classification, "NETWORK_ERROR")
        self.assertEqual(evidence.layer, "TRANSPORT")

    def test_exact_tushare_no_permission_is_application(self):
        evidence = classify_exception(Exception("抱歉，您没有接口(ft_limit)的访问权限"), "ft_limit")
        self.assertEqual(evidence.classification, "APPLICATION_NO_PERMISSION")
        self.assertEqual(evidence.layer, "TUSHARE_APPLICATION")

    def test_rate_limit(self):
        evidence = classify_exception(Exception("每分钟最多访问 10 次"), "fut_settle")
        self.assertEqual(evidence.classification, "RATE_LIMITED")

    def test_empty_success_is_silent_empty(self):
        frame, state, rows = call_with_evidence("x", "y", lambda: pd.DataFrame())
        self.assertTrue(frame.empty)
        self.assertEqual(state, "SILENT_EMPTY")
        self.assertEqual(len(rows), 1)

    def test_network_retries_exact_backoff(self):
        calls, waits = [], []
        def broken():
            calls.append(1)
            raise ConnectionError("temporary")
        _, state, rows = call_with_evidence("x", "y", broken, sleep=waits.append)
        self.assertEqual(state, "NETWORK_ERROR")
        self.assertEqual(len(calls), 4)
        self.assertEqual(waits, [1, 3, 9])
        self.assertEqual(len(rows), 4)

    def test_canonical_hash_ignores_row_order_when_sorted(self):
        a = pd.DataFrame({"k": [2, 1], "v": ["b", "a"]})
        b = a.iloc[::-1].reset_index(drop=True)
        self.assertEqual(table_hash(a, ["k"]), table_hash(b, ["k"]))

    def test_attempt_evidence_never_contains_environment_token(self):
        old = os.environ.get("TUSHARE_TOKEN")
        os.environ["TUSHARE_TOKEN"] = "x" * 40
        try:
            _, _, rows = call_with_evidence("x", "y", lambda: (_ for _ in ()).throw(Exception("endpoint error")))
            self.assertNotIn("x" * 40, repr(rows))
        finally:
            if old is None:
                os.environ.pop("TUSHARE_TOKEN", None)
            else:
                os.environ["TUSHARE_TOKEN"] = old


if __name__ == "__main__":
    unittest.main()
