"""Credential/provider/cache/backoff coverage without real keys or network."""
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import format_datetime
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import zlib
import time
import tkinter as tk
from tkinter import ttk

from subnet_watch.app import App
from subnet_watch.core import Sample, make_alert, evaluate
from subnet_watch.credentials import CredentialStore, CredentialError, WindowsDPAPI
from subnet_watch.polling import PollingPolicy, monthly_estimate, retry_after_seconds
from subnet_watch.providers import TaostatsProvider, ProviderError
from subnet_watch.storage import Store
from urllib.error import HTTPError


TEST_CREDENTIAL = "unit-test-placeholder-not-a-real-key"


class TestProtector:
    """Injected test-only stand-in; never used by the application."""
    def protect(self, data):
        return b"testing:" + bytes(value ^ 0xA5 for value in data)

    def unprotect(self, data):
        if not data.startswith(b"testing:"):
            raise CredentialError("Cannot unlock for this test user.")
        return bytes(value ^ 0xA5 for value in data[8:])


def live_sample(price="0.2", when=None):
    when = when or time.time()
    return Sample("taostats:19", 19, "Fixture subnet", Decimal(price), Decimal("-2.5"), when, when, "taostats",
                  {"liquidity": Decimal("500"), "block_number": 123})


class DirectoryTest(unittest.TestCase):
    def setUp(self):
        qa = Path(__file__).resolve().parent.parent / "qa"
        qa.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=qa)
        self.db = Path(self.temp.name) / "test.sqlite3"

    def tearDown(self):
        self.temp.cleanup()


class CredentialTests(DirectoryTest):
    def test_protected_roundtrip_replace_delete_no_plaintext(self):
        vault = CredentialStore.for_database(self.db, TestProtector())
        self.assertIsNone(vault.load())
        vault.save(TEST_CREDENTIAL)
        self.assertNotIn(TEST_CREDENTIAL.encode(), vault.path.read_bytes())
        self.assertEqual(vault.load(), TEST_CREDENTIAL)
        vault.save(TEST_CREDENTIAL + "-replacement")
        self.assertEqual(vault.load(), TEST_CREDENTIAL + "-replacement")
        vault.delete()
        self.assertFalse(vault.exists)
        vault.delete()

    def test_wrong_user_and_damaged_blob_fail_closed(self):
        vault = CredentialStore.for_database(self.db, TestProtector())
        vault.save(TEST_CREDENTIAL)
        class WrongUser:
            def unprotect(self, data):
                raise ValueError("Unexpected sensitive diagnostics that must never escape")
        vault.protector = WrongUser()
        with self.assertRaises(CredentialError) as caught:
            vault.load()
        self.assertNotIn("sensitive", str(caught.exception))
        vault.path.write_bytes(b"damaged")
        with self.assertRaises(CredentialError):
            vault.load()

    def test_other_platform_never_saves_plaintext(self):
        vault = CredentialStore.for_database(self.db)
        with patch("subnet_watch.credentials.sys.platform", "linux"):
            with self.assertRaises(CredentialError):
                vault.save(TEST_CREDENTIAL)
        self.assertFalse(vault.exists)

    def test_failed_replacement_preserves_existing_credential(self):
        vault = CredentialStore.for_database(self.db, TestProtector())
        vault.save(TEST_CREDENTIAL)
        before = vault.path.read_bytes()
        class Failure:
            def protect(self, data):
                raise RuntimeError("Unsafe diagnostic")
        vault.protector = Failure()
        with self.assertRaises(CredentialError):
            vault.save("replacement-placeholder")
        self.assertEqual(vault.path.read_bytes(), before)

    def test_header_controls_rejected(self):
        vault = CredentialStore.for_database(self.db, TestProtector())
        with self.assertRaises(CredentialError):
            vault.save("example\r\nInjected: header")
        self.assertFalse(vault.exists)


