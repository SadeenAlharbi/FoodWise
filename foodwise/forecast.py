"""توقع الطلب اليومي لكل منتج للأيام السبعة القادمة.

- الهدف: مبيعات يوم الهدف، وتُستبعد الأيام التي نفد فيها المخزون لأن مبيعاتها أقل من الطلب الحقيقي.
- الميزات تُحسب من بيانات حتى يوم القرار فقط، إضافة لمعلومات معروفة مسبقًا عن يوم الهدف
  (يوم الأسبوع، قرب الراتب، الحرارة المتوقعة).
- نقارن نموذجين من تعلم الآلة (Gradient Boosting وRandom Forest) بطريقتين بسيطتين على آخر 6 أسابيع
  (اختبار زمني)، ونستخدم الأدق. المقارنة تتم مرتين: للأيام 1-7، وللأيام 8-30 بنموذج مستقل.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor

from foodwise import config, seasons

FEATURES = ["h", "dow", "payday", "season", "season_now", "temp", "rel_last_week", "rel_dow4", "rel_mean7", "cat_bakery", "cat_produce"]


class Panel:
    def __init__(self, raw: dict[str, pd.DataFrame]):
        s = raw["sales"]
        self.products = raw["products"].set_index("product_id")
        self.dates = pd.DatetimeIndex(sorted(s.date.unique()))
        self.ids = list(self.products.index)
        self.S = s.pivot(index="date", columns="product_id", values="qty_sold").reindex(self.dates)[self.ids]
        self.OUT = s.pivot(index="date", columns="product_id", values="stockout").reindex(self.dates)[self.ids]
        self.temp = raw["weather"].set_index("date").temp_max
        self.as_of = self.dates[-1]


def payday_flag(d: pd.Timestamp) -> int:
    return int(config.PAYDAY <= d.day <= config.PAYDAY + 3 or d.day <= 2)


def build_frame(panel: Panel, origins, horizon: int = config.FORECAST_DAYS) -> pd.DataFrame:
    """صف لكل (منتج، يوم قرار، أفق h). لا يستخدم أي مبيعات بعد يوم القرار."""
    S = panel.S.to_numpy(dtype=float)
    pos = {d: i for i, d in enumerate(panel.dates)}
    rows = []
    season_of: dict = {}
    for o in origins:
        i = pos[o]
        if i < 35:
            continue
        hist = S[: i + 1]
        mean7 = hist[-7:].mean(axis=0)
        mean28 = hist[-28:].mean(axis=0)
        # نوع يوم القرار: متوسط آخر 28 يومًا يعكس موسمه، فيتعلم النموذج أثر الانتقال بين المواسم لا الموسم وحده
        season_now = seasons.day_type(o)
        for h in range(1, horizon + 1):
            t = o + pd.Timedelta(days=h)
            if t not in season_of:
                season_of[t] = seasons.day_type(t)
            k0 = math.ceil(h / 7)                      # أقرب أسبوع معروف لنفس يوم الأسبوع
            last_week = hist[i + h - 7 * k0]
            dow4 = np.mean([hist[i + h - 7 * k] for k in range(k0, k0 + 4)], axis=0)
            for j, pid in enumerate(panel.ids):
                base = max(mean28[j], 0.5)
                cat = panel.products.category[pid]
                rows.append({
                    "product_id": pid, "origin": o, "target": t, "h": h, "dow": t.dayofweek,
                    "payday": payday_flag(t), "season": season_of[t], "season_now": season_now, "temp": panel.temp.get(t, np.nan), "base": base,
                    "rel_last_week": last_week[j] / base, "rel_dow4": dow4[j] / base, "rel_mean7": mean7[j] / base,
                    "cat_bakery": int(cat == "bakery"), "cat_produce": int(cat == "produce"),
                    "naive": last_week[j], "dow4": dow4[j],
                })
    df = pd.DataFrame(rows)
    y = panel.S.stack().rename("y")
    out = panel.OUT.stack().rename("stockout")
    df = df.join(y, on=["target", "product_id"]).join(out, on=["target", "product_id"])
    return df


def wape(y, p) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float(np.abs(y - p).sum() / max(y.sum(), 1e-9))


MODEL_NAMES = {"gb": "Gradient Boosting", "rf": "Random Forest", "dow4": "متوسط نفس اليوم في آخر 4 أسابيع",
               "naive": "نفس اليوم الأسبوع الماضي"}
RANGES = [(1, config.HORIZON), (config.HORIZON + 1, config.FORECAST_DAYS)]


def _make(kind: str, feats: list[str]):
    if kind == "gb":
        cats = [feats.index(c) for c in ("dow", "season", "season_now") if c in feats]
        return HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, min_samples_leaf=80,
                                             categorical_features=cats, random_state=0)
    return RandomForestRegressor(n_estimators=150, min_samples_leaf=10, max_features=0.5, random_state=0, n_jobs=-1)


def _fit(kind: str, train: pd.DataFrame, feats: list[str] = FEATURES):
    m = _make(kind, feats)
    m.fit(train[feats], train.y / train.base)
    m.feats = feats
    return m


def _predict(kind: str, model, frame: pd.DataFrame) -> np.ndarray:
    if kind in ("gb", "rf"):
        return model.predict(frame[model.feats]) * frame.base.to_numpy()
    return frame[kind].to_numpy()


def season_check(valid: pd.DataFrame, kind: str) -> dict:
    """هل يفيد "نوع اليوم"؟ نتدرب على ما قبل رمضان 1447 فقط، ثم نتوقع أيام رمضان والعيد (1-7 أيام قادمة)
    بنموذج يعرف نوع اليوم ونموذج لا يعرفه، ونقارن الدقة."""
    ev = seasons.events()
    ram = ev[ev.name == "رمضان"].start
    start = ram[ram.dt.year == 2026].iloc[0]
    end = ev[(ev.name == "عيد الفطر") & (ev.start > start)].end.iloc[0]
    v = valid[valid.h <= config.HORIZON]
    train = v[v.target < start - pd.Timedelta(days=1)]
    test = v[(v.target >= start) & (v.target <= end) & (v.origin >= start - pd.Timedelta(days=1))].copy()
    no_season = [f for f in FEATURES if f not in ("season", "season_now")]
    acc = {}
    for label, feats in (("with", FEATURES), ("without", no_season)):
        m = _fit(kind, train, feats)
        acc[label] = round(100 * (1 - wape(test.y, _predict(kind, m, test))), 1)
    return {"period": [str(start.date()), str(end.date())], "accuracy_with_season_pct": acc["with"],
            "accuracy_without_season_pct": acc["without"]}


def run(raw: dict[str, pd.DataFrame]) -> dict:
    panel = Panel(raw)
    as_of = panel.as_of
    test_start = as_of - pd.Timedelta(days=config.TEST_DAYS - 1)
    origins = [d for d in panel.dates if d < as_of]
    df = build_frame(panel, origins)
    df = df[df.target <= as_of]
    valid = df[df.stockout == 0]
    in_test = (df.origin >= test_start - pd.Timedelta(days=1)) & (df.target >= test_start)
    future = build_frame(panel, [as_of])
    future["demand"] = 0.0
    test_parts, all_parts, ranges = [], [], {}

    for lo, hi in RANGES:
        r_valid = valid[(valid.h >= lo) & (valid.h <= hi)]
        train = r_valid[r_valid.target < test_start]
        test = r_valid[(r_valid.origin >= test_start - pd.Timedelta(days=1)) & (r_valid.target >= test_start)].copy()
        models = {k: _fit(k, train) for k in ("gb", "rf")}
        scores = {}
        for k in ("gb", "rf", "dow4", "naive"):
            test[k] = _predict(k, models.get(k), test)
            scores[k] = wape(test.y, test[k])
        chosen = min(scores, key=scores.get)
        best_simple = min(["dow4", "naive"], key=scores.get)
        test["pred"] = test[chosen]
        test_parts.append(test)
        # توقعات فترة الاختبار لكل الأيام (حتى أيام نفاد المخزون) للتحقق من حساب الهدر
        r_all = df[in_test & (df.h >= lo) & (df.h <= hi)].copy()
        r_all["pred"] = _predict(chosen, models.get(chosen), r_all)
        all_parts.append(r_all)
        # التوقع الفعلي: نعيد تدريب النموذج المختار على كل البيانات المتاحة
        mask = (future.h >= lo) & (future.h <= hi)
        final = _fit(chosen, r_valid) if chosen in ("gb", "rf") else None
        future.loc[mask, "demand"] = _predict(chosen, final, future[mask])
        ranges[f"{lo}-{hi}"] = {
            "chosen": chosen, "chosen_name": MODEL_NAMES[chosen],
            "accuracy_pct": {MODEL_NAMES[k]: round(100 * (1 - v), 1) for k, v in sorted(scores.items(), key=lambda x: x[1])},
            "improvement_vs_simple_pct": round(100 * (scores[best_simple] - scores[chosen]) / scores[best_simple], 1),
        }
    future["demand"] = future.demand.clip(lower=0)
    test = pd.concat(test_parts)
    test_all = pd.concat(all_parts)
    main = test[test.h <= config.HORIZON]

    # نسب الخطأ (الفعلي ÷ المتوقع) لكل فئة: تُستخدم لصنع سيناريوهات طلب واقعية
    cats = main.product_id.map(panel.products.category)
    ratio = (main.y / main.pred.clip(lower=0.5)).clip(0, 3)
    ratios = {c: ratio[cats == c].to_numpy() for c in config.CATEGORY_AR}

    by_days = {}
    for lo, hi in [(1, 7), (8, 14), (15, 30)]:
        g = test[(test.h >= lo) & (test.h <= hi)]
        by_days[f"{lo}-{hi}"] = round(100 * (1 - wape(g.y, g.pred)), 1)
    first = ranges[f"1-{config.HORIZON}"]
    kind = first["chosen"] if first["chosen"] in ("gb", "rf") else "gb"
    report = {
        "season_check": season_check(valid, kind),
        "chosen": first["chosen"], "chosen_name": first["chosen_name"],
        "accuracy_pct": round(100 * (1 - wape(main.y, main.pred)), 1),
        "ranges": ranges,
        "accuracy_by_days_ahead_pct": by_days,
        "test_period": [str(test_start.date()), str(as_of.date())],
        "per_product_accuracy_pct": {pid: round(100 * (1 - wape(g.y, g.pred)), 1) for pid, g in main.groupby("product_id")},
    }
    return {"forecast": future[["product_id", "target", "h", "demand", "temp"]], "ratios": ratios,
            "report": report, "test": test[["product_id", "origin", "target", "h", "y", "pred"]],
            "test_all": test_all[["product_id", "origin", "target", "h", "pred"]]}
