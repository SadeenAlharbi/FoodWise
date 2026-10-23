"""اختبارات أساسية: اتساق البيانات، عدم استخدام المستقبل في التوقع، وقواعد القرارات، والواجهة."""
import unittest

import pandas as pd

from foodwise import config, forecast, rescue, store


class DataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = store.load_raw()

    def test_one_branch_and_full_calendar(self):
        self.assertEqual(len(self.raw["info"]), 1)
        s = self.raw["sales"]
        self.assertEqual(s.groupby("product_id").date.nunique().min(), config.DAYS)

    def test_batch_balance(self):
        """المستلم = المباع + المهدر + المنقذ + المتبقي، لكل منتج."""
        b, s, w, d = self.raw["batches"], self.raw["sales"], self.raw["waste"], self.raw["decisions_history"]
        cur = self.raw["current_stock"].merge(b[["batch_id", "product_id"]])
        for pid in b.product_id.unique():
            got = b[b.product_id == pid].qty_received.sum()
            used = (s[s.product_id == pid].qty_sold.sum() + w[w.product_id == pid].qty.sum()
                    + d[d.product_id == pid].qty_actual.sum() + cur[cur.product_id == pid].qty_on_hand.sum())
            self.assertAlmostEqual(got, used, delta=2 + 0.002 * got, msg=pid)


class ForecastTest(unittest.TestCase):
    def test_features_use_only_past(self):
        raw = store.load_raw()
        panel = forecast.Panel(raw)
        o = panel.dates[200]
        before = forecast.build_frame(panel, [o])
        panel.S.loc[panel.S.index > o] = 9999          # لو استُخدم المستقبل لتغيرت الميزات
        after = forecast.build_frame(panel, [o])
        cols = ["rel_last_week", "rel_dow4", "rel_mean7", "base"]
        pd.testing.assert_frame_equal(before[cols], after[cols])

    def test_report_saved(self):
        r = store.model_report()
        self.assertIn(r["chosen"], {"gb", "rf", "naive", "dow4"})
        self.assertGreater(r["accuracy_pct"], 50)


class WasteCheckTest(unittest.TestCase):
    def test_backtest_total_close_to_actual(self):
        import json
        r = json.loads((config.OUT_DIR / "waste_backtest.json").read_text(encoding="utf-8"))
        self.assertLess(abs(r["bias_pct"]), 25)
        self.assertGreater(r["caught_pct"], 70)


class OutcomeTest(unittest.TestCase):
    def test_actual_measured_automatically_after_expiry(self):
        from foodwise import outcomes
        log = pd.DataFrame([{"rec_id": "X", "status": "معتمد", "date": "2026-10-20", "product_id": "P09",
                             "batch_id": "B1", "action": "donate", "expiry_date": "2026-10-20",
                             "waste_qty": 60, "qty_expected": 60}])
        raw = {"info": pd.DataFrame({"last_data_day": [pd.Timestamp("2026-10-19")]}),
               "waste": pd.DataFrame({"date": [pd.Timestamp("2026-10-20")], "batch_id": ["B1"], "qty": [10.0]})}
        self.assertTrue(outcomes.measure(log, raw).pending.iloc[0])          # البيانات لم تصل بعد
        raw["info"] = pd.DataFrame({"last_data_day": [pd.Timestamp("2026-10-21")]})
        r = outcomes.measure(log, raw).iloc[0]                               # وصلت بيانات اليوم التالي
        self.assertFalse(r.pending)
        self.assertEqual(r.qty_actual, 50)                                   # 60 متوقع هدرها − 10 انهدرت فعلًا