class MetricTests(unittest.TestCase):
    def test_all_documented_metrics_scale_and_counts(self):
        row = {"netuid": 19, "name": "Fixture", "price": "0.000851835", "timestamp": "2026-10-09T23:00:00Z",
               "price_change_1_day": "-5", "price_change_1_hour": "1.2", "price_change_1_week": "-12.3",
               "price_change_1_month": "30", "liquidity": "560550190686", "total_tao": "280275141546",
               "market_cap": "1000000000000", "total_alpha": "2000000000000", "alpha_in_pool": "1000000000",
               "alpha_staked": "1999000000000", "tao_volume_24_hr": "62023561032",
               "tao_buy_volume_24_hr": "30000000000", "tao_sell_volume_24_hr": "32023561032",
               "buys_24_hr": 100, "sells_24_hr": "80", "buyers_24_hr": 20, "sellers_24_hr": 18, "block_number": 123}
        sample = TaostatsProvider.parse_pool(row, {}, time.time())
        self.assertEqual(sample.price, Decimal("0.000851835"))
        self.assertEqual(sample.change_24h, Decimal("-5"))
        self.assertEqual(sample.metrics["liquidity"], Decimal("560.550190686"))
        self.assertEqual(sample.metrics["total_tao"], Decimal("280.275141546"))
        self.assertEqual(sample.metrics["tao_volume_24_hr"], Decimal("62.023561032"))
        self.assertEqual(sample.metrics["alpha_in_pool"], Decimal("1"))
        self.assertEqual(sample.metrics["price_change_1_week"], Decimal("-12.3"))
        self.assertEqual(sample.metrics["sells_24_hr"], 80)

    def test_missing_negative_invalid_metrics_unavailable(self):
        row = {"netuid": 19, "price": "0.2", "liquidity": "-1", "market_cap": "NaN",
               "tao_volume_24_hr": None, "buys_24_hr": "1.5", "sells_24_hr": -1, "buyers_24_hr": True}
        sample = TaostatsProvider.parse_pool(row, {}, time.time())
        for field in ("liquidity", "market_cap", "tao_volume_24_hr", "buys_24_hr", "sells_24_hr", "buyers_24_hr", "price_change_1_month"):
            self.assertIsNone(sample.metrics[field])

    def test_metadata_cache_avoids_additional_startup_call(self):
        calls = []
        def transport(path, page):
            calls.append(path)
            return {"data": [{"netuid": 19, "price": "0.2"}], "pagination": {"next_page": None}}
        provider = TaostatsProvider(TEST_CREDENTIAL, transport, {19: "Cached identity"}, time.time())
        self.assertEqual(provider.fetch()[0].name, "Cached identity")
        self.assertEqual(calls, [provider.pool_path])

    def test_pool_auth_failure_stops_before_metadata(self):
        calls = []
        def transport(path, page):
            calls.append(path)
            raise ProviderError("API key was rejected.", 401)
        provider = TaostatsProvider(TEST_CREDENTIAL, transport)
        with self.assertRaises(ProviderError):
            provider.fetch()
        self.assertEqual(calls, [provider.pool_path])

    def test_http_429_retry_after_and_no_unsafe_response_details(self):
        provider = TaostatsProvider(TEST_CREDENTIAL)
        class Opener:
            def open(self, request, timeout):
                raise HTTPError(request.full_url, 429, "Do not display this remote error", {"Retry-After": "900"}, None)
        with patch("subnet_watch.providers.build_opener", return_value=Opener()):
            with self.assertRaises(ProviderError) as caught:
                provider.fetch()
        self.assertEqual(caught.exception.status, 429)
        self.assertEqual(caught.exception.retry_after, 900)
        self.assertNotIn("remote error", str(caught.exception))
        self.assertNotIn(TEST_CREDENTIAL, str(caught.exception))

    def test_optional_name_rate_limit_preserves_prices_but_delays_polling(self):
        def transport(path, page):
            if "identity" in path:
                raise ProviderError("Rate limited", 429, 900)
            return {"data": [{"netuid": 19, "price": ".2"}], "pagination": {"next_page": None}}
        provider = TaostatsProvider(TEST_CREDENTIAL, transport)
        self.assertEqual(len(provider.fetch()), 1)
        self.assertEqual(provider.advisory_error.retry_after, 900)

    def test_duplicate_pagination_does_not_publish_incomplete_catalog(self):
        provider = TaostatsProvider(TEST_CREDENTIAL, lambda path, page: {
            "data": [{"netuid": 19, "price": ".2"}], "pagination": {"next_page": 2 if page == 1 else None}})
        with self.assertRaises(ProviderError):
            provider.fetch()


