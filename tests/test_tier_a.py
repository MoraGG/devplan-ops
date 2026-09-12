# -*- coding: utf-8 -*-
"""Tier A 引擎自测：验证相对工期引擎 + 兼容游标 + MySQL 连通。

运行：在 app/ 目录下执行
  DB_HOST=192.168.2.132 DB_PASS= python3 test_tier_a.py
前置：Docker MySQL 已启动且已 source 01_ddl.sql + 02_seed.sql。
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import RelativeDateEngine  # noqa: E402

T0 = "2026-07-14"
ok = True


def check(name, cond, extra=""):
    global ok
    status = "PASS" if cond else "FAIL"
    if not cond:
        ok = False
    print(f"  [{status}] {name} {extra}")


print("=== 引擎读取标准库并推算工期 ===")
try:
    eng = RelativeDateEngine(T0)
except Exception as e:
    print("  [FAIL] 引擎初始化异常:", repr(e))
    sys.exit(1)

# 1. 拓扑 + 偏移
off = eng.compute_offsets()
n_computed = sum(1 for v in off.values() if v is not None)
check("节点总数>0", len(eng.nodes) > 0, f"(nodes={len(eng.nodes)})")
check("偏移已推算节点>0", n_computed > 0, f"(computed={n_computed})")

# 2. CPM 关键路径
backbone = eng.critical_path()
check("关键路径非空", len(backbone) > 0, f"(backbone={len(backbone)})")

# 3. to_dict 输出完整性
d = eng.to_dict(project="示例代建项目A（住宅）")
check("总工期非空", d.get("total_days") is not None, f"(total_days={d.get('total_days')})")
check("交付日期非空", d.get("delivery_date") is not None, f"(delivery={d.get('delivery_date')})")
check("关键路径列表非空", len(d["critical_path"]) > 0)
check("里程碑列表非空", len(d["milestones"]) > 0, f"(milestones={len(d['milestones'])})")
print(f"  · 项目 T0={d['t0']} 交付={d['delivery_date']} 总工期≈{d['total_months']}月")
print(f"  · 关键路径节点 {len(d['critical_path'])} 个；里程碑 {len(d['milestones'])} 个")

# 4. 参数化分支（若存在规则数据则验证 resolve 不报错）
try:
    eng2 = RelativeDateEngine(T0, prereq_json=json.dumps({"p1": 33}))
    d2 = eng2.to_dict()
    check("带前置参数可解析", d2.get("total_days") is not None)
except Exception as e:
    check("带前置参数可解析", False, f"(异常 {repr(e)})")

# 5. 项目级固定日期覆盖（需要 project_node_fixed 数据；无数据也应安全跳过）
try:
    eng3 = RelativeDateEngine(T0, project_id=1)
    eng3.to_dict()
    check("project_id 覆盖分支安全", True)
except Exception as e:
    check("project_id 覆盖分支安全", False, f"(异常 {repr(e)})")

print("\n=== 结果 ===", "全部通过 ✓" if ok else "存在失败 ✗")
sys.exit(0 if ok else 1)
