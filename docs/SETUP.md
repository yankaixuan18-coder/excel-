# 配置步骤（从零开始）

整个配置只需做一次。之后每周就是一条命令的事。

## 1. 注册腾讯文档开放平台开发者并创建应用

1. 打开开放平台：<https://docs.qq.com/open/>（"开放平台/开发者"入口）。
2. 用你的账号登录，按提示**注册成为开发者**（可能需要资质审核，个人开发者按页面引导走）。
3. 创建一个**应用**，拿到：
   - **Client ID（client_id）**
   - **Client Secret（client_secret）**
4. 在应用设置里配置**回调地址（redirect_uri）**，填：
   ```
   http://localhost:8888/callback
   ```
   必须和 `config.toml` 里的 `redirect_uri` 完全一致。
5. 给应用勾选所需**权限/scope**（至少要有读写在线表格的权限，例如 `doc`）。

> 官方接入教程：<https://docs.qq.com/open/document/app/get_started.html>
> 授权说明：<https://docs.qq.com/open/document/app/oauth2/>

## 2. 找到「文档ID」与「子表ID」

- **文档ID（book_id）**：打开你的周利润表，看浏览器地址栏：
  ```
  https://docs.qq.com/sheet/XXXXXXXXXXXX   ← XXXX... 就是 book_id
  ```
- **子表ID（sheet_id）**：一个文档里有多个标签页（伍纺源/昕亦/光伊/春知处…），每个是一个子表。
  获取方式二选一：
  - 切到该标签页时，地址栏可能带 `tab=` 或 `sheet=` 参数，那就是 sheet_id；
  - 或先填好 book_id 后运行：
    ```
    python run.py raw-read --target 光伊 --range A1:A1
    ```
    （若你还不知道 sheet_id，可先随便填，按官方"获取子表列表"接口或返回报错信息确认正确的 sheet_id。）

## 3. 填写 config.toml

```bash
cp config.example.toml config.toml
```

逐项填写（含密钥，已被 `.gitignore` 忽略，不会提交）。重点：

| 字段 | 含义 | 怎么填 |
|------|------|--------|
| `client_id` / `client_secret` | 应用凭据 | 第 1 步拿到 |
| `book_id` / `sheet_id` | 文档/子表 | 第 2 步拿到 |
| `date_col` | 日期列 | 一般 `A` |
| `marker_col` | 判定块末行的列 | 一般 `B`（SKU 列，块内每行都有值） |
| `last_col` | 最右数据列 | 覆盖到你最右边那列（如 `AL`） |
| `clear_cols` | 每周手动填、新块留空的列 | 见下 |
| `year` | 日期年份 | 如 `2025` |

### 关于 `clear_cols`（很重要）

你每周新建的那一块，截图里**原始数据列是空的、计算列显示 #DIV/0!**——说明你现在是"复制公式与商品信息，但不抄上一周的实际数字"。

所以请把**每周手动录入的实际数据列**列进 `clear_cols`（这些列新块留空）：
例如 可售天数/库存/销量/订单/销售额/评论数/点击/花费 等。

> **安全机制**：公式单元格**永远会被保留并平移**（例如父ASIN 汇总行那种 `=SUM(...)`），
> 即使它所在的列被你写进了 `clear_cols`。也就是说 `clear_cols` 只会清掉"手填的数值"，
> 多写几列也不会误伤公式（像 CPC/ROAS/转化率 这些公式列写进去也无害）。

- 想"**整块原样复制（连上周数字一起）**"？把 `clear_cols = []`。
- 不确定填哪些列？先 `clear_cols = []` 跑 dry-run，看预览里哪些列被当成常量照抄了（公式列会显示成公式），再把"实际数据列"挑进来。

## 4. 授权 + 试跑

```bash
python run.py auth                       # 浏览器登录并同意
python run.py read --target 光伊         # 看识别到的块/新日期对不对
python run.py run  --target 光伊         # dry-run 预览写入内容
python run.py run  --target 光伊 --apply # 确认后真正写入
```

建议第一次 `--apply` 先在一个**复制出来的副本文档**上测试，确认效果符合预期，再用到正式表。
