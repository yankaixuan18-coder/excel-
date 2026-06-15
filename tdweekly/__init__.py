"""tdweekly —— 腾讯文档「周利润表」每周自动复制行 + 填日期 工具。

模块划分:
- a1.py     : A1 表示法工具 + 公式相对行号平移(纯逻辑, 可离线单测)
- core.py   : 日期区间推算 + 上一周块识别 + 复制方案生成(纯逻辑, 可离线单测)
- config.py : 读取 config.toml
- auth.py   : 腾讯文档开放平台 OAuth2.0 鉴权 + token 缓存
- client.py : 腾讯文档开放平台 API 客户端(读取 / 批量更新)
- cli.py    : 命令行入口(auth / read / run)
"""

__version__ = "0.1.0"
