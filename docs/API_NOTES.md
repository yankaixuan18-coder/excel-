# 接口细节 & 需对照官方文档核对的点

本工具的纯逻辑（公式平移 / 日期推算 / 块识别）已在本地单元测试验证。
联网部分（鉴权与读写接口）依据腾讯文档开放平台公开资料 + 与 Google Sheets
同构的模型实现；开发环境无法访问 `docs.qq.com`，**未对真实接口联调**。
首次使用请按本文逐项核对。所有可调项都集中在少数几处。

## 官方文档入口

- 开放平台总览：<https://docs.qq.com/open/document/app/>
- 接入/鉴权教程：<https://docs.qq.com/open/document/app/get_started.html>
- OAuth2.0：<https://docs.qq.com/open/document/app/oauth2/>
- 在线表格 v2：<https://docs.qq.com/open/document/app/openapi/v2/>
- 请求类型示例（批量插图）：<https://docs.qq.com/open/document/app/openapi/v2/sheet/requests/InsertImages.html>

## 1. 鉴权（`tdweekly/auth.py` + `config.toml`）

- 授权 URL：`https://docs.qq.com/oauth/v2/authorize`
- 取/刷新 token：`POST https://docs.qq.com/oauth/v2/token`
  - `grant_type=authorization_code`（首次）/ `grant_type=refresh_token`（刷新）
- 用户信息（取 open_id）：`https://docs.qq.com/oauth/v2/userinfo`
- **需核对**：
  - 版本是 `oauth/v2` 还是 `oauth/v1`（资料里两者都出现过）。如不同，改 `config.toml` 里的 `oauth_*_url`。
  - `scope` 的合法取值（示例用 `all`，也可能是 `doc` 等逗号分隔）。
  - token 响应里字段名（`access_token`/`expires_in`/`refresh_token`，以及 open_id 是放在 token 响应还是要单独调 userinfo）。

## 2. API 请求头（`client._headers()`）

资料显示需携带三元组：`Access-Token`、`Client-Id`、`Open-Id`。
**需核对**头部的确切拼写（连字符 vs 下划线，大小写）。

## 3. 读取表格（`client.get_grid_raw` / `_parse_grid`）

当前实现：
```
GET {api_base}/sheetbook/v2/{book_id}/sheets/{sheet_id}/values/{A1范围}?valueRenderOption=FORMULA
```
- **需核对**：
  - 读取端点的真实路径与参数（范围是放路径还是 query；要公式时的参数名是不是 `valueRenderOption=FORMULA`）。
  - 返回 JSON 结构 → 决定 `_parse_grid()` / `_normalize_cell()` 怎么取"值"和"公式"。
- **排查办法**：`python run.py raw-read --range A1:B5`，把真实结构打印出来，再按字段名改 `_parse_grid`（只改这一处）。

## 4. 写入（`client.batch_update` + 三个 `*_request`）

当前实现（仿 Google Sheets 的 batchUpdate 模型）：
```
POST {api_base}/sheetbook/v2/{book_id}:batchUpdate
body = {"requests": [ {...}, ... ]}
```
请求类型与字段（**需核对**确切命名）：

- **插入行** `insertDimension`
  ```json
  {"insertDimension": {"range": {"sheetId": "...", "dimension": "ROWS",
     "startIndex": <0基>, "endIndex": <0基, 不含>}, "inheritFromBefore": true}}
  ```
- **写单元格** `updateCells`
  ```json
  {"updateCells": {"start": {"sheetId":"...","rowIndex":<0基>,"columnIndex":<0基>},
     "fields": "userEnteredValue",
     "rows": [{"values": [{"userEnteredValue": {"formulaValue": "=H11/G11"}}, ...]}, ...]}}
  ```
  - 值的子字段：公式 `formulaValue`、数字 `numberValue`、文本 `stringValue`、布尔 `boolValue`。
  - 空单元格用 `{}`（配合 `fields=userEnteredValue` 表示清空）。
- **合并日期列** `mergeCells`
  ```json
  {"mergeCells": {"range": {"sheetId":"...","startRowIndex":..,"endRowIndex":..,
     "startColumnIndex":..,"endColumnIndex":..}, "mergeType": "MERGE_ALL"}}
  ```

**索引基准需核对**：本工具内部按"0 基、end 不含"处理（Google 风格）。
若腾讯用 1 基或闭区间，请相应调整 `cli.cmd_run` 里的 `insert_at_0/start_row_0` 与 `client` 的请求构造。

## 5. 行号 / 插入位置的换算（已在 `cli.cmd_run` 内）

- `block.end_row` 是上一周块最后一行（**1 基**）。
- 在它下面插入 = 0 基 `startIndex = block.end_row`（因为 1 基第 N+1 行 = 0 基索引 N）。
- 新块写入起点 0 基 `rowIndex = block.end_row`。
- 若实际接口是 1 基，请整体 +/- 1 并重测 dry-run。

## 修改清单（出问题时只动这几处）

| 现象 | 改哪里 |
|------|--------|
| 鉴权失败 / URL 版本不同 | `config.toml` 的 `oauth_*_url`、`auth.py` |
| 请求头被拒 | `client._headers()` |
| 读不到数据 / 解析为空 | `client._parse_grid` + `_normalize_cell`（先 `raw-read`） |
| 写入端点/字段不符 | `client.*_request()` |
| 行号差 1 / 区间含不含端点 | `cli.cmd_run` 的索引换算 |