class CacheTests(DirectoryTest):
    def setUp(self):
        super().setUp()
        self.store = Store(self.db)

    def tearDown(self):
        self.store.close()
        super().tearDown()

    def test_restart_preserves_both_times_metrics_and_no_cached_trigger(self):
        sample = live_sample()
        a = make_alert(sample, "target", "down", ".3", False, 0, sample.observed_time)
        self.store.cache_catalog("taostats", [sample], sample.observed_time)
        self.store.close()
        self.store = Store(self.db)
        loaded = self.store.cached_catalog("taostats")[0]
        self.assertEqual(loaded.source_time, sample.source_time)
        self.assertEqual(loaded.observed_time, sample.observed_time)
        self.assertEqual(loaded.metrics, sample.metrics)
        self.assertTrue(loaded.cached)
        self.assertFalse(loaded.fresh(time.time()))
        self.assertIsNone(evaluate(a, loaded, time.time()))
        self.assertIsNone(a.last_seen)

    def test_complete_catalog_removes_missing_subnet_preserving_watch(self):
        sample = live_sample()
        self.store.add_watch(sample)
        self.store.cache_catalog("taostats", [sample], sample.observed_time)
        self.store.cache_catalog("taostats", [], sample.observed_time+1)
        self.assertFalse(self.store.cached_catalog("taostats"))
        self.assertIn(sample.key, self.store.watched())

    def test_compressed_archive_retention_and_identity_cache(self):
        sample = live_sample()
        self.store.cache_catalog("taostats", [sample], 1000)
        self.store.cache_catalog("taostats", [sample], 1000+8*86400)
        rows = self.store.connection.execute("SELECT body FROM snapshots").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(zlib.decompress(rows[0][0]))[0]["source_time"], sample.source_time)
        self.store.save_metadata("taostats", {19: "Cached identity"}, 12345)
        self.assertEqual(self.store.metadata("taostats"), ({19: "Cached identity"}, 12345))

    def test_archive_count_bound(self):
        with patch("subnet_watch.storage.ARCHIVE_MAX_BATCHES", 2):
            for i in range(3):
                self.store.cache_catalog("taostats", [live_sample()], 1000+i)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM snapshots").fetchone()[0], 2)

    def test_archive_byte_bound(self):
        with patch("subnet_watch.storage.ARCHIVE_MAX_BYTES", 1):
            self.store.cache_catalog("taostats", [live_sample()], time.time())
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM snapshots").fetchone()[0], 0)


