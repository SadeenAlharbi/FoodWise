"""قائمة الإنقاذ اليوم: دفعات متوقع أن يتبقى منها شيء عند انتهاء صلاحيتها، مع القرار المقترح وسببه.

قاعدة القرار حسب ما بقي على الصلاحية (نفس الترتيب العالمي: بيع، ثم تبرع مخطط له، ثم آخر خصم):
- 3 أيام: نقل لقسم Eat Fresh (خضار وفواكه) أو لواجهة العرض (بقية الفئات).
- مرحلة التبرع (يومان، أو يوم للمنتج الذي صلاحيته 3 أيام): تبرع بالكمية المتوقع ألا تُباع حتى مع الخصم،
  وخصم على الباقي. فتصل الجمعية كمية مخطط لها وما زال على صلاحيتها وقت للتوزيع.
- يوم: خصم أكبر.
- ينتهي اليوم: آخر خصم حتى الإغلاق.
"""
from __future__ import annotations

import pandas as pd

from foodwise import config

WINDOW_DAYS = 4   # ننظر للدفعات التي تنتهي خلال 5 أيام (من اليوم حتى بعد 4 أيام)


def expiry_text(days_left: int) -> str:
    return {0: "ينتهي اليوم", 1: "ينتهي غدًا", 2: "خلال يومين"}.get(days_left, f"خلال {days_left} أيام")


def donation_day(shelf_life: int) -> int:
    """متى يُتبرع بالفائض: قبل الانتهاء بيومين، أو بيوم للمنتج الذي صلاحيته 3 أيام.
    المنتج الذي صلاحيته يومان (كالخبز الطازج) لا يُتبرع به لأنه لا يبقى له وقت للتوزيع: يرجع 0."""
    return max(0, min(config.DONATE_DAYS, shelf_life - 2))


def discount_pct(days_left: int) -> int:
    if days_left <= 0:
        return config.DISCOUNT_LAST
    if days_left == 1:
        return config.DISCOUNT_SHORT
    return config.DISCOUNT_LONG


def suggest(days_left: int, category: str, share: float = 0.0, shelf_life: int = 7) -> tuple[str, str]:
    """القرار الرئيسي للدفعة: يرجع (نوع القرار، نص القرار). مرحلة التبرع تُقسَّم في build."""
    if days_left <= 0:
        return "discount", f"خصم {config.DISCOUNT_LAST}% حتى الإغلاق"
    if days_left == donation_day(shelf_life) and days_left > 0:
        return "donate", f"تبرع بالفائض المتوقع ل{config.CHARITY_NAME}"
    if days_left == 1:
        return "discount", f"خصم {config.DISCOUNT_SHORT}%"
    if days_left == config.EATFRESH_DAYS and category in config.EATFRESH_CATEGORIES:
        return "eatfresh", "نقل لقسم Eat Fresh"          # يُستخدم في تحضير الوجبات والسلطات قبل انتهائه
    return "front", "نقل لواجهة العرض"


def options(days_left: int, category: str = "") -> dict[str, str]:
    """كل القرارات الممكنة للدفعة، ليختار المدير بديلًا إذا رفض المقترح."""
    out = {"discount": f"خصم {discount_pct(days_left)}%", "front": "نقل لواجهة العرض"}
    if category in config.EATFRESH_CATEGORIES:
        out["eatfresh"] = "نقل لقسم Eat Fresh"
    if days_left >= 1:                                   # لا تبرع بمنتج ينتهي اليوم
        out["donate"] = f"تبرع ل{config.CHARITY_NAME}"
    return out


def priority(value: float) -> str:
    if value >= config.PRIORITY_HIGH:
        return "عالية"
    if value >= config.PRIORITY_MID:
        return "متوسطة"
    return "منخفضة"


def _row(b, pr, action: str, action_text: str, qty: int, reason: str) -> dict:
    value = qty * pr.unit_cost
    saved_qty = round(qty * config.RESCUE_RATE[action])
    return {
        "rec_id": f"{b.batch_id}-{action}", "batch_id": b.batch_id, "product_id": b.product_id,
        "product_name": pr.product_name, "category": pr.category, "unit": pr.unit,
        "days_left": int(b.days_left), "expiry_text": expiry_text(int(b.days_left)),
        "stock": round(b.qty_on_hand), "exp_sold": round(b.exp_sold), "waste_qty": qty, "waste_value": value,
        "priority": priority(value), "action": action, "action_text": action_text,
        "saved_qty": saved_qty, "saved_value": saved_qty * pr.unit_cost, "reason": reason,
    }


def build(batches: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    p = products.set_index("product_id")
    rows = []
    for b in batches.itertuples():
        if b.days_left > WINDOW_DAYS or b.exp_waste < 1:
            continue
        pr = p.loc[b.product_id]
        qty = round(b.exp_waste)
        if qty < 1:
            continue
        base = (f"المخزون {round(b.qty_on_hand)} {pr.unit}، والمتوقع بيعه قبل انتهاء الصلاحية "
                f"{round(b.exp_sold)} {pr.unit} فقط، فيتبقى نحو {qty} {pr.unit} قيمتها {qty * pr.unit_cost:,.0f} ر.س.")
        action, text = suggest(int(b.days_left), pr.category, 0.0, int(pr.shelf_life))
        if action != "donate":
            rows.append(_row(b, pr, action, text, qty, base))
            continue
        # مرحلة التبرع: ما يتوقع ألا يُباع حتى مع الخصم يُتبرع به، والباقي يُخصم
        pct = discount_pct(int(b.days_left))
        donate_qty = round(qty * (1 - config.RESCUE_RATE["discount"]))
        sell_qty = qty - donate_qty
        if donate_qty >= 1:
            rows.append(_row(b, pr, "donate", text, donate_qty,
                             base + f" المتوقع ألا يُباع حتى مع خصم {pct}% نحو {donate_qty} {pr.unit}، "
                                    f"فيُتبرع به وما زال على صلاحيته وقت للتوزيع."))
        if sell_qty >= 1:
            rows.append(_row(b, pr, "discount", f"خصم {pct}%", sell_qty,
                             base + f" يُخصم {sell_qty} {pr.unit} {pct}% لبيعها، ويُتبرع بالباقي."))
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values("waste_value", ascending=False).reset_index(drop=True)
    return out
