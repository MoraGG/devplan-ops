# -*- coding: utf-8 -*-
"""生成多项目演示数据：清理测试项目，套模板生成 3 个差异化演示项目。

每个项目带不同前置参数（地上层数/交付形式/开发贷/户内改造/外立面），
使相对工期引擎按参数化规则算出不同总工期，体现"不同前置参数→不同计划"。
连接走 dbconn（SQLite / MySQL 通用）。
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "db"))
from dbconn import get_conn
from engine import RelativeDateEngine

# (名称, 委托方, 楼型id, T0, 前置参数)
DEMOS = [
    ("滨江新城代建项目（住宅）", "某城投集团", 1, "2026-07-14",
     {"p7": "18", "p9": "精装", "p8": "无", "p10": "有", "p11": "保温涂料"}),     # 18F高层
    ("中央广场代建项目（商业综合体）", "某商管公司", 6, "2026-09-01",
     {"p7": "27", "p9": "精装", "p8": "有", "p10": "有", "p11": "保温涂料+铝板"}),  # 27F高层
    ("智造园代建项目（产业园）", "某产投集团", 5, "2027-01-10",
     {"p7": "11", "p9": "毛坯", "p8": "无", "p10": "无", "p11": "保温涂料"}),     # 11F小高层
]

con = get_conn(); cur = con.cursor()
cur.execute("DELETE FROM plan_node"); cur.execute("DELETE FROM plan_version"); cur.execute("DELETE FROM project")
con.commit()

for name, client, bt_id, t0, prereq in DEMOS:
    prereq_json = json.dumps(prereq, ensure_ascii=False)
    eng = RelativeDateEngine(t0, prereq_json)
    d = eng.to_dict(project=name)
    cur.execute(
        "INSERT INTO project(name,client,building_type_id,plan_start,plan_deliver,status,prereq_json) "
        "VALUES(?,?,?,?,?,?,?)", (name, client, bt_id, t0, d["delivery_date"], "进行中", prereq_json))
    pid = cur.lastrowid
    cur.execute("INSERT INTO plan_version(project_id,version_no,plan_type,status) VALUES(?,1,'内控','基准')", (pid,))
    vid = cur.lastrowid
    con.commit()
    n = eng.apply_to_project(pid, vid, "内控")
    print(f"  {name}: T0={t0} 交付={d['delivery_date']} 总工期={d['total_months']}月 写入节点={n}")

cur.close(); con.close()
print("演示数据生成完成（含前置参数，工期按参数化规则差异化）。")
