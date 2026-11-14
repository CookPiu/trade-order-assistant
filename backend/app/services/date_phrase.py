"""交期表述换算：由服务端按当前日期计算，不交给模型（FR-011）。"""
import re
from datetime import date, timedelta

WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
RELATIVE = {"今天": 0, "今日": 0, "明天": 1, "明日": 1, "后天": 2, "大后天": 3}
CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _num(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    if s in CN_NUM:
        return CN_NUM[s]
    if len(s) == 2 and s[0] == "十" and s[1] in CN_NUM:
        return 10 + CN_NUM[s[1]]
    return None


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date_phrase(text: str | None, today: date) -> date | None:
    if not text:
        return None
    t = re.sub(r"\s", "", str(text))
    if m := re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", t):
        return _safe(int(m[1]), int(m[2]), int(m[3]))
    if m := re.search(r"(\d{1,2})[月/.](\d{1,2})[日号]?", t):
        d = _safe(today.year, int(m[1]), int(m[2]))
        if d and d < today - timedelta(days=30):
            d = _safe(today.year + 1, int(m[1]), int(m[2]))
        return d
    for word in sorted(RELATIVE, key=len, reverse=True):
        if word in t:
            return today + timedelta(days=RELATIVE[word])
    if m := re.search(r"([0-9一二两三四五六七八九十]+)天(后|之后|以后|内|之内)", t):
        n = _num(m[1])
        if n is not None:
            return today + timedelta(days=n)
    if m := re.search(r"(下下|下|本|这)?(?:周|星期|礼拜)([一二三四五六日天])", t):
        target = WEEKDAYS[m[2]]
        monday = today - timedelta(days=today.weekday())
        if m[1] == "下下":
            return monday + timedelta(days=14 + target)
        if m[1] == "下":
            return monday + timedelta(days=7 + target)
        d = monday + timedelta(days=target)
        if m[1] is None and d < today:
            d += timedelta(days=7)
        return d
    if "月底" in t:
        nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        return nxt - timedelta(days=1)
    if m := re.fullmatch(r"(\d{1,2})[日号]", t):
        d = _safe(today.year, today.month, int(m[1]))
        if d and d < today:
            d = _safe(today.year + (today.month == 12), today.month % 12 + 1, int(m[1]))
        return d
    return None
