# -*- coding: utf-8 -*-
"""把现有 MySQL(dev_plan) 全量迁移到自包含 SQLite 文件(devplan.db)。

用途：让应用脱离外部 MySQL 服务，变为可发布的单端口自包含应用。
生产部署若用 MySQL，不必运行本脚本（设 DB_TYPE=mysql 即可）。

运行：python3 migrate_to_sqlite.py
"""
import os
import json
import datetime
import pymysql
import sqlite3

MYSQL = dict(host=os.environ.get("DB_HOST", "127.0.0.1"),
             port=int(os.environ.get("DB_PORT", "3306")),
             user=os.environ.get("DB_USER", "root"),
             password=os.environ.get("DB_PASS", ""),
             database=os.environ.get("DB_NAME", "dev_plan"), charset="utf8mb4")

HERE = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.join(HERE, "devplan.db")


def map_type(mt: str) -> str:
    mt = mt.upper()
    if any(k in mt for k in ("TINYINT", "SMALLINT", "MEDIUMINT", "INT", "BIGINT")):
        return "INTEGER"
    if any(k in mt for k in ("DECIMAL", "FLOAT", "DOUBLE", "REAL")):
        return "REAL"
    return "TEXT"


def serialize(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


def main():
    # autocommit=True：避免 SELECT 长事务长期持有元数据锁(MDL)，
    # 否则并发/后续 DDL（如 load_seed 的 DROP TABLE）会被 MDL 阻塞。
    mcon = pymysql.connect(**MYSQL, cursorclass=pymysql.cursors.DictCursor, autocommit=True)
    mcur = mcon.cursor()
    mcur.execute("SHOW TABLES")
    tables = [list(r.values())[0] for r in mcur.fetchall()]

    if os.path.exists(SQLITE_PATH):
        os.remove(SQLITE_PATH)
    scon = sqlite3.connect(SQLITE_PATH)
    scur = scon.cursor()

    for t in tables:
        mcur.execute(f"SHOW COLUMNS FROM `{t}`")
        cols = mcur.fetchall()
        coldefs, pk_done = [], False
        for c in cols:
            fname = c["Field"]
            ftype = map_type(c["Type"])
            if c["Key"] == "PRI" and not pk_done:
                pk_done = True
                coldefs.append(f'"{fname}" INTEGER PRIMARY KEY' if ftype == "INTEGER"
                               else f'"{fname}" {ftype} PRIMARY KEY')
            else:
                coldefs.append(f'"{fname}" {ftype}')
        scur.execute(f'CREATE TABLE "{t}" ({", ".join(coldefs)})')

        mcur.execute(f"SELECT * FROM `{t}`")
        rows = mcur.fetchall()
        if rows:
            colnames = list(rows[0].keys())
            placeholders = ",".join(["?"] * len(colnames))
            col_list = ",".join(f'"{c}"' for c in colnames)
            data = [tuple(serialize(v) for v in r.values()) for r in rows]
            scur.executemany(
                f'INSERT INTO "{t}" ({col_list}) VALUES ({placeholders})', data)
        scon.commit()
        print(f"  {t}: {len(rows)} 行")

    mcon.close()
    scon.close()
    print("迁移完成 ->", SQLITE_PATH)


if __name__ == "__main__":
    main()
