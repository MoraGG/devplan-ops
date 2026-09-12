#!/usr/bin/env python3
"""执行跟踪闭环 · 本地验证脚本（SQLite 副本，不污染真实库）。

流程：复制 db/devplan.db → _verify_exec.db；跑 init_buffer 迁移；
验证三版生成 / 填报 / 对比 / 预警。验证后删除副本。
"""
import os
import sys
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "devplan.db")
DST = os.path.join(HERE, "_verify_exec.db")
if os.path.exists(DST):
    os.remove(DST)
shutil.copy(SRC, DST)
os.environ["SQLITE_PATH"] = DST

sys.path.insert(0, os.path.join(HERE, "..", "app"))
sys.path.insert(0, HERE)

import init_buffer  # noqa: E402
init_buffer.main()

import importlib.util  # noqa: E402

APP_PATH = os.path.join(HERE, "..", "app", "app.py")
_spec = importlib.util.spec_from_file_location("appmod", APP_PATH)
appmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(appmod)

generate_version = appmod.generate_version
ensure_all_versions = appmod.ensure_all_versions
save_actual = appmod.save_actual
compare_rows = appmod.compare_rows
version_vid = appmod.version_vid
compute_alerts = appmod.compute_alerts
db = appmod.db
regenerate_all_versions = appmod.regenerate_all_versions

ok = True


def check(name, cond, extra=""):
    global ok
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        ok = False


con = db()
cur = con.cursor()

# 1. buffer 列存在
cur.execute("PRAGMA table_info(project)")
cols = {r["name"] for r in cur.fetchall()}
check("project 含 buffer_kh/buffer_ly", {"buffer_kh", "buffer_ly"} <= cols)

# 2. 取一个项目
cur.execute("SELECT id,name FROM project ORDER BY id LIMIT 1")
proj = cur.fetchone()
pid = proj["id"]
print(f"-- 验证项目: id={pid} name={proj['name']}")


def q(sql, args=()):
    """短生命周期查询：每次开/关连接，避免与应用函数（自带连接）相互锁。"""
    c = db(); cu = c.cursor()
    cu.execute(sql, args)
    rows = cu.fetchall()
    cu.close(); c.close()
    return rows


# 3. 三版生成
ensure_all_versions(pid)
vers = {r["plan_type"]: r["c"] for r in q(
    "SELECT plan_type,COUNT(*) AS c FROM plan_version WHERE project_id=? GROUP BY plan_type", (pid,))}
check("plan_version 三版齐全", set(vers.keys()) == {"内控", "考核", "履约"}, str(vers))

# 4. 每版 plan_node 行数一致（= 内控版行数）
cnt = {r["plan_type"]: r["c"] for r in q(
    "SELECT plan_type,COUNT(*) AS c FROM plan_node pn JOIN plan_version pv ON pn.version_id=pv.id "
    "WHERE pn.project_id=? GROUP BY plan_type", (pid,))}
base_n = cnt.get("内控")
check("三版 plan_node 行数一致", base_n and all(c == base_n for c in cnt.values()), str(cnt))

# 5. buffer 默认 0 → 考核/履约 finish_inner == 内控
inner = {r["std_node_id"]: r["finish_inner"] for r in q(
    "SELECT std_node_id,finish_inner FROM plan_node pn JOIN plan_version pv ON pn.version_id=pv.id "
    "WHERE pn.project_id=? AND pv.plan_type='内控'", (pid,))}
kh = {r["std_node_id"]: r["finish_inner"] for r in q(
    "SELECT std_node_id,finish_inner FROM plan_node pn JOIN plan_version pv ON pn.version_id=pv.id "
    "WHERE pn.project_id=? AND pv.plan_type='考核'", (pid,))}
eq = all(kh.get(k) == v for k, v in inner.items())
check("buffer=0 时 考核==内控", eq)

# 6. 设 buffer 后重生成，考核应整体后移（先关测试连接再调应用函数）
c = db(); cu = c.cursor()
cu.execute("UPDATE project SET buffer_kh=14,buffer_ly=30 WHERE id=?", (pid,))
c.commit(); cu.close(); c.close()
regenerate_all_versions(pid)
kh2 = {r["std_node_id"]: r["finish_inner"] for r in q(
    "SELECT std_node_id,finish_inner FROM plan_node pn JOIN plan_version pv ON pn.version_id=pv.id "
    "WHERE pn.project_id=? AND pv.plan_type='考核'", (pid,))}
shifted = all(kh2.get(k) and inner.get(k) and kh2[k] > inner[k] for k in inner if inner[k])
check("buffer=14 后 考核整体晚于内控", shifted)
# 还原 buffer 为 0 保持干净
c = db(); cu = c.cursor()
cu.execute("UPDATE project SET buffer_kh=0,buffer_ly=0 WHERE id=?", (pid,))
c.commit(); cu.close(); c.close()
regenerate_all_versions(pid)

# 7. 实际填报同步三版（挑一个有计划日的节点，偏差才有意义）
snid = next((k for k in inner if inner[k]), next(iter(inner.keys())))
save_actual(pid, [dict(std_node_id=snid, actual_start="2026-10-01", actual_finish="2027-01-15", progress_pct=100)])
af = {r["plan_type"]: r["actual_finish"] for r in q(
    "SELECT plan_type,actual_finish,progress_pct FROM plan_node pn JOIN plan_version pv ON pn.version_id=pv.id "
    "WHERE pn.project_id=? AND pn.std_node_id=?", (pid, snid))}
check("实际进度写入三版", set(af.keys()) == {"内控", "考核", "履约"} and all(v == "2027-01-15" for v in af.values()), str(af))

# 8. 预警三版均可计算
for pt in ("内控", "考核", "履约"):
    hits = compute_alerts(pid, pt, as_of=__import__("datetime").date(2026, 9, 11))
    check(f"compute_alerts({pt}) 无异常", isinstance(hits, list), f"hits={len(hits)}")

# 9. 对比数据
rows = compare_rows(pid)
check("compare_rows 返回节点列表", len(rows) == base_n, f"n={len(rows)}")
sample = next(r for r in rows if r["std_node_id"] == snid)
check("对比含偏差字段", "kh_diff" in sample and "ly_diff" in sample and "af_diff" in sample,
      str({k: sample[k] for k in ("fi_inner", "fi_kh", "fi_ly", "actual", "af_diff")}))

print("\n结果:", "全部通过 ✅" if ok else "存在失败 ❌")
sys.exit(0 if ok else 1)

