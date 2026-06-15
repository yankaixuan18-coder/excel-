"""读取 config.toml (Python 3.11+ 自带 tomllib, 无需第三方库)。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .a1 import col_to_index


@dataclass
class Target:
    """一个要处理的子表(文档里的一个 sheet 标签页)。"""

    name: str
    book_id: str          # 文档(整个文件)的 ID, 取自分享链接
    sheet_id: str         # 子表(标签页)的 ID
    date_col: str = "A"   # 日期所在列
    marker_col: str = "B" # 定位"父ASIN"行与块末行的列(通常是 SKU 列)
    parent_text: str = "父ASIN"  # 块首标记文字(出现在 marker_col)
    first_col: str = "A"  # 读取/写入的起始列
    last_col: str = "BZ"  # 读取/写入的结束列(覆盖你所有数据列即可)
    clear_cols: list[str] = field(default_factory=list)  # 每周手动填、新块留空的列
    year: int | None = None     # 日期所在年份(默认取当前年)
    step_days: int = 7          # 每块间隔天数(周报 = 7)
    max_scan_rows: int = 30000  # 扫描列时的最大行数

    # ---- 派生的 0 基索引 ----
    @property
    def date_col_idx_abs(self) -> int:
        return col_to_index(self.date_col)

    @property
    def first_col_idx_abs(self) -> int:
        return col_to_index(self.first_col)

    @property
    def date_col_idx_rel(self) -> int:
        """日期列相对 first_col 的下标。"""
        return self.date_col_idx_abs - self.first_col_idx_abs

    @property
    def clear_col_idxs_rel(self) -> set[int]:
        return {col_to_index(c) - self.first_col_idx_abs for c in self.clear_cols}


@dataclass
class AppConfig:
    client_id: str
    # —— 方式一(推荐, 最简单): 直接从开放平台「开发者信息」页复制 ——
    access_token: str = ""   # 有效期约 30 天, 过期回那个页面重新复制
    open_id: str = ""
    # —— 方式二(可选): 走 OAuth 授权码流程时才需要 ——
    client_secret: str = ""
    redirect_uri: str = "http://localhost:8888/callback"
    scope: str = "all"
    # 各端点 base(若官方改版可在此集中调整, 详见 docs/API_NOTES.md)
    oauth_authorize_url: str = "https://docs.qq.com/oauth/v2/authorize"
    oauth_token_url: str = "https://docs.qq.com/oauth/v2/token"
    oauth_userinfo_url: str = "https://docs.qq.com/oauth/v2/userinfo"
    api_base: str = "https://docs.qq.com/openapi"
    token_cache: str = ".td_token.json"
    targets: list[Target] = field(default_factory=list)

    def target(self, name: str | None) -> Target:
        if not self.targets:
            raise ValueError("config.toml 里没有配置任何 [[targets]]。")
        if name is None:
            return self.targets[0]
        for t in self.targets:
            if t.name == name:
                return t
        raise ValueError(f"找不到名为 {name!r} 的 target。可选: {[t.name for t in self.targets]}")


def load_config(path: str | Path = "config.toml") -> AppConfig:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"找不到配置文件 {p}。请先复制 config.example.toml 为 config.toml 并填写。"
        )
    with p.open("rb") as f:
        raw = tomllib.load(f)

    app = raw.get("app", {})
    targets = [Target(**t) for t in raw.get("targets", [])]
    return AppConfig(
        client_id=app["client_id"],
        access_token=app.get("access_token", ""),
        open_id=app.get("open_id", ""),
        client_secret=app.get("client_secret", ""),
        redirect_uri=app.get("redirect_uri", "http://localhost:8888/callback"),
        scope=app.get("scope", "all"),
        oauth_authorize_url=app.get("oauth_authorize_url", "https://docs.qq.com/oauth/v2/authorize"),
        oauth_token_url=app.get("oauth_token_url", "https://docs.qq.com/oauth/v2/token"),
        oauth_userinfo_url=app.get("oauth_userinfo_url", "https://docs.qq.com/oauth/v2/userinfo"),
        api_base=app.get("api_base", "https://docs.qq.com/openapi"),
        token_cache=app.get("token_cache", ".td_token.json"),
        targets=targets,
    )
