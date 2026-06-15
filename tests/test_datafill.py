"""datafill 模块单元测试。"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tdweekly.config import Target
from tdweekly.datafill import build_row_fill, load_data_table, lookup, resolve_country

try:
    import openpyxl  # noqa: F401
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


def _t(**kw):
    base = dict(name="x", book_id="b", sheet_id="s")
    base.update(kw)
    return Target(**base)


class TestResolveCountry(unittest.TestCase):
    def test_explicit_country(self):
        self.assertEqual(resolve_country(_t(country="加拿大")), "加拿大")

    def test_country_code(self):
        self.assertEqual(resolve_country(_t(country_code="CA")), "加拿大")
        self.assertEqual(resolve_country(_t(country_code="de")), "德国")

    def test_name_prefix(self):
        self.assertEqual(resolve_country(_t(name="CA外卖包-王倩")), "加拿大")

    def test_default_us(self):
        self.assertEqual(resolve_country(_t(name="披萨包-王倩")), "美国")
        self.assertEqual(resolve_country(_t(name="外卖包 小链接")), "美国")


class TestBuildRowFill(unittest.TestCase):
    def test_match_by_asin(self):
        index = {
            ("B0AAA", "美国"): {"inventory": 10},
            ("B0BBB", "美国"): {"inventory": 20},
        }
        grid = [
            [{"value": ""}, {"value": "B0AAA"}],   # asin 在第 1 列
            [{"value": ""}, {"value": "B0BBB"}],
            [{"value": ""}, {"value": "B0ZZZ"}],   # 匹配不到
        ]
        out = build_row_fill(grid, asin_col_rel=1, index=index, country="美国")
        self.assertEqual(out[0]["inventory"], 10)
        self.assertEqual(out[1]["inventory"], 20)
        self.assertIsNone(out[2])

    def test_lookup_strips(self):
        index = {("B0AAA", "加拿大"): {"x": 1}}
        self.assertEqual(lookup(index, " B0AAA ", " 加拿大 ")["x"], 1)
        self.assertIsNone(lookup(index, "B0AAA", "美国"))


@unittest.skipUnless(HAS_OPENPYXL, "需要 openpyxl")
class TestLoadDataTable(unittest.TestCase):
    def test_load(self):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["asin_country", "inventory", "sales_volume"])
        ws.append(["B0AAA；加拿大", 295, 35])
        ws.append(["B0BBB；美国", 100, 7])
        ws.append([None, 0, 0])  # 空 key 跳过
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "data.xlsx")
            wb.save(p)
            idx = load_data_table(p)
        self.assertEqual(idx[("B0AAA", "加拿大")]["inventory"], 295)
        self.assertEqual(idx[("B0BBB", "美国")]["sales_volume"], 7)
        self.assertEqual(len(idx), 2)


if __name__ == "__main__":
    unittest.main()
