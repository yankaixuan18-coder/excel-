"""命令行入口。

  python run.py auth                      # 一次性授权(浏览器登录腾讯文档)
  python run.py read   [--target 名字]    # 只读: 打印识别到的上一周块 + 推算的新日期(不写入)
  python run.py run    [--target 名字]    # 复制上一周块到下方 + 填新日期; 默认 dry-run(只预览)
  python run.py run    --apply            # 真正写入腾讯文档
  python run.py raw-read [--range A1:B5]  # 调试: 打印读取接口的原始 JSON
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys

from . import core, datafill
from .auth import authorize, get_valid_token
from .client import TencentDocsClient
from .config import AppConfig, Target, load_config


def _client(cfg: AppConfig) -> TencentDocsClient:
    return TencentDocsClient(cfg, get_valid_token(cfg))


def _detect_block_and_date(client: TencentDocsClient, t: Target):
    """读取列 -> 识别上一周块 -> 推算新日期。返回 (block, new_date)。"""
    date_col = client.get_column(t.book_id, t.sheet_id, t.date_col, t.max_scan_rows)
    marker_col = client.get_column(t.book_id, t.sheet_id, t.marker_col, t.max_scan_rows)
    block = core.find_last_block(marker_col, date_col, t.parent_text)
    year = t.year or datetime.date.today().year
    new_date, _, _ = core.next_range(block.prev_date, year, t.step_days)
    return block, new_date


def cmd_auth(cfg: AppConfig, args) -> int:
    if cfg.access_token and cfg.open_id:
        print("已在 config.toml 配置 access_token + open_id, 无需授权, 可直接运行 read / run。")
        return 0
    authorize(cfg)
    return 0


def cmd_read(cfg: AppConfig, args) -> int:
    t = cfg.target(args.target)
    client = _client(cfg)
    block, new_date = _detect_block_and_date(client, t)
    print(f"[{t.name}] 上一周块: 第 {block.start_row}-{block.end_row} 行 "
          f"(共 {block.height} 行), 日期 = {block.prev_date}")
    print(f"[{t.name}] 将新增:   第 {block.end_row + 1}-{block.end_row + block.height} 行, "
          f"新日期 = {new_date}")
    return 0


def cmd_run(cfg: AppConfig, args) -> int:
    client = _client(cfg)
    # 数据表(配置了才加载, 用于自动填数)
    try:
        index = datafill.maybe_load(cfg)
    except Exception as e:
        print("[数据] 加载数据表失败:", e, file=sys.stderr)
        return 1
    if index is not None:
        print(f"[数据] 已加载数据表 {cfg.data_table}: {len(index)} 条记录")

    targets = cfg.targets if args.all else [cfg.target(args.target)]
    rc = 0
    for t in targets:
        try:
            _run_one(cfg, client, t, index, args.apply)
        except Exception as e:
            print(f"[{t.name}] 出错: {e}", file=sys.stderr)
            rc = 1
    return rc


def _run_one(cfg: AppConfig, client: TencentDocsClient, t: Target, index, apply: bool) -> None:
    block, new_date = _detect_block_and_date(client, t)

    # 读取源块整宽内容(值 + 公式)
    src_range = f"{t.first_col}{block.start_row}:{t.last_col}{block.end_row}"
    source_grid = client.get_grid(t.book_id, t.sheet_id, src_range)

    # 按 ASIN + 站点 匹配数据
    row_fill = None
    fill_map_idx = None
    if index is not None:
        country = datafill.resolve_country(t)
        row_fill = datafill.build_row_fill(source_grid, t.asin_col_idx_rel, index, country)
        fill_map_idx = t.fill_map_idx_rel(cfg.default_fill_map)
        n = sum(1 for x in row_fill if x)
        print(f"[{t.name}] 站点={country}, 匹配到数据的行: {n}/{len(row_fill)}")

    plan = core.build_copy_plan(
        block,
        source_grid,
        new_date=new_date,
        date_col_index=t.date_col_idx_rel,
        clear_col_indexes=t.clear_col_idxs_rel,
        clear_from_index=t.clear_from_idx_rel,
        fill_map_idx=fill_map_idx,
        row_fill=row_fill,
    )

    insert_at_0 = block.end_row          # 1基末行之后 = 0基索引 = block.end_row
    start_row_0 = block.end_row
    start_col_0 = t.first_col_idx_abs
    reqs = [
        TencentDocsClient.insert_rows_request(t.sheet_id, insert_at_0, plan.height),
        TencentDocsClient.update_cells_request(t.sheet_id, start_row_0, start_col_0, plan.rows),
    ]
    merge_start_0 = start_row_0 + plan.date_row_offset
    merge_end_0_excl = start_row_0 + plan.height
    if merge_end_0_excl - merge_start_0 > 1:
        dcol0 = t.date_col_idx_abs
        reqs.append(
            TencentDocsClient.merge_cells_request(
                t.sheet_id, merge_start_0, merge_end_0_excl, dcol0, dcol0 + 1
            )
        )

    _print_plan(t, plan)
    if not apply:
        print(f"[{t.name}] === DRY-RUN(未写入) === 加 --apply 才真正写入")
        print(json.dumps(_preview(reqs), ensure_ascii=False, indent=2)[:3000])
        return

    resp = client.batch_update(t.book_id, reqs)
    print(f"[{t.name}] === 已写入 ===", json.dumps(resp, ensure_ascii=False)[:500])


def cmd_probe(cfg: AppConfig, args) -> int:
    """实测多种候选读取地址, 找出哪个能返回 200。"""
    t = cfg.target(args.target)
    client = _client(cfg)
    print(f"[{t.name}] 探测读取地址 book={t.book_id} sheet={t.sheet_id} ...\n")
    results = client.probe_read(t.book_id, t.sheet_id)
    ok = None
    for r in results:
        mark = "✅" if r["status"] == 200 else "  "
        print(f"{mark} [{r['status']}] {r['url']}")
        if r["status"] == 200 and ok is None:
            ok = r
    print()
    if ok:
        print("=== 第一个成功(200)的返回内容(节选), 请把这段发我 ===")
        print(ok["url"])
        print(ok["body"])
    else:
        print("没有候选返回 200。请把上面每行的状态码, 以及下面这条的返回体发我:")
        # 打印第一个非 200 的 body 以便诊断
        print(results[0]["body"])
    return 0


def cmd_raw_read(cfg: AppConfig, args) -> int:
    t = cfg.target(args.target)
    client = _client(cfg)
    rng = args.range or f"{t.first_col}1:{t.last_col}5"
    raw = client.get_grid_raw(t.book_id, t.sheet_id, rng)
    print(json.dumps(raw, ensure_ascii=False, indent=2)[:8000])
    return 0


def cmd_headers(cfg: AppConfig, args) -> int:
    """打印某一行的表头(列字母=表头名), 用来做 fill_map。"""
    from .a1 import index_to_col

    t = cfg.target(args.target)
    client = _client(cfg)
    row = args.row or 2
    rng = f"{t.first_col}{row}:{t.last_col}{row}"
    grid = client.get_grid(t.book_id, t.sheet_id, rng)
    cells = grid[0] if grid else []
    base = t.first_col_idx_abs
    items = []
    for i, c in enumerate(cells):
        v = c.get("value")
        if isinstance(v, str):
            v = v.strip()
        if v not in (None, ""):
            items.append(f"{index_to_col(base + i)}={v}")
    print(f"[{t.name}] 第 {row} 行表头({len(items)} 个非空):")
    for it in items:
        print("  " + it)
    return 0


def _print_plan(t: Target, plan: core.CopyPlan) -> None:
    print(f"[{t.name}] 复制源: 第 {plan.src_start_row}-{plan.src_end_row} 行 "
          f"({plan.prev_date})  ->  新块: 第 {plan.new_start_row}-{plan.new_end_row} 行 "
          f"({plan.new_date})")
    n_formula = sum(c.kind == "formula" for row in plan.rows for c in row)
    n_value = sum(c.kind == "value" for row in plan.rows for c in row)
    n_blank = sum(c.kind == "blank" for row in plan.rows for c in row)
    print(f"        单元格: 公式 {n_formula} 个, 常量 {n_value} 个, 留空 {n_blank} 个")


def _preview(reqs: list[dict]) -> list[dict]:
    """更可读的请求预览: updateCells 只展示前两行。"""
    out = []
    for r in reqs:
        if "updateCells" in r:
            uc = dict(r["updateCells"])
            rows = uc.get("rows", [])
            uc["rows"] = rows[:2] + ([{"...": f"共 {len(rows)} 行"}] if len(rows) > 2 else [])
            out.append({"updateCells": uc})
        else:
            out.append(r)
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tdweekly", description="腾讯文档周利润表: 每周复制行 + 填日期")
    p.add_argument("--config", default="config.toml", help="配置文件路径(默认 config.toml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth", help="一次性授权")

    pr = sub.add_parser("read", help="只读: 预览将要新增的行与日期")
    pr.add_argument("--target", help="子表名(默认第一个)")

    pp = sub.add_parser("run", help="复制上一周块 + 填日期 + 填数(默认 dry-run)")
    pp.add_argument("--target", help="子表名(默认第一个)")
    pp.add_argument("--all", action="store_true", help="处理 config 里所有 targets")
    pp.add_argument("--apply", action="store_true", help="真正写入(不加则仅预览)")

    ph = sub.add_parser("headers", help="打印表头(列字母=表头名), 用于生成 fill_map")
    ph.add_argument("--target", help="子表名(默认第一个)")
    ph.add_argument("--row", type=int, help="表头所在行(默认 2)")

    pb = sub.add_parser("probe", help="实测多种候选读取地址, 确定正确端点")
    pb.add_argument("--target", help="子表名(默认第一个)")

    rr = sub.add_parser("raw-read", help="调试: 打印读取接口原始 JSON")
    rr.add_argument("--target", help="子表名(默认第一个)")
    rr.add_argument("--range", help="读取范围, 如 A1:B5")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    handlers = {
        "auth": cmd_auth,
        "read": cmd_read,
        "run": cmd_run,
        "headers": cmd_headers,
        "probe": cmd_probe,
        "raw-read": cmd_raw_read,
    }
    try:
        return handlers[args.cmd](cfg, args)
    except Exception as e:
        print("错误:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
