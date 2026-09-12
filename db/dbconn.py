# -*- coding: utf-8 -*-
"""房地产开发运营计划系统 · 统一数据库连接层

两种模式，由环境变量 DB_TYPE 切换：

- DB_TYPE=sqlite（默认）：自包含文件库 db/devplan.db，开箱即用，
  本地开发/离线演示用，无需任何外部服务。
- DB_TYPE=mysql：生产模式，连接 MySQL 8.0。连接参数全部从环境变量读取
  （DB_HOST / DB_PORT / DB_USER / DB_PASS / DB_NAME），代码内不留任何明文口令。

MySQL 模式下用 QmarkCursor 把 SQLite 风格的 '?' 占位符自动改写为 '%s'，
使 engine.py / app.py 无需改写即可跨两种库运行；两种模式的游标都支持
r["列名"] 字典式访问（sqlite3 用 dict row_factory，MySQL 用 DictCursor）。

SQLite 并发注意：保持 journal_mode=DELETE（不用 WAL，部分环境 WAL 遗留
-wal/-shm 锁文件会导致假死锁），并设 busy_timeout=5000 缓解写锁。
"""
import os
import sqlite3

DB_TYPE = os.environ.get("DB_TYPE", "sqlite").lower()

# ---- MySQL 连接参数（仅 DB_TYPE=mysql 时使用，全部来自环境变量）----
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASS = os.environ.get("DB_PASS", "")
DB_NAME = os.environ.get("DB_NAME", "dev_plan")

HERE = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.environ.get("SQLITE_PATH", os.path.join(HERE, "devplan.db"))


def _dict_factory(cursor, row):
    """让 SQLite 返回可变 dict，与 pymysql DictCursor 行为一致（支持 r['k'] 赋值）。"""
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def get_conn():
    if DB_TYPE == "mysql":
        # 仅 mysql 模式才 import，避免本地/预览环境强依赖 pymysql
        import pymysql
        from pymysql.cursors import DictCursor

        class QmarkCursor(DictCursor):
            """把 SQLite 风格 '?' 占位符改写为 MySQL 的 '%s'。"""

            def execute(self, sql, args=None):
                if isinstance(sql, str):
                    sql = sql.replace("?", "%s")
                return super().execute(sql, args)

            def executemany(self, sql, args):
                if isinstance(sql, str):
                    sql = sql.replace("?", "%s")
                return super().executemany(sql, args)

        return pymysql.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
            database=DB_NAME, charset="utf8mb4",
            cursorclass=QmarkCursor, autocommit=True,
        )

    con = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
    con.row_factory = _dict_factory
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA busy_timeout=5000")
    return con
