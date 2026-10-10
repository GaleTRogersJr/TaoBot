import json
from pathlib import Path
import tempfile
import unittest
from decimal import Decimal
from subnet_watch.core import Sample, make_alert, evaluate, number, change_text, timestamp
from subnet_watch.storage import Store
from subnet_watch.providers import TaostatsProvider, ProviderError, NoRedirect


NOW = 1000.0


def sample(price="0.2", when=NOW, key="demo:1", change="5"):
    return Sample(key, 1, "Demo subnet", number(price), number(change), when, when, "demo")


def alert(kind="target", direction="up", amount="0.3", repeat=False, cooldown=300):
    return make_alert(sample(), kind, direction, amount, repeat, cooldown, NOW)


class AlertTests(unittest.TestCase):
    def test_exact_target_equality_and_one_shot(self):
        a = alert()
        self.assertIsNone(evaluate(a, sample(), NOW))
        event = evaluate(a, sample("0.3", NOW+1), NOW+1)
        self.assertEqual(event["reason"], "Observed threshold crossing")
        self.assertTrue(a.done)
        self.assertIsNone(evaluate(a, sample("0.5", NOW+2), NOW+2))

    def test_initial_already_met_is_labeled(self):
        event = evaluate(alert(), sample("0.4"), NOW)
        self.assertIn("already met", event["reason"])

    def test_below_target(self):
        a = alert(direction="down", amount="0.1")
        self.assertIsNone(evaluate(a, sample(), NOW))
        self.assertIsNotNone(evaluate(a, sample("0.1", NOW+1), NOW+1))

    def test_percentage_reference_and_both_directions(self):
        rise, fall = alert("percent", "up", "10"), alert("percent", "down", "10")
        self.assertEqual(rise.target, Decimal("0.22"))
        self.assertEqual(fall.target, Decimal("0.18"))
        self.assertEqual(rise.baseline_time, NOW)
        self.assertIsNotNone(evaluate(rise, sample("0.22", NOW+1), NOW+1))
        self.assertIsNotNone(evaluate(fall, sample("0.18", NOW+1), NOW+1))

    def test_either_direction_boundaries_and_correct_event_target(self):
        for price, boundary in (("0.22", "0.22"), ("0.18", "0.18"), ("0.23", "0.22"), ("0.17", "0.18")):
            with self.subTest(price=price):
                a = alert("percent", "either", "10")
                self.assertIsNone(evaluate(a, sample(), NOW))
                event = evaluate(a, sample(price, NOW+1), NOW+1)
                self.assertEqual(Decimal(event["target"]), Decimal(boundary))
                self.assertIn("≥ 0.22", event["condition"])
                self.assertIn("≤ 0.18", event["condition"])
                self.assertTrue(a.done)
                self.assertIsNone(evaluate(a, sample("0.17", NOW+2), NOW+2))

    def test_either_direction_inside_band_does_not_trigger(self):
        a = alert("percent", "either", "10")
        for when, price in enumerate(("0.2", "0.219999", "0.180001"), int(NOW)):
            self.assertIsNone(evaluate(a, sample(price, when), when))
        self.assertTrue(a.armed)

    def test_either_repeat_inside_band_rearm_and_cooldown(self):
        a = alert("percent", "either", "10", repeat=True, cooldown=10)
        self.assertIsNotNone(evaluate(a, sample("0.22"), NOW))
        # Outside-to-outside, even across both boundaries, does not rearm.
        self.assertIsNone(evaluate(a, sample("0.18", NOW+1), NOW+1))
        self.assertIsNone(evaluate(a, sample("0.2", NOW+2), NOW+2))
        self.assertTrue(a.armed)
        self.assertIsNone(evaluate(a, sample("0.18", NOW+3), NOW+3))
        event = evaluate(a, sample("0.18", NOW+10), NOW+10)
        self.assertEqual(Decimal(event["target"]), Decimal("0.18"))
        self.assertIsNone(evaluate(a, sample("0.22", NOW+11), NOW+11))

    def test_either_percent_validation_and_stale_protection(self):
        with self.assertRaises(ValueError):
            alert("percent", "either", "100")
        with self.assertRaises(ValueError):
            alert("target", "either", "0.3")
        a = alert("percent", "either", "10")
        self.assertIsNone(evaluate(a, sample("0.23", NOW-181), NOW))
        evaluate(a, sample(), NOW)
        self.assertIsNone(evaluate(a, sample("0.18", NOW), NOW))
        self.assertIsNone(evaluate(a, sample("0.18", NOW-1), NOW))

    def test_repeat_rearms_only_on_clear(self):
        a = alert(repeat=True, cooldown=0)
        self.assertIsNotNone(evaluate(a, sample("0.4"), NOW))
        self.assertIsNone(evaluate(a, sample("0.4", NOW+1), NOW+1))
        self.assertIsNone(evaluate(a, sample("0.2", NOW+2), NOW+2))
        self.assertIsNotNone(evaluate(a, sample("0.3", NOW+3), NOW+3))

    def test_repeat_cooldown_waits_with_rearmed_condition(self):
        a = alert(repeat=True, cooldown=10)
        evaluate(a, sample("0.4"), NOW)
        evaluate(a, sample("0.2", NOW+1), NOW+1)
        self.assertIsNone(evaluate(a, sample("0.4", NOW+2), NOW+2))
        event = evaluate(a, sample("0.4", NOW+10), NOW+10)
        self.assertEqual(event["reason"], "Target still met after cooldown")

    def test_stale_invalid_missing_future_never_trigger(self):
        for s in [sample("0.4", NOW-181), sample("NaN"), sample(None), sample("0"),
                  sample("-1"), sample("Infinity"), sample("0.4", NOW+31)]:
            a = alert()
            self.assertIsNone(evaluate(a, s, NOW))
            self.assertIsNone(a.last_seen)

    def test_duplicate_and_out_of_order_never_trigger(self):
        a = alert()
        evaluate(a, sample(), NOW)
        self.assertIsNone(evaluate(a, sample("0.4"), NOW))
        self.assertIsNone(evaluate(a, sample("0.4", NOW-1), NOW))

    def test_provider_timestamp_not_fetch_time_controls_freshness(self):
        s = sample("0.4", NOW-200)
        s.observed_time = NOW
        self.assertFalse(s.fresh(NOW))
        self.assertIsNone(evaluate(alert(), s, NOW))

    def test_gap_is_labeled_without_claiming_crossing(self):
        a = alert()
        evaluate(a, sample(), NOW)
        a.gap = True
        event = evaluate(a, sample("0.4", NOW+1), NOW+1)
        self.assertIn("monitoring gap", event["reason"])

    def test_long_interval_gap_is_labeled(self):
        a = alert()
        evaluate(a, sample(), NOW)
        event = evaluate(a, sample("0.4", NOW+190), NOW+190)
        self.assertIn("monitoring gap", event["reason"])

    def test_paused_and_wrong_source_do_not_trigger(self):
        a = alert()
        a.enabled = False
        self.assertIsNone(evaluate(a, sample("0.4"), NOW))
        a.enabled = True
        self.assertIsNone(evaluate(a, sample("0.4", key="taostats:1"), NOW))

    def test_percentage_creation_requires_fresh_data(self):
        with self.assertRaises(ValueError):
            make_alert(sample(when=NOW-181), "percent", "up", "10", False, 0, NOW)

    def test_values_and_pathological_input_rejected(self):
        for value in ("0", "-2", "NaN", "Infinity", "oops", "1e999999999", "1e-999999999", "2"*65):
            with self.subTest(value=value), self.assertRaises(ValueError):
                alert(amount=value)
        with self.assertRaises(ValueError):
            alert("percent", "down", "100")

    def test_edit_can_reset_trigger_and_percentage_reference(self):
        original = alert()
        evaluate(original, sample("0.4"), NOW)
        edited = make_alert(sample("0.4", NOW+1), "percent", "up", "10", False, 0, NOW+1)
        edited.id = original.id
        self.assertEqual(edited.target, Decimal("0.44"))
        self.assertFalse(edited.done)
        self.assertIsNone(edited.last_seen)


