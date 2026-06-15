"""core 模块单元测试 (标准库 unittest, 无需 pytest)。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

from tdweekly.core import (
    Block,
    build_copy_plan,
    find_last_block,
    format_range,
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

    def test_short_format_parse(self):
        # 李子向式简写: 6.7-13 = 6月7日到6月13日
        s, e = parse_range("6.7-13", 2026)
        self.assertEqual((s.month, s.day), (6, 7))
        self.assertEqual((e.month, e.day), (6, 13))

    def test_short_format_next_week_keeps_style(self):
        # 简写式应继续输出简写式
        self.assertEqual(next_range("6.7-13", 2026)[0], "6.14-20")
        self.assertEqual(next_range("6.14-20", 2026)[0], "6.21-27")

    def test_format_range_short(self):
        self.assertEqual(format_range(date(2026, 6, 7), date(2026, 6, 13), "short"), "6.7-13")

    def test_short_crossing_month_falls_back_to_full(self):
        # 起止跨月时, 简写式无法表达, 自动回退完整式
        self.assertEqual(format_range(date(2026, 6, 29), date(2026, 7, 2), "short"), "6.29-7.2")


class TestFindLastBlock(unittest.TestCase):
    def test_last_block_parent_anchored(self):
        # 光伊式: 父ASIN 行就是块首, 日期也在该行(offset 0); 两个块背靠背
        marker = ["BD_IFDB", "SKU", "父ASIN", "sku1", "sku2", "父ASIN", "sku1", "sku2"]
        date_col = ["父ASIN", "日期", "5.31-6.6", "", "", "6.7-6.13", "", ""]
        b = find_last_block(marker, date_col)
        self.assertEqual(b.start_row, 6)
        self.assertEqual(b.end_row, 8)
        self.assertEqual(b.height, 3)
        self.assertEqual(b.date_offset, 0)
        self.assertEqual(b.prev_date, "6.7-6.13")

    def test_lizixiang_layout_date_below_parent(self):
        # 李子向式: 行1黄标题"父ASIN", 行2表头, 行3蓝"父ASIN", 行4-6是SKU, 日期在行4
        marker = ["父ASIN", "SKU", "父ASIN", "蓝色", "橙色", "红色", ""]
        date_col = ["", "日期", "", "6.7-13", "", "", ""]
        b = find_last_block(marker, date_col)
        self.assertEqual(b.start_row, 3)      # 块从蓝"父ASIN"行开始
        self.assertEqual(b.end_row, 6)        # 到最后一个SKU
        self.assertEqual(b.height, 4)         # 父ASIN + 3 SKU
        self.assertEqual(b.date_offset, 1)    # 日期在父ASIN行的下一行
        self.assertEqual(b.prev_date, "6.7-13")

    def test_fallback_to_date_anchor_when_no_parent(self):
        # 没有"父ASIN"行时, 回退按日期定位
        marker = ["SKU", "sku1", "sku2", ""]
        date_col = ["日期", "6.7-6.13", "", ""]
        b = find_last_block(marker, date_col)
        self.assertEqual(b.start_row, 2)
        self.assertEqual(b.end_row, 3)

    def test_no_block_raises(self):
        with self.assertRaises(ValueError):
            find_last_block(["日期", "SKU"], ["x", "y"])


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

    def test_clear_from_col_and_fill(self):
        # 整行复制: BC(下标5)起清空; F(下标2)按数据填; 公式列保留
        block = Block(start_row=2, end_row=2, prev_date="6.7-13")  # 单行块
        grid = [[
            {"value": "6.7-13", "formula": None},  # 0 日期
            {"value": "sku", "formula": None},     # 1 常量
            {"value": 99, "formula": None},        # 2 库存(原值, 将被数据覆盖)
            {"value": 0.5, "formula": "=C2/B2"},   # 3 公式(应保留并平移)
            {"value": "老备注", "formula": None},   # 4 (<BC, 照抄)
            {"value": "比价方案旧", "formula": None},# 5 BC -> 清空
            {"value": "效果旧", "formula": None},    # 6 -> 清空
        ]]
        plan = build_copy_plan(
            block, grid, new_date="6.14-20", date_col_index=0,
            clear_col_indexes=set(), clear_from_index=5,
            fill_map_idx={2: "inventory"},
            row_fill=[{"inventory": 295}],
        )
        row = plan.rows[0]
        self.assertEqual(row[0].value, "6.14-20")        # 日期
        self.assertEqual(row[1].value, "sku")            # 常量照抄
        self.assertEqual(row[2].value, 295)              # 数据填充覆盖原值
        self.assertEqual(row[3].formula, "=C3/B3")       # 公式保留并平移
        self.assertEqual(row[4].value, "老备注")          # <BC 照抄
        self.assertEqual(row[5].kind, "blank")           # BC 清空
        self.assertEqual(row[6].kind, "blank")           # BC 之后清空

    def test_formula_not_overwritten_by_fill(self):
        # 即便某列在 fill_map, 若源是公式(如汇总行), 也保留公式不被数据覆盖
        block = Block(start_row=2, end_row=2, prev_date="6.7-13")
        grid = [[
            {"value": "6.7-13", "formula": None},
            {"value": 0, "formula": "=SUM(C3:C5)"},  # 1 汇总公式
        ]]
        plan = build_copy_plan(
            block, grid, new_date="6.14-20", date_col_index=0,
            clear_col_indexes=set(), fill_map_idx={1: "inventory"},
            row_fill=[{"inventory": 999}],
        )
        # 仍是公式(平移后), 而不是被数据值 999 覆盖
        self.assertEqual(plan.rows[0][1].kind, "formula")
        self.assertEqual(plan.rows[0][1].formula, "=SUM(C4:C6)")

    def test_date_offset_places_date_on_correct_row(self):
        # 李子向式: 块首是父ASIN行, 日期在第2行(offset 1)
        block = Block(start_row=3, end_row=6, prev_date="6.7-13", date_offset=1)  # height 4
        grid = [[{"value": "", "formula": None}] for _ in range(4)]
        grid[1][0] = {"value": "6.7-13", "formula": None}  # 源日期在 offset 1
        plan = build_copy_plan(
            block, grid, new_date="6.14-20", date_col_index=0, clear_col_indexes=set()
        )
        self.assertEqual(plan.date_row_offset, 1)
        self.assertEqual(plan.rows[0][0].kind, "blank")   # 父ASIN行的日期列留空
        self.assertEqual(plan.rows[1][0].kind, "value")   # 日期写在 offset 1
        self.assertEqual(plan.rows[1][0].value, "6.14-20")


if __name__ == "__main__":
    unittest.main()
