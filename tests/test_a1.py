"""a1 模块单元测试 (标准库 unittest, 无需 pytest)。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tdweekly.a1 import col_to_index, index_to_col, shift_formula_rows


class TestColumnConversion(unittest.TestCase):
    def test_round_trip(self):
        for col in ["A", "B", "Z", "AA", "AB", "AZ", "BA", "AL", "BZ"]:
            self.assertEqual(index_to_col(col_to_index(col)), col)

    def test_known_values(self):
        self.assertEqual(col_to_index("A"), 0)
        self.assertEqual(col_to_index("Z"), 25)
        self.assertEqual(col_to_index("AA"), 26)
        self.assertEqual(index_to_col(0), "A")
        self.assertEqual(index_to_col(26), "AA")


class TestShiftFormula(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(shift_formula_rows("=J5/G5", 7), "=J12/G12")

    def test_absolute_row_unchanged(self):
        self.assertEqual(shift_formula_rows("=A$1*B2", 7), "=A$1*B9")

    def test_absolute_col_relative_row_shifts(self):
        self.assertEqual(shift_formula_rows("=$A5", 3), "=$A8")

    def test_fully_absolute_unchanged(self):
        self.assertEqual(shift_formula_rows("=$A$5", 3), "=$A$5")

    def test_string_literal_not_touched(self):
        self.assertEqual(shift_formula_rows('=IF(A2="A2",0,A2)', 3), '=IF(A5="A2",0,A5)')

    def test_function_name_not_touched(self):
        # LOG10( 是函数, 不能被当成单元格引用 LOG10
        self.assertEqual(shift_formula_rows("=LOG10(A2)", 5), "=LOG10(A7)")

    def test_range_reference(self):
        self.assertEqual(shift_formula_rows("=SUM(A2:A5)", 10), "=SUM(A12:A15)")

    def test_sheet_qualified_reference(self):
        self.assertEqual(shift_formula_rows("=Sheet1!B3+C3", 4), "=Sheet1!B7+C7")

    def test_zero_delta_noop(self):
        self.assertEqual(shift_formula_rows("=J5/G5", 0), "=J5/G5")

    def test_div_formula_like_sheet(self):
        # 类似利润表里的转化率: 订单/点击
        self.assertEqual(shift_formula_rows("=IFERROR(H5/G5,0)", 6), "=IFERROR(H11/G11,0)")


if __name__ == "__main__":
    unittest.main()
