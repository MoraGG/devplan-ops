#!/usr/bin/env python3
"""标准库版本化迁移脚本（双库通用：SQLite / MySQL）。

职责：
  1. 给 std_node_rule 补齐 version_no / is_active / effective_from 三列（若已存在则跳过，幂等）。
  2. 建 std_rule_version 版本目录表（SQLite / MySQL 语法分别适配，IF NOT EXISTS 幂等）。
  3. 把现有规则初始化为 v1 基线：std_node_rule 全部行 version_no=1,is_active=1；
     std_node_dependency 既有列可能 NULL，补默认值。
  4. 插入 std_rule_version(v1) 基线版本记录（若不存在）。

运行：
  本地（SQLite 默认）：  python db/init_rule_version.py
  服务器（MySQL）：       DB_TYPE=mysql DB_HOST=127.0.0.1 DB_PORT=3306 DB_USER=root DB_PASS= DB_NAME=dev_plan python db/init_rule_version.py
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


CREATE_SQLITE = """
CREATE TABLE IF NOT EXISTS std_rule_version (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version_no INTEGER NOT NULL UNIQUE,
  name VARCHAR(120),
  note VARCHAR(255),
  effective_from DATE,
  operator VARCHAR(64) DEFAULT '代建运营部',
  source_version_no INTEGER,
  change_summary TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_MYSQL = """
CREATE TABLE IF NOT EXISTS std_rule_version (
  id INT PRIMARY KEY AUTO_INCREMENT,
  version_no INT NOT NULL UNIQUE,
  name VARCHAR(120),
  note VARCHAR(255),
  effective_from DATE,
  operator VARCHAR(64) DEFAULT '代建运营部',
  source_version_no INT,
  change_summary TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB
"""


def main():
    con = get_conn()
    cur = con.cursor()

    # 1. std_node_rule 补三列
    add_col(cur, "std_node_rule", "version_no", "INT DEFAULT 1")
    add_col(cur, "std_node_rule", "is_active", "TINYINT DEFAULT 1")
    add_col(cur, "std_node_rule", "effective_from", "DATE")
    cur.execute(
        "UPDATE std_node_rule SET version_no=1, is_active=1 "
        "WHERE version_no IS NULL OR is_active IS NULL"
    )

    # 2. 建版本目录表（按库类型）
    cur.execute(CREATE_MYSQL if DB_TYPE == "mysql" else CREATE_SQLITE)

    # 3. std_node_dependency 既有列可能 NULL，补默认值
    cur.execute(
        "UPDATE std_node_dependency SET version_no=COALESCE(version_no,1), "
        "is_active=COALESCE(is_active,1) WHERE version_no IS NULL OR is_active IS NULL"
    )

    # 4. 插基线版本 v1（若不存在）
    cur.execute("SELECT COUNT(*) AS c FROM std_rule_version WHERE version_no=1")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO std_rule_version(version_no,name,note,operator) "
            "VALUES(1,'初始基线（绿城2026版）','系统初始化导入','代建运营部')"
        )

    con.commit()
    cur.close()
    con.close()
    print(f"[init_rule_version] done (DB_TYPE={DB_TYPE}): std_node_rule 三列补齐，"
          f"std_rule_version 就绪，现有规则标为 v1 基线。")


if __name__ == "__main__":
    main()
