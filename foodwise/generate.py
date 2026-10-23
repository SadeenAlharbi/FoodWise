"""مولد بيانات تجريبية لفرع واحد (تُستبدل لاحقًا ببيانات الفرع الحقيقية بنفس الأعمدة).

المحاكاة يومًا بيوم لكل منتج:
- الطلب = أساس × يوم الأسبوع × موعد الراتب × الموسم × أثر الحرارة × تذبذب عشوائي.
- يطلب الفرع في أيام التوريد بطريقته المعتادة: متوسط آخر 7 أيام × أيام التغطية × 1.3 (مصدر الهدر الرئيسي).
- البيع غالبًا من الأقرب انتهاءً، وبعض العملاء يختارون الأحدث.
- ما يبقى من دفعة بعد انتهاء صلاحيتها هدر، ومعه تلف بسيط في المناولة يزيد في الأيام الحارة للخضار.
- منذ بدء استخدام FoodWise (آخر 8 أسابيع) ينفذ الفرع أغلب قرارات الإنقاذ، فيُباع أو يُتبرع بجزء مما كان سيُهدر.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from foodwise import config, seasons

PRODUCTS = [
    # id, name, category, unit, unit_kg, cost, price, shelf, case, interval, base
    ("P01", "خبز صامولي", "bakery", "كيس", 0.6, 3.0, 5.0, 3, 10, 1, 95),
    ("P02", "خبز تميس", "bakery", "رغيف", 0.25, 0.8, 1.5, 2, 20, 1, 160),
    ("P03", "كرواسون", "bakery", "قطعة", 0.08, 1.6, 3.0, 4, 24, 1, 70),
    ("P04", "كعك بالسمسم", "bakery", "كيس", 0.4, 4.0, 7.0, 5, 12, 2, 30),
    ("P05", "طماطم", "produce", "كجم", 1.0, 4.5, 7.0, 6, 10, 2, 60),
    ("P06", "خيار", "produce", "كجم", 1.0, 4.0, 6.5, 6, 10, 2, 45),
    ("P07", "خس", "produce", "حبة", 0.5, 2.5, 4.5, 3, 12, 2, 40),
    ("P08", "موز", "produce", "كجم", 1.0, 5.75, 8.5, 6, 13, 2, 50),
    ("P09", "فراولة", "produce", "علبة", 0.25, 12.0, 18.0, 3, 8, 2, 22),
    ("P10", "حليب المراعي 1 لتر", "dairy", "عبوة", 1.0, 6.5, 8.5, 7, 12, 3, 85),
    ("P11", "لبن 1 لتر", "dairy", "عبوة", 1.0, 5.5, 7.5, 7, 12, 3, 70),
    ("P12", "زبادي", "dairy", "علبة", 0.17, 2.2, 3.0, 12, 24, 3, 90),
    ("P13", "جبنة بيضاء", "dairy", "علبة", 0.5, 14.0, 19.0, 10, 6, 3, 18),
    ("P14", "لبنة", "dairy", "علبة", 0.4, 11.0, 15.0, 10, 6, 3, 22),
]
COLS = ["product_id", "product_name", "category", "unit", "unit_kg", "unit_cost", "unit_price",
        "shelf_life", "case_size", "delivery_interval", "base_demand"]

# منتجات وصلتها في آخر يومين شحنات أكبر من حاجتها (حالات تحتاج قرار اليوم)
OVERSTOCK = {"P01": 2.6, "P02": 1.8, "P03": 3.0, "P05": 2.6, "P06": 2.6, "P07": 1.6, "P08": 2.6, "P09": 1.8, "P10": 1.5}

# أثر يوم الأسبوع (0=الاثنين ... 6=الأحد)؛ الخميس والجمعة أعلى
DOW = np.array([0.92, 0.9, 0.95, 1.18, 1.25, 1.05, 0.95])


def products_table() -> pd.DataFrame:
    return pd.DataFrame(PRODUCTS, columns=COLS)


def is_delivery_day(product_id: str, interval: int, d: pd.Timestamp) -> bool:
    """جدول التوريد الثابت لكل منتج (كل يوم، أو كل يومين، أو كل 3 أيام)."""
    return (d.toordinal() + int(product_id[1:])) % interval == 0


def usual_need(avg7: float, on_hand: float, category: str, interval: int) -> float:
    """الكمية التي يطلبها الفرع عادة (قبل التقريب للكرتون)."""
    return avg7 * (interval * config.USUAL_ORDER_FACTOR[category] + config.USUAL_SAFETY_DAYS[category]) - on_hand


# أثر المواسم على الطلب حسب الفئة (نوع اليوم من foodwise.seasons)
SEASON_FACTOR = {
    1: {"bakery": 1.30, "produce": 1.20, "dairy": 1.25},   # رمضان: يزيد الطلب على الخبز والألبان والخضار
    2: {"bakery": 0.80, "produce": 0.85, "dairy": 0.85},   # العيد: زيارات وسفر وإغلاق مبكر
    3: {"bakery": 0.92, "produce": 0.95, "dairy": 0.93},   # الإجازات: سفر جزء من الأسر
}


def season_factor(cat: str, d: pd.Timestamp) -> float:
    t = seasons.day_type(d)
    return SEASON_FACTOR[t][cat] if t else 1.0


def payday_factor(d: pd.Timestamp) -> float:
    return 1.12 if config.PAYDAY <= d.day <= config.PAYDAY + 3 else (1.06 if d.day <= 2 else 1.0)


def weather(dates: pd.DatetimeIndex, rng) -> pd.Series:
    """أعلى حرارة يومية في بريدة (تقريبية): نحو 19° في يناير و45° في يوليو."""
    doy = dates.dayofyear.to_numpy()
    temp = 32 + 13 * np.sin(2 * np.pi * (doy - 105) / 365) + rng.normal(0, 1.8, len(dates))
    return pd.Series(np.round(temp, 0), index=dates, name="temp_max")


def demand_factor(cat: str, temp: float) -> float:
    if cat == "dairy":       # اللبن والزبادي يزيد في الحر
        return 1 + 0.008 * max(0.0, temp - 30)
    if cat == "produce":
        return 1 + 0.004 * max(0.0, temp - 30)
    return 1 - 0.003 * max(0.0, temp - 30)


def generate(seed: int = config.SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    prods = products_table()
    end = pd.Timestamp(config.LAST_DATA_DAY)
    dates = pd.date_range(end=end, periods=config.DAYS, freq="D")
    # الطقس يشمل أيام التوقع القادمة (في الواقع يأتي من خدمة الأرصاد)
    all_days = pd.date_range(dates[0], end + pd.Timedelta(days=config.HORIZON + 7), freq="D")
    temp = weather(all_days, rng)
    # أيام طقس إضافية لتوقعات الفترات الأطول (مولد مستقل حتى لا تتغير بقية البيانات)
    extra = pd.date_range(all_days[-1] + pd.Timedelta(days=1), end + pd.Timedelta(days=config.FORECAST_DAYS + 7), freq="D")
    if len(extra):
        temp = pd.concat([temp, weather(extra, np.random.default_rng(seed + 1000))])
    fw_start = end - pd.Timedelta(weeks=config.FOODWISE_WEEKS) + pd.Timedelta(days=1)
    traffic = rng.lognormal(0, 0.06, len(dates))

    sales, batches, waste, orders, decisions, snaps = [], [], [], [], [], []
    open_by_product = {}
    bid = 0
    for p in prods.itertuples():
        stock: list[dict] = []   # دفعات مفتوحة: id, qty, expiry
        hist: list[float] = []
        for i, d in enumerate(dates):
            t = temp[d]
            # (1) توريد الصباح بالطريقة المعتادة
            if is_delivery_day(p.product_id, p.delivery_interval, d):
                avg7 = np.mean(hist[-7:]) if hist else p.base_demand
                on_hand = sum(b["qty"] for b in stock)
                need = usual_need(avg7, on_hand, p.category, p.delivery_interval)
                cases = max(1, math.ceil(need / p.case_size))
                life = p.shelf_life - (1 if rng.random() < 0.12 and p.shelf_life > 1 else 0)
                # شحنات أكبر من المعتاد في آخر الأيام، لم تنتهِ صلاحيتها بعد (حالات تحتاج قرار اليوم)
                if p.product_id in OVERSTOCK and (end - d).days < 3 and d + pd.Timedelta(days=life - 1) > end:
                    cases = math.ceil(cases * OVERSTOCK[p.product_id])
                qty = cases * p.case_size
                bid += 1
                b = {"batch_id": f"B{bid:05d}", "qty": float(qty), "expiry": d + pd.Timedelta(days=life - 1)}
                stock.append(b)
                batches.append({"batch_id": b["batch_id"], "product_id": p.product_id, "received_date": d,
                                "expiry_date": b["expiry"], "qty_received": qty, "unit_cost": p.unit_cost})
                orders.append({"date": d, "product_id": p.product_id, "cases": cases, "qty": qty})
            # (2) الطلب والبيع
            lam = (p.base_demand * DOW[d.dayofweek] * payday_factor(d) * demand_factor(p.category, t)
                   * season_factor(p.category, d)
                   * (1 + 0.06 * math.sin(2 * math.pi * d.dayofyear / 365)) * traffic[i])
            demand = rng.poisson(lam * rng.lognormal(0, 0.12))
            avail = sum(b["qty"] for b in stock)
            sold = min(demand, avail)
            rest = float(sold)
            stock.sort(key=lambda b: b["expiry"])
            fresh_first = rest * 0.15
            for b in reversed(stock):              # 15% من العملاء يختارون الأحدث
                take = min(b["qty"], fresh_first)
                b["qty"] -= take
                fresh_first -= take
                rest -= take
            for b in stock:                         # الباقي من الأقرب انتهاءً
                take = min(b["qty"], rest)
                b["qty"] -= take
                rest -= take
            sales.append({"date": d, "product_id": p.product_id, "qty_sold": float(sold),
                          "stockout": int(demand > avail)})
            hist.append(float(sold))
            # (3) قرارات الإنقاذ بعد بدء FoodWise: دفعة تنتهي اليوم أو غدًا ومتوقع بقاء جزء منها
            if fw_start <= d < end:   # قرارات اليوم الأخير لم تُتخذ بعد
                for b in stock:
                    days_left = (b["expiry"] - d).days
                    if days_left == 1 and b["qty"] >= 1:
                        exp_left = max(0.0, b["qty"] - np.mean(hist[-7:]) * 0.6)
                        if exp_left < 1:
                            continue
                        action = "donate" if p.category == "bakery" else "discount"
                        on_time = rng.random() < 0.84
                        done = exp_left * (rng.uniform(0.45, 0.8) if on_time else rng.uniform(0.1, 0.3))
                        done = float(min(b["qty"], round(done)))
                        b["qty"] -= done
                        decisions.append({"date": d, "product_id": p.product_id, "batch_id": b["batch_id"],
                                          "action": action, "qty_expected": round(exp_left * config.RESCUE_RATE[action]),
                                          "qty_actual": done, "on_time": int(on_time)})
            # (4) نهاية اليوم: تلف مناولة ثم انتهاء الصلاحية
            dmg = 0.004 + (0.012 if p.category == "produce" and t >= 42 else 0)
            for b in stock:
                lost = float(rng.binomial(int(b["qty"]), dmg)) if b["qty"] >= 1 else 0.0
                if lost:
                    b["qty"] -= lost
                    waste.append({"date": d, "product_id": p.product_id, "batch_id": b["batch_id"],
                                  "qty": lost, "reason": "تلف"})
                if b["expiry"] <= d and b["qty"] > 0:
                    waste.append({"date": d, "product_id": p.product_id, "batch_id": b["batch_id"],
                                  "qty": round(b["qty"], 1), "reason": "انتهاء صلاحية"})
                    b["qty"] = 0
            stock = [b for b in stock if b["qty"] > 1e-9]
            if d >= fw_start - pd.Timedelta(days=config.TEST_DAYS + 7):   # رصيد الدفعات نهاية كل يوم (للتحقق من حساب الهدر)
                snaps += [{"date": d, "batch_id": b["batch_id"], "qty": round(b["qty"], 2)} for b in stock]
        open_by_product[p.product_id] = stock

    current = pd.DataFrame([{"batch_id": b["batch_id"], "qty_on_hand": round(b["qty"], 1)}
                            for s in open_by_product.values() for b in s])
    weather_df = temp.rename_axis("date").reset_index()
    return {
        "products": prods,
        "sales": pd.DataFrame(sales),
        "batches": pd.DataFrame(batches),
        "current_stock": current,
        "waste": pd.DataFrame(waste),
        "orders": pd.DataFrame(orders),
        "decisions_history": pd.DataFrame(decisions),
        "stock_snapshots": pd.DataFrame(snaps),
        "weather": weather_df,
        "info": pd.DataFrame([{"branch_name": config.BRANCH_NAME, "last_data_day": end,
                               "foodwise_start": fw_start}]),
    }


def save(tables: dict[str, pd.DataFrame]) -> None:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(config.RAW_DIR / f"{name}.csv", index=False, encoding="utf-8")
