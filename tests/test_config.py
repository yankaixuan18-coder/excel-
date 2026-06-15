"""config 模块单元测试: book_id / sheet_id 链接归一化。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tdweekly.config import Target, clean_book_id, clean_sheet_id


class TestCleanIds(unittest.TestCase):
    def test_book_id_from_url(self):
        self.assertEqual(
            clean_book_id("https://docs.qq.com/sheet/DSkRYQXFzd3pEZ2Jy?tab=85npxo"),
            "DSkRYQXFzd3pEZ2Jy",
        )

    def test_book_id_plain(self):
        self.assertEqual(clean_book_id("DSkRYQXFzd3pEZ2Jy"), "DSkRYQXFzd3pEZ2Jy")

    def test_sheet_id_from_url(self):
        self.assertEqual(
            clean_sheet_id("https://docs.qq.com/sheet/DSkRYQXFzd3pEZ2Jy?tab=85npxo"),
            "85npxo",
        )

    def test_sheet_id_plain(self):
        self.assertEqual(clean_sheet_id("85npxo"), "85npxo")

    def test_target_post_init_normalizes(self):
        t = Target(
            name="x",
            book_id="https://docs.qq.com/sheet/DSkRYQXFzd3pEZ2Jy?tab=85npxo",
            sheet_id="https://docs.qq.com/sheet/DSkRYQXFzd3pEZ2Jy?tab=85npxo",
        )
        self.assertEqual(t.book_id, "DSkRYQXFzd3pEZ2Jy")
        self.assertEqual(t.sheet_id, "85npxo")


if __name__ == "__main__":
    unittest.main()
