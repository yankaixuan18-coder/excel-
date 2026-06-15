"""core 模块单元测试 (标准库 unittest, 无需 pytest)。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tdweekly.core import (
    Block,
    build_copy_plan,
    find_last_block,
    next_range,
    parse_range,
)


class TestDateRange(unittest.TestCase):
    def test_parse(self):
        s, e = parse_range("5.31-6.6", 2025)
        self.assertEqual((s.month, s.day), (5, 31))
        self.assertEqual((e.month, e.day), (6, 6))

    def test_next_week(self):
        # 截图里的真实序列: 5.31-6.6 -> 6.7-6.13 -> 6.14-6.20
        self.assertEqual(next_range("5.31-6.6", 2025)[0], "6.7-6.13")
        self.assertEqual(next_range("6.7-6.13", 2025)[0], "6.14-6.20")
        self.assertEqual(next_range("6.14-6.20", 2025)[0], "6.21-6.27")

    def test_next_week_month_boundary(self):
        self.assertEqual(next_range("5.10-5.16", 2025)[0], "5.17-5.23")

    def test_year_boundary(self):
        # 跨年: 12.27-1.2 (上一周 12.27 起) -> 下一周 1.3-1.9
        self.assertEqual(next_range("12.27-1.2", 2025)[0], "1.3-1.9")


class TestFindLastBlock(unittest.TestCase):
    def _columns(self):
        # 模拟 A 列(日期, 仅块首有值)与 B 列(SKU, 块内每行有值)
        # 行1-2 表头; 块1 = 行3-5(5.31-6.6); 块2 = 行6-8(6.7-6.13)
        date_col = ["父ASIN", "日期", "5.31-6.6", "", "", "6.7-6.13", "", ""]
        marker = ["BD_IFDB", "SKU", "父ASIN", "sku1", "sku2", "父ASIN", "sku1", "sku2"]
        return date_col, marker

    def test_last_block(self):
        date_col, marker = self._columns()
        b = find_last_block(date_col, marker)
        self.assertEqual(b.start_row, 6)
        self.assertEqual(b.end_row, 8)
        self.assertEqual(b.height, 3)
        self.assertEqual(b.prev_date, "6.7-6.13")

    def test_no_block_raises(self):
        with self.assertRaises(ValueError):
            find_last_block(["日期", "SKU"], ["x", "y"])

    def test_trailing_blank_rows_ignored(self):
        # B 列末尾有空行不应被算进块
        date_col = ["日期", "6.7-6.13", "", ""]
        marker = ["SKU", "父ASIN", "sku1", ""]
        b = find_last_block(date_col, marker)
        self.assertEqual(b.end_row, 3)  # 行4 是空, 不算
        self.assertEqual(b.height, 2)


class TestBuildCopyPlan(unittest.TestCase):
    def test_plan(self):
        block = Block(start_row=6, end_row=8, prev_date="6.7-6.13")  # height 3
        # 源块 3 行, 4 列(A 日期, B SKU 常量, C 公式, D 每周手动填)
        grid = [
            [
                {"value": "6.7-6.13", "formula": None},
                {"value": "父ASIN", "formula": None},
                {"value": 0.5, "formula": "=E6/D6"},
                {"value": 123, "formula": None},
            ],
            [
                {"value": "", "formula": None},
                {"value": "sku1", "formula": None},
                {"value": 0.3, "formula": "=E7/D7"},
                {"value": 45, "formula": None},
            ],
            [
                {"value": "", "formula": None},
                {"value": "sku2", "formula": None},
                {"value": 0.2, "formula": "=E8/D8"},
                {"value": 67, "formula": None},
            ],
        ]
        plan = build_copy_plan(
            block,
            grid,
            new_date="6.14-6.20",
            date_col_index=0,
            clear_col_indexes={3},  # D 列每周手动填 -> 留空
        )
        self.assertEqual((plan.new_start_row, plan.new_end_row), (9, 11))
        self.assertEqual(plan.height, 3)

        # 日期列: 仅第一行写新日期, 其余空
        self.assertEqual(plan.rows[0][0].kind, "value")
        self.assertEqual(plan.rows[0][0].value, "6.14-6.20")
        self.assertEqual(plan.rows[1][0].kind, "blank")

        # B 列常量照抄
        self.assertEqual(plan.rows[1][1].kind, "value")
        self.assertEqual(plan.rows[1][1].value, "sku1")

        # C 列公式: 行号 +3 (块高)
        self.assertEqual(plan.rows[0][2].kind, "formula")
        self.assertEqual(plan.rows[0][2].formula, "=E9/D9")
        self.assertEqual(plan.rows[1][2].formula, "=E10/D10")
        self.assertEqual(plan.rows[2][2].formula, "=E11/D11")

        # D 列(clear)留空
        self.assertEqual(plan.rows[0][3].kind, "blank")
        self.assertEqual(plan.rows[2][3].kind, "blank")

    def test_formula_in_clear_col_is_preserved(self):
        # 父ASIN 汇总行在"销量"列是 SUM 公式, 即便该列被列入 clear_cols 也应保留
        block = Block(start_row=10, end_row=12, prev_date="6.7-6.13")  # height 3
        grid = [
            [  # 父ASIN 行: D 列是汇总公式
                {"value": "6.7-6.13", "formula": None},
                {"value": "父ASIN", "formula": None},
                {"value": 41, "formula": "=SUM(C11:C12)"},
            ],
            [  # SKU 行: C 列是手填数值
                {"value": "", "formula": None},
                {"value": "sku1", "formula": None},
                {"value": 20, "formula": None},
            ],
            [
                {"value": "", "formula": None},
                {"value": "sku2", "formula": None},
                {"value": 21, "formula": None},
            ],
        ]
        plan = build_copy_plan(
            block, grid, new_date="6.14-6.20",
            date_col_index=0, clear_col_indexes={2},  # C 列(销量)在 clear 里
        )
        # 父ASIN 行的 SUM 公式应保留并平移(+3): C11:C12 -> C14:C15
        self.assertEqual(plan.rows[0][2].kind, "formula")
        self.assertEqual(plan.rows[0][2].formula, "=SUM(C14:C15)")
        # SKU 行的手填数值应留空
        self.assertEqual(plan.rows[1][2].kind, "blank")
        self.assertEqual(plan.rows[2][2].kind, "blank")


if __name__ == "__main__":
    unittest.main()
