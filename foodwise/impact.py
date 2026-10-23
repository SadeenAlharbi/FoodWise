"""أثر الفرع: ما حفظته القرارات، والهدر الفعلي قبل FoodWise وبعده."""
from __future__ import annotations

import pandas as pd

from foodwise import config


def build(raw: dict[str, pd.DataFrame], live: pd.DataFrame | None = None) -> dict:
    """live: قرارات اعتمدها المدير في التطبيق، ونتيجتها محسوبة تلقائيًا (أو بانتظار البيانات)."""
    p = raw["products"].set_index("product_id")
    info = raw["info"].iloc[0]
    last = pd.Timestamp(info.last_data_day)
    fw_start = pd.Timestamp(info.foodwise_start)

    w = raw["waste"].copy()
    w["value"] = w.qty * w.product_id.map(p.unit_cost)
    month_start = last.replace(day=1)
    prev_start = (month_start - pd.Timedelta(days=1)).replace(day=1)
    prev_end = prev_start + pd.Timedelta(days=last.day - 1)          # نفس عدد الأيام من الشهر الماضي
    waste_month = w[(w.date >= month_start) & (w.date <= last)].value.sum()
    waste_prev = w[(w.date >= prev_start) & (w.date <= prev_end)].value.sum()

    # المؤشر الرئيسي: نسبة الهدر من المبيعات (كلاهما بسعر البيع)
    s = raw["sales"]
    sales_v = s.qty_sold * s.product_id.map(p.unit_price)
    waste_v = w.qty * w.product_id.map(p.unit_price)

    def pct(a, b):
        sv = sales_v[(s.date >= a) & (s.date <= b)].sum()
        return float(waste_v[(w.date >= a) & (w.date <= b)].sum() / sv * 100) if sv else 0.0

    pct_month, pct_prev = pct(month_start, last), pct(prev_start, prev_end)
    # المقارنة بخط الأساس: نسبة الهدر في 8 أسابيع قبل بدء FoodWise (كما في طريقة الحساب)
    pct_base = pct(fw_start - pd.Timedelta(days=56), fw_start - pd.Timedelta(days=1))
    change = (pct_month - pct_base) / pct_base * 100 if pct_base else 0.0

    d = raw["decisions_history"].copy()
    d["pending"] = False
    if live is not None and len(live):
        d = pd.concat([d, live], ignore_index=True)
    d["unit"] = d.product_id.map(p.unit)
    d["product_name"] = d.product_id.map(p.product_name)
    d["value_expected"] = d.qty_expected * d.product_id.map(p.unit_cost)
    d["value_actual"] = d.qty_actual * d.product_id.map(p.unit_cost)
    d["kg_actual"] = d.qty_actual * d.product_id.map(p.unit_kg)
    done = d[~d.pending.astype(bool)]
    dm = done[done.date >= month_start]
    donated = dm[dm.action == "donate"]

    # الهدر الأسبوعي (آخر 20 أسبوعًا)، كل أسبوع ينتهي في يوم ثابت
    weeks = []
    for k in range(19, -1, -1):
        end = last - pd.Timedelta(days=7 * k)
        start = end - pd.Timedelta(days=6)
        weeks.append({"start": start, "end": end,
                      "value": float(w[(w.date >= start) & (w.date <= end)].value.sum()),
                      "pct": pct(start, end),
                      "with_foodwise": bool(start >= fw_start)})
    weeks = pd.DataFrame(weeks)
    before = weeks[~weeks.with_foodwise].tail(8).pct.mean()
    after = weeks[weeks.with_foodwise].pct.mean()

    recent = w[w.date > last - pd.Timedelta(days=28)]
    by_cat = recent.groupby(recent.product_id.map(p.category)).value.sum()
    by_cat = (by_cat / by_cat.sum() * 100).sort_values(ascending=False)

    table = d.sort_values(["date", "pending"], ascending=False).head(12)

    # ملخص هذا الشهر حسب نوع القرار: يبقى بنفس الحجم مهما كثرت القرارات
    month_all = d[d.date >= month_start]
    by_action = []
    for act, name in config.ACTION_AR.items():
        g = month_all[month_all.action == act]
        g_done = g[~g.pending.astype(bool)]
        if not len(g):
            continue
        expected, actual = float(g_done.value_expected.sum()), float(g_done.value_actual.sum())
        by_action.append({"action": name, "count": int(len(g_done)), "pending": int(len(g) - len(g_done)),
                          "expected": expected, "actual": actual,
                          "success_pct": actual / expected * 100 if expected else None})
    by_action.sort(key=lambda r: r["actual"], reverse=True)
    return {
        "saved_month": float(dm.value_actual.sum()),
        "saved_month_count": int(len(dm)),
        "waste_month": float(waste_month), "waste_prev": float(waste_prev), "waste_change_pct": float(change),
        "waste_pct_month": pct_month, "waste_pct_prev": pct_prev, "waste_pct_base": pct_base,
        "on_time_pct": float(dm.on_time.mean() * 100) if len(dm) else 0.0,
        "donated_kg": float(donated.kg_actual.sum()), "donated_count": int(len(donated)),
        "weeks": weeks, "weekly_before": float(before), "weekly_after": float(after),
        "by_category": [{"category": config.CATEGORY_AR[c], "pct": float(v),
                         "value": float(recent[recent.product_id.map(p.category) == c].value.sum())}
                        for c, v in by_cat.items()],
        "table": table, "month_label": month_start, "foodwise_start": fw_start,
        "pending_count": int(d.pending.astype(bool).sum()),
        "by_action": by_action,
    }
