"""A1 表示法工具 + 公式相对行号平移。

为什么需要平移公式:
    把"上一周"那一整块行复制到它下面时, 公式里的**相对行引用**必须跟着往下移,
    否则新行里的公式仍然指向旧行 —— 就像你在表格里手动"复制粘贴"时, Excel/腾讯
    文档会自动把 =J5/G5 调整成 =J12/G12 一样。本模块用来复刻这个调整。

设计原则:
    - 只做纯字符串/数值计算, 不联网, 方便离线单元测试。
    - 绝对行引用(带 $ 的, 例如 G$5)保持不变。
    - 不修改字符串字面量(双引号内)里的内容。
    - 尽量避免把函数名(如 LOG10()) 误判成单元格引用。
"""

import re

# 匹配双引号字符串字面量(Excel/腾讯文档里 "" 表示一个转义的双引号)
_STRING_RE = re.compile(r'"(?:[^"]|"")*"')

# 匹配单元格引用, 形如  A1 / $A1 / A$1 / $A$1 / Sheet1!A1 里的 A1。
#   group1 = 列前的 $(绝对列)
#   group2 = 列字母
#   group3 = 行前的 $(绝对行)
#   group4 = 行号
# 约束:
#   - 前面不能紧跟字母/数字/下划线(避免匹配到标识符的一部分, 如 ASIN 文本)
#   - 后面不能紧跟字母/数字/下划线/左括号(避免把函数名 LOG10( 当成引用)
_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_])(\$?)([A-Za-z]{1,3})(\$?)(\d+)(?![A-Za-z0-9_(])"
)


def col_to_index(col: str) -> int:
    """列名 -> 0 基索引。 'A' -> 0, 'Z' -> 25, 'AA' -> 26。"""
    col = col.strip().upper()
    if not col or not col.isalpha():
        raise ValueError(f"非法列名: {col!r}")
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def index_to_col(idx: int) -> str:
    """0 基索引 -> 列名。 0 -> 'A', 25 -> 'Z', 26 -> 'AA'。"""
    if idx < 0:
        raise ValueError(f"列索引不能为负: {idx}")
    n = idx + 1
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def _shift_segment(seg: str, delta: int) -> str:
    """对一段(不含字符串字面量的)公式文本做相对行号平移。"""

    def repl(m: "re.Match[str]") -> str:
        dollar_col, col, dollar_row, row = m.groups()
        if dollar_row == "$":  # 绝对行, 不动
            return m.group(0)
        new_row = int(row) + delta
        if new_row < 1:  # 理论上向下复制不会出现, 兜底夹紧
            new_row = 1
        return f"{dollar_col}{col}{dollar_row}{new_row}"

    return _REF_RE.sub(repl, seg)


def shift_formula_rows(formula: str, delta: int) -> str:
    """把公式里所有"相对行引用"的行号整体 +delta。

    >>> shift_formula_rows("=J5/G5", 7)
    '=J12/G12'
    >>> shift_formula_rows("=A$1*B2", 7)   # 绝对行不动
    '=A$1*B9'
    >>> shift_formula_rows('=IF(A2="",0,A2)', 3)  # 不碰字符串字面量
    '=IF(A5="",0,A5)'
    """
    if not formula or delta == 0:
        return formula

    out = []
    last = 0
    for m in _STRING_RE.finditer(formula):
        out.append(_shift_segment(formula[last:m.start()], delta))
        out.append(m.group(0))  # 字符串字面量原样保留
        last = m.end()
    out.append(_shift_segment(formula[last:], delta))
    return "".join(out)