class PollingTests(unittest.TestCase):
    def test_numeric_and_http_date_retry_after(self):
        self.assertEqual(retry_after_seconds("120", 1000), 120)
        date = format_datetime(datetime.fromtimestamp(1120, timezone.utc), usegmt=True)
        self.assertEqual(retry_after_seconds(date, 1000), 120)
        self.assertIsNone(retry_after_seconds("bad", 1000))
        self.assertIsNone(retry_after_seconds("Infinity", 1000))

    def test_rate_limit_cannot_be_bypassed_and_backoff_bounded(self):
        policy = PollingPolicy(300)
        policy.fail(ProviderError("Rate limited", 429, 1200), 1000)
        self.assertEqual(policy.next_allowed, 2200)
        self.assertFalse(policy.automatic_allowed(2199))
        self.assertFalse(policy.manual_allowed(2199))
        self.assertTrue(policy.manual_allowed(2200))
        for i in range(12):
            policy.fail(ProviderError("Connection failed"), 3000+i)
        self.assertEqual(policy.failures, 6)
        self.assertEqual(policy.next_allowed-(3000+11), 3600)
        self.assertFalse(policy.automatic_allowed(policy.next_allowed-1))
        self.assertTrue(policy.automatic_allowed(policy.next_allowed))
        policy.success(100000)
        self.assertEqual(policy.failures, 0)
        self.assertEqual(policy.next_allowed, 100300)

    def test_long_retry_after_and_legacy_exhaustion_remain_recoverable(self):
        policy = PollingPolicy(300)
        for i in range(8):
            policy.fail(ProviderError("Rate limited", 429, 7200), 1000)
        self.assertEqual(policy.next_allowed, 8200)
        restarted = PollingPolicy(300)
        legacy_state = policy.to_dict()
        legacy_state["exhausted"] = True
        restarted.restore(legacy_state)
        self.assertFalse(restarted.manual_allowed(8199))
        self.assertFalse(restarted.automatic_allowed(8199))
        self.assertTrue(restarted.automatic_allowed(8200))

    def test_auth_pause_persists_and_success_resets(self):
        policy = PollingPolicy(300)
        policy.fail(ProviderError("Rejected", 401), 1000)
        restarted = PollingPolicy(300)
        restarted.restore(policy.to_dict())
        self.assertFalse(restarted.automatic_allowed(100000))
        self.assertFalse(restarted.manual_allowed(100000))
        restarted.success(100000)
        self.assertFalse(restarted.auth_failed)
        self.assertEqual(restarted.next_allowed, 100300)

    def test_request_budget_accounts_for_pages(self):
        self.assertEqual(monthly_estimate(1, 1, 300), 9052)
        self.assertEqual(monthly_estimate(2, 1, 300), 17980)
        self.assertEqual(monthly_estimate(1, 1, 30), 89404)


class FakeProvider:
    source = "taostats"
    pool_path = TaostatsProvider.pool_path
    identity_path = TaostatsProvider.identity_path
    def __init__(self, key, names=None, metadata_at=0):
        self.names = names or {}
        self.metadata_at = metadata_at
        self.page_counts = {self.pool_path: 1, self.identity_path: 1}


