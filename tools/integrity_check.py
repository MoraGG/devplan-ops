# -*- coding: utf-8 -*-
"""数据完整性体检（本地 SQLite devplan.db）。运行：python tools/integrity_check.py"""
import os
import sys
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "db", "devplan.db")
if not os.path.exists(DB):
    print("找不到", DB); sys.exit(1)

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()


def q(sql, args=()):
    cur.execute(sql, args)
    return cur.fetchall()


print("== 表行数 ==")
for t in ["std_node", "std_node_dependency", "std_node_rule", "profession", "prereq_param",
          "project", "plan_version", "plan_node", "alert_rule", "alert_record",
          "project_node_rule", "project_node_fixed", "rule_change_log", "building_type"]:
    try:
        n = q(f"SELECT COUNT(*) c FROM {t}")[0]["c"]
        print(f"  {t:<22} {n}")
    except Exception as e:
        print(f"  {t:<22} !! {e}")

print("\n== 1. std_node 调度依据缺失（既非 T0 基准、又无依赖行、也无参数化分支）==")
bad = q("""SELECT sn.id, sn.excel_row, sn.level, sn.name
           FROM std_node sn
           LEFT JOIN std_node_dependency d ON d.std_node_id = sn.id
           WHERE (sn.base_is_t0 IS NULL OR sn.base_is_t0=0)
             AND d.std_node_id IS NULL
             AND sn.id NOT IN (SELECT DISTINCT std_node_id FROM std_node_rule)
           ORDER BY sn.excel_row""")
for r in bad:
    print(f"  R{r['excel_row']:<5} [{r['level']}] {r['name']}")
print(f"  小计 {len(bad)} 个")

print("\n== 2. 依赖指向不存在的标准节点（depend_std_node_id 悬空）==")
bad2 = q("""SELECT d.std_node_id, d.depend_std_node_id, d.depend_row
            FROM std_node_dependency d
            LEFT JOIN std_node sn ON sn.id = d.depend_std_node_id
            WHERE d.depend_std_node_id IS NOT NULL AND sn.id IS NULL""")
for r in bad2:
    print("  ", dict(r))
print(f"  小计 {len(bad2)} 个")

print("\n== 3. 依赖引用不存在的 Excel 行号（depend_row 无法解析）==")
bad3 = q("""SELECT d.std_node_id, d.depend_row FROM std_node_dependency d
            WHERE d.depend_row IS NOT NULL
              AND (d.base_is_t0 IS NULL OR d.base_is_t0=0)
              AND d.depend_row NOT IN (SELECT excel_row FROM std_node WHERE excel_row IS NOT NULL)""")
for r in bad3:
    print("  ", dict(r))
print(f"  小计 {len(bad3)} 个")

print("\n== 4. 参数化分支引用不存在的 Excel 行号 / 空 offset_expr ==")
bad4 = q("""SELECT std_node_id, branch_order, depend_row, offset_expr FROM std_node_rule
            WHERE (offset_expr IS NULL OR TRIM(offset_expr)='')
               OR (depend_row IS NOT NULL AND depend_row NOT IN
                   (SELECT excel_row FROM std_node WHERE excel_row IS NOT NULL))""")
for r in bad4:
    print("  ", dict(r))
print(f"  小计 {len(bad4)} 个")

print("\n== 5. plan_node：有排程日期为空的节点（按项目/版本）==")
bad5 = q("""SELECT pn.project_id, pn.version_id, COUNT(*) c
            FROM plan_node pn WHERE pn.finish_inner IS NULL
            GROUP BY pn.project_id, pn.version_id""")
for r in bad5:
    print(f"  项目{r['project_id']} 版本{r['version_id']}: {r['c']} 个空日期")
print(f"  受影响分组 {len(bad5)}")

print("\n== 6. plan_node 的 std_node_id 悬空 ==")
bad6 = q("""SELECT COUNT(*) c FROM plan_node pn
            LEFT JOIN std_node sn ON sn.id=pn.std_node_id WHERE sn.id IS NULL""")[0]["c"]
print(f"  {bad6} 个")

print("\n== 7. project 交付日 vs 引擎交付日 一致性（抽查）==")
for p in q("SELECT id,name,plan_start,plan_deliver,prereq_json FROM project"):
    print(f"  项目{p['id']} {p['name']}  T0={p['plan_start']}  存库交付={p['plan_deliver']}  prereq={p['prereq_json']}")

print("\n== 8. prereq_param 的 id->code 映射（校验 check_coverage.py 里硬编码 p7..p11）==")
for r in q("SELECT id, code, name, options_json FROM prereq_param ORDER BY id"):
    print(f"  p{r['id']:<3} code={r['code']:<10} name={r['name']}  opts={r['options_json']}")

con.close()
print("\n完成。")
