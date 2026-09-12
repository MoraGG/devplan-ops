#!/usr/bin/env python3
"""执行跟踪闭环 · 数据迁移脚本（双库通用：SQLite / MySQL）。

职责：
  给 project 表补 buffer_kh / buffer_ly 两列（考核/履约版相对内控的期量裕度，天）。
  列已存在则跳过，幂等。默认 0。

说明：
  - 三版 plan_node 由 app 层懒生成（打开对比/填报页或编辑项目时），本脚本不触碰 plan_node。
  - 运行：
    本地（SQLite 默认）：  python db/init_buffer.py
    服务器（MySQL）：       DB_TYPE=mysql DB_HOST=127.0.0.1 DB_PORT=3306 DB_USER=root DB_PASS= DB_NAME=dev_plan python db/init_buffer.py
依赖：dbconn（经 DB_TYPE 切换连接）
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(HERE, "..", "app")
sys.path.insert(0, APP_DIR)
sys.path.insert(0, HERE)

from dbconn import get_conn, DB_TYPE  # noqa: E402


def add_col(cur, tbl, col, typ):
    """给表加列；列已存在（双库报错 Duplicate/already exists）则忽略，保证幂等。"""
    try:
        cur.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
    except Exception as e:  # noqa: BLE001
        m = str(e).lower()
        if "duplicate" in m or "already exists" in m:
            return
        raise


def main():
    con = get_conn()
    cur = con.cursor()
    add_col(cur, "project", "buffer_kh", "INT DEFAULT 0")
    add_col(cur, "project", "buffer_ly", "INT DEFAULT 0")
    con.commit()
    cur.close()
    con.close()
    print(f"[init_buffer] done (DB_TYPE={DB_TYPE}): project 表 buffer_kh/buffer_ly 就绪（默认 0）。")


if __name__ == "__main__":
    main()
