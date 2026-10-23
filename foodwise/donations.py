"""التكامل مع الجمعيات.

1) طلب استلام تلقائي: كل قرار تبرع يعتمده المدير يُنشئ طلب استلام للجمعية بالكمية والوزن والموعد،
   ويتابع المدير حالته حتى التسليم. التسليم يُحتسب مباشرة في أثر الفرع.
2) التبرعات المتوقعة: من محاكاة الأيام القادمة نعرف ما يُتوقع أن يتبقى دون بيع في كل يوم،
   فيُرسل للجمعية إشعار مسبق لتخطط للاستلام. الكمية تقديرية وتتأكد يوم الاستلام بعد قرارات الخصم والعرض.
3) بوابة الجمعية: تؤكد الجمعية طلبات الاستلام وتسجل استلامها، وترد على الإشعارات المسبقة (ستستلم / لا تستطيع)،
   فتظهر الحالة والرد عند مدير الفرع تلقائيًا.
"""
from __future__ import annotations

from datetime import datetime

import hashlib

import pandas as pd

from foodwise import config


def _read(path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _write(df: pd.DataFrame, path) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


# ------------------------------------------------------------------ طلبات الاستلام
def pickups() -> pd.DataFrame:
    return _read(config.PICKUPS_FILE)


def create_pickup(rec_id: str, product: pd.Series, qty: float, date: str) -> None:
    """يُنشأ مرة واحدة لكل قرار تبرع معتمد."""
    old = pickups()
    if len(old):
        if rec_id in set(old[old.status != "cancelled"].rec_id):
            return
        old = old[old.rec_id != rec_id]              # طلب أُلغي سابقًا لنفس المنتج يُستبدل بالجديد
    now = datetime.now().strftime("%H:%M")
    row = pd.DataFrame([{"rec_id": rec_id, "date": date, "product_id": product.name,
                         "product_name": product.product_name, "unit": product.unit,
                         "qty": round(qty), "kg": round(qty * product.unit_kg, 1),
                         "charity": config.CHARITY_NAME, "pickup_time": config.PICKUP_TIME,
                         "status": "sent", "sent_at": now, "updated_at": now}])
    _write(pd.concat([old, row], ignore_index=True) if len(old) else row, config.PICKUPS_FILE)


def advance_pickup(rec_id: str) -> None:
    """ينقل الطلب للحالة التالية: أُرسل ← أكدت الجمعية ← تم التسليم."""
    df = pickups()
    if not len(df) or rec_id not in set(df.rec_id):
        return
    i = df.index[df.rec_id == rec_id][0]
    nxt = config.PICKUP_NEXT.get(df.at[i, "status"])
    if nxt:
        df.at[i, "status"] = nxt[0]
        df.at[i, "updated_at"] = datetime.now().strftime("%H:%M")
        _write(df, config.PICKUPS_FILE)


def can_edit(rec_id: str) -> bool:
    """لا يُعدّل قرار التبرع بعد تأكيد الجمعية أو التسليم، لأن المنتج خرج فعلًا."""
    df = pickups()
    if not len(df):
        return True
    st = df[df.rec_id == rec_id].status
    return not len(st) or st.iloc[0] in ("sent", "cancelled")


def cancel_pickup(rec_id: str) -> None:
    df = pickups()
    if len(df) and ((df.rec_id == rec_id) & (df.status == "sent")).any():
        i = df.index[df.rec_id == rec_id][0]
        df.at[i, "status"] = "cancelled"
        df.at[i, "updated_at"] = datetime.now().strftime("%H:%M")
        _write(df, config.PICKUPS_FILE)


# ------------------------------------------------------------------ التبرعات المتوقعة
def notices() -> pd.DataFrame:
    return _read(config.NOTICES_FILE)


def expected(products: pd.DataFrame, today: pd.Timestamp) -> list[dict]:
    """التبرعات المخطط لها في الأيام القادمة: الكمية المتوقع ألا تُباع حتى مع الخصم، في يوم التبرع بها
    (قبل انتهاء صلاحيتها بيومين، أو بيوم للمنتج الذي صلاحيته يومان). اليوم نفسه في قائمة الإنقاذ."""
    from foodwise.rescue import donation_day
    path = config.OUT_DIR / "daily_waste.csv"
    if not path.exists():
        return []
    d = pd.read_csv(path, parse_dates=["date"]).merge(products, on="product_id")
    d = d[d.category.isin(config.DONATION_CATEGORIES)].copy()
    d["stage"] = d.shelf_life.map(donation_day)
    d = d[d.stage > 0]
    d["give"] = d.day - d.stage
    d = d[d.give.between(1, config.DONATION_NOTICE_DAYS)]
    d["date"] = today + pd.to_timedelta(d.give, unit="D")
    d["qty"] = d.qty * (1 - config.RESCUE_RATE["discount"])
    g = d.groupby(["date", "product_id", "product_name", "unit", "unit_kg"], as_index=False).qty.sum()
    g = g[g.qty >= 1]
    g["qty"] = g.qty.round()
    g["kg"] = g.qty * g.unit_kg
    g = g[g.kg >= config.DONATION_MIN_KG]            # كميات صغيرة جدًا لا تستحق مشوار استلام
    sent = notices()
    sent = dict(zip(sent.date, sent.sent_at)) if len(sent) else {}
    resp = responses()
    resp = dict(zip(resp.date, resp.answer)) if len(resp) else {}
    days = []
    for date, items in g.sort_values(["date", "kg"], ascending=[True, False]).groupby("date"):
        key = date.strftime("%Y-%m-%d")
        days.append({"date": date, "key": key, "days_ahead": int((date - today).days),
                     "items": items.to_dict("records"), "kg": float(items.kg.sum()),
                     "sent_at": sent.get(key), "response": resp.get(key)})
    return days


def send_notice(day_key: str, days: list[dict]) -> None:
    day = next((d for d in days if d["key"] == day_key), None)
    old = notices()
    if day is None or (len(old) and day_key in set(old.date)):
        return
    row = pd.DataFrame([{"date": day_key, "charity": config.CHARITY_NAME, "kg": round(day["kg"], 1),
                         "items": "، ".join(f"{i['product_name']} {i['qty']:.0f} {i['unit']}" for i in day["items"]),
                         "sent_at": datetime.now().strftime("%H:%M")}])
    _write(pd.concat([old, row], ignore_index=True) if len(old) else row, config.NOTICES_FILE)


# ------------------------------------------------------------------ رد الجمعية على الإشعارات المسبقة
def responses() -> pd.DataFrame:
    return _read(config.RESPONSES_FILE)


def respond(day_key: str, answer: str) -> None:
    """الجمعية ترد على إشعار مُرسل فقط، ويمكنها تغيير ردها."""
    if answer not in config.RESPONSE_AR:
        return
    sent = notices()
    if not len(sent) or day_key not in set(sent.date):
        return
    old = responses()
    if len(old):
        old = old[old.date != day_key]
    row = pd.DataFrame([{"date": day_key, "answer": answer, "at": datetime.now().strftime("%H:%M")}])
    _write(pd.concat([old, row], ignore_index=True) if len(old) else row, config.RESPONSES_FILE)


def state_token() -> str:
    """يتغير عند أي تحديث في طلبات الاستلام أو الإشعارات أو الردود أو القرارات، لتحديث الصفحتين تلقائيًا."""
    h = hashlib.md5()
    for p in (config.PICKUPS_FILE, config.NOTICES_FILE, config.RESPONSES_FILE, config.DECISIONS_FILE):
        h.update(p.read_bytes() if p.exists() else b"-")
    return h.hexdigest()[:12]
