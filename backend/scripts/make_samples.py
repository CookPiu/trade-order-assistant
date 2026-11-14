"""生成演示素材：发货签收单图片与批量导入 Excel（FR-061）。

用法（在 backend 目录）：uv run python -m scripts.make_samples
交期按运行当天计算，演示前重新生成一次即可。
"""
import random
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.core import clock
from app.core.config import ROOT_DIR

SAMPLES = ROOT_DIR / "samples"
FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype"), Path("/System/Library/Fonts")]
EXCEL_HEADERS = ["单据类型", "合同编号", "物料名称", "规格", "数量", "单价", "交期", "备注"]


def _font(size: int, names=("simhei.ttf", "msyh.ttc", "simsun.ttc", "NotoSansCJK-Regular.ttc", "PingFang.ttc")):
    for d in FONT_DIRS:
        for n in names:
            p = d / n
            if p.exists():
                return ImageFont.truetype(str(p), size)
    raise SystemExit("找不到中文字体，请安装黑体或微软雅黑")


def make_receipt(path: Path, today: date) -> None:
    w, h = 1400, 980
    img = Image.new("RGB", (w, h), (247, 244, 236))
    d = ImageDraw.Draw(img)
    title, body, hand = _font(52), _font(30), _font(34, ("simkai.ttf", "STKAITI.TTF", "simhei.ttf", "msyh.ttc"))
    ink = (40, 40, 48)
    d.text((w // 2 - 160, 50), "发 货 签 收 单", font=title, fill=ink)
    d.text((80, 150), "合同编号：2026-CG-031", font=body, fill=ink)
    d.text((780, 150), f"日期：{today:%Y年%m月%d日}", font=body, fill=ink)
    d.text((80, 205), "发货单位：华东建材供应有限公司", font=body, fill=ink)
    d.text((780, 205), "到货单位：科技城项目部", font=body, fill=ink)
    x0, x1, y = 80, w - 80, 270
    cols = [80, 420, 680, 860, 1040, w - 80]
    heads = ["物资名称", "规格型号", "单位", "数量", "金额（元）"]
    for r in range(4):
        d.line((x0, y + r * 80, x1, y + r * 80), fill=ink, width=3)
    for c in cols:
        d.line((c, y, c, y + 240), fill=ink, width=3)
    for i, t in enumerate(heads):
        d.text((cols[i] + 20, y + 22), t, font=body, fill=ink)
    row = ["42.5水泥", "P.O42.5 散装", "吨", "500", "220,000.00"]
    for i, t in enumerate(row):
        d.text((cols[i] + 20 + random.randint(-4, 4), y + 100 + random.randint(-5, 5)), t, font=hand, fill=(20, 30, 90))
    d.text((80, 540), "合计金额（大写）：贰拾贰万元整", font=hand, fill=(20, 30, 90))
    d.text((80, 620), "备注：科技城项目追加采购，分两批到货", font=body, fill=ink)
    d.text((80, 760), "发货人：孙明", font=body, fill=ink)
    d.text((560, 760), "收货人签字：", font=body, fill=ink)
    d.text((760, 750), "陈工", font=_font(46, ("simkai.ttf", "simhei.ttf")), fill=(20, 30, 90))
    d.ellipse((1080, 700, 1280, 900), outline=(200, 40, 40), width=6)
    d.text((1112, 782), "收货专用章", font=_font(28), fill=(200, 40, 40))
    img = img.rotate(-1.6, expand=True, fillcolor=(90, 90, 90)).filter(ImageFilter.GaussianBlur(0.6))
    img.save(path, quality=88)


def make_batch_excel(path: Path, today: date) -> None:
    d = lambda n: today + timedelta(days=n)  # noqa: E731
    rows = [
        ["销售", "2026-WZ-089", "螺纹钢20", "HRB400E", 50, 3650, d(5), ""],
        ["销售", "2026-WZ-089", "三级螺纹16", "HRB400E", 40, 3680, d(6), ""],
        ["销售", "2026-WZ-089", "25螺", "HRB400E", 30, 3620, d(7), ""],
        ["销售", "2026-WZ-998", "螺纹钢20", "HRB400E", 20, 3650, d(5), "合同号错误"],
        ["销售", "2026-WZ-089", "螺纹钢20", "HRB400E", 30, None, d(8), "单价缺失"],
        ["采购", "2026-CG-031", "42.5水泥", "P.O 42.5", 200, 440, d(4), ""],
        ["采购", "2026-CG-031", "PO42.5", "P.O 42.5", 300, 440, d(9), ""],
        ["采购", "2026-CG-040", "螺纹钢20", "HRB400E", 100, 3550, d(10), ""],
        ["采购", "2026-CG-040", "三级钢16", "HRB400E", 80, 3570, d(10), ""],
        ["销售", "2026-WZ-095", "25螺", "HRB400E", 20, 3630, d(30), "交期晚于合同到期日"],
    ]
    wb = Workbook()
    ws = wb.active
    ws.title = "订单"
    ws.append(EXCEL_HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E8C")
    for r in rows:
        ws.append(r)
    for row in ws.iter_rows(min_row=2, min_col=7, max_col=7):
        for c in row:
            c.number_format = "yyyy-mm-dd"
    for col, width in zip("ABCDEFGH", (10, 16, 14, 12, 10, 10, 14, 20)):
        ws.column_dimensions[col].width = width
    wb.save(path)


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    today = clock.today()
    random.seed(7)
    make_receipt(SAMPLES / "发货签收单_42.5水泥.jpg", today)
    make_batch_excel(SAMPLES / "批量订单示例.xlsx", today)
    print("已生成：", *(p.name for p in SAMPLES.iterdir()))


if __name__ == "__main__":
    main()
