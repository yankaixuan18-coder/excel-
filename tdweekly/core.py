"""核心纯逻辑: 日期区间推算 + 上一周块识别 + 新块单元格方案生成。

这一层不联网, 全部可离线单元测试 —— 也是整个工具最容易出错、最需要被验证的部分。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .a1 import shift_formula_rows

# 日期区间格式，同时支持两种写法：
#   完整式  "6.7-6.13" (月.日-月.日)
#   简写式  "6.7-13"   (月.日-日, 起止同月时省略第二个月份)
FULL_RANGE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\s*-\s*(\d{1,2})\.(\d{1,2})\s*$")
SHORT_RANGE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\s*-\s*(\d{1,2})\s*$")
# 用于"这格是不是日期区间"的判定(两种都认)
DATE_RANGE_RE = re.compile(r"^\s*\d{1,2}\.\d{1,2}\s*-\s*(?:\d{1,2}\.)?\d{1,2}\s*$")


# --------------------------------------------------------------------------- #
# 日期区间
# --------------------------------------------------------------------------- #
def _match_range(text: str):
    """返回 (style, (sm, sd, em, ed))；style ∈ {'full','short'}；无法识别返回 None。"""
    m = FULL_RANGE_RE.match(text)
    if m:
        sm, sd, em, ed = (int(x) for x in m.groups())
        return "full", (sm, sd, em, ed)
    m = SHORT_RANGE_RE.match(text)
    if m:
        sm, sd, ed = (int(x) for x in m.groups())
        return "short", (sm, sd, sm, ed)  # 简写式起止同月
    return None


def parse_range(text: str, year: int) -> tuple[date, date]:
    """把 "6.7-6.13" 或 "6.7-13" 解析成 (start_date, end_date)。

    year 用来补全年份；若结束早于开始(跨年, 如 12.28-1.3)，结束年份自动 +1。
    """
    r = _match_range(str(text).strip())
    if r is None:
        raise ValueError(f"无法识别日期区间: {text!r} (支持 6.7-6.13 或 6.7-13)")
    _, (sm, sd, em, ed) = r
    start = date(year, sm, sd)
    end = date(year, em, ed)
    if end < start:  # 跨年
        end = date(year + 1, em, ed)
    return start, end


def range_style(text: str) -> str | None:
    """返回该区间的写法风格 'full' / 'short'，无法识别返回 None。"""
    r = _match_range(str(text).strip())
    return r[0] if r else None


def format_range(start: date, end: date, style: str = "full") -> str:
    """(start, end) -> 区间字符串。style='short' 且起止同月时输出简写式。"""
    if style == "short" and start.month == end.month:
        return f"{start.month}.{start.day}-{end.day}"
    return f"{start.month}.{start.day}-{end.month}.{end.day}"


def next_range(prev_text: str, year: int, step_days: int = 7) -> tuple[str, date, date]:
    """根据"上一周"的区间推算"下一周"的区间，并沿用其写法风格。

    - 新区间开始 = 上一周开始 + step_days(默认 7 天)
    - 新区间天数跨度与上一周一致
    - 若上一周是简写式但新区间跨月了，则自动回退成完整式
    返回 (区间字符串, 开始日期, 结束日期)。
    """
    style = range_style(prev_text) or "full"
    start, end = parse_range(prev_text, year)
    span = (end - start).days
    new_start = start + timedelta(days=step_days)
    new_end = new_start + timedelta(days=span)
    return format_range(new_start, new_end, style), new_start, new_end


# --------------------------------------------------------------------------- #
# 块识别
# --------------------------------------------------------------------------- #
def _norm(v: Any) -> str:
    return "" if v is None else str(v).strip()


@dataclass
class Block:
    """表格里"一周"对应的一整块行(1 基行号, 含首尾)。"""

    start_row: int    # 块的第一行(通常是"父ASIN"行)
    end_row: int      # 块的最后一行
    prev_date: str    # 该块里的日期区间文本
    date_offset: int = 0  # 日期所在行相对块首的偏移(光伊式=0; 李子向式=1)

    @property
    def height(self) -> int:
        return self.end_row - self.start_row + 1


def find_last_block(
    marker_col_values: list[Any],
    date_col_values: list[Any],
    parent_text: str = "父ASIN",
) -> Block:
    """识别最底部(=最近一周)的那一块。两列按行对齐, 索引 0 对应表格第 1 行。

    - marker_col_values: 标记列(一般 B 列)。块以"父ASIN"行开头, 块内每行都非空,
      用来定位块首(最后一个 == parent_text 的行)和块末(其后最后一个非空行)。
    - date_col_values  : 日期列(一般 A 列)。块内某一行写有日期区间, 可能在块首,
      也可能在父ASIN行的下一行。

    若整列找不到"父ASIN", 回退为按日期行定位(兼容没有父ASIN行的表)。
    """
    starts = [i for i, v in enumerate(marker_col_values) if _norm(v) == parent_text]
    if starts:
        src_start = starts[-1]
    else:
        dstarts = [
            i for i, v in enumerate(date_col_values)
            if _norm(v) and DATE_RANGE_RE.match(_norm(v))
        ]
        if not dstarts:
            raise ValueError(
                f"既找不到 '{parent_text}' 行, 也找不到日期区间, 无法定位上一周的块。"
                "请检查 config 里的 marker_col / date_col / parent_text。"
            )
        src_start = dstarts[-1]

    # 块末行 = 从块首往下, marker 列最后一个非空行
    end = src_start
    for i in range(src_start, len(marker_col_values)):
        if _norm(marker_col_values[i]):
            end = i

    # 在块范围内找日期及其相对偏移
    date_offset = 0
    prev_date = ""
    for i in range(src_start, min(end, len(date_col_values) - 1) + 1):
        v = _norm(date_col_values[i])
        if v and DATE_RANGE_RE.match(v):
            date_offset = i - src_start
            prev_date = v
            break
    if not prev_date:
        raise ValueError(
            f"在第 {src_start + 1}-{end + 1} 行这一块里没找到日期区间。请检查 date_col。"
        )
    return Block(
        start_row=src_start + 1, end_row=end + 1, prev_date=prev_date, date_offset=date_offset
    )


# --------------------------------------------------------------------------- #
# 新块单元格方案
# --------------------------------------------------------------------------- #
@dataclass
class OutCell:
    """新行里某个单元格要写入什么。kind ∈ {formula, value, blank}。"""

    kind: str
    formula: str | None = None
    value: Any = None


@dataclass
class CopyPlan:
    """一次复制操作的完整方案(供 client 转成 API 请求, 也供 dry-run 打印)。"""

    src_start_row: int
    src_end_row: int
    new_start_row: int
    new_end_row: int
    height: int
    prev_date: str
    new_date: str
    date_row_offset: int = 0  # 日期在新块里的相对行(用于合并/写入定位)
    # rows[r][c] = OutCell, r/c 从 0 开始, 对应新块第 r+1 行、第 (first_col+c) 列
    rows: list[list[OutCell]] = field(default_factory=list)


def build_copy_plan(
    block: Block,
    source_grid: list[list[dict]],
    new_date: str,
    date_col_index: int,
    clear_col_indexes: set[int],
) -> CopyPlan:
    """根据上一周的块 + 读到的源单元格, 生成新块每个单元格的写入方案。

    source_grid: 长度 = block.height 的二维列表; 每个单元格是
                 {"value": <显示值>, "formula": <公式串或 None>}。
                 第 0 列对应表格里的"第一列"(通常就是 A 列)。
    date_col_index: 日期列相对 source_grid 第 0 列的下标(A 列且从 A 开始读 => 0)。
    clear_col_indexes: 这些列在新块里留空(每周手动填的实际数据列)。

    规则(复刻"手动复制粘贴 + 改日期"):
      - 日期列: 仅新块第一行写 new_date, 其余行留空(留给合并单元格)。
      - 有公式的单元格: 公式行号整体下移 height 行后写入(**公式始终保留**,
        即便该列在 clear_cols 里 —— 例如父ASIN 汇总行的 SUM 公式应保留并重新汇总)。
      - clear 列里"非公式"的单元格: 留空(这才是你每周手填的实际数据)。
      - 其余(常量, 如 SKU/ASIN 文本): 原值照抄; 空值则留空。
    """
    delta = block.height  # 向下移动的行数 = 块高
    plan = CopyPlan(
        src_start_row=block.start_row,
        src_end_row=block.end_row,
        new_start_row=block.end_row + 1,
        new_end_row=block.end_row + block.height,
        height=block.height,
        prev_date=block.prev_date,
        new_date=new_date,
        date_row_offset=block.date_offset,
    )

    for r, src_row in enumerate(source_grid):
        out_row: list[OutCell] = []
        for c, cell in enumerate(src_row):
            if c == date_col_index:
                # 新日期写在与源块相同的相对行; 其余行留空(供合并)
                out_row.append(
                    OutCell("value", value=new_date)
                    if r == block.date_offset
                    else OutCell("blank")
                )
                continue
            # 公式优先: 始终保留并平移(即便在 clear 列, 如汇总行的 SUM)
            formula = cell.get("formula")
            if formula:
                out_row.append(OutCell("formula", formula=shift_formula_rows(formula, delta)))
                continue
            if c in clear_col_indexes:  # 非公式的手填数据列 -> 留空
                out_row.append(OutCell("blank"))
                continue
            value = cell.get("value")
            if value in (None, ""):
                out_row.append(OutCell("blank"))
            else:
                out_row.append(OutCell("value", value=value))
        plan.rows.append(out_row)

    return plan
