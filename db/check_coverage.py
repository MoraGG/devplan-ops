# -*- coding: utf-8 -*-
"""排程覆盖度体检：用引擎算出 148 个标准节点的相对偏移，统计有多少节点拿不到日期。
连接按 DB_TYPE 走 dbconn（mysql / sqlite 均可）。
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import RelativeDateEngine  # noqa: E402

T0 = os.environ.get("COV_T0", "2026-07-14")
PREREQ = json.dumps({"p7": "18", "p9": "精装", "p8": "无", "p10": "有", "p11": "保温涂料"},
                    ensure_ascii=False)

eng = RelativeDateEngine(T0, PREREQ)
eng.compute_offsets()

total = len(eng.nodes)
ok = sum(1 for v in eng.offset.values() if v is not None)
miss = [(eng.nodes[i]["excel_row"], eng.nodes[i]["level"], eng.nodes[i]["name"], eng.nodes[i]["level"])
        for i, v in eng.offset.items() if v is None]
miss.sort()

print(f"DB_TYPE={os.environ.get('DB_TYPE','sqlite')}  DB_HOST={os.environ.get('DB_HOST','-')}")
print(f"标准节点 {total} 个，有排程日期 {ok} 个，无日期 {len(miss)} 个  → 覆盖率 {ok/total*100:.1f}%")
print("无排程节点清单（按 Excel 行）：")
for er, lv, nm, _ in miss:
    print(f"  R{er:>4}  [{lv:<4}] {nm}")
