"""腾讯文档开放平台「在线表格」API 客户端。

本客户端封装两件事:
  1. 读取一段区域的单元格(值 + 公式)              -> get_grid()
  2. 批量更新(插入行 / 写单元格 / 合并单元格)      -> batch_update()

写入采用官方 batchUpdate 模型(与 Google Sheets 风格一致):
    POST {api_base}/sheetbook/v2/{bookID}:batchUpdate
    body = {"requests": [ {请求类型: {...}}, ... ]}
已知请求类型: insertDimension(插入行/列)、updateCells(写单元格)、
mergeCells(合并)、insertImages(插图) 等。

⚠️ 重要: 沙箱环境访问不到 docs.qq.com, 以下端点路径与字段名是依据公开资料
   与 Google Sheets 同构模型实现的, **请在首次使用前对照官方文档核对**:
     - 接入/鉴权: https://docs.qq.com/open/document/app/get_started.html
     - 在线表格 : https://docs.qq.com/open/document/app/openapi/v2/
     - 请求类型 : https://docs.qq.com/open/document/app/openapi/v2/sheet/requests/InsertImages.html
   若字段名有出入, 改动集中在本文件的 *_request() 与 _parse_grid() 即可。
   排查时可用  `python run.py raw-read`  打印原始返回 JSON。
"""

from __future__ import annotations

import json
from typing import Any

import requests

from .a1 import col_to_index
from .auth import Token
from .config import AppConfig, Target


def _check(resp: requests.Response) -> None:
    """统一处理鉴权类错误, 给出可读提示。"""
    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"鉴权失败(HTTP {resp.status_code})。access_token 可能已过期(有效期约30天)或权限不足。"
            f"请回开放平台「开发者信息」页重新复制 access_token 填到 config.toml。\n返回: {resp.text[:300]}"
        )
    resp.raise_for_status()


class TencentDocsClient:
    def __init__(self, cfg: AppConfig, token: Token):
        self.cfg = cfg
        self.token = token

    # ------------------------------------------------------------------ #
    # 公共
    # ------------------------------------------------------------------ #
    def _headers(self) -> dict[str, str]:
        # 官方要求的鉴权三元组 + JSON
        return {
            "Access-Token": self.token.access_token,
            "Client-Id": self.cfg.client_id,
            "Open-Id": self.token.open_id,
            "Content-Type": "application/json",
        }

    def _book_url(self, book_id: str, suffix: str = "") -> str:
        return f"{self.cfg.api_base}/sheetbook/v2/{book_id}{suffix}"

    # ------------------------------------------------------------------ #
    # 读取
    # ------------------------------------------------------------------ #
    def _read_url(self, book_id: str, sheet_id: str, a1_range: str) -> str:
        return self.cfg.read_url_template.format(
            base=self.cfg.api_base, book=book_id, sheet=sheet_id, range=a1_range
        )

    def get_grid_raw(self, book_id: str, sheet_id: str, a1_range: str) -> dict:
        """读取一段区域, 返回原始 JSON(调试用)。

        a1_range 形如 'A1:B30000' 或 'A3:BZ8'。
        valueRenderOption=FORMULA 让返回里带上公式串(以便复制时平移行号)。
        读取地址用 cfg.read_url_template(可用 probe 命令实测确定)。
        """
        url = self._read_url(book_id, sheet_id, a1_range)
        params = {"valueRenderOption": "FORMULA"}
        r = requests.get(url, headers=self._headers(), params=params, timeout=60)
        _check(r)
        return r.json()

    def probe_read(self, book_id: str, sheet_id: str, a1_range: str = "A1:B3") -> list[dict]:
        """实测多种候选读取地址, 返回每个的状态, 用于确定正确端点。"""
        candidates = [
            "{base}/sheetbook/v2/{book}/sheets/{sheet}/values/{range}",
            "{base}/sheetbook/v2/{book}/values/{sheet}!{range}",
            "{base}/sheetbook/v2/{book}/values/{range}",
            "{base}/sheetbook/v2/{book}/sheets/{sheet}?range={range}",
            "{base}/sheetbook/v2/{book}/sheets/{sheet}/cells/{range}",
            "{base}/sheetbook/v2/{book}/sheets/{sheet}",
            "{base}/sheetbook/v2/{book}/sheets",
            "{base}/sheetbook/v2/{book}",
            "{base}/sheet/v2/{book}/sheets/{sheet}/values/{range}",
            "{base}/drive/v2/files/{book}",  # 文件元数据: 验证 token/book 是否有效
        ]
        results = []
        for tmpl in candidates:
            url = tmpl.format(base=self.cfg.api_base, book=book_id, sheet=sheet_id, range=a1_range)
            try:
                r = requests.get(url, headers=self._headers(), timeout=30)
                body = r.text[:600]
                results.append({"template": tmpl, "url": url, "status": r.status_code, "body": body})
            except Exception as e:  # pragma: no cover - 联网
                results.append({"template": tmpl, "url": url, "status": "ERR", "body": str(e)[:300]})
        return results

    def get_grid(self, book_id: str, sheet_id: str, a1_range: str) -> list[list[dict]]:
        """读取一段区域, 归一化成二维 [{'value':.., 'formula':..}]。"""
        return _parse_grid(self.get_grid_raw(book_id, sheet_id, a1_range))

    def get_column(self, book_id: str, sheet_id: str, col: str, max_rows: int) -> list[Any]:
        """读取单独一列的值(用于扫描日期列 / 标记列)。"""
        a1_range = f"{col}1:{col}{max_rows}"
        grid = self.get_grid(book_id, sheet_id, a1_range)
        return [row[0]["value"] if row else "" for row in grid]

    # ------------------------------------------------------------------ #
    # 写入(batchUpdate)
    # ------------------------------------------------------------------ #
    def batch_update(self, book_id: str, requests_list: list[dict]) -> dict:
        url = self._book_url(book_id, ":batchUpdate")
        body = {"requests": requests_list}
        r = requests.post(url, headers=self._headers(), data=json.dumps(body), timeout=60)
        _check(r)
        return r.json()

    # ---- 请求体构造器(对照官方文档核对字段名) ---- #
    @staticmethod
    def insert_rows_request(sheet_id: str, start_index_0: int, count: int) -> dict:
        """在 start_index_0(0 基)处插入 count 行, 继承上一行格式。"""
        return {
            "insertDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": start_index_0,
                    "endIndex": start_index_0 + count,
                },
                "inheritFromBefore": True,
            }
        }

    @staticmethod
    def update_cells_request(
        sheet_id: str, start_row_0: int, start_col_0: int, rows: list[list["OutCellLike"]]
    ) -> dict:
        """从 (start_row_0, start_col_0) 开始写入 rows。

        rows[r][c] 需有 .kind ∈ {formula, value, blank} 以及 .formula/.value。
        """
        api_rows = []
        for out_row in rows:
            values = []
            for cell in out_row:
                values.append(_cell_to_value(cell))
            api_rows.append({"values": values})
        return {
            "updateCells": {
                "rows": api_rows,
                # 写入哪些属性: 这里只写"用户输入的值/公式"
                "fields": "userEnteredValue",
                "start": {
                    "sheetId": sheet_id,
                    "rowIndex": start_row_0,
                    "columnIndex": start_col_0,
                },
            }
        }

    @staticmethod
    def merge_cells_request(
        sheet_id: str, start_row_0: int, end_row_0_excl: int, start_col_0: int, end_col_0_excl: int
    ) -> dict:
        """合并单元格(用于把新块的日期列竖向合并)。"""
        return {
            "mergeCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": start_row_0,
                    "endRowIndex": end_row_0_excl,
                    "startColumnIndex": start_col_0,
                    "endColumnIndex": end_col_0_excl,
                },
                "mergeType": "MERGE_ALL",
            }
        }


