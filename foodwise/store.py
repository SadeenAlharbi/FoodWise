"""قراءة الملفات وتسجيل قرارات المستخدم."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from foodwise import config

DATE_COLS = {"sales": ["date"], "batches": ["received_date", "expiry_date"], "waste": ["date"], "orders": ["date"],
             "decisions_history": ["date"], "stock_snapshots": ["date"], "weather": ["date"], "info": ["last_data_day", "foodwise_start"]}


def load_raw() -> dict[str, pd.DataFrame]:
    out = {}
    for f in config.RAW_DIR.glob("*.csv"):
        out[f.stem] = pd.read_csv(f, parse_dates=DATE_COLS.get(f.stem, []))
    return out


def load_out(name: str) -> pd.DataFrame:
    return pd.read_csv(config.OUT_DIR / f"{name}.csv")


def model_report() -> dict:
    return json.loads((config.OUT_DIR / "model_report.json").read_text(encoding="utf-8"))


def _read(path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def decisions(history: bool = False) -> pd.DataFrame:
    """القرارات السارية فقط. history=True يرجع السجل كاملًا ومعه القرارات التي عُدّلت."""
    log = _read(config.DECISIONS_FILE)
    if history or not len(log) or "edited_at" not in log:
        return log
    return log[log.edited_at.isna()].reset_index(drop=True)


def record_decision(rec_id: str, status: str, details: dict | None = None) -> bool:
    """details: تفاصيل القرار (المنتج، الدفعة، الكميات) لقياس نتيجته تلقائيًا لاحقًا."""
    if rec_id in set(decisions().get("rec_id", [])):
        return False
    log = decisions(history=True)
    row = pd.DataFrame([{"rec_id": rec_id, "status": status, "at": datetime.now().strftime("%H:%M"), **(details or {})}])
    log = pd.concat([log, row], ignore_index=True) if len(log) else row
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    log.to_csv(config.DECISIONS_FILE, index=False)
    return True


def edit_decision(rec_id: str) -> bool:
    """يلغي القرار الساري ليختار المدير من جديد. القرار القديم يبقى في السجل مع وقت تعديله."""
    log = decisions(history=True)
    if not len(log):
        return False
    if "edited_at" not in log:
        log["edited_at"] = None
    active = (log.rec_id == rec_id) & log.edited_at.isna()
    if not active.any():
        return False
    log["edited_at"] = log.edited_at.astype(object)
    log.loc[active, "edited_at"] = datetime.now().strftime("%H:%M")
    log.to_csv(config.DECISIONS_FILE, index=False)
    return True


def order_approval() -> pd.DataFrame:
    return _read(config.ORDER_APPROVALS_FILE)


def approve_order(rows: pd.DataFrame) -> None:
    """يعتمد المنتجات التي اختارها المدير فقط، ويضيفها لما اعتُمد سابقًا."""
    old = order_approval()
    if len(old):
        rows = rows[~rows.product_id.isin(old.product_id)]
    rows = rows.assign(approved_at=datetime.now().strftime("%H:%M"))
    out = pd.concat([old, rows], ignore_index=True) if len(old) else rows
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(config.ORDER_APPROVALS_FILE, index=False)
