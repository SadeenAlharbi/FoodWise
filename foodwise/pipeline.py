"""تشغيل كامل: البيانات ← توقع الطلب ← محاكاة الهدر والطلبيات ← قائمة الإنقاذ.

    python -m foodwise.pipeline              # يولد البيانات إذا لم تكن موجودة ثم يحسب كل شيء
    python -m foodwise.pipeline --regenerate # يعيد توليد البيانات ويمسح قرارات اليوم
"""
from __future__ import annotations

import argparse
import json
import time


from foodwise import backtest, config, forecast, generate, rescue, simulate, store


def run(regenerate: bool = False) -> dict:
    t0 = time.time()
    if regenerate or not (config.RAW_DIR / "sales.csv").exists():
        print("توليد بيانات الفرع...", flush=True)
        generate.save(generate.generate())
        for f in (config.DECISIONS_FILE, config.ORDER_APPROVALS_FILE, config.PICKUPS_FILE, config.NOTICES_FILE, config.RESPONSES_FILE):
            f.unlink(missing_ok=True)
    raw = store.load_raw()
    print("توقع الطلب واختباره على آخر 6 أسابيع...", flush=True)
    fc = forecast.run(raw)
    print("محاكاة الأيام القادمة (الهدر والطلبيات)...", flush=True)
    sim = simulate.run(raw, fc)
    recs = rescue.build(sim["batches"], raw["products"])

    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    fc["forecast"].to_csv(config.OUT_DIR / "forecast.csv", index=False)
    fc["test"].to_csv(config.OUT_DIR / "forecast_test.csv", index=False)
    sim["products"].to_csv(config.OUT_DIR / "product_waste.csv", index=False)
    sim["batches"].to_csv(config.OUT_DIR / "batches.csv", index=False)
    sim["orders"].to_csv(config.OUT_DIR / "orders.csv", index=False)
    sim["daily_waste"].to_csv(config.OUT_DIR / "daily_waste.csv", index=False)
    recs.to_csv(config.OUT_DIR / "rescue.csv", index=False)
    print("التحقق من حساب الهدر على أيام سابقة...", flush=True)
    fw_start = raw["info"].foodwise_start.iloc[0]
    before = {**raw, "sales": raw["sales"][raw["sales"].date < fw_start]}
    bt = backtest.run(raw, forecast.run(before))
    bt["detail"].to_csv(config.OUT_DIR / "waste_backtest.csv", index=False)
    (config.OUT_DIR / "waste_backtest.json").write_text(json.dumps(bt["summary"], ensure_ascii=False, indent=2),
                                                        encoding="utf-8")
    report = {**fc["report"], "waste_check": bt["summary"], "today": str(sim["today"].date()), "runtime_sec": round(time.time() - t0, 1)}
    (config.OUT_DIR / "model_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"انتهى خلال {time.time() - t0:.0f} ثانية. دقة توقع الطلب: {report['accuracy_pct']}%", flush=True)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--regenerate", action="store_true")
    run(ap.parse_args().regenerate)
