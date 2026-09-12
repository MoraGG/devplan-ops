"""房地产开发运营计划系统 · 相对工期引擎（读库版）

核心约束（来自需求 V0.2）：
  - 工期计算【仅】依据 Excel L 列公式解析出的依赖关系（std_node_dependency），
    即「依赖节点 + 偏移天数 + 是否 T0 基准」。
  - 【绝不】读取 M~S 列「集团标准期量描述」文字（std_duration 仅作参考展示）。

算法：
  1. 自 std_node / std_node_dependency 构建有向依赖图；
  2. 拓扑排序后递推每个节点的「相对 T0 偏移天数」；T0 锚点偏移 = 0；
  3. CPM：自交付节点沿单一依赖回溯主干，再在相邻主干节点间补入落在时间段内、
     且位于该依赖路径上的中间节点，得到完整关键路径。

连接统一走 dbconn.get_conn()（DB_TYPE 决定 mysql / sqlite）。
"""
import datetime
import json
import re
from collections import defaultdict, deque
from dbconn import get_conn


class RelativeDateEngine:
    def __init__(self, t0, prereq_json=None, project_id=None):
        self.t0 = t0 if isinstance(t0, datetime.date) else datetime.date.fromisoformat(t0)
        self.nodes = {}          # node_id -> dict
        self.row_to_id = {}      # excel_row -> node_id
        self.deps_raw = []       # 默认边（std_node_dependency）
        self.deps = []           # 当前生效边（resolve 后按 prereq 解析）
        self.rules = {}          # node_id -> [分支 dict]（标准库参数化规则）
        self.project_rules = {}  # node_id -> [分支 dict]（项目级 override 规则）
        self.project_fixed = {}  # node_id -> fixed_date 字符串（项目级固定日期覆盖）
        self.project_id = project_id
        self.prereq_code = {}    # prereq_param id -> code
        self.prereq = {}         # 当前项目参数值 code -> value
        self._load()
        if prereq_json is not None:
            self.resolve(prereq_json)

    def _load(self):
        con = get_conn(); cur = con.cursor()
        cur.execute("""SELECT id, excel_row, level, seq, name, profession_id, duration,
                              tmpl_finish_formula, depend_row, offset_days, base_is_t0
                       FROM std_node ORDER BY id""")
        for r in cur.fetchall():
            self.nodes[r["id"]] = r
            if r["excel_row"]:
                self.row_to_id[r["excel_row"]] = r["id"]
        cur.execute("""SELECT std_node_id, depend_std_node_id, depend_row, offset_days, base_is_t0
                       FROM std_node_dependency WHERE is_active=1""")
        for r in cur.fetchall():
            self.deps_raw.append((r["std_node_id"], r["depend_std_node_id"], r["depend_row"],
                                  r["offset_days"], r["base_is_t0"]))
        self.deps = list(self.deps_raw)
        # 参数化规则（仅生效版本 is_active=1 参与计算）
        cur.execute("""SELECT std_node_id, branch_order, is_default, conditions_json,
                              depend_row, offset_expr, direction, base_is_t0
                       FROM std_node_rule WHERE is_active=1 ORDER BY std_node_id, branch_order""")
        for r in cur.fetchall():
            self.rules.setdefault(r["std_node_id"], []).append(dict(r))
        # 项目级规则（override）：存在则整体覆盖标准库对应节点
        if self.project_id is not None:
            cur.execute("""SELECT std_node_id, branch_order, is_default, conditions_json,
                                  depend_row, offset_expr, direction, base_is_t0
                           FROM project_node_rule
                           WHERE project_id=? ORDER BY std_node_id, branch_order""", (self.project_id,))
            for r in cur.fetchall():
                self.project_rules.setdefault(r["std_node_id"], []).append(dict(r))
            # 项目级固定日期覆盖：直接以 (fixed_date - T0) 作为偏移，忽略公式/规则
            cur.execute("SELECT std_node_id, fixed_date FROM project_node_fixed WHERE project_id=?",
                        (self.project_id,))
            for r in cur.fetchall():
                self.project_fixed[r["std_node_id"]] = r["fixed_date"]
        # 参数 code 映射
        cur.execute("SELECT id, code FROM prereq_param")
        self.prereq_code = {r["id"]: r["code"] for r in cur.fetchall()}
        # 职能名
        cur.execute("SELECT id, name FROM profession")
        self.prof = {r["id"]: r["name"] for r in cur.fetchall()}
        cur.close(); con.close()

    # ---------- 参数化解析：按项目 prereq_json 选出每个节点的生效分支 ----------
    def _parse_prereq(self, prereq_json):
        if not prereq_json:
            return {}
        try:
            pj = json.loads(prereq_json) if isinstance(prereq_json, str) else prereq_json
        except Exception:
            return {}
        res = {}
        for k, v in pj.items():
            if isinstance(k, str) and k.startswith("p") and v not in (None, ""):
                try:
                    pid = int(k[1:])
                except Exception:
                    continue
                code = self.prereq_code.get(pid)
                if code:
                    res[code] = int(v) if code == "topfloor" else v
        return res

    def _cond_match(self, cond):
        pv = self.prereq.get(cond["param"])
        if pv is None:
            return False
        cv = cond["value"]; op = cond["op"]
        if op == "=":
            return str(pv) == str(cv)
        if op == "<>":
            return str(pv) != str(cv)
        try:
            pv = float(pv); cv = float(cv)
        except Exception:
            return False
        return {">=": pv >= cv, "<=": pv <= cv, ">": pv > cv, "<": pv < cv}[op]

    def _eval_offset(self, expr):
        if expr is None:
            return None
        if "topfloor" not in expr:
            return int(eval(expr, {"__builtins__": {}}, {}))
        val = self.prereq.get("topfloor") or 0
        safe = re.sub(r"[^0-9topfloor+\-*/(). ]", "", expr)
        return int(eval(safe, {"__builtins__": {}}, {"topfloor": float(val)}))

    def resolve(self, prereq_json):
        """依据项目前置参数，把参数化节点解析为具体生效边，覆盖 self.deps。"""
        self.prereq = self._parse_prereq(prereq_json)
        edges = []
        for nid in self.nodes:
            if nid in self.project_fixed:
                continue  # 固定日期节点：偏移由 compute_offsets 直接注入，不参与依赖推导
            rs = self.project_rules.get(nid) or self.rules.get(nid)
            if rs:
                chosen = None
                for b in rs:
                    conds = b["conditions_json"]
                    conds = json.loads(conds) if isinstance(conds, str) else (conds or [])
                    if b["is_default"] or all(self._cond_match(c) for c in conds):
                        chosen = b; break
                if chosen is None or chosen["depend_row"] is None:
                    continue  # 该参数组合下此节点不排程
                did = self.row_to_id.get(chosen["depend_row"])
                off = self._eval_offset(chosen["offset_expr"])
                edges.append((nid, did, chosen["depend_row"], off, 0))
            else:
                for d in self.deps_raw:
                    if d[0] == nid:
                        edges.append(d); break
        self.deps = edges


    # ---------- 1. 偏移天数递推 ----------
    def compute_offsets(self):
        offset = {}
        # T0 锚点：被 base_is_t0 依赖指向的节点（excel_row 对应 depend_row）
        anchor_rows = {d[2] for d in self.deps if d[4] == 1}
        for nid, n in self.nodes.items():
            if n["excel_row"] in anchor_rows:
                offset[nid] = 0
        # 项目级固定日期覆盖：以 (fixed_date - T0) 作为绝对偏移注入（优先级最高）
        for nid, ds in self.project_fixed.items():
            try:
                offset[nid] = (datetime.date.fromisoformat(ds) - self.t0).days
            except Exception:
                pass
        # 拓扑排序（depend -> node 方向）
        indeg = defaultdict(int)
        adj = defaultdict(list)
        for cid, did, drow, off, bt in self.deps:
            if did and did in self.nodes:
                indeg[cid] += 1
                adj[did].append(cid)
        for nid in self.nodes:
            if nid not in indeg:
                indeg[nid] = 0
        q = deque([nid for nid in self.nodes if indeg[nid] == 0])
        topo = []
        indeg2 = dict(indeg)
        while q:
            u = q.popleft(); topo.append(u)
            for v in adj[u]:
                indeg2[v] -= 1
                if indeg2[v] == 0:
                    q.appendleft(v)
        # 递推
        for nid in topo:
            if nid in offset:
                continue
            best = None
            for (cid, did, drow, off, bt) in self.deps:
                if cid != nid or not did or did not in offset:
                    continue
                if bt:
                    val = off                      # 相对 T0
                else:
                    val = offset[did] + off if offset.get(did) is not None else None
                if val is not None and (best is None or val > best):
                    best = val
            offset[nid] = best
        self.offset = offset
        return offset

    # ---------- 2. 关键路径（CPM） ----------
    def _ancestors(self, nid):
        s = set(); cur = nid; g = 0
        while cur and cur not in s and g < 2000:
            s.add(cur)
            # 找 cur 的依赖前驱
            prev = None
            for (cid, did, drow, off, bt) in self.deps:
                if cid == cur and did in self.nodes:
                    prev = did; break
            cur = prev; g += 1
        return s

    def critical_path(self):
        if not hasattr(self, "offset"):
            self.compute_offsets()
        # 交付节点：名称含「项目计划交付」或偏移最大者
        deliv = None
        for nid, n in self.nodes.items():
            if n["name"] and "项目计划交付" in n["name"]:
                deliv = nid; break
        if deliv is None:
            deliv = max(self.offset, key=lambda k: self.offset[k] or -1e9)
        # 主干回溯
        backbone = []; cur = deliv; seen = set()
        while cur is not None and cur not in seen:
            seen.add(cur); backbone.append(cur)
            prev = None
            for (cid, did, drow, off, bt) in self.deps:
                if cid == cur and did in self.nodes:
                    prev = did; break
            cur = prev
        backbone.reverse()
        full = set(backbone)
        for i in range(len(backbone) - 1):
            A, B = backbone[i], backbone[i + 1]
            if self.offset.get(A) is None or self.offset.get(B) is None:
                continue
            fa, fb = self.offset[A], self.offset[B]
            anc_B = self._ancestors(B)
            for nid in self.nodes:
                if nid in (A, B) or nid in full or self.offset.get(nid) is None:
                    continue
                if fa <= self.offset[nid] <= fb and A in self._ancestors(nid) and nid in anc_B:
                    full.add(nid)
        self.critical = full
        return backbone

    # ---------- 3. 输出 ----------
    def to_dict(self, project="示例代建项目A（住宅）"):
        if not hasattr(self, "offset"):
            self.compute_offsets()
        if not hasattr(self, "critical"):
            self.critical_path()
        def dstr(o):
            return None if o is None else (self.t0 + datetime.timedelta(days=o)).isoformat()
        nodes = []
        for nid, n in self.nodes.items():
            o = self.offset.get(nid)
            nodes.append(dict(id=nid, level=n["level"], name=n["name"],
                              prof=self.prof.get(n["profession_id"], ""),
                              formula=n["tmpl_finish_formula"], off=o,
                              date=dstr(o), critical=(nid in self.critical)))
        cps = sorted(self.critical, key=lambda x: (self.offset.get(x) or 0))
        deliv = [nid for nid, n in self.nodes.items() if n["name"] and "项目计划交付" in n["name"]]
        deliv = deliv[0] if deliv else max(self.offset, key=lambda k: self.offset[k] or -1e9)
        total = self.offset.get(deliv)
        return dict(
            project=project, t0=self.t0.isoformat(),
            total_days=total,
            total_months=round(total / 30, 1) if total else None,
            delivery_date=dstr(total),
            critical_path=[dict(id=e, level=self.nodes[e]["level"], name=self.nodes[e]["name"],
                                prof=self.prof.get(self.nodes[e]["profession_id"], ""),
                                date=dstr(self.offset.get(e))) for e in cps],
            milestones=[dict(id=e, level=self.nodes[e]["level"], name=self.nodes[e]["name"],
                             prof=self.prof.get(self.nodes[e]["profession_id"], ""),
                             date=dstr(self.offset.get(e)), critical=(e in self.critical))
                       for e in self.nodes if self.nodes[e]["level"] == "里程碑"],
            engine_note="工期引擎仅基于 Excel L 列公式（std_node_dependency），未读取 M~S 标准期量文字。"
        )

    # ---------- 4. 套模板生成项目计划节点（写入 plan_node） ----------
    def apply_to_project(self, project_id, version_id, plan_type="内控", buffer_days=0):
        """套模板生成某版 plan_node。
        finish_inner = T0 + 相对偏移 + buffer_days（版本期量裕度）。
        内控版 buffer_days=0；考核/履约版由调用方传入项目级 buffer（如 +14 天）。"""
        if not hasattr(self, "offset"):
            self.compute_offsets()
        con = get_conn(); cur = con.cursor()
        rows = []
        for nid, n in self.nodes.items():
            o = self.offset.get(nid)
            base = (self.t0 + datetime.timedelta(days=o)) if o is not None else None
            fin = (base + datetime.timedelta(days=buffer_days)).isoformat() if base is not None else None
            rows.append((project_id, version_id, nid, n["level"], n["seq"], n["name"],
                         n["profession_id"], fin, None, None, None, None, '正常'))
        cur.executemany(
            """INSERT INTO plan_node(project_id,version_id,std_node_id,level,seq,name,profession_id,
               finish_inner,start_inner,finish_assess,finish_perform,actual_finish,status)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        con.commit(); cur.close(); con.close()
        return len(rows)


# ---------- 5. 预警引擎 ----------
def compute_alerts(project_id, plan_type="内控", as_of=None):
    """按 (level, plan_type) 规则比对计划完成日与参考日（actual_finish 或 as_of），
    偏差天数 ≥ 阈值则写 alert_record 并刷新 plan_node.status。

    逻辑：
      - 计划完成日 P 取该版本 plan_node.finish_inner（各版本 finish_inner 已是该版计划日；
        考核/履约版 = 内控版 + 项目级 buffer，由 apply_to_project 写入）；
      - 参考日 ref：有 actual_finish 用实际完成日，否则用 as_of（业务当前日）；
      - 偏差 dev = (ref − P).days；dev ≥ threshold_days 即命中；
      - 有实际完成且 dev>0 → 节点状态「延期」；否则按 dev 正负 → 「延期」/「预警」。
    返回命中列表。每次重算会清空该版本旧记录后重写（反映当前最新状态）。"""
    if as_of is None:
        as_of = datetime.date.today()
    as_of = _as_date(as_of) or datetime.date.today()
    con = get_conn(); cur = con.cursor()
    try:
        cur.execute(
            "SELECT id,level,plan_type,threshold_days,notify_target FROM alert_rule WHERE plan_type=?",
            (plan_type,))
        rules = {r["level"]: dict(r) for r in cur.fetchall()}
        cur.execute(
            "SELECT id FROM plan_version WHERE project_id=? AND plan_type=? ORDER BY id LIMIT 1",
            (project_id, plan_type))
        vr = cur.fetchone(); vid = vr["id"] if vr else None
        if vid is None:
            return []
        # 先重置本版本节点状态为正常，再按命中刷新，避免陈旧状态残留
        cur.execute(
            "UPDATE plan_node SET status='正常' WHERE project_id=? AND version_id=?",
            (project_id, vid))
        # 清理本版本旧预警记录（避免重复累计）
        cur.execute(
            "DELETE FROM alert_record WHERE plan_node_id IN "
            "(SELECT id FROM plan_node WHERE project_id=? AND version_id=?)",
            (project_id, vid))
        cur.execute(
            "SELECT id,level,name,finish_inner,actual_finish "
            "FROM plan_node WHERE project_id=? AND version_id=?", (project_id, vid))
        nodes = cur.fetchall()
        hits = []
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for n in nodes:
            rule = rules.get(n["level"])
            if not rule:
                continue
            P = _as_date(n["finish_inner"])
            if P is None:
                continue
            af = _as_date(n["actual_finish"])
            ref = af if af else as_of
            dev = (ref - P).days
            if dev >= rule["threshold_days"]:
                if af:
                    kind = "实际较计划滞后"
                    nstatus = "延期"
                else:
                    kind = "计划完成日已过仍未完成" if dev > 0 else "临近计划完成日"
                    nstatus = "延期" if dev > 0 else "预警"
                msg = (f"节点『{n['name']}』（{n['level']}）{kind}："
                       f"计划({plan_type})完成 {P.isoformat()}，"
                       + (f"实际完成 {ref.isoformat()}" if af else f"截至 {ref.isoformat()} 未完成")
                       + f"，偏差 {dev} 天（阈值 {rule['threshold_days']} 天）")
                cur.execute(
                    "INSERT INTO alert_record(plan_node_id,alert_rule_id,triggered_at,delay_days,message) "
                    "VALUES(?,?,?,?,?)", (n["id"], rule["id"], now, dev, msg))
                cur.execute("UPDATE plan_node SET status=? WHERE id=?", (nstatus, n["id"]))
                hits.append(dict(plan_node_id=n["id"], level=n["level"], name=n["name"],
                                 plan_type=plan_type, delay_days=dev, threshold=rule["threshold_days"],
                                 notify=rule["notify_target"], message=msg, status=nstatus))
        con.commit()
        return hits
    finally:
        cur.close(); con.close()


def _as_date(v):
    """将 DATE / 字符串统一转为 date 对象；无法解析返回 None。"""
    if v is None:
        return None
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def ensure_default_alert_rules():
    """alert_rule 为空时插入设计默认值：里程碑/一级 ≥14 天、二级/二级* ≥7 天（内控版）。"""
    con = get_conn(); cur = con.cursor()
    try:
        cur.execute("SELECT COUNT(*) AS c FROM alert_rule")
        if cur.fetchone()["c"] == 0:
            defaults = [
                ("里程碑", "内控", 14, "代建运营部 / 项目总经理"),
                ("一级",   "内控", 14, "代建运营部 / 项目总经理"),
                ("二级",   "内控", 7,  "项目工程负责人"),
                ("二级*",  "内控", 7,  "项目工程负责人"),
            ]
            cur.executemany(
                "INSERT INTO alert_rule(level,plan_type,threshold_days,notify_target) VALUES(?,?,?,?)",
                defaults)
            con.commit()
    finally:
        cur.close(); con.close()


if __name__ == "__main__":
    eng = RelativeDateEngine("2026-07-14")
    data = eng.to_dict()
    print("T0:", data["t0"], "| 交付:", data["delivery_date"], "| 总工期(月):", data["total_months"])
    print("关键路径节点数:", len(data["critical_path"]))
    print("关键路径:")
    for p in data["critical_path"]:
        print(f"  [{p['level']}] {p['name']}  ({p['date']})")
    print("里程碑关键路径标记:", sum(1 for m in data["milestones"] if m["critical"]), "/ 13")
