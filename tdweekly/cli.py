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

from . import core
from .auth import authorize, get_valid_token
from .client import TencentDocsClient
from .config import AppConfig, Target, load_config


def _client(cfg: AppConfig) -> TencentDocsClient:
    return TencentDocsClient(cfg, get_valid_token(cfg))


def _detect_block_and_date(client: TencentDocsClient, t: Target):
    """读取列 -> 识别上一周块 -> 推算新日期。返回 (block, new_date)。"""
    date_col = client.get_column(t.book_id, t.sheet_id, t.date_col, t.max_scan_rows)
    marker_col = client.get_column(t.book_id, t.sheet_id, t.marker_col, t.max_scan_rows)
    block = core.find_last_block(date_col, marker_col)
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
    t = cfg.target(args.target)
    client = _client(cfg)
    block, new_date = _detect_block_and_date(client, t)

    # 读取源块整宽内容(值 + 公式)
    src_range = f"{t.first_col}{block.start_row}:{t.last_col}{block.end_row}"
    source_grid = client.get_grid(t.book_id, t.sheet_id, src_range)

    plan = core.build_copy_plan(
        block,
        source_grid,
        new_date=new_date,
        date_col_index=t.date_col_idx_rel,
        clear_col_indexes=t.clear_col_idxs_rel,
    )

    # 组装 batchUpdate 请求
    insert_at_0 = block.end_row          # 1基末行之后 = 0基索引 = block.end_row
    start_row_0 = block.end_row          # 新块第一行(0基) = 旧末行(1基) 对应 0 基同值
    start_col_0 = t.first_col_idx_abs
    reqs = [
        TencentDocsClient.insert_rows_request(t.sheet_id, insert_at_0, plan.height),
        TencentDocsClient.update_cells_request(t.sheet_id, start_row_0, start_col_0, plan.rows),
    ]
    # 日期列竖向合并(若块高 > 1)
    if plan.height > 1:
        dcol0 = t.date_col_idx_abs
        reqs.append(
            TencentDocsClient.merge_cells_request(
                t.sheet_id, start_row_0, start_row_0 + plan.height, dcol0, dcol0 + 1
            )
        )

    _print_plan(t, plan)

    if not args.apply:
        print("\n=== DRY-RUN(未写入) ===")
        print("将发送的 batchUpdate 请求预览(节选):")
        print(json.dumps(_preview(reqs), ensure_ascii=False, indent=2)[:4000])
        print("\n确认无误后加 --apply 真正写入: python run.py run --apply"
              + (f" --target {args.target}" if args.target else ""))
        return 0

    resp = client.batch_update(t.book_id, reqs)
    print("\n=== 已写入 ===")
    print(json.dumps(resp, ensure_ascii=False)[:1000])
    return 0


def cmd_raw_read(cfg: AppConfig, args) -> int:
    t = cfg.target(args.target)
    client = _client(cfg)
    rng = args.range or f"{t.first_col}1:{t.last_col}5"
    raw = client.get_grid_raw(t.book_id, t.sheet_id, rng)
    print(json.dumps(raw, ensure_ascii=False, indent=2)[:8000])
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

    pp = sub.add_parser("run", help="复制上一周块 + 填日期(默认 dry-run)")
    pp.add_argument("--target", help="子表名(默认第一个)")
    pp.add_argument("--apply", action="store_true", help="真正写入(不加则仅预览)")

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
        "raw-read": cmd_raw_read,
    }
    try:
        return handlers[args.cmd](cfg, args)
    except Exception as e:
        print("错误:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