class RescueTest(unittest.TestCase):
    def test_rules(self):
        S = rescue.suggest
        self.assertEqual(S(3, "produce", shelf_life=6)[0], "eatfresh")      # قبل الانتهاء بثلاثة أيام
        self.assertEqual(S(3, "dairy", shelf_life=7)[0], "front")
        self.assertEqual(S(2, "produce", shelf_life=6)[0], "donate")       # تبرع مخطط له قبل الانتهاء بيومين
        self.assertEqual(S(1, "dairy", shelf_life=7)[0], "discount")
        self.assertEqual(S(1, "bakery", shelf_life=3)[0], "donate")        # صلاحية 3 أيام: قبل الانتهاء بيوم
        self.assertEqual(S(1, "bakery", shelf_life=2)[0], "discount")      # الخبز الطازج (يومان) لا يُتبرع به
        self.assertEqual(S(0, "bakery", shelf_life=3)[0], "discount")      # لا تبرع بمنتج ينتهي اليوم
        self.assertIn("50%", S(0, "produce", shelf_life=6)[1])
        self.assertNotIn("donate", rescue.options(0, "produce"))
        self.assertIn("eatfresh", rescue.options(1, "produce"))
        self.assertNotIn("eatfresh", rescue.options(1, "dairy"))
        self.assertEqual(rescue.priority(200), "عالية")

    def test_list_sorted_with_units(self):
        r = store.load_out("rescue")
        self.assertTrue((r.waste_value.diff().dropna() <= 1e-9).all())
        self.assertTrue((r.waste_qty >= 1).all())
        self.assertTrue(r.reason.str.contains("ر.س").all())


class SeasonsTest(unittest.TestCase):
    def test_upcoming_seasons(self):
        from foodwise import seasons
        T = pd.Timestamp
        self.assertEqual(seasons.upcoming(T("2026-10-20")), [])                       # لا موسم خلال أسبوع
        self.assertEqual(seasons.upcoming(T("2026-11-18")), ["بعد يومين: إجازة الخريف"])
        self.assertIn("رمضان: حتى 8 مارس", seasons.upcoming(T("2027-02-20")))
        self.assertIn("بعد 7 أيام: عيد الفطر", seasons.upcoming(T("2027-03-02")))
        self.assertEqual(seasons.upcoming(T("2026-09-23")), ["اليوم الوطني: اليوم"])
        e = seasons.events()
        self.assertTrue((e.end >= e.start).all())

    def test_day_type(self):
        from foodwise import seasons
        T = pd.Timestamp
        self.assertEqual(seasons.day_type(T("2026-10-20")), 0)
        self.assertEqual(seasons.day_type(T("2026-03-01")), 1)     # رمضان
        self.assertEqual(seasons.day_type(T("2026-03-20")), 2)     # عيد الفطر
        self.assertEqual(seasons.day_type(T("2026-05-27")), 2)     # العيد مقدم على الإجازة الصيفية
        self.assertEqual(seasons.day_type(T("2026-07-15")), 3)     # إجازة

    def test_season_feature_in_model(self):
        self.assertIn("season", forecast.FEATURES)
        rep = store.model_report()["season_check"]
        self.assertGreater(rep["accuracy_with_season_pct"], rep["accuracy_without_season_pct"])


class AppTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = (config.DECISIONS_FILE, config.ORDER_APPROVALS_FILE, config.PICKUPS_FILE, config.NOTICES_FILE,
                     config.RESPONSES_FILE)
        config.RESPONSES_FILE = Path(self.tmp.name) / "r.csv"
        config.DECISIONS_FILE = Path(self.tmp.name) / "d.csv"
        config.ORDER_APPROVALS_FILE = Path(self.tmp.name) / "o.csv"
        config.PICKUPS_FILE = Path(self.tmp.name) / "p.csv"
        config.NOTICES_FILE = Path(self.tmp.name) / "n.csv"
        from app import app
        self.c = app.test_client()

    def tearDown(self):
        (config.DECISIONS_FILE, config.ORDER_APPROVALS_FILE, config.PICKUPS_FILE, config.NOTICES_FILE,
         config.RESPONSES_FILE) = self.orig
        self.tmp.cleanup()

    def test_pages(self):
        for u in ["/", "/waste", "/waste?cat=dairy", "/waste?days=3", "/waste?days=30&cat=produce", "/waste?days=99", "/orders", "/orders?product=P10", "/impact"]:
            r = self.c.get(u)
            self.assertEqual(r.status_code, 200, u)
            html = r.get_data(as_text=True)
            for word in ["Random Forest", "WAPE", "اصطناعية", "تجريبية", "السلامة"]:
                self.assertNotIn(word, html, f"{word} في {u}")

    def test_approve_decision(self):
        rid = store.load_out("rescue").rec_id.iloc[0]
        self.c.post(f"/decide/{rid}", data={"decision": "approve"})
        self.assertEqual(store.decisions().set_index("rec_id").status[rid], "معتمد")
        self.assertIn("1 قرار معتمد", self.c.get("/").get_data(as_text=True))
        self.assertIn("بانتظار النتيجة", self.c.get("/impact").get_data(as_text=True))
        self.assertIn("نتائج القرارات حسب نوعها", self.c.get("/impact").get_data(as_text=True))
        self.assertEqual(store.decisions().set_index("rec_id").batch_id[rid], store.load_out("rescue").batch_id.iloc[0])

    def test_rejected_product_hidden(self):
        r = store.load_out("rescue").iloc[0]
        self.assertIn(r.reason, self.c.get("/").get_data(as_text=True))
        self.c.post(f"/decide/{r.rec_id}", data={"decision": "reject"})
        self.assertNotIn(r.reason, self.c.get("/").get_data(as_text=True))

    def test_reject_and_choose_alternative(self):
        r = store.load_out("rescue").iloc[0]
        alt = next(k for k in ("donate", "discount", "front") if k != r.action)
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn("اختر قرارًا آخر", html)
        self.c.post(f"/decide/{r.rec_id}", data={"decision": "alternative", "alt": alt})
        log = store.decisions().set_index("rec_id")
        self.assertEqual(log.status[r.rec_id], "معتمد")
        self.assertEqual(log.action[r.rec_id], alt)
        self.assertEqual(log.suggested[r.rec_id], r.action)
        self.assertIn("معتمد:", self.c.get("/").get_data(as_text=True))
        from foodwise import outcomes
        m = outcomes.measure(store.decisions(), store.load_raw())
        self.assertEqual(m.action.iloc[0], alt)

    def test_approve_only_picked_products(self):
        self.c.post("/orders", data={"pick": ["P01", "P05"]})
        self.assertEqual(set(store.order_approval().product_id), {"P01", "P05"})
        self.c.post("/orders", data={"pick": ["P05", "P10"]})
        self.assertEqual(set(store.order_approval().product_id), {"P01", "P05", "P10"})
        self.c.post("/orders", data={})
        self.assertEqual(len(store.order_approval()), 3)

    def test_donation_creates_pickup_and_counts_when_delivered(self):
        from foodwise import donations, outcomes
        recs = store.load_out("rescue")
        r = recs[recs.action == "donate"].iloc[0]
        other = recs[recs.action != "donate"].iloc[0]
        self.c.post(f"/decide/{other.rec_id}", data={"decision": "approve"})
        self.assertEqual(len(donations.pickups()), 0)          # الخصم والعرض لا يُنشئان طلب استلام
        self.c.post(f"/decide/{r.rec_id}", data={"decision": "approve"})
        pk = donations.pickups().set_index("rec_id")
        self.assertEqual(pk.status[r.rec_id], "sent")
        self.assertEqual(pk.qty[r.rec_id], r.saved_qty)
        self.assertIn("طلبات استلام التبرعات", self.c.get("/").get_data(as_text=True))
        m = outcomes.measure(store.decisions(), store.load_raw(), donations.pickups())
        self.assertTrue(m[m.action == "donate"].pending.all())
        self.c.post(f"/pickup/{r.rec_id}")
        self.c.post(f"/pickup/{r.rec_id}")
        self.c.post(f"/pickup/{r.rec_id}")                     # لا يتجاوز "تم التسليم"
        self.assertEqual(donations.pickups().status.iloc[0], "delivered")
        m = outcomes.measure(store.decisions(), store.load_raw(), donations.pickups())
        dn = m[m.action == "donate"].iloc[0]
        self.assertFalse(dn.pending)
        self.assertEqual(dn.qty_actual, r.saved_qty)

    def test_upcoming_donations_and_notice(self):
        from foodwise import donations
        raw = store.load_raw()
        today = pd.Timestamp(config.LAST_DATA_DAY) + pd.Timedelta(days=1)
        days = donations.expected(raw["products"], today)
        self.assertTrue(len(days))
        for d in days:
            self.assertTrue(1 <= d["days_ahead"] <= config.DONATION_NOTICE_DAYS)
        self.c.post(f"/notice/{days[0]['key']}")
        self.c.post(f"/notice/{days[0]['key']}")
        self.assertEqual(len(donations.notices()), 1)
        self.assertIn("أُرسل الإشعار الساعة", self.c.get("/").get_data(as_text=True))

    def test_edit_decision(self):
        from foodwise import outcomes
        recs = store.load_out("rescue")
        r = recs[recs.action != "donate"].iloc[0]
        self.c.post(f"/decide/{r.rec_id}", data={"decision": "approve"})
        self.assertIn("تعديل القرار", self.c.get("/").get_data(as_text=True))
        self.c.post(f"/edit/{r.rec_id}")
        self.assertEqual(len(store.decisions()), 0)                     # رجع "يحتاج قرارًا"
        self.assertEqual(len(store.decisions(history=True)), 1)         # والقديم باقٍ في السجل
        self.c.post(f"/decide/{r.rec_id}", data={"decision": "reject"})
        self.assertNotIn(r.reason, self.c.get("/").get_data(as_text=True))
        self.assertIn("مرفوضة اليوم", self.c.get("/").get_data(as_text=True))
        self.c.post(f"/edit/{r.rec_id}")
        self.c.post(f"/decide/{r.rec_id}", data={"decision": "approve"})
        self.assertEqual(store.decisions().set_index("rec_id").status[r.rec_id], "معتمد")
        self.assertEqual(len(outcomes.measure(store.decisions(), store.load_raw())), 1)

    def test_edit_donation_cancels_pickup_until_confirmed(self):
        from foodwise import donations
        recs = store.load_out("rescue")
        d1, d2 = recs[recs.action == "donate"].rec_id.iloc[:2]
        self.c.post(f"/decide/{d1}", data={"decision": "approve"})
        self.c.post(f"/edit/{d1}")
        self.assertEqual(donations.pickups().set_index("rec_id").status[d1], "cancelled")
        self.c.post(f"/decide/{d1}", data={"decision": "approve"})       # تبرع من جديد = طلب جديد
        pk = donations.pickups()
        self.assertEqual(list(pk[pk.rec_id == d1].status), ["sent"])
        self.c.post(f"/decide/{d2}", data={"decision": "approve"})
        self.c.post(f"/pickup/{d2}")                                     # أكدت الجمعية
        self.c.post(f"/edit/{d2}")
        self.assertEqual(store.decisions().set_index("rec_id").status[d2], "معتمد")
        self.assertIn("لا يمكن التعديل بعد تأكيد الجمعية", self.c.get("/").get_data(as_text=True))

    def test_charity_portal(self):
        from foodwise import donations
        recs = store.load_out("rescue")
        r = recs[recs.action == "donate"].iloc[0]
        self.assertIn("لا توجد طلبات استلام اليوم", self.c.get("/charity").get_data(as_text=True))
        v0 = self.c.get("/api/state").get_json()["v"]
        self.c.post(f"/decide/{r.rec_id}", data={"decision": "approve"})
        self.assertNotEqual(self.c.get("/api/state").get_json()["v"], v0)       # المدير اعتمد ← تتحدث الجمعية
        html = self.c.get("/charity").get_data(as_text=True)
        self.assertIn(r.product_name, html)
        self.assertIn("بانتظار تأكيدكم", html)
        self.assertNotIn("قائمة الإنقاذ اليوم", html)                            # الجمعية لا ترى صفحات المدير
        self.c.post(f"/pickup/{r.rec_id}")                                       # الجمعية تؤكد
        self.assertIn("أكدت الجمعية الاستلام", self.c.get("/").get_data(as_text=True))
        self.c.post(f"/pickup/{r.rec_id}")                                       # الجمعية استلمت
        self.assertEqual(donations.pickups().status.iloc[0], "delivered")

    def test_charity_responds_to_notice(self):
        from foodwise import donations
        raw = store.load_raw()
        day = donations.expected(raw["products"], pd.Timestamp(config.LAST_DATA_DAY) + pd.Timedelta(days=1))[0]["key"]
        self.c.post(f"/charity/respond/{day}", data={"answer": "yes"})
        self.assertEqual(len(donations.responses()), 0)                         # لا رد قبل إشعار الفرع
        self.c.post(f"/notice/{day}")
        self.assertIn("سنستلم", self.c.get("/charity").get_data(as_text=True))
        self.c.post(f"/charity/respond/{day}", data={"answer": "no"})
        self.assertIn("الجمعية لا تستطيع الاستلام", self.c.get("/").get_data(as_text=True))
        self.c.post(f"/charity/respond/{day}", data={"answer": "yes"})
        self.assertEqual(list(donations.responses().answer), ["yes"])
        self.assertIn("الجمعية ستستلم", self.c.get("/").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