# --------------------------------------------------------------------------- #
# 值转换 / 解析
# --------------------------------------------------------------------------- #
class OutCellLike:  # 仅用于类型提示(实际传入的是 core.OutCell)
    kind: str
    formula: str | None
    value: Any


def _cell_to_value(cell: "OutCellLike") -> dict:
    """core.OutCell -> API 的 cell value 结构。"""
    if cell.kind == "blank":
        return {}  # 空对象 = 不写内容(配合 fields=userEnteredValue 即清空)
    if cell.kind == "formula":
        return {"userEnteredValue": {"formulaValue": cell.formula}}
    v = cell.value
    if isinstance(v, bool):
        return {"userEnteredValue": {"boolValue": v}}
    if isinstance(v, (int, float)):
        return {"userEnteredValue": {"numberValue": v}}
    return {"userEnteredValue": {"stringValue": str(v)}}


def _parse_grid(resp: dict) -> list[list[dict]]:
    """把读取返回归一化成 [[{'value':.., 'formula':..}, ..], ..]。

    腾讯文档返回结构可能与下面假设不同; 若解析为空请用 raw-read 查看真实结构,
    然后按真实字段名修改本函数(只需改这一处)。
    这里兼容两种常见形态:
      A) Google 风格: {'values': [[{'userEnteredValue': {...}, 'formattedValue': ...}, ..], ..]}
      B) 简单二维数组: {'data': {'values': [[v, ..], ..]}} 或 {'values': [[v,..],..]}
    """
    grid_rows = None
    # 形态 A / B 的 values 入口
    if isinstance(resp.get("values"), list):
        grid_rows = resp["values"]
    elif isinstance(resp.get("data"), dict) and isinstance(resp["data"].get("values"), list):
        grid_rows = resp["data"]["values"]
    elif isinstance(resp.get("data"), dict) and isinstance(resp["data"].get("rows"), list):
        grid_rows = [r.get("values", r) for r in resp["data"]["rows"]]

    if grid_rows is None:
        raise ValueError(
            "无法解析读取返回的表格结构。请运行 `python run.py raw-read` 查看真实 JSON, "
            "再按真实字段名修改 client._parse_grid()。"
        )

    out: list[list[dict]] = []
    for row in grid_rows:
        out_row = []
        for cell in row:
            out_row.append(_normalize_cell(cell))
        out.append(out_row)
    return out


def _normalize_cell(cell: Any) -> dict:
    """把单个单元格(可能是富对象, 也可能是裸值)统一成 {'value':.., 'formula':..}。"""
    if cell is None:
        return {"value": "", "formula": None}
    if isinstance(cell, (str, int, float, bool)):
        s = cell
        formula = s if isinstance(s, str) and s.startswith("=") else None
        return {"value": "" if formula else s, "formula": formula}
    if isinstance(cell, dict):
        # 富对象: 取公式与显示值
        uev = cell.get("userEnteredValue") or {}
        formula = uev.get("formulaValue")
        if formula is None:
            # 有些返回直接把公式放在 formula / f 字段
            formula = cell.get("formula") or cell.get("f")
        value = (
            cell.get("formattedValue")
            or cell.get("value")
            or cell.get("v")
            or uev.get("stringValue")
            or uev.get("numberValue")
            or ""
        )
        if formula and not str(formula).startswith("="):
            formula = "=" + str(formula)
        return {"value": "" if formula else value, "formula": formula}
    return {"value": str(cell), "formula": None}