class StoreTests(unittest.TestCase):
    def setUp(self):
        qa = Path(__file__).resolve().parent.parent / "qa"
        qa.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=qa)
        self.path = Path(self.temp.name)/"watch.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_watch_unique_unlimited_and_restart(self):
        self.store.add_watch(sample())
        self.store.add_watch(sample())
        for i in range(2, 1002):
            s = sample(key=f"demo:{i}")
            s.netuid = i
            self.store.add_watch(s)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(len(self.store.watched()), 1001)

    def test_trigger_state_history_atomic_persistent_no_retrigger(self):
        a = alert(repeat=True)
        event = evaluate(a, sample("0.4"), NOW)
        self.store.persist_evaluation([a], [event])
        self.store.close()
        self.store = Store(self.path)
        restored = self.store.alerts()[0]
        self.assertFalse(restored.armed)
        self.assertEqual(restored.last_seen, NOW)
        self.assertEqual(len(self.store.history()), 1)
        self.assertIsNone(evaluate(restored, sample("0.4", NOW+301), NOW+301))

    def test_edit_pause_remove_preserves_history(self):
        s, a = sample(), alert()
        self.store.add_watch(s)
        event = evaluate(a, sample("0.4"), NOW)
        self.store.persist_evaluation([a], [event])
        a.enabled = False
        self.store.save_alert(a)
        self.assertFalse(self.store.alerts()[0].enabled)
        edited = alert(amount="0.5")
        edited.id = a.id
        self.store.save_alert(edited)
        self.assertEqual(len(self.store.alerts()), 1)
        self.assertEqual(self.store.alerts()[0].target, Decimal("0.5"))
        self.store.remove_watch(s.key)
        self.assertFalse(self.store.alerts())
        self.assertEqual(len(self.store.history()), 1)

    def test_credentials_not_saved(self):
        with self.assertRaises(ValueError):
            self.store.set_setting("api_key", "secret")
        self.store.set_setting("interval", 90)
        self.assertEqual(self.store.setting("interval"), 90)

    def test_either_direction_and_existing_alerts_persist(self):
        for direction in ("up", "down", "either"):
            self.store.save_alert(alert("percent", direction, "10"))
        self.store.close()
        self.store = Store(self.path)
        restored = self.store.alerts()
        self.assertEqual([a.direction for a in restored], ["up", "down", "either"])
        either = restored[2]
        event = evaluate(either, sample("0.18"), NOW)
        self.store.persist_evaluation([either], [event])
        self.assertEqual(Decimal(self.store.history()[0]["target"]), Decimal("0.18"))


