"""واجهة FoodWise لمدير الفرع.

    python -m foodwise.pipeline   # أول مرة فقط (أو بعد تحديث البيانات)
    python app.py                 # ثم افتحي http://127.0.0.1:5050
"""
from __future__ import annotations

import math
import os

import pandas as pd
from flask import Flask, jsonify, redirect, render_template, request, url_for

from foodwise import charts, config, donations, impact, outcomes, seasons, store
from foodwise import rescue as rescue_rules

app = Flask(__name__)

DAYS_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر",
             "نوفمبر", "ديسمبر"]
PERIOD_AR = {3: "3 أيام", 7: "7 أيام", 14: "أسبوعين", 21: "3 أسابيع", 30: "شهر"}
NAV = [("rescue", "قائمة الإنقاذ اليوم"), ("waste", "توقع الهدر"), ("orders", "طلبية المخزون القادمة"),
       ("impact", "أثر الفرع")]


# ------------------------------------------------------------------ تنسيق الأرقام (كل رقم مع وحدته)
def _bad(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


@app.template_filter("num")
def f_num(v, d: int = 0):
    return "—" if _bad(v) else f"{v:,.{d}f}"


@app.template_filter("sar")
def f_sar(v):
    return "—" if _bad(v) else f"{v:,.0f} ر.س"


@app.template_filter("pct")
def f_pct(v, d: int = 0):
    return "—" if _bad(v) else f"{v:.{d}f}%"


@app.template_filter("qty")
def f_qty(v, unit: str):
    return "—" if _bad(v) else f"{v:,.0f} {unit}"


@app.template_filter("cat")
def f_cat(v):
    return config.CATEGORY_AR.get(v, v)


def day_ar(d) -> str:
    d = pd.Timestamp(d)
    return f"{DAYS_AR[d.dayofweek]} {d.day} {MONTHS_AR[d.month - 1]}"


def short_date(d) -> str:
    d = pd.Timestamp(d)
    return f"{d.day} {MONTHS_AR[d.month - 1]}"


app.jinja_env.filters["day"] = day_ar
app.jinja_env.filters["short"] = short_date


# ------------------------------------------------------------------ بيانات مشتركة
def today() -> pd.Timestamp:
    return pd.Timestamp(config.LAST_DATA_DAY) + pd.Timedelta(days=1)


def payday_of(year: int, month: int) -> pd.Timestamp:
    """رواتب موظفي الدولة يوم 27 ميلادي؛ إذا وافق الجمعة تُصرف الخميس قبله، وإذا وافق السبت تُصرف الأحد بعده."""
    d = pd.Timestamp(year=year, month=month, day=config.PAYDAY)
    return d - pd.Timedelta(days=1) if d.dayofweek == 4 else (d + pd.Timedelta(days=1) if d.dayofweek == 5 else d)


def next_payday(t: pd.Timestamp) -> pd.Timestamp:
    d = payday_of(t.year, t.month)
    if d < t:
        nxt = t + pd.offsets.MonthBegin(1)
        d = payday_of(nxt.year, nxt.month)
    return d


def rescue_with_status() -> pd.DataFrame:
    recs = store.load_out("rescue")
    log = store.decisions()
    lg = log.set_index("rec_id") if len(log) else pd.DataFrame()
    recs["status"] = recs.rec_id.map(lg.status) if len(lg) else None
    recs["status"] = recs["status"].fillna("مقترح")
    # إذا اختار المدير قرارًا بديلًا نعرضه ونحسب أثره بدل المقترح
    chosen = recs.rec_id.map(lg.chosen_text) if len(lg) and "chosen_text" in lg else None
    recs["chosen_text"] = chosen
    if len(lg) and "qty_expected" in lg and "chosen_text" in lg:
        alt = recs.chosen_text.notna()
        recs.loc[alt, "saved_value"] = (recs.loc[alt, "rec_id"].map(lg.qty_expected).astype(float)
                                        * recs.loc[alt, "saved_value"] / recs.loc[alt, "saved_qty"].clip(lower=1))
    recs["editable"] = [donations.can_edit(r) for r in recs.rec_id]
    recs["alternatives"] = [{k: v for k, v in rescue_rules.options(int(r.days_left), r.category).items() if k != r.action}
                            for r in recs.itertuples()]
    return recs


@app.context_processor
def common():
    try:
        pending = int((rescue_with_status().status == "مقترح").sum())
    except FileNotFoundError:
        pending = 0
    return {"nav": NAV, "pending": pending, "branch": config.BRANCH_NAME, "last_update": config.LAST_DATA_DAY,
            "charity": config.CHARITY_NAME, "state": donations.state_token()}


# ------------------------------------------------------------------ الصفحات
@app.route("/")
def rescue():
    recs = rescue_with_status()
    pw = store.load_out("product_waste").merge(store.load_raw()["products"], on="product_id")
    waste7 = float((pw.waste_7d * pw.unit_cost).sum())
    approved = recs[recs.status == "معتمد"]
    t = today()
    payday = next_payday(t)
    kpi = {
        "waste7": waste7, "need": len(recs), "high": int((recs.priority == "عالية").sum()),
        "saved_today": float(approved.saved_value.sum()), "approved": len(approved),
        "decided": int((recs.status != "مقترح").sum()),
    }
    n = (payday - t).days
    when = {0: "اليوم", 1: "غدًا", 2: "بعد يومين"}.get(n, f"بعد {n} أيام")
    factors = [f"{when}: يوم الراتب"] + seasons.upcoming(t)   # المواسم القريبة تظهر قبل أسبوع من بدايتها
    pk = donations.pickups()
    return render_template("rescue.html", active="rescue", recs=recs, kpi=kpi, factors=factors, today=t,
                           editing=request.args.get("edit"),
                           rejected=recs[recs.status == "مرفوض"],
                           pickups=pk.iloc[::-1] if len(pk) else pk, pickup_status=config.PICKUP_STATUS,
                           response_ar=config.RESPONSE_AR,
                           upcoming=donations.expected(store.load_raw()["products"], t),
                           notice_days=config.DONATION_NOTICE_DAYS)


@app.post("/decide/<rec_id>")
def decide(rec_id):
    recs = store.load_out("rescue").set_index("rec_id")
    if rec_id not in recs.index:                          # منتج غير موجود في قائمة اليوم
        return redirect(url_for("rescue"))
    r = recs.loc[rec_id]
    batches = store.load_raw()["batches"].set_index("batch_id")
    details = {"date": today().strftime("%Y-%m-%d"), "product_id": r.product_id, "batch_id": r.batch_id,
               "action": r.action, "expiry_date": batches.expiry_date[r.batch_id].strftime("%Y-%m-%d"),
               "waste_qty": float(r.waste_qty), "qty_expected": float(r.saved_qty)}
    decision = request.form.get("decision")
    alt = request.form.get("alt")
    if alt and alt in rescue_rules.options(int(r.days_left), r.category):
        # رفض المقترح واختيار قرار آخر: يُسجَّل القرار البديل معتمدًا وتُقاس نتيجته تلقائيًا مثل غيره
        details.update({"suggested": r.action, "action": alt,
                        "chosen_text": rescue_rules.options(int(r.days_left), r.category)[alt],
                        "qty_expected": float(round(r.waste_qty * config.RESCUE_RATE[alt]))})
        status = "معتمد"
    else:
        status = "معتمد" if decision == "approve" else "مرفوض"
    if store.record_decision(rec_id, status, details) and status == "معتمد" and details["action"] == "donate":
        # التبرع المعتمد يُنشئ طلب استلام للجمعية تلقائيًا
        product = store.load_raw()["products"].set_index("product_id").loc[details["product_id"]]
        donations.create_pickup(rec_id, product, details["qty_expected"], details["date"])
    return redirect(url_for("rescue"))


@app.post("/edit/<rec_id>")
def edit(rec_id):
    """تعديل القرار: يرجع المنتج لحالة "يحتاج قرارًا"، ويُلغى طلب الاستلام إن لم تؤكده الجمعية بعد."""
    if donations.can_edit(rec_id) and store.edit_decision(rec_id):
        donations.cancel_pickup(rec_id)
    return redirect(url_for("rescue", edit=rec_id))      # تظهر خيارات القرار مباشرة للمنتج المعدَّل


@app.post("/pickup/<rec_id>")
def pickup(rec_id):
    """تأكيد الجمعية للطلب ثم تسجيل استلامه (من بوابة الجمعية)."""
    donations.advance_pickup(rec_id)
    return redirect(url_for("charity_portal"))


# ------------------------------------------------------------------ بوابة الجمعية
@app.route("/charity")
def charity_portal():
    raw = store.load_raw()
    t = today()
    pk = donations.pickups()
    pk = pk[pk.date == t.strftime("%Y-%m-%d")].iloc[::-1] if len(pk) else pk
    notified = [d for d in donations.expected(raw["products"], t) if d["sent_at"]]
    month = impact.build(raw, outcomes.measure(store.decisions(), raw, donations.pickups()))
    return render_template("charity.html", portal="charity", active="charity", today=t, pickups=pk,
                           notified=notified, received_kg=month["donated_kg"], received_n=month["donated_count"],
                           status_ar=config.CHARITY_STATUS, next_step=config.PICKUP_NEXT,
                           response_ar=config.RESPONSE_AR,
                           waiting=int((pk.status == "sent").sum()) if len(pk) else 0)


@app.post("/charity/respond/<day_key>")
def charity_respond(day_key):
    donations.respond(day_key, request.form.get("answer", ""))
    return redirect(url_for("charity_portal") + "#upcoming")


@app.get("/api/state")
def api_state():
    """تستخدمه صفحتا المدير والجمعية لتحديث نفسيهما عند أي تغيير من الطرف الآخر."""
    return jsonify(v=donations.state_token())


@app.post("/notice/<day_key>")
def notice(day_key):
    donations.send_notice(day_key, donations.expected(store.load_raw()["products"], today()))
    return redirect(url_for("rescue") + "#upcoming")


@app.route("/waste")
def waste():
    raw = store.load_raw()
    pw = store.load_out("product_waste").merge(raw["products"], on="product_id")
    try:
        days = int(request.args.get("days", 7))
    except ValueError:
        days = 7
    days = days if days in config.PERIODS else 7
    pw["waste"] = pw[f"waste_{days}d"]
    pw["demand"] = pw[f"demand_{days}d"]
    pw["cost"] = pw.waste * pw.unit_cost
    totals = {"cost": pw.cost.sum(), "kg": (pw.waste * pw.unit_kg).sum(), "n": int((pw.waste >= 1).sum())}
    cat = request.args.get("cat", "all")
    view = pw if cat == "all" else pw[pw.category == cat]
    view = view.sort_values("cost", ascending=False)
    top = view[view.waste >= 1].head(8)
    chart = charts.hbar(top.product_name.tolist(), top.cost.round(0).tolist(), "ر.س")
    return render_template("waste.html", active="waste", rows=view, totals=totals, chart=chart, cat=cat,
                           cats=config.CATEGORY_AR, days=days, periods=PERIOD_AR, label=PERIOD_AR[days])


@app.route("/orders", methods=["GET", "POST"])
def orders():
    raw = store.load_raw()
    prods = raw["products"]
    o = store.load_out("orders").merge(prods, on="product_id")
    o["diff_cases"] = o.usual_cases - o.smart_cases
    o["diff_value"] = (o.usual_qty - o.smart_qty) * o.unit_cost
    if request.method == "POST":
        picked = request.form.getlist("pick")
        if picked:
            store.approve_order(o[o.product_id.isin(picked)][["product_id", "delivery_date", "smart_cases", "smart_qty"]])
        return redirect(url_for("orders", product=request.form.get("product", "")))
    approval = store.order_approval()
    approved = dict(zip(approval.product_id, approval.approved_at)) if len(approval) else {}

    pid = request.args.get("product")
    if pid not in set(prods.product_id):
        pid = o.sort_values("diff_value", ascending=False).product_id.iloc[0]
    p = prods.set_index("product_id").loc[pid]
    s = raw["sales"]
    hist = s[(s.product_id == pid) & (s.date > s.date.max() - pd.Timedelta(days=56))]
    fc = store.load_out("forecast")
    fc = fc[fc.product_id == pid].sort_values("h")
    chart = charts.history_forecast([short_date(d) for d in hist.date], hist.qty_sold.tolist(),
                                    [short_date(d) for d in fc.target], fc.demand.round(1).tolist(), p.unit)
    return render_template("orders.html", active="orders", rows=o.sort_values("delivery_date"),
                           approved=approved, chart=chart, product=pid, products=prods, p=p,
                           fc_total=float(fc.demand.sum()))


@app.route("/impact")
def impact_page():
    raw = store.load_raw()
    data = impact.build(raw, outcomes.measure(store.decisions(), raw, donations.pickups()))
    weeks = data["weeks"]
    chart = charts.weekly_columns([short_date(d) for d in weeks.start], weeks.pct.round(2).tolist(),
                                  weeks.with_foodwise.tolist(), "بداية استخدام FoodWise", "%")
    return render_template("impact.html", active="impact", d=data, chart=chart,
                           action_ar=config.ACTION_AR)


if __name__ == "__main__":
    # محليًا: http://127.0.0.1:5050 ، وعند النشر تُحدد الاستضافة HOST و PORT
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5050)), debug=False)
