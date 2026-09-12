# -*- coding: utf-8 -*-
"""重建前备份：把 dev_plan 全库导出为 MySQL 方言 SQL（表结构 + 数据）。
产物：db/_backup/dev_plan_<时间戳>.sql（本地留存，不入库，见 .gitignore 的 *_backup 约定）。
"""
import os, json, datetime, pymysql
from pymysql.converters import escape_string

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "_backup")
os.makedirs(OUTDIR, exist_ok=True)

MYSQL = dict(host=os.environ.get("DB_HOST", "127.0.0.1"),
             port=int(os.environ.get("DB_PORT", "3306")),
             user=os.environ.get("DB_USER", "root"),
             password=os.environ.get("DB_PASS", ""),
             database=os.environ.get("DB_NAME", "dev_plan"), charset="utf8mb4")


def lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (datetime.datetime, datetime.date)):
        return "'" + v.isoformat(sep=" ") if isinstance(v, datetime.datetime) else "'" + v.isoformat() + "'"
    if isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False)
    if isinstance(v, bytes):
        return "0x" + v.hex()
    return "'" + escape_string(str(v)) + "'"


def main():
    con = pymysql.connect(**MYSQL, cursorclass=pymysql.cursors.DictCursor)
    cur = con.cursor()
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTDIR, f"dev_plan_{ts}.sql")
    cur.execute("SHOW TABLES")
    tables = [list(r.values())[0] for r in cur.fetchall()]
    total = 0
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"-- dev_plan backup @ {ts}\nSET FOREIGN_KEY_CHECKS=0;\n")
        for t in tables:
            cur.execute(f"SHOW CREATE TABLE `{t}`")
            ddl = list(cur.fetchone().values())[1]
            f.write(f"\nDROP TABLE IF EXISTS `{t}`;\n{ddl};\n")
            cur.execute(f"SELECT * FROM `{t}`")
            rows = cur.fetchall()
            total += len(rows)
            if rows:
                cols = list(rows[0].keys())
                cl = ",".join(f"`{c}`" for c in cols)
                for r in rows:
                    vals = ",".join(lit(r[c]) for c in cols)
                    f.write(f"INSERT INTO `{t}` ({cl}) VALUES ({vals});\n")
        f.write("\nSET FOREIGN_KEY_CHECKS=1;\n")
    con.close()
    print(f"备份完成 -> {path}")
    print(f"表数 {len(tables)}  总行数 {total}  字节 {os.path.getsize(path)}")


if __name__ == "__main__":
    main()