class StartupTests(DirectoryTest):
    def setUp(self):
        super().setUp()
        self.vault = CredentialStore.for_database(self.db, TestProtector())
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = None

    def tearDown(self):
        self.root.update_idletasks()
        if self.app:
            self.app.close()
        else:
            self.root.destroy()
        super().tearDown()

    def start(self):
        self.app = App(self.root, self.db, notifications=False, credentials=self.vault, provider_factory=FakeProvider)
        return self.app

    def test_auto_saved_credential_and_cache_no_startup_events(self):
        self.vault.save(TEST_CREDENTIAL)
        store = Store(self.db)
        sample = live_sample(".4")
        store.set_setting("mode", "taostats")
        store.cache_catalog("taostats", [sample], sample.observed_time)
        store.save_alert(make_alert(sample, "target", "up", ".3", False, 0, sample.observed_time))
        store.close()
        app = self.start()
        self.assertIsNotNone(app.provider)
        self.assertEqual(app.interval, 30)
        self.assertTrue(app.samples[sample.key].cached)
        self.assertFalse(app.store.history())
        self.assertFalse(app.alerts[0].done)

    def test_live_same_timestamp_replaces_cache_without_retriggering(self):
        self.vault.save(TEST_CREDENTIAL)
        sample = live_sample(".4")
        store = Store(self.db)
        store.set_setting("mode", "taostats")
        store.cache_catalog("taostats", [sample], sample.observed_time)
        a = make_alert(sample, "target", "up", ".3", False, 0, sample.observed_time)
        event = evaluate(a, sample, sample.observed_time)
        store.persist_evaluation([a], [event])
        store.close()
        app = self.start()
        app.apply_samples([sample])
        self.assertFalse(app.samples[sample.key].cached)
        self.assertTrue(app.samples[sample.key].fresh(time.time()))
        self.assertEqual(len(app.store.history()), 1)

    def test_settings_unchanged_key_preserves_rate_limit_and_auth_pause(self):
        self.vault.save(TEST_CREDENTIAL)
        app = self.start()
        app.policy.fail(ProviderError("Rate limited", 429, 1200), time.time())
        deadline = app.policy.next_allowed
        app.configure_connection("taostats", "", True, 60)
        self.assertEqual(app.policy.next_allowed, deadline)
        self.assertFalse(app.policy.manual_allowed(time.time()))
        app.policy.fail(ProviderError("Rejected", 401), time.time())
        app.configure_connection("taostats", "", True, 300)
        self.assertTrue(app.policy.auth_failed)
        app.configure_connection("taostats", TEST_CREDENTIAL + "-replacement", True, 300)
        self.assertFalse(app.policy.auth_failed)

    def test_demo_switch_cannot_bypass_saved_live_backoff(self):
        self.vault.save(TEST_CREDENTIAL)
        app = self.start()
        app.policy.fail(ProviderError("Rate limited", 429, 1200), time.time())
        deadline = app.policy.next_allowed
        app.configure_connection("demo", "", True, 300)
        app.configure_connection("taostats", "", True, 300)
        self.assertEqual(app.policy.next_allowed, deadline)

    def test_explicit_interval_retained_and_forget_disconnects(self):
        self.vault.save(TEST_CREDENTIAL)
        store = Store(self.db)
        store.set_setting("mode", "taostats")
        store.set_setting("interval", 60)
        store.close()
        app = self.start()
        self.assertEqual(app.interval, 60)
        app.forget_credentials()
        self.assertFalse(self.vault.exists)
        self.assertIsNone(app.provider)
        self.assertEqual(app.api_key, "")

    def test_settings_form_masks_replacement_and_keeps_empty_current_key(self):
        self.vault.save(TEST_CREDENTIAL)
        app = self.start()
        app.next_refresh = float("inf")
        dialog = app.settings()
        def descendants(widget):
            return [child for w in widget.winfo_children() for child in [w, *descendants(w)]]
        fields = [w for w in descendants(dialog) if type(w) is ttk.Entry]
        self.assertEqual(fields[0].cget("show"), "•")
        self.assertEqual(fields[0].get(), "")
        fields[1].delete(0, "end")
        fields[1].insert(0, "30")
        save = next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget("text") == "Save & connect")
        save.invoke()
        self.assertEqual(app.api_key, TEST_CREDENTIAL)
        self.assertEqual(self.vault.load(), TEST_CREDENTIAL)
        self.assertEqual(app.store.setting("mode"), "taostats")
        self.assertEqual(app.interval, 30)
        self.assertEqual(app.store.setting("interval"), 30)

    def test_chart_rate_limit_persists_even_when_details_closes(self):
        self.vault.save(TEST_CREDENTIAL)
        app = self.start()
        app.next_refresh = float("inf")
        sample = live_sample()
        app.apply_samples([sample])
        def fail(*args):
            raise ProviderError("Rate limited", 429, 900)
        app.provider.fetch_candles = fail
        app.catalog.selection_set(sample.key)
        dialog = app.subnet_details()
        dialog.destroy()
        deadline = time.monotonic()+2
        while not app.policy.failures and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertEqual(app.policy.failures, 1)
        self.assertGreater(app.store.setting("polling")["next_allowed"], time.time()+850)


if __name__ == "__main__":
    unittest.main()
