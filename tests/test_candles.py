"""Candle validation, history request limits and native chart interactions."""
from decimal import Decimal
from types import SimpleNamespace
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch
from subnet_watch.candles import Candle, CandleHistory, HistoryWait, parse_candles
from subnet_watch.chart import CandleChart
from subnet_watch.providers import TaostatsProvider, ProviderError


def bars():
    return {"s": "ok", "t": [200, 100], "o": [".2", ".3"], "h": [".3", ".4"],
            "l": [".1", ".2"], "c": [".25", ".25"]}


class CandleTests(unittest.TestCase):
    def test_chronological_tao_prices_and_range(self):
        result = parse_candles(bars(), 100, 200)
        self.assertEqual([c.time for c in result], [100, 200])
        self.assertEqual(result[-1].close, Decimal(".25"))
        self.assertEqual(len(parse_candles(bars(), 150, 200)), 1)

    def test_no_data_and_untrusted_error(self):
        self.assertEqual(parse_candles({"s": "no_data"}, 0, 300), [])
        with self.assertRaises(ProviderError) as caught:
            parse_candles({"s": "error", "errmsg": "Do not display remote content"}, 0, 300)
        self.assertNotIn("remote content", str(caught.exception))

    def test_bad_columns_timestamps_and_ohlc_rejected(self):
        mutations = [("t", [100, 100]), ("t", [True, 200]), ("t", [100.5, 200]),
                     ("t", [100]), ("o", None), ("o", ["NaN", ".2"]),
                     ("c", [0, ".2"]), ("h", [".1", ".4"]), ("l", [".4", ".2"])]
        for key, value in mutations:
            with self.subTest(key=key, value=value), self.assertRaises(ProviderError):
                payload = bars()
                payload[key] = value
                parse_candles(payload, 0, 300)

    def test_subnet_history_request_has_expected_symbol_and_no_usd_scaling(self):
        calls = []
        def transport(path, parameters):
            calls.append((path, parameters))
            return bars()
        provider = TaostatsProvider("unit-test-placeholder", transport)
        candles = provider.fetch_candles(19, "60", 100, 200)
        self.assertEqual(candles[-1].close, Decimal(".25"))
        self.assertEqual(calls[0], (provider.candle_path, {"symbol": "SUB-19", "resolution": "60",
                                                         "from": 100, "to": 200, "countback": 200}))
        with self.assertRaises(ProviderError):
            provider.fetch_candles(0, "60", 100, 200)

    def test_recent_cache_avoids_request_and_cooldown_applies_across_subnets(self):
        calls = []
        provider = SimpleNamespace(source="taostats", fetch_candles=lambda *args: calls.append(args) or [])
        history = CandleHistory()
        with patch("subnet_watch.candles.time.time", return_value=100000):
            first = history.load(provider, 19, "1 hour · 7 days")
            cached = history.load(provider, 19, "1 hour · 7 days")
            self.assertFalse(first[2])
            self.assertTrue(cached[2])
            self.assertEqual(len(calls), 1)
            with self.assertRaises(ProviderError):
                history.load(provider, 20, "1 hour · 7 days")
            with self.assertRaises(ProviderError):
                history.load(provider, 19, "1 hour · 7 days", force=True)
        with patch("subnet_watch.candles.time.time", return_value=100031):
            history.load(provider, 19, "1 hour · 7 days", force=True)
        with patch("subnet_watch.candles.time.time", return_value=100400):
            history.load(provider, 19, "1 hour · 7 days")
        self.assertEqual(len(calls), 3)

    def test_retry_after_and_cache_capacity(self):
        history = CandleHistory()
        provider = SimpleNamespace(source="taostats", fetch_candles=lambda *args: [])
        with patch("subnet_watch.candles.time.time", return_value=100000):
            def fail(*args):
                raise ProviderError("Rate limited", 429, 900)
            provider.fetch_candles = fail
            with self.assertRaises(ProviderError):
                history.load(provider, 19, "1 hour · 7 days")
            self.assertEqual(history.next_allowed, 100900)
        provider.fetch_candles = lambda *args: []
        for i in range(40):
            with patch("subnet_watch.candles.time.time", return_value=101000+i*31):
                history.load(provider, i+1, "1 hour · 7 days")
        self.assertEqual(len(history.cache), 32)


class ChartTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.callback_errors = []
        self.root.report_callback_exception = lambda *args: self.callback_errors.append(args)
        self.root.geometry("820x530")
        self.errors = []
        self.chart = CandleChart(self.root, lambda chosen, force: (parse_candles(bars(), 0, 300), time.time(), False),
                                 lambda: "", self.errors.append)
        self.chart.pack(fill="both", expand=True)

    def tearDown(self):
        self.root.destroy()
        self.assertFalse(self.callback_errors)

    def finish(self):
        deadline = time.monotonic()+2
        while self.chart.loading and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(self.chart.loading)

    def test_draw_hover_resize_and_flat_price(self):
        self.chart.load()
        self.finish()
        self.assertEqual(len(self.chart.canvas.find_withtag("wick")), 2)
        self.chart.hover(SimpleNamespace(x=self.chart.positions[-1]))
        self.assertIn("O 0.2", self.chart.inspect.cget("text"))
        self.assertIn("TAO / alpha", self.chart.inspect.cget("text"))
        self.root.geometry("600x390")
        self.root.update()
        self.chart.candles = [Candle(100, *[Decimal(".2")]*4)]
        self.chart.draw()
        self.assertEqual(len(self.chart.canvas.find_withtag("body")), 1)

    def test_network_error_empty_and_connection_changed_results(self):
        def fail(*args):
            raise ProviderError("Rate limited", 429, 60)
        self.chart.loader = fail
        self.chart.load()
        self.finish()
        self.assertEqual(self.errors[0].status, 429)
        self.assertEqual(self.chart.canvas.find_withtag("wick"), ())
        self.chart.loader = lambda *args: ([], time.time(), False)
        self.chart.load()
        self.chart.available = lambda: "Connection changed."
        self.finish()
        self.assertIn("Connection changed", self.chart.status.cget("text"))

    def test_closing_panel_while_request_in_flight(self):
        release = threading.Event()
        self.chart.loader = lambda *args: (release.wait(1) and [], time.time(), False)
        self.chart.load()
        self.chart.destroy()
        release.set()
        self.root.update()
        self.assertIsNone(self.chart.timer)

    def test_local_request_spacing_schedules_pending_chart_and_cancel_on_close(self):
        def wait(*args):
            raise HistoryWait(30)
        self.chart.loader = wait
        self.chart.load()
        self.finish()
        self.assertIsNotNone(self.chart.timer)
        self.assertIn("Loading this chart in 30 seconds", self.chart.status.cget("text"))
        self.assertFalse(self.errors)
        self.chart.destroy()
        self.assertIsNone(self.chart.timer)


if __name__ == "__main__":
    unittest.main()
