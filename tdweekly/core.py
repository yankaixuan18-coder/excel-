"""核心纯逻辑: 日期区间推算 + 上一周块识别 + 新块单元格方案生成。

这一层不联网, 全部可离线单元测试 —— 也是整个工具最容易出错、最需要被验证的部分。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .a1 import shift_formula_rows

# 日期区间格式, 例如 "5.31-6.6" / "6.14-6.20" (月.日-月.日, 不带前导零)
DATE_RANGE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\s*-\s*(\d{1,2})\.(\d{1,2})\s*$")


# --------------------------------------------------------------------------- #
# 日期区间
# --------------------------------------------------------------------------- #
def parse_range(text: str, year: int) -> tuple[date, date]:
    """把 "5.31-6.6" 解析成 (start_date, end_date)。

    year 用来补全年份; 若结束日期早于开始日期(跨年, 如 12.28-1.3), 结束年份自动 +1。
    """
    m = DATE_RANGE_RE.match(str(text))
    if not m:
        raise ValueError(f"无法识别日期区间: {text!r} (期望形如 5.31-6.6)")
    sm, sd, em, ed = (int(x) for x in m.groups())
    start = date(year, sm, sd)
    end = date(year, em, ed)
    if end < start:  # 跨年
        end = date(year + 1, em, ed)
    return start, end


def format_range(start: date, end: date) -> str:
    """(start, end) -> "5.31-6.6" (不带前导零)。"""
    return f"{start.month}.{start.day}-{end.month}.{end.day}"


def next_range(prev_text: str, year: int, step_days: int = 7) -> tuple[str, date, date]:
    """根据"上一周"的区间推算"下一周"的区间。

    - 新区间的开始 = 上一周开始 + step_days(默认 7 天)
    - 新区间的天数跨度与上一周保持一致(例如一周 = 7 天, 即 end-start 相差 6 天)
    返回 (区间字符串, 开始日期, 结束日期)。
    """
    start, end = parse_range(prev_text, year)
    span = (end - start).days  # 例如一周 = 6
    new_start = start + timedelta(days=step_days)
    new_end = new_start + timedelta(days=span)
    return format_range(new_start, new_end), new_start, new_end


# --------------------------------------------------------------------------- #
# 块识别
# --------------------------------------------------------------------------- #
@dataclass
class Block:
    """表格里"一周"对应的一整块行(1 基行号, 含首尾)。"""

    start_row: int  # 块的第一行(就是日期所在行)
    end_row: int    # 块的最后一行
    prev_date: str  # 该块 A 列里的日期区间文本

    @property
    def height(self) -> int:
        return self.end_row - self.start_row + 1


def find_last_block(
    date_col_values: list[Any],
    marker_col_values: list[Any],
) -> Block:
    """识别最底部(=最近一周)的那一块。

    入参是两列从第 1 行开始、按行对齐的值列表:
      - date_col_values : 日期列(A 列)。每一块只有第一行有日期(合并单元格),
                          其余行为空。块的"开始"= 该列里匹配日期区间格式的行。
      - marker_col_values: 标记列(默认 B 列 SKU), 块内每一行都非空, 用来确定块的末行。

    返回最后一个日期块。
    """
    starts = [
        i
        for i, v in enumerate(date_col_values)
        if v not in (None, "") and DATE_RANGE_RE.match(str(v).strip())
    ]
    if not starts:
        raise ValueError(
            "在日期列里没有找到任何形如 5.31-6.6 的日期区间, 无法定位上一周的块。"
            "请检查 config 里的 date_col 是否正确。"
        )
    src_start = starts[-1]  # 0 基

    # 从块开始往下, 找到 marker 列最后一个非空行 = 块末行
    end = src_start
    for i in range(src_start, len(marker_col_values)):
        if marker_col_values[i] not in (None, ""):
            end = i
        # 注意: 不在第一个空行就 break, 因为合并/空格可能造成中间空洞;
        #       取"最后一个非空行"更稳妥。
    prev_date = str(date_col_values[src_start]).strip()
    return Block(start_row=src_start + 1, end_row=end + 1, prev_date=prev_date)


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
    )

    for r, src_row in enumerate(source_grid):
        out_row: list[OutCell] = []
        for c, cell in enumerate(src_row):
            if c == date_col_index:
                out_row.append(
                    OutCell("value", value=new_date) if r == 0 else OutCell("blank")
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
