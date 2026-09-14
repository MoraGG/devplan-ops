"""由读库引擎生成关键路径视图 HTML（替代一次性脚本）。
数据 100% 来自 MySQL（std_node + std_node_dependency），证明数据层打通。
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import RelativeDateEngine

eng = RelativeDateEngine("2026-07-14")
data = eng.to_dict()

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if s is not None else "")

path_html = ""
for i, p in enumerate(data["critical_path"]):
    cls = "node mile" if p["level"] == "里程碑" else ("node lv1" if p["level"] == "一级" else "node lv2")
    path_html += f'<div class="{cls}"><div class="nm">{esc(p["name"])}</div><div class="dt">{esc(p["date"])}</div></div>'
    if i < len(data["critical_path"]) - 1:
        path_html += '<div class="arrow">→</div>'

ms_html = ""
for m in data["milestones"]:
    tag = '<span class="tag t-mile">关键路径</span>' if m["critical"] else '<span class="tag t-ok">非关键</span>'
    crit_cls = "crit" if m["critical"] else ""
    ms_html += (f'<tr class="{crit_cls}"><td>{esc(m["name"])}</td><td>{esc(m["prof"])}</td>'
                f'<td>{esc(m["date"]) or "—"}</td><td>{tag}</td></tr>')

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>开发运营计划系统 · 关键路径视图（引擎驱动）</title>
<style>
*{{box-sizing:border-box}}body{{font-family:-apple-system,'Segoe UI',sans-serif;background:#f5f7fa;color:#1f2937;margin:0;padding:24px}}
h1{{font-size:20px;margin:0 0 4px}}.sub{{color:#6b7280;font-size:13px;margin-bottom:20px}}
.card{{background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:20px}}
.kpi{{display:flex;gap:16px;flex-wrap:wrap}}.kpi div{{background:#eef2ff;border-radius:10px;padding:12px 18px}}
.kpi b{{font-size:22px;display:block;color:#4338ca}}
.path{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}}
.node{{background:#4338ca;color:#fff;border-radius:8px;padding:9px 11px;min-width:108px}}
.node .nm{{font-weight:600;font-size:12.5px;line-height:1.3}}.node .dt{{font-size:11.5px;opacity:.85;margin-top:3px}}
.node.mile{{background:#dc2626}}.node.lv1{{background:#6366f1}}.node.lv2{{background:#0ea5e9}}
.arrow{{color:#9ca3af;font-size:16px}}
.crit{{border-left:4px solid #ef4444;background:#fff5f5}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #eee}}
th{{color:#6b7280;font-weight:600}}.tag{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px}}
.t-mile{{background:#fee2e2;color:#b91c1c}}.t-ok{{background:#dcfce7;color:#15803d}}
.note{{background:#fffbeb;border-left:4px solid #f59e0b;padding:10px 14px;font-size:13px;color:#92400e;border-radius:6px}}
.dbg{{background:#ecfdf5;border-left:4px solid #10b981;padding:10px 14px;font-size:13px;color:#065f46;border-radius:6px;margin-bottom:20px}}
</style></head><body>
<h1>房地产开发运营计划系统 · 项目关键路径视图</h1>
<div class="sub">引擎驱动 · 数据 100% 来自 MySQL（std_node + std_node_dependency）· CPM 关键路径 · 非甘特图</div>
<div class="dbg">✅ 本页由 <code>db/engine.py</code> 读库实时计算生成，非 Excel 一次性脚本。工期引擎仅依据公式依赖，未读取标准期量文字。</div>
<div class="card"><div class="kpi">
<div><b>{esc(data['project'])}</b></div><div><b>{esc(data['t0'])}</b>项目启动(T0)</div>
<div><b>{esc(data['delivery_date'])}</b>计划交付</div><div><b>{esc(data['total_months'])} 月</b>总工期</div>
<div><b>{len(data['critical_path'])} 个</b>关键路径节点</div></div></div>
<div class="card"><h3 style="margin-top:0">计划关键路径（决定交付日期的最长依赖链）</h3><div class="path">{path_html}</div></div>
<div class="card"><h3 style="margin-top:0">13 个里程碑节点（计划完成日期 · 红框=关键路径）</h3>
<table><thead><tr><th>里程碑</th><th>主责</th><th>计划完成</th><th>是否关键路径</th></tr></thead><tbody>{ms_html}</tbody></table></div>
<div class="note">⚠️ 计算口径：工期引擎<strong>仅基于 Excel L 列公式</strong>（依赖节点+偏移天数+是否T0基准）拓扑递推，<strong>未读取</strong> M~S 列「集团标准期量描述」文字。标准期量文字仅参考展示。规则调整只需改 std_node_dependency 数据，无需改代码。</div>
<script>window.__DATA__={json.dumps(data, ensure_ascii=False)};</script>
</body></html>"""

OUT_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "prototype", "critical_path.html")
with open(OUT_HTML, "w", encoding="utf-8") as f:
    f.write(html)
print(f"已生成 {OUT_HTML}，字节:", len(html))
print("关键路径节点:", len(data["critical_path"]), "| 交付:", data["delivery_date"])
