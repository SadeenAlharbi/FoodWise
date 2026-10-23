"""التحقق من حساب الهدر: نرجع لأيام سابقة ونحسب الهدر المتوقع كأننا في ذلك اليوم،
ثم نقارنه بما حدث فعلًا لنفس الدفعات.

نختار الأسابيع الستة قبل بدء FoodWise، لأن الفرع وقتها لم يكن يتخذ قرارات إنقاذ،
فالهدر المسجل هو الهدر الحقيقي بدون أي تدخل. نموذج الطلب هنا يُدرَّب على ما قبل هذه الأسابيع فقط.

- يوم القرار o: نأخذ رصيد كل دفعة نهاية اليوم o، وتوقع الطلب الذي صدر في ذلك اليوم (نموذج لم يرَ فترة الاختبار).
- المتوقع: هدر كل دفعة تنتهي خلال 7 أيام من المحاكاة.
- الفعلي: ما سُجل هدرًا لانتهاء الصلاحية من نفس الدفعة.
- لا يدخل "التلف" في المقارنة لأن الحساب لا يتوقع التلف.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from foodwise import config
from foodwise.simulate import demand_matrix, simulate


def run(raw: dict[str, pd.DataFrame], fc: dict, step: int = 2, scenarios: int = 100) -> dict:
    rng = np.random.default_rng(7)
    prods = raw["products"].set_index("product_id")
    snaps = raw["stock_snapshots"]
    batches = raw["batches"].set_index("batch_id")
    sales = raw["sales"]
    waste = raw["waste"]
    expired = waste[waste.reason == "انتهاء صلاحية"].groupby("batch_id").qty.sum()
    preds = fc["test_all"]
    as_of = sales.date.max()
    origins = sorted(preds.origin.unique())
    fw_start = pd.Timestamp(raw["info"].foodwise_start.iloc[0])
    end = min(as_of, fw_start - pd.Timedelta(days=1))
    origins = [pd.Timestamp(o) for o in origins if pd.Timestamp(o) + pd.Timedelta(days=config.HORIZON) <= end][::step]

    rows = []
    for o in origins:
        today = o + pd.Timedelta(days=1)
        snap = snaps[(snaps.date == o) & (snaps.qty > 0)]
        recent = sales[(sales.date > o - pd.Timedelta(days=7)) & (sales.date <= o)].groupby("product_id").qty_sold.mean()
        for pid, g in snap.groupby(snap.batch_id.map(batches.product_id)):
            p = prods.loc[pid]
            prow = p.copy()
            prow["product_id"] = pid
            f = preds[(preds.origin == o) & (preds.product_id == pid) & (preds.h <= config.HORIZON)].set_index("h").pred.sort_index()
            if len(f) < config.HORIZON:
                continue
            bl = []
            for r in g.itertuples():
                dl = (batches.expiry_date[r.batch_id] - today).days
                bl.append({"id": r.batch_id, "qty": float(r.qty), "days_left": int(dl)})
            dem = demand_matrix(f, fc["ratios"].get(p.category), rng, n=scenarios, days=21)
            res = simulate(bl, dem, prow, today, float(recent.get(pid, p.base_demand)))
            for b in bl:
                if b["days_left"] > config.HORIZON - 1:
                    continue
                rows.append({"origin": o, "product_id": pid, "batch_id": b["id"], "days_left": b["days_left"],
                             "predicted": res["waste"].get(b["id"], 0.0),
                             "actual": float(expired.get(b["id"], 0.0)),
                             "unit_cost": p.unit_cost})
    df = pd.DataFrame(rows)
    df["pred_value"] = df.predicted * df.unit_cost
    df["actual_value"] = df.actual * df.unit_cost
    flagged, happened = df.predicted >= 1, df.actual >= 1
    summary = {
        "origins": len(origins), "batches_checked": int(len(df)),
        "predicted_value": round(float(df.pred_value.sum()), 0), "actual_value": round(float(df.actual_value.sum()), 0),
        "bias_pct": round(float((df.pred_value.sum() - df.actual_value.sum()) / df.actual_value.sum() * 100), 1),
        "error_pct": round(float((df.pred_value - df.actual_value).abs().sum() / df.actual_value.sum() * 100), 1),
        "caught_pct": round(float((flagged & happened).sum() / max(happened.sum(), 1) * 100), 1),
        "correct_alerts_pct": round(float((flagged & happened).sum() / max(flagged.sum(), 1) * 100), 1),
        "batches_with_waste": int(happened.sum()), "batches_flagged": int(flagged.sum()),
    }
    by_cat = df.assign(category=df.product_id.map(prods.category)).groupby("category")[["pred_value", "actual_value"]].sum().round(0)
    summary["by_category"] = {config.CATEGORY_AR[c]: {"predicted": float(r.pred_value), "actual": float(r.actual_value)}
                              for c, r in by_cat.iterrows()}
    return {"summary": summary, "detail": df}
