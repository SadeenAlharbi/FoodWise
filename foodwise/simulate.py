"""محاكاة الأيام القادمة لكل منتج: البيع من الأقرب انتهاءً، ووصول التوريدات، وما يتبقى عند انتهاء الصلاحية.

نكرر المحاكاة 200 مرة بطلب أعلى وأقل من التوقع بحجم أخطاء التوقع الفعلية، ونأخذ المتوسط.
اليوم 0 هو يوم القرار (أول يوم بعد آخر بيانات).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from foodwise import config
from foodwise.generate import is_delivery_day, usual_need

SIM_DAYS = config.FORECAST_DAYS + 14   # نمد المحاكاة بعد آخر يوم معروض حتى نعرف مصير الدفعات الطويلة


def demand_matrix(forecast: pd.Series, ratios: np.ndarray, rng, n: int = config.SCENARIOS,
                  days: int = SIM_DAYS) -> np.ndarray:
    """forecast: الطلب المتوقع لأيام h=1..N. بعدها نكرر آخر أسبوع بنفس ترتيب أيام الأسبوع."""
    base = forecast.to_numpy(dtype=float)
    m = len(base)
    point = np.array([base[d] if d < m else base[m - 7 + (d - m) % 7] for d in range(days)])
    if ratios is None or len(ratios) == 0:
        return np.tile(point, (n, 1))
    return point[None, :] * rng.choice(ratios, size=(n, days))


def simulate(batches: list[dict], demand: np.ndarray, product, today: pd.Timestamp, avg7: float,
             first_order_qty: float | None = None) -> dict:
    """batches: [{id, qty, days_left}] حيث days_left=0 تعني تنتهي آخر اليوم.
    التوريدات القادمة بطريقة الفرع المعتادة، إلا أول توريد إذا حُددت كميته (لمقارنة الطلبية المقترحة).
    يرجع لكل دفعة: متوسط المبيع والهدر، ويوم الهدر."""
    n, days = demand.shape
    out_sold, out_waste, meta = {}, {}, {}
    morning = np.zeros(days)
    for s in range(n):
        stock = [dict(b) for b in batches]
        first_done = False
        for d in range(days):
            day = today + pd.Timedelta(days=d)
            morning[d] += sum(b["qty"] for b in stock)
            if is_delivery_day(product.product_id, product.delivery_interval, day):
                on_hand = sum(b["qty"] for b in stock)
                if first_order_qty is not None and not first_done:
                    qty = first_order_qty
                else:
                    need = usual_need(avg7, on_hand, product.category, product.delivery_interval)
                    qty = max(1, math.ceil(need / product.case_size)) * product.case_size
                first_done = True
                bid = f"NEW-{d}"
                stock.append({"id": bid, "qty": float(qty), "days_left": d + product.shelf_life - 1})
                meta[bid] = {"arrival": d, "qty": qty, "days_left": d + product.shelf_life - 1}
            rest = float(demand[s, d])
            stock.sort(key=lambda b: b["days_left"])
            fresh = rest * 0.15
            for b in reversed(stock):
                take = min(b["qty"], fresh)
                b["qty"] -= take
                fresh -= take
                rest -= take
                out_sold[b["id"]] = out_sold.get(b["id"], 0.0) + take
            for b in stock:
                take = min(b["qty"], rest)
                b["qty"] -= take
                rest -= take
                out_sold[b["id"]] = out_sold.get(b["id"], 0.0) + take
            for b in stock:
                if b["days_left"] == d and b["qty"] > 0:
                    out_waste[b["id"]] = out_waste.get(b["id"], 0.0) + b["qty"]
                    b["qty"] = 0
            stock = [b for b in stock if b["qty"] > 1e-9]
    return {"sold": {k: v / n for k, v in out_sold.items()}, "waste": {k: v / n for k, v in out_waste.items()},
            "new": meta, "morning_stock": morning / n}


def run(raw: dict[str, pd.DataFrame], fc: dict) -> dict:
    rng = np.random.default_rng(1)
    prods = raw["products"]
    today = pd.Timestamp(config.LAST_DATA_DAY) + pd.Timedelta(days=1)
    cur = raw["current_stock"].merge(raw["batches"], on="batch_id")
    cur["days_left"] = (pd.to_datetime(cur.expiry_date) - today).dt.days
    sales = raw["sales"]
    recent = sales[sales.date > sales.date.max() - pd.Timedelta(days=7)].groupby("product_id").qty_sold.mean()
    forecast = fc["forecast"].sort_values("h")

    batch_rows, prod_rows, order_rows, daily_rows = [], [], [], []
    for p in prods.itertuples():
        f = forecast[forecast.product_id == p.product_id].set_index("h").demand
        dem = demand_matrix(f, fc["ratios"].get(p.category), rng)
        mine = cur[cur.product_id == p.product_id]
        bl = [{"id": r.batch_id, "qty": float(r.qty_on_hand), "days_left": int(r.days_left)} for r in mine.itertuples()]
        avg7 = float(recent.get(p.product_id, p.base_demand))
        res = simulate(bl, dem, p, today, avg7)

        for r in mine.itertuples():
            batch_rows.append({"batch_id": r.batch_id, "product_id": p.product_id, "qty_on_hand": r.qty_on_hand,
                               "days_left": int(r.days_left), "expiry_date": r.expiry_date,
                               "exp_sold": res["sold"].get(r.batch_id, 0.0),
                               "exp_waste": res["waste"].get(r.batch_id, 0.0)})
        # هدر 3 و7 أيام = كل ما ينتهي خلال الفترة دون بيع (المخزون الحالي + التوريدات القادمة)
        # هدر كل فترة = كل ما ينتهي خلالها دون بيع (المخزون الحالي + التوريدات القادمة)
        ends = [(b["id"], b["days_left"]) for b in bl] + [(k, m["days_left"]) for k, m in res["new"].items()]
        # ما يتبقى دون بيع في كل يوم من الأيام القادمة (للتبرعات المتوقعة)
        for k, dl in ends:
            if dl <= config.DONATION_NOTICE_DAYS + config.DONATE_DAYS and res["waste"].get(k, 0.0) > 0:
                daily_rows.append({"product_id": p.product_id, "batch_id": k, "day": dl,
                                   "date": today + pd.Timedelta(days=dl), "qty": res["waste"][k]})
        row = {"product_id": p.product_id, "stock": float(mine.qty_on_hand.sum())}
        for P in config.PERIODS:
            row[f"waste_{P}d"] = sum(res["waste"].get(k, 0.0) for k, dl in ends if dl <= P - 1)
            row[f"demand_{P}d"] = float(f.loc[1:P].sum())
        prod_rows.append(row)

        # الطلبية القادمة: أول يوم توريد بعد اليوم (تُطلب اليوم وتصل لاحقًا)
        nd = next(d for d in range(1, SIM_DAYS) if is_delivery_day(p.product_id, p.delivery_interval, today + pd.Timedelta(days=d)))
        cover = range(nd, nd + p.delivery_interval)
        cover_demand = float(sum(f.get(d + 1, f.iloc[(d) % len(f)]) for d in cover))
        # المخزون الصالح المتوقع صباح يوم التوريد
        usable = float(res["morning_stock"][nd])
        smart_need = cover_demand * config.SMART_ORDER_BUFFER - usable
        smart = max(0, math.ceil(smart_need / p.case_size)) * p.case_size
        usual = max(1, math.ceil(usual_need(avg7, usable, p.category, p.delivery_interval) / p.case_size)) * p.case_size
        w_usual = simulate(bl, dem[:60], p, today, avg7, first_order_qty=usual)
        w_smart = simulate(bl, dem[:60], p, today, avg7, first_order_qty=smart)
        key = f"NEW-{nd}"
        order_rows.append({"product_id": p.product_id, "delivery_day": nd,
                           "delivery_date": today + pd.Timedelta(days=nd), "cover_days": p.delivery_interval,
                           "cover_demand": cover_demand, "usable_stock": usable,
                           "usual_qty": usual, "smart_qty": smart,
                           "usual_cases": usual // p.case_size, "smart_cases": smart // p.case_size,
                           "waste_usual": w_usual["waste"].get(key, 0.0), "waste_smart": w_smart["waste"].get(key, 0.0)})

    return {"batches": pd.DataFrame(batch_rows), "products": pd.DataFrame(prod_rows),
            "orders": pd.DataFrame(order_rows), "daily_waste": pd.DataFrame(daily_rows), "today": today}
