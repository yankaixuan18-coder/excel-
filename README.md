# 腾讯文档「周利润表」每周自动复制行 + 填日期

每周点一下命令，自动把**上一周那一整块行**复制到下方，并填好**新一周的日期区间**（如 `6.14-6.20` → `6.21-6.27`）。专为你那套结构设计：每周一个块 = 1 行父ASIN + 若干 SKU 行，A 列是合并的日期。

> 为什么是命令行工具而不是"文档里加个按钮"？
> 腾讯文档的在线表格本身**没有宏/脚本**，且表格是 canvas 渲染、无法靠网页脚本改单元格。
> 能稳定做到精确"复制整块行 + 填日期"的，只有**官方开放平台 API**。本工具就是它的封装。

---

## 它做了什么

1. 读取目标子表的日期列、SKU 列，**自动识别最底部（最近一周）的块**及其行范围。
2. 根据上一周日期 **+7 天**算出新一周的日期区间（支持跨月、跨年）。
3. 在该块下方**插入等高的空行**。
4. 把上一周的内容写进新行：
   - **公式**：行号自动下移（`=H5/G5` → `=H11/G11`，复刻手动复制粘贴的效果）；
   - **常量**（SKU/ASIN 等文字）：原样照抄；
   - **每周手动填的实际数据列**（销量/订单/花费…）：留空，等你填；
   - **日期列**：新块首行写新日期，并竖向合并。
5. 默认 **dry-run 只预览**，确认后加 `--apply` 才真正写入。

---

## 快速开始

```bash
# 0) 装依赖(只有 requests; Python 需 3.11+)
pip install -r requirements.txt

# 1) 一次性配置: 在腾讯文档开放平台建应用、拿 client_id/secret、找文档ID/子表ID
#    详细图文步骤见 docs/SETUP.md
cp config.example.toml config.toml
#    用编辑器填好 config.toml

# 2) 一次性授权(浏览器登录腾讯文档并同意)
python run.py auth

# 3) 先只读预览, 确认识别到的"上一周块"和"新日期"对不对
python run.py read --target 光伊

# 4) 预览这次会怎么写(仍然不写入)
python run.py run --target 光伊

# 5) 确认无误, 真正写入
python run.py run --target 光伊 --apply
```

之后每周你只需要重复第 5 步（一条命令）。多个店铺就配多个 `[[targets]]`，分别 `--target`。

---

## 目录结构

```
run.py                 顶层入口
config.example.toml    配置模板(复制成 config.toml 填写)
requirements.txt
tdweekly/
  a1.py        A1 表示法 + 公式相对行号平移   ← 已单测
  core.py      日期推算 + 块识别 + 复制方案     ← 已单测
  config.py    读取 config.toml
  auth.py      OAuth2.0 鉴权 + token 缓存
  client.py    腾讯文档 API 客户端(读/批量更新)
  cli.py       命令行(auth/read/run/raw-read)
tests/         纯逻辑单元测试(unittest, 无需联网)
docs/
  SETUP.md       从零开始的配置步骤
  API_NOTES.md   接口细节与"需对照官方文档核对"的点
```

跑测试：

```bash
python -m unittest discover -s tests -v
```

---

## ⚠️ 必读：关于接口的诚实说明

- **纯逻辑部分**（公式行号平移、日期推算、块识别、复制方案）已用单元测试在本地验证通过。
- **联网部分**（鉴权 URL、读取/写入的字段名）是依据腾讯文档开放平台公开资料 + 与 Google Sheets 同构的模型实现的。开发环境无法访问 `docs.qq.com`，**未能对真实接口做联调**。
- 因此**首次使用请按 `docs/API_NOTES.md` 对照官方文档核对**端点与字段名；若有出入，改动集中在 `tdweekly/client.py`（`*_request()` 与 `_parse_grid()`）和 `config.toml` 里的 URL，一处即可。
- 排查读取返回结构用：`python run.py raw-read --range A1:B5`。
- 任何写入前先看 dry-run 预览；第一次 `--apply` 建议先在一个**副本文档**上试。

官方文档入口：<https://docs.qq.com/open/document/app/>
