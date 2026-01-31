#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
state.db 导出和导入工具

用法:
    导出所有用户的基金列表:
        python state_manager.py export

    导出指定用户的基金列表:
        python state_manager.py export --user admin

    导入基金列表到指定用户 (替换现有列表):
        python state_manager.py import --user admin --codes 004703,000979,001234

    导入基金列表到指定用户 (追加到现有列表):
        python state_manager.py import --user admin --codes 004703,000979 --append

    从文件导入 (每行一个基金代码):
        python state_manager.py import --user admin --file codes.txt

    查看当前状态:
        python state_manager.py show
"""

import argparse
import os
import pickle
import sys
from typing import Dict, List


DEFAULT_STATE_DB = "data/state.db"


def load_state(state_db: str) -> dict:
    """加载state.db"""
    if not os.path.exists(state_db):
        print(f"错误: 文件 {state_db} 不存在")
        sys.exit(1)

    with open(state_db, "rb") as f:
        state = pickle.load(f)
    return state


def save_state(state_db: str, state: dict):
    """保存state.db"""
    # 创建目录（如果不存在）
    os.makedirs(os.path.dirname(state_db) or ".", exist_ok=True)

    with open(state_db, "wb") as f:
        pickle.dump(state, f)
    print(f"已保存到 {state_db}")


def show_state(args):
    """显示当前状态"""
    state = load_state(args.db)

    favour: Dict[str, List[str]] = state.get("favour", {})
    share = state.get("share", {})

    print("=" * 50)
    print("用户关注列表:")
    print("=" * 50)

    for user, codes in favour.items():
        print(f"\n用户: {user}")
        print(f"  关注数量: {len(codes)}")
        if codes:
            print(f"  基金代码: {', '.join(codes)}")

    print("\n" + "=" * 50)
    print(f"分享链接数量: {len(share)}")
    print("=" * 50)


def export_codes(args):
    """导出基金代码"""
    state = load_state(args.db)
    favour: Dict[str, List[str]] = state.get("favour", {})

    if args.user:
        if args.user not in favour:
            print(f"错误: 用户 {args.user} 不存在")
            sys.exit(1)
        codes = favour[args.user]
        print(f"用户 {args.user} 的基金列表 ({len(codes)}个):")
        for code in codes:
            print(code)
    else:
        # 导出所有用户
        all_codes = set()
        for user, codes in favour.items():
            print(f"# 用户: {user} ({len(codes)}个)")
            for code in codes:
                print(code)
                all_codes.add(code)
            print()
        print(f"# 共 {len(all_codes)} 个不重复基金代码")


def import_codes(args):
    """导入基金代码"""
    if not args.user:
        print("错误: 必须指定用户名 (--user)")
        sys.exit(1)

    # 获取基金代码列表
    codes = []

    if args.codes:
        # 从命令行参数获取
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    elif args.file:
        # 从文件获取
        if not os.path.exists(args.file):
            print(f"错误: 文件 {args.file} 不存在")
            sys.exit(1)
        with open(args.file, "r") as f:
            for line in f:
                line = line.strip()
                # 跳过空行和注释
                if line and not line.startswith("#"):
                    codes.append(line)
    else:
        print("错误: 必须指定 --codes 或 --file")
        sys.exit(1)

    # 验证基金代码格式
    valid_codes = []
    for code in codes:
        if len(code) == 6 and code.isdigit():
            valid_codes.append(code)
        else:
            print(f"警告: 跳过无效代码 '{code}' (必须是6位数字)")

    if not valid_codes:
        print("错误: 没有有效的基金代码")
        sys.exit(1)

    # 加载或创建状态
    if os.path.exists(args.db):
        state = load_state(args.db)
    else:
        print(f"文件 {args.db} 不存在，将创建新文件")
        state = {"favour": {}, "share": {}}

    favour = state.get("favour", {})

    if args.append and args.user in favour:
        # 追加模式：合并现有列表
        existing = favour[args.user]
        for code in valid_codes:
            if code not in existing:
                existing.append(code)
        favour[args.user] = existing
        print(f"已追加 {len(valid_codes)} 个代码到用户 {args.user}")
    else:
        # 替换模式
        favour[args.user] = valid_codes
        print(f"已设置用户 {args.user} 的基金列表 ({len(valid_codes)} 个)")

    state["favour"] = favour
    save_state(args.db, state)

    print(f"基金代码: {', '.join(valid_codes)}")


def main():
    parser = argparse.ArgumentParser(
        description="state.db 导出和导入工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_STATE_DB,
        help=f"state.db 文件路径 (默认: {DEFAULT_STATE_DB})"
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # show 命令
    show_parser = subparsers.add_parser("show", help="显示当前状态")

    # export 命令
    export_parser = subparsers.add_parser("export", help="导出基金代码")
    export_parser.add_argument("--user", "-u", help="指定用户名 (不指定则导出所有)")

    # import 命令
    import_parser = subparsers.add_parser("import", help="导入基金代码")
    import_parser.add_argument("--user", "-u", required=True, help="用户名")
    import_parser.add_argument("--codes", "-c", help="基金代码列表，逗号分隔")
    import_parser.add_argument("--file", "-f", help="从文件导入 (每行一个代码)")
    import_parser.add_argument("--append", "-a", action="store_true", help="追加模式 (不覆盖现有列表)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "show":
        show_state(args)
    elif args.command == "export":
        export_codes(args)
    elif args.command == "import":
        import_codes(args)


if __name__ == "__main__":
    main()