class ProviderTests(unittest.TestCase):
    def row(self, **updates):
        row = {"netuid": 19, "name": "Pool name", "price": "0.06940675512635053689",
               "price_change_1_day": "-5.034051585669554908", "timestamp": "2026-10-09T23:00:00Z"}
        row.update(updates)
        return row

    def test_documented_units_names_and_nulls(self):
        s = TaostatsProvider.parse_pool(self.row(), {19: "Identity name"}, NOW)
        self.assertEqual(s.price, Decimal("0.06940675512635053689"))
        self.assertEqual(s.change_24h, Decimal("-5.034051585669554908"))
        self.assertEqual(s.name, "Identity name")
        s = TaostatsProvider.parse_pool(self.row(price_change_1_day=None), {}, NOW)
        self.assertIsNone(s.change_24h)
        self.assertEqual(change_text(s.change_24h), "Unavailable")
        self.assertEqual(s.name, "Pool name")
        self.assertEqual(change_text(number("0")), "+0.00%")

    def test_invalid_timestamp_is_not_replaced_with_fetch_time(self):
        s = TaostatsProvider.parse_pool(self.row(timestamp="bad"), {}, NOW)
        self.assertIsNone(s.source_time)
        self.assertFalse(s.fresh(NOW))
        self.assertIsNone(timestamp("2026-10-09T23:00:00"))

    def test_pagination_and_name_join(self):
        calls = []
        def transport(path, page):
            calls.append((path, page))
            if "identity" in path:
                return {"data": [{"netuid": 19, "subnet_name": "Verified name"}], "pagination": {"next_page": None}}
            return {"data": [self.row(netuid=19 if page == 1 else 20)], "pagination": {"next_page": 2 if page == 1 else None}}
        p = TaostatsProvider("key", transport)
        rows = p.fetch()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].name, "Verified name")
        self.assertIn((p.pool_path, 2), calls)

    def test_metadata_failure_does_not_block_price(self):
        def transport(path, page):
            if "identity" in path:
                raise ProviderError("Unavailable")
            return {"data": [self.row()], "pagination": {"next_page": None}}
        p = TaostatsProvider("key", transport)
        self.assertEqual(p.fetch()[0].name, "Pool name")
        self.assertIn("lookup unavailable", p.warning)

    def test_repeated_pagination_schema_and_redirect_fail_closed(self):
        p = TaostatsProvider("key", lambda path, page: {"data": [], "pagination": {"next_page": 1}})
        with self.assertRaises(ProviderError):
            p._pages(p.pool_path)
        p.transport = lambda path, page: {"data": []}
        with self.assertRaises(ProviderError):
            p._pages(p.pool_path)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))


if __name__ == "__main__":
    unittest.main()
