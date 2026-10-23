"""رسوم SVG تُبنى في الخادم: لا تحتاج إنترنت ولا مكتبات خارجية وقت العرض."""
from __future__ import annotations

import math
from html import escape

INK = "#10292D"
MUTED = "#5B7470"
GRID = "#E3EBE7"
GREEN = "#0B6B47"
GREEN_LIGHT = "#22B573"
AMBER = "#D99A1E"
CLAY = "#C2562B"


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * exp >= v:
            return m * exp
    return 10 * exp


def _fmt(v: float) -> str:
    if abs(v) < 10 and v != int(v):
        return f"{v:.1f}"
    return f"{v:,.0f}"


def hbar(labels: list[str], values: list[float], unit: str, color: str = AMBER, width: int = 640) -> str:
    """أشرطة أفقية: الاسم يمين، الشريط يتجه لليسار، والقيمة مع وحدتها بجانبه."""
    if not values:
        return ""
    row, top = 34, 8
    h = top + row * len(values) + 8
    label_w, value_w = 150, 90
    bar_w = width - label_w - value_w - 16
    vmax = max(values) or 1
    parts = [f'<svg class="chart" viewBox="0 0 {width} {h}" role="img" aria-label="رسم أشرطة" '
             f'xmlns="http://www.w3.org/2000/svg">']
    for i, (lab, v) in enumerate(zip(labels, values)):
        y = top + i * row
        w = max(2, bar_w * v / vmax)
        x_right = width - label_w
        parts.append(f'<text x="{width}" y="{y + 21}" text-anchor="end" font-size="14" fill="{INK}">{escape(lab)}</text>')
        parts.append(f'<rect x="{x_right - 8 - w:.1f}" y="{y + 6}" width="{w:.1f}" height="20" rx="5" fill="{color}"/>')
        parts.append(f'<text x="{x_right - 14 - w:.1f}" y="{y + 21}" text-anchor="end" font-size="13" '
                     f'font-weight="600" fill="{INK}">{_fmt(v)} {escape(unit)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _frame(width, height, pad, ymax, unit, nticks=4):
    l, r, t, b = pad
    out = []
    for k in range(nticks + 1):
        val = ymax * k / nticks
        y = height - b - (height - t - b) * k / nticks
        out.append(f'<line x1="{l}" x2="{width - r}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>')
        out.append(f'<text x="{l - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="12" fill="{MUTED}">{_fmt(val)}</text>')
    out.append(f'<text x="{l - 8}" y="{t - 10}" text-anchor="end" font-size="12" fill="{MUTED}">{escape(unit)}</text>')
    return out


def history_forecast(dates: list[str], actual: list[float], f_dates: list[str], forecast: list[float],
                     unit: str, width: int = 900, height: int = 300) -> str:
    """المبيعات الفعلية (خط متصل) ثم الطلب المتوقع (خط متقطع). المحور الزمني من اليسار لليمين."""
    pad = (56, 16, 30, 40)
    l, r, t, b = pad
    n = len(dates) + len(f_dates)
    ymax = _nice_max(max(actual + forecast) * 1.1)
    xs = lambda i: l + (width - l - r) * i / max(1, n - 1)
    ys = lambda v: height - b - (height - t - b) * v / ymax
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="المبيعات والطلب المتوقع" '
             f'xmlns="http://www.w3.org/2000/svg">'] + _frame(width, height, pad, ymax, unit)
    pts = " ".join(f"{xs(i):.1f},{ys(v):.1f}" for i, v in enumerate(actual))
    parts.append(f'<polyline points="{pts}" fill="none" stroke="{GREEN}" stroke-width="2.2"/>')
    k0 = len(actual) - 1
    fpts = " ".join(f"{xs(k0 + i):.1f},{ys(v):.1f}" for i, v in enumerate([actual[-1]] + forecast))
    parts.append(f'<polyline points="{fpts}" fill="none" stroke="{AMBER}" stroke-width="2.6" stroke-dasharray="6 5"/>')
    for i, v in enumerate(forecast):
        parts.append(f'<circle cx="{xs(k0 + 1 + i):.1f}" cy="{ys(v):.1f}" r="3.5" fill="{AMBER}"/>')
    parts.append(f'<line x1="{xs(k0):.1f}" x2="{xs(k0):.1f}" y1="{t}" y2="{height - b}" stroke="{MUTED}" stroke-dasharray="3 4"/>')
    parts.append(f'<text x="{xs(k0) + 6:.1f}" y="{t + 12}" font-size="12" fill="{MUTED}">اليوم</text>')
    all_dates = dates + f_dates
    step = max(1, n // 8)
    for i in range(0, n, step):
        parts.append(f'<text x="{xs(i):.1f}" y="{height - 14}" text-anchor="middle" font-size="12" fill="{MUTED}">{all_dates[i]}</text>')
    parts.append("</svg>")
    return "".join(parts)


def weekly_columns(labels: list[str], values: list[float], highlight: list[bool], marker_label: str,
                   unit: str, width: int = 900, height: int = 300) -> str:
    """أعمدة أسبوعية؛ الأسابيع مع FoodWise بلون أخضر وقبلها بلون رمادي، مع خط يوضح البداية."""
    pad = (56, 16, 30, 40)
    l, r, t, b = pad
    n = len(values)
    ymax = _nice_max(max(values) * 1.1)
    slot = (width - l - r) / n
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="الهدر الأسبوعي" '
             f'xmlns="http://www.w3.org/2000/svg">'] + _frame(width, height, pad, ymax, unit)
    first = None
    for i, (v, hl) in enumerate(zip(values, highlight)):
        x = l + slot * i + slot * 0.18
        bh = (height - t - b) * v / ymax
        parts.append(f'<rect x="{x:.1f}" y="{height - b - bh:.1f}" width="{slot * 0.64:.1f}" height="{bh:.1f}" rx="3" '
                     f'fill="{GREEN_LIGHT if hl else "#B9C8C3"}"/>')
        if hl and first is None:
            first = l + slot * i
        if i % 2 == 0 or i == n - 1:
            parts.append(f'<text x="{x + slot * 0.32:.1f}" y="{height - 14}" text-anchor="middle" font-size="11" '
                         f'fill="{MUTED}">{labels[i]}</text>')
    if first is not None:
        parts.append(f'<line x1="{first:.1f}" x2="{first:.1f}" y1="{t - 6}" y2="{height - b}" stroke="{GREEN}" '
                     f'stroke-width="1.5" stroke-dasharray="4 4"/>')
        parts.append(f'<text x="{first + 6:.1f}" y="{t + 6}" font-size="12" font-weight="600" fill="{GREEN}">'
                     f'{escape(marker_label)}</text>')
    parts.append("</svg>")
    return "".join(parts)
