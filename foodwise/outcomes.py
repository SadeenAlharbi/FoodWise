"""قياس نتيجة القرارات تلقائيًا من بيانات الفرع، بدون إدخال يدوي من الموظف.

عند اعتماد قرار يُحفظ: الدفعة، والكمية المتوقع هدرها لو لم نفعل شيئًا، والكمية المتوقع إنقاذها.
عندما تصل بيانات الأيام التالية (المبيعات والهدر من نظام نقاط البيع والمخزون) وتنتهي صلاحية الدفعة:
    الكمية المحفوظة فعلًا = الهدر المتوقع بدون قرار − الهدر المسجل فعلًا لنفس الدفعة بعد القرار.
قبل وصول هذه البيانات يظهر القرار "بانتظار النتيجة".
"""
from __future__ import annotations

import pandas as pd

from foodwise import config

COLS = ["date", "product_id", "batch_id", "action", "expiry_date", "waste_qty", "qty_expected"]


def _with_details(log: pd.DataFrame) -> pd.DataFrame:
    """القرارات القديمة المحفوظة بلا تفاصيل تُكمَّل من قائمة الإنقاذ."""
    log = log.copy()
    for c in COLS:
        if c not in log.columns:
            log[c] = None
    missing = log.product_id.isna()
    if not missing.any():
        return log
    rescue = pd.read_csv(config.OUT_DIR / "rescue.csv").rename(columns={"saved_qty": "qty_expected"})
    rescue["date"] = (pd.Timestamp(config.LAST_DATA_DAY) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    batches = pd.read_csv(config.RAW_DIR / "batches.csv")[["batch_id", "expiry_date"]]
    rescue = rescue.merge(batches, on="batch_id", how="left").set_index("rec_id")
    for c in COLS:
        log.loc[missing, c] = log.loc[missing, "rec_id"].map(rescue[c])
    return log


def measure(log: pd.DataFrame, raw: dict[str, pd.DataFrame], pickups: pd.DataFrame | None = None) -> pd.DataFrame:
    """pickups: طلبات استلام التبرعات؛ التبرع الذي سُلّم للجمعية يُحتسب بكميته المسلّمة مباشرة."""
    if not len(log):
        return pd.DataFrame()
    d = _with_details(log)
    d = d[(d.status == "معتمد") & d.product_id.notna()].copy()
    if not len(d):
        return pd.DataFrame()
    d["date"] = pd.to_datetime(d.date)
    d["expiry_date"] = pd.to_datetime(d.expiry_date)
    last = pd.Timestamp(raw["info"].last_data_day.iloc[0])
    w = raw["waste"]
    rows = []
    delivered = {}
    if pickups is not None and len(pickups):
        dv = pickups[pickups.status == "delivered"]
        delivered = dict(zip(dv.rec_id, dv.qty))
    for r in d.itertuples():
        ready = last >= r.expiry_date or r.rec_id in delivered
        if r.rec_id in delivered:
            actual = float(delivered[r.rec_id])
        elif ready:
            wasted = float(w[(w.batch_id == r.batch_id) & (w.date >= r.date)].qty.sum())
            actual = max(0.0, float(r.waste_qty) - wasted)
        else:
            actual = float("nan")
        rows.append({"date": r.date, "product_id": r.product_id, "batch_id": r.batch_id, "action": r.action,
                     "qty_expected": float(r.qty_expected), "qty_actual": actual,
                     "on_time": int(actual > 0) if ready else float("nan"), "pending": not ready})
    return pd.DataFrame(rows)
