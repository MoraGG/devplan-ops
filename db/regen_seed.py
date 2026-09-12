import openpyxl, re, os
import pymysql
from pymysql.converters import escape_string

SRC = "/root/uploads/1789086116145035650-远建2026版三级计划（绿城基础含公式）.xlsx"
OUT = "/workspace/db/02_seed.sql"
wb = openpyxl.load_workbook(SRC, data_only=False)
ws = wb["节点计划 (终稿)"]
rows = list(ws.iter_rows(min_row=4, values_only=True))

LEVEL_MAP = {'里程碑': '里程碑', '一级': '一级', '二级': '二级', '三级': '二级*'}
BT = [('BT18', '18F高层'), ('BT4', '4F及以下'), ('BT6', '6F叠拼'), ('BT8', '8F洋房'),
      ('BT11', '11F小高层'), ('BT27', '27F高层'), ('BT33', '33F高层')]
PRE = [('volum', '容积率', '["小于2.5","大于2.5"]'), ('basefloor', '地下室层数', '[1,2,3]'),
       ('pile', '桩基形式', '["管桩","灌注桩"]'), ('hsupp', '水平支撑层数', '[0,1]'),
       ('demoarea', '首开示范区面积', '["小于7000㎡","大于7000㎡"]'), ('voidlayer', '有无架空层', '["有","无"]'),
       ('topfloor', '地上最高层数', '["数值"]'), ('devloan', '有无开发贷', '["有","无"]'),
       ('delivery', '交付形式', '["毛坯","精装"]'), ('interior', '有无户内改造', '["有","无"]'),
       ('facade', '外立面形式', '["保温涂料","保温涂料+铝板"]')]

def esc(s):
    if s is None:
        return 'NULL'
    return "'" + escape_string(str(s)) + "'"

def parse_formula(f):
    if not isinstance(f, str) or not f.startswith('='):
        return None
    # 偏移量 (+/-d) 可选：=L53 这种「纯等于、偏移0」也要匹配，否则会被误判为无依赖
    m = re.findall(r'L(\d+)([+\-]\d+)?', f[1:])
    if m:
        row = int(m[0][0]); off = 0
        if m[0][1]:
            off = int(m[0][1][1:]) * (1 if m[0][1][0] == '+' else -1)
        return dict(depend_row=row, offset_days=off, base_is_t0=int(row == 6))
    return dict(depend_row=None, offset_days=None, base_is_t0=0)

profs = []; profset = set()
for r in rows:
    if r[3] in LEVEL_MAP and r[5]:
        p = str(r[5]).strip()
        if p not in profset:
            profset.add(p); profs.append(p)
profmap = {p: i + 1 for i, p in enumerate(profs)}

nodes = []; rownum_map = {}
for idx, r in enumerate(rows):
    if r[3] not in LEVEL_MAP:
        continue
    er = idx + 4
    level = LEVEL_MAP[r[3]]
    lvl_seq = r[0] if r[3] == '里程碑' else (r[1] if r[3] == '一级' else (r[2] if r[3] in ('二级', '三级') else None))
    fm = parse_formula(r[11])
    nodes.append(dict(excel_row=er, level=level, seq=lvl_seq, name=str(r[4]).strip(),
                      prof=str(r[5]).strip() if r[5] else None, deliverable=r[19], support_doc=r[20],
                      duration=r[7], formula=r[11], **(fm or {})))
    rownum_map[er] = len(nodes)

S = []
S.append("-- 房地产开发运营计划系统 · 种子数据（来自 Excel 实测，pymysql.escape_string 转义）\nUSE dev_plan;\n")
S.append("INSERT INTO profession(code,name) VALUES")
S.append(",\n".join(f"('P{i+1}',{esc(p)})" for i, p in enumerate(profs)) + ";\n")
S.append("INSERT INTO building_type(code,name) VALUES")
S.append(",\n".join(f"({esc(c)},{esc(n)})" for c, n in BT) + ";\n")
S.append("INSERT INTO prereq_param(code,name,options_json) VALUES")
S.append(",\n".join(f"({esc(c)},{esc(n)},{esc(o)})" for c, n, o in PRE) + ";\n")

S.append("-- 标准节点库（148 条，按 Excel 行序）")
S.append("INSERT INTO std_node(excel_row,level,seq,name,profession_id,deliverable,support_doc,duration,tmpl_finish_formula,depend_row,offset_days,base_is_t0,has_condition) VALUES")
vl = []
for n in nodes:
    pid = profmap.get(n['prof']) if n['prof'] else 'NULL'
    fm = n.get('formula')
    fm_sql = esc(fm) if fm else 'NULL'
    dur = n['duration'] if isinstance(n['duration'], (int, float)) else 'NULL'
    dr = n.get('depend_row'); off = n.get('offset_days'); bt = n.get('base_is_t0', 0); hc = n.get('has_condition', 0)
    vl.append(f"({n['excel_row']},{esc(n['level'])},{n['seq'] if n['seq'] is not None else 'NULL'},{esc(n['name'])},{pid},{esc(n['deliverable'])},{esc(n['support_doc'])},{dur},{fm_sql},{dr if dr else 'NULL'},{off if off is not None else 'NULL'},{bt},{hc})")
S.append(",\n".join(vl) + ";\n")

S.append("-- 标准期量（7 楼型 × 节点）")
sd = []
for i, n in enumerate(nodes):
    sid = i + 1
    for j, (c, _) in enumerate(BT):
        cell = rows[n['excel_row'] - 4][12 + j]
        if cell and str(cell).strip():
            sd.append(f"({sid},{j+1},{esc(str(cell).strip())})")
S.append("INSERT INTO std_duration(std_node_id,building_type_id,std_desc) VALUES")
S.append(",\n".join(sd) + ";\n")

S.append("-- 标准节点依赖（解析公式 Lx±d）")
dep = []
for i, n in enumerate(nodes):
    if n.get('depend_row'):
        did = rownum_map.get(n['depend_row'])
        off = n['offset_days']; direction = '之后' if off >= 0 else '之前'
        dep.append(f"({i+1},{did if did else 'NULL'},{n['depend_row']},{off},{n.get('base_is_t0',0)},{esc(direction)},{n.get('has_condition',0)})")
S.append("INSERT INTO std_node_dependency(std_node_id,depend_std_node_id,depend_row,offset_days,base_is_t0,direction,has_condition) VALUES")
S.append(",\n".join(dep) + ";\n")

open(OUT, "w", encoding="utf-8").write("\n".join(S))
print("重新生成", OUT, "字节:", os.path.getsize(OUT))
print("nodes:", len(nodes), "std_duration:", len(sd), "dep:", len(dep))
