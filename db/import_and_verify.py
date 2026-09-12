import pymysql, time, sys, re

def conn():
    return pymysql.connect(host="127.0.0.1", port=3306, user="root",
                            password="devplan123", database="dev_plan",
                            charset="utf8mb4", autocommit=False)

for i in range(30):
    try:
        c = pymysql.connect(host="127.0.0.1", port=3306, user="root",
                            password="devplan123", charset="utf8mb4")
        c.close(); print("MySQL 就绪"); break
    except Exception:
        time.sleep(2)
else:
    print("MySQL 未就绪"); sys.exit(1)

def split_stmts(sql):
    # 去注释行
    lines = []
    for ln in sql.split("\n"):
        if ln.strip().startswith("--"):
            continue
        lines.append(ln)
    body = "\n".join(lines)
    out = []
    for s in body.split(";"):
        s = s.strip()
        if s:
            out.append(s)
    return out

def run_sql_file(path):
    sql = open(path, encoding="utf-8").read()
    stmts = split_stmts(sql)
    con = conn(); cur = con.cursor()
    ok = 0
    for s in stmts:
        cur.execute(s)
        ok += 1
    con.commit(); cur.close(); con.close()
    print(f"执行 {path}: {ok} 条语句")

# 可重跑：先清空已有表
con = conn(); cur = con.cursor()
cur.execute("SET FOREIGN_KEY_CHECKS=0")
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='dev_plan'")
tabs = [r[0] for r in cur.fetchall()]
for t in tabs:
    cur.execute(f"DROP TABLE IF EXISTS {t}")
cur.execute("SET FOREIGN_KEY_CHECKS=1")
con.commit(); cur.close(); con.close()
print(f"已清空 {len(tabs)} 张表")

run_sql_file("/workspace/db/01_ddl.sql")
run_sql_file("/workspace/db/02_seed.sql")

con = conn(); cur = con.cursor()
checks = {
    "profession": "SELECT COUNT(*) FROM profession",
    "building_type": "SELECT COUNT(*) FROM building_type",
    "prereq_param": "SELECT COUNT(*) FROM prereq_param",
    "std_node": "SELECT COUNT(*) FROM std_node",
    "std_duration": "SELECT COUNT(*) FROM std_duration",
    "std_node_dependency": "SELECT COUNT(*) FROM std_node_dependency",
    "std_node_by_level": "SELECT level, COUNT(*) FROM std_node GROUP BY level",
    "std_duration_by_bt": "SELECT bt.code, COUNT(*) FROM std_duration sd JOIN building_type bt ON bt.id=sd.building_type_id GROUP BY bt.code",
    "depend_with_formula": "SELECT COUNT(*) FROM std_node WHERE tmpl_finish_formula IS NOT NULL",
    "t0_based": "SELECT COUNT(*) FROM std_node_dependency WHERE base_is_t0=1",
}
for k, q in checks.items():
    cur.execute(q)
    print(f"  [{k}]", cur.fetchall())

cur.execute("""SELECT sn.name, d.depend_row, d.offset_days, d.direction, d.base_is_t0
               FROM std_node_dependency d JOIN std_node sn ON sn.id=d.std_node_id
               ORDER BY d.id LIMIT 5""")
print("\n依赖抽样:")
for r in cur.fetchall():
    print("  ", r)
cur.close(); con.close()
print("\n导入与校验完成。")
