# -*- coding: utf-8 -*-
"""房地产开发运营计划系统 · Web 管理后台（MVP 正式前端，自包含版）

依赖：Flask + db/engine.py（相对工期引擎）+ db/dbconn.py（连接层，默认 SQLite）
运行：python3 app.py  ->  监听 $PORT（默认 5000），绑定 0.0.0.0
说明：发布/预览用默认 SQLite（DB_TYPE=sqlite，无需外部服务）；部署到自带 MySQL 的
      服务器时，设环境变量 DB_TYPE=mysql 即可切回生产库，代码无需改动。
"""
import os
import sys
import datetime
import json
from flask import Flask, render_template, request, redirect, url_for, jsonify

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "db"))
from engine import RelativeDateEngine, ensure_default_alert_rules, compute_alerts  # noqa: E402
from dbconn import get_conn  # noqa: E402

TODAY = datetime.date(2026, 9, 11)  # 系统当前业务日期（演示用，可改为 datetime.date.today()）

app = Flask(__name__)
app.jinja_env.globals["TODAY"] = TODAY

# 启动即保证预警默认规则存在（里程碑/一级≥14天、二级/二级*≥7天，内控版）
ensure_default_alert_rules()


def db():
    return get_conn()


def engine_for(t0, prereq_json=None, project_id=None):
    return RelativeDateEngine(t0, prereq_json, project_id)


def parse_prereq_opts(options_json):
    """解析前置参数可选项：返回选项字符串列表；['数值'] 表示自由数值输入 -> 返回 None；其余 -> 空列表(文本)。"""
    try:
        opts = json.loads(options_json)
    except Exception:
        return []
    if isinstance(opts, list):
        if len(opts) == 1 and str(opts[0]) == "数值":
            return None  # 自由数值输入
        return [str(x) for x in opts]
    return []


def load_prereqs():
    """读取前置参数表，并解析出每个参数的下拉选项（opts）。"""
    con = db(); cur = con.cursor()
    cur.execute("SELECT id,code,name,options_json FROM prereq_param ORDER BY id")
    prereqs = [dict(r) for r in cur.fetchall()]
    for pr in prereqs:
        pr["opts"] = parse_prereq_opts(pr["options_json"])
    cur.close(); con.close()
    return prereqs


def load_project(pid):
    con = db(); cur = con.cursor()
    cur.execute("SELECT id,name,client,building_type_id,plan_start,plan_deliver,status,prereq_json "
                "FROM project WHERE id=?", (pid,))
    p = cur.fetchone()
    cur.close(); con.close()
    return p


def building_types():
    con = db(); cur = con.cursor()
    cur.execute("SELECT id,name FROM building_type ORDER BY id")
    bts = cur.fetchall()
    cur.close(); con.close()
    return bts


# ---------------- 看板 / 项目列表 ----------------
@app.route("/")
def dashboard():
    con = db(); cur = con.cursor()
    cur.execute("SELECT id,name,client,building_type_id,plan_start,plan_deliver,status,prereq_json FROM project ORDER BY id")
    projects = cur.fetchall()
    cur.execute("SELECT id,name FROM building_type")
    bt = {r["id"]: r["name"] for r in cur.fetchall()}
    # 各项目预警计数（读取最近一次计算的结果）
    cur.execute("SELECT pn.project_id AS pid, COUNT(*) AS c FROM alert_record ar "
                "JOIN plan_node pn ON ar.plan_node_id=pn.id GROUP BY pn.project_id")
    alert_by_proj = {r["pid"]: r["c"] for r in cur.fetchall()}
    cur.close(); con.close()

    cards = []
    for p in projects:
        t0 = p["plan_start"]
        eng = engine_for(t0, p["prereq_json"], p["id"])
        d = eng.to_dict(project=p["name"])
        # 下一个未过期的里程碑
        upcoming = [m for m in d["milestones"] if m["date"] and m["date"] >= TODAY.isoformat()]
        next_ms = upcoming[0] if upcoming else None
        cards.append(dict(
            id=p["id"], name=p["name"], client=p["client"],
            building_type=bt.get(p["building_type_id"], "—"),
            t0=(t0.isoformat() if hasattr(t0, "isoformat") else str(t0)),
            delivery=d["delivery_date"],
            total_months=d["total_months"], total_days=d["total_days"],
            crit_nodes=len(d["critical_path"]),
            crit_miles=sum(1 for m in d["milestones"] if m["critical"]),
            status=p["status"],
            next_milestone=next_ms,
            alerts=alert_by_proj.get(p["id"], 0),
        ))
    kpi = dict(
        total=len(cards),
        on_going=sum(1 for c in cards if c["status"] == "进行中"),
        delivered=sum(1 for c in cards if c["status"] == "已交付"),
        avg_months=round(sum(c["total_months"] or 0 for c in cards) / len(cards), 1) if cards else 0,
        alerts=sum(alert_by_proj.values()),
    )
    return render_template("dashboard.html", cards=cards, kpi=kpi)


# ---------------- 新建项目 ----------------
@app.route("/project/new", methods=["GET", "POST"])
def new_project():
    bts = building_types()
    prereqs = load_prereqs()
    if request.method == "POST":
        con = db(); cur = con.cursor()
        name = request.form["name"].strip()
        client = request.form.get("client", "").strip()
        bt_id = int(request.form["building_type_id"])
        t0 = request.form["plan_start"]
        status = request.form.get("status", "进行中")
        prereq = {f"p{pr['id']}": request.form.get(f"p{pr['id']}") for pr in prereqs}
        prereq_json = json.dumps(prereq, ensure_ascii=False)
        # 交付日先按引擎预估（套模板后回填）
        eng = engine_for(t0, prereq_json)
        d = eng.to_dict(project=name)
        cur.execute(
            "INSERT INTO project(name,client,building_type_id,plan_start,plan_deliver,status,prereq_json) "
            "VALUES(?,?,?,?,?,?,?)",
            (name, client, bt_id, t0, d["delivery_date"], status, prereq_json))
        pid = cur.lastrowid
        cur.execute(
            "INSERT INTO plan_version(project_id,version_no,plan_type,status) VALUES(?,1,'内控','基准')",
            (pid,))
        vid = cur.lastrowid
        con.commit(); cur.close(); con.close()
        n = eng.apply_to_project(pid, vid, "内控")
        # 回写交付日
        con = db(); cur = con.cursor()
        cur.execute("UPDATE project SET plan_deliver=? WHERE id=?", (d["delivery_date"], pid))
        con.commit(); cur.close(); con.close()
        return redirect(url_for("project_detail", pid=pid))
    return render_template("new_project.html", bts=bts, prereqs=prereqs, existing={})


# ---------------- 编辑项目 ----------------
@app.route("/project/<int:pid>/edit", methods=["GET", "POST"])
def edit_project(pid):
    p = load_project(pid)
    if not p:
        return "项目不存在", 404
    bts = building_types()
    prereqs = load_prereqs()
    existing = json.loads(p["prereq_json"]) if p["prereq_json"] else {}
    if request.method == "POST":
        con = db(); cur = con.cursor()
        name = request.form["name"].strip()
        client = request.form.get("client", "").strip()
        bt_id = int(request.form["building_type_id"])
        t0 = request.form["plan_start"]
        status = request.form.get("status", "进行中")
        prereq = {f"p{pr['id']}": request.form.get(f"p{pr['id']}") for pr in prereqs}
        prereq_json = json.dumps(prereq, ensure_ascii=False)
        old_t0 = p["plan_start"]
        old_prereq = p["prereq_json"]
        cur.execute(
            "UPDATE project SET name=?,client=?,building_type_id=?,plan_start=?,status=?,prereq_json=? WHERE id=?",
            (name, client, bt_id, t0, status, prereq_json, pid))
        # T0 或前置参数改变则重算交付日并重新生成该版本计划节点
        if t0 != old_t0 or prereq_json != old_prereq:
            eng = engine_for(t0, prereq_json, pid)
            d = eng.to_dict(project=name)
            cur.execute("UPDATE project SET plan_deliver=? WHERE id=?", (d["delivery_date"], pid))
            cur.execute("SELECT id FROM plan_version WHERE project_id=? AND plan_type='内控' ORDER BY id LIMIT 1", (pid,))
            vr = cur.fetchone(); vid = vr["id"] if vr else None
            if vid:
                cur.execute("DELETE FROM plan_node WHERE project_id=? AND version_id=?", (pid, vid))
                con.commit()
                eng.apply_to_project(pid, vid, "内控")
        con.commit(); cur.close(); con.close()
        return redirect(url_for("project_detail", pid=pid))
    return render_template("edit_project.html", p=p, bts=bts, prereqs=prereqs, existing=existing)


# ---------------- 项目详情 ----------------
@app.route("/project/<int:pid>")
def project_detail(pid):
    con = db(); cur = con.cursor()
    cur.execute("SELECT id,name,client,building_type_id,plan_start,plan_deliver,status,prereq_json FROM project WHERE id=?", (pid,))
    p = cur.fetchone()
    if not p:
        cur.close(); con.close(); return "项目不存在", 404
    cur.execute("SELECT id,name FROM building_type")
    bt = {r["id"]: r["name"] for r in cur.fetchall()}
    # 基准内控版本
    cur.execute("SELECT id FROM plan_version WHERE project_id=? AND plan_type='内控' ORDER BY id LIMIT 1", (pid,))
    vr = cur.fetchone(); vid = vr["id"] if vr else None
    # 计划节点（按 Excel 行序全量展示）
    cur.execute(
        "SELECT pn.id,pn.level,pn.seq,pn.name,pn.std_node_id,pn.finish_inner,pn.status,pr.name AS prof, sn.excel_row "
        "FROM plan_node pn LEFT JOIN profession pr ON pn.profession_id=pr.id "
        "LEFT JOIN std_node sn ON pn.std_node_id=sn.id "
        "WHERE pn.project_id=? AND pn.version_id=? ORDER BY sn.excel_row", (pid, vid))
    rows = cur.fetchall()
    cur.execute("SELECT DISTINCT std_node_id FROM std_node_rule")
    rule_ids = {r["std_node_id"] for r in cur.fetchall()}
    cur.execute("SELECT DISTINCT std_node_id FROM project_node_rule WHERE project_id=?", (pid,))
    rule_over = {r["std_node_id"] for r in cur.fetchall()}
    cur.execute("SELECT DISTINCT std_node_id FROM project_node_fixed WHERE project_id=?", (pid,))
    fixed_over = {r["std_node_id"] for r in cur.fetchall()}
    override_ids = rule_over | fixed_over
    cur.execute("SELECT id,excel_row,level,seq,name FROM std_node ORDER BY level,seq,excel_row")
    all_nodes = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) AS c FROM alert_record ar JOIN plan_node pn ON ar.plan_node_id=pn.id "
                "WHERE pn.project_id=?", (pid,))
    alert_count = cur.fetchone()["c"]
    cur.close(); con.close()
    rule_params = [pr for pr in load_prereqs() if pr["code"] in ("topfloor", "devloan", "delivery", "interior", "facade")]

    # 引擎：关键路径（标准库图 + 本项目 T0 + 本项目前置参数 + 本项目 override）
    eng = engine_for(p["plan_start"], p["prereq_json"], p["id"])
    d = eng.to_dict(project=p["name"])
    crit_ids = {c["id"] for c in d["critical_path"]}

    # 里程碑距今天数（m.date 为 ISO 字符串或 date 对象）
    for m in d["milestones"]:
        md = m["date"]
        m["days_from_today"] = ((md - TODAY).days if isinstance(md, datetime.date)
                                else (datetime.date.fromisoformat(md) - TODAY).days) if md else None

    for r in rows:
        r["critical"] = r["std_node_id"] in crit_ids
        fi = r["finish_inner"]
        r["days_from_today"] = ((fi - TODAY).days if isinstance(fi, datetime.date)
                                else (datetime.date.fromisoformat(fi) - TODAY).days) if fi else None
    return render_template("project_detail.html", p=p, building_type=bt.get(p["building_type_id"], "—"),
                           data=d, rows=rows, rule_ids=rule_ids, override_ids=override_ids,
                           rule_params=rule_params, all_nodes=all_nodes, alert_count=alert_count,
                           crit_miles=sum(1 for m in d["milestones"] if m["critical"]))


@app.route("/project/<int:pid>/critical-path.json")
def critical_path_json(pid):
    con = db(); cur = con.cursor()
    cur.execute("SELECT id,name,plan_start,prereq_json FROM project WHERE id=?", (pid,))
    p = cur.fetchone(); cur.close(); con.close()
    if not p:
        return jsonify(error="not found"), 404
    eng = engine_for(p["plan_start"], p["prereq_json"], p["id"])
    return jsonify(eng.to_dict(project=p["name"]))


# ---------------- 标准节点库（可编辑，体现"规则数据化"） ----------------
@app.route("/std-nodes")
def std_nodes():
    con = db(); cur = con.cursor()
    cur.execute("SELECT id,excel_row,level,seq,name,profession_id,tmpl_finish_formula,depend_row,offset_days,base_is_t0 FROM std_node ORDER BY excel_row")
    nodes = cur.fetchall()
    cur.execute("SELECT id,name FROM profession")
    prof = {r["id"]: r["name"] for r in cur.fetchall()}
    cur.execute("SELECT id,excel_row,level,seq,name FROM std_node")
    node_meta = {r["id"]: r for r in cur.fetchall()}
    cur.execute("SELECT std_node_id,depend_row,offset_days,base_is_t0,direction,depend_std_node_id FROM std_node_dependency")
    deps = {(r["std_node_id"]): r for r in cur.fetchall()}
    cur.execute("SELECT DISTINCT std_node_id FROM std_node_rule")
    rule_ids = {r["std_node_id"] for r in cur.fetchall()}
    cur.close(); con.close()
    for n in nodes:
        n["prof"] = prof.get(n["profession_id"], "—")
        dp = deps.get(n["id"])
        if dp:
            if dp["base_is_t0"]:
                n["dep_desc"] = "T0基准" + (f" +{dp['offset_days']}天" if dp["offset_days"] else "")
            else:
                dn = node_meta.get(dp["depend_std_node_id"])
                dname = dn["name"] if dn else f"L{dp['depend_row']}"
                n["dep_desc"] = (f"依赖 {dname}(L{dp['depend_row']}) "
                                 f"{dp['direction']} {abs(dp['offset_days'])}天")
        else:
            n["dep_desc"] = "—"
        if n["id"] in rule_ids:
            n["dep_desc"] += " · 含参数化分支"
    return render_template("std_nodes.html", nodes=nodes, rule_ids=rule_ids, total=len(nodes))


@app.route("/std-node/<int:nid>/edit", methods=["GET", "POST"])
def edit_std_node(nid):
    con = db(); cur = con.cursor()
    if request.method == "POST":
        depend_row = request.form.get("depend_row") or None
        offset_days = int(request.form["offset_days"])
        direction = request.form.get("direction", "之后")
        base_is_t0 = 1 if request.form.get("base_is_t0") == "1" else 0
        # 主责专业：表单提交才更新，未提交（None/空）保持原值，避免误清空
        prof_raw = request.form.get("profession_id")
        profession_id = int(prof_raw) if prof_raw not in (None, "") else None
        off = offset_days if direction == "之后" else -offset_days
        # 解析 depend_row -> 真实依赖节点 id（引擎依赖 depend_std_node_id 做遍历）
        depend_std_node_id = None
        if depend_row and not base_is_t0:
            cur.execute("SELECT id FROM std_node WHERE excel_row=?", (int(depend_row),))
            r = cur.fetchone()
            depend_std_node_id = r["id"] if r else None
        # upsert 依赖
        cur.execute("SELECT id FROM std_node_dependency WHERE std_node_id=?", (nid,))
        exist = cur.fetchone()
        if exist:
            cur.execute(
                "UPDATE std_node_dependency SET depend_row=?,offset_days=?,direction=?,base_is_t0=?,depend_std_node_id=? "
                "WHERE std_node_id=?", (depend_row, off, direction, base_is_t0, depend_std_node_id, nid))
        else:
            cur.execute(
                "INSERT INTO std_node_dependency(std_node_id,depend_std_node_id,depend_row,offset_days,direction,base_is_t0) "
                "VALUES(?,?,?,?,?,?)", (nid, depend_std_node_id, depend_row, off, direction, base_is_t0))
        # 同步 tmpl_finish_formula 文本（仅展示用）
        formula = "T0" if base_is_t0 else (f"=L{depend_row}{('+' if off>=0 else '')}{off}" if depend_row else None)
        if profession_id is not None:
            cur.execute("UPDATE std_node SET depend_row=?,offset_days=?,base_is_t0=?,tmpl_finish_formula=?,profession_id=? WHERE id=?",
                        (depend_row, off, base_is_t0, formula, profession_id, nid))
        else:
            cur.execute("UPDATE std_node SET depend_row=?,offset_days=?,base_is_t0=?,tmpl_finish_formula=? WHERE id=?",
                        (depend_row, off, base_is_t0, formula, nid))
        con.commit(); cur.close(); con.close()
        return redirect(url_for("std_nodes"))
    cur.execute("SELECT id,level,seq,name,profession_id,tmpl_finish_formula,depend_row,offset_days,base_is_t0 FROM std_node WHERE id=?", (nid,))
    node = cur.fetchone()
    cur.execute("SELECT std_node_id,depend_row,offset_days,base_is_t0,direction FROM std_node_dependency WHERE std_node_id=?", (nid,))
    dep = cur.fetchone()
    cur.execute("SELECT id,name FROM profession")
    profs = cur.fetchall()
    # 全部标准节点（供依赖下拉选择，按名称而非行号）
    cur.execute("SELECT id,excel_row,level,seq,name FROM std_node ORDER BY level,seq,excel_row")
    all_nodes = cur.fetchall()
    cur.execute("SELECT 1 FROM std_node_rule WHERE std_node_id=? LIMIT 1", (nid,))
    has_rule = bool(cur.fetchone())
    cur.close(); con.close()
    return render_template("edit_std_node.html", node=node, dep=dep, profs=profs, all_nodes=all_nodes, has_rule=has_rule)


# ---------------- 编辑参数化分支规则（IF/AND 条件，扁平分支卡片） ----------------
@app.route("/std-node/<int:nid>/rules", methods=["GET", "POST"])
def edit_std_node_rules(nid):
    con = db(); cur = con.cursor()
    cur.execute("SELECT id,excel_row,level,seq,name FROM std_node WHERE id=?", (nid,))
    node = cur.fetchone()
    if not node:
        cur.close(); con.close(); return "节点不存在", 404
    cur.execute("SELECT id,excel_row,level,seq,name FROM std_node ORDER BY level,seq,excel_row")
    all_nodes = cur.fetchall()
    # 规则相关参数（仅 B8~B12 五个），带 opts
    prereqs = load_prereqs()
    rule_params = [pr for pr in prereqs if pr["code"] in ("topfloor", "devloan", "delivery", "interior", "facade")]
    # 现有分支
    cur.execute("""SELECT branch_order,is_default,conditions_json,depend_row,offset_expr,direction
                   FROM std_node_rule WHERE std_node_id=? ORDER BY branch_order""", (nid,))
    rules = []
    for r in cur.fetchall():
        try:
            conds = json.loads(r["conditions_json"]) if r["conditions_json"] else []
        except Exception:
            conds = []
        oe = r["offset_expr"] or ""
        if oe.lstrip("-").isdigit():
            val = int(oe)
            rules.append(dict(conditions=conds, depend_row=r["depend_row"],
                              offset_days=abs(val), direction=("之后" if val >= 0 else "之前"),
                              advanced="", is_default=bool(r["is_default"])))
        else:
            rules.append(dict(conditions=conds, depend_row=r["depend_row"],
                              offset_days=0, direction=r["direction"] or "之后",
                              advanced=oe, is_default=bool(r["is_default"])))
    cur.close(); con.close()

    if request.method == "POST":
        raw = request.form.get("rules_json", "[]")
        try:
            branches = json.loads(raw)
        except Exception:
            branches = []
        clean = []
        for b in branches:
            if not isinstance(b, dict):
                continue
            conds = []
            for cd in b.get("conditions", []):
                if not isinstance(cd, dict):
                    continue
                p = cd.get("param"); op = cd.get("op"); v = cd.get("value")
                if not p or op not in ("<=", ">=", ">", "<", "=", "<>"):
                    continue
                if v in (None, ""):
                    continue
                if p == "topfloor":
                    try:
                        v = int(v)
                    except Exception:
                        pass
                conds.append({"param": p, "op": op, "value": v})
            is_default = bool(b.get("is_default"))
            depend_row = b.get("depend_row") or None
            adv = (b.get("offset_expr") or "").strip()
            if adv:
                offset_expr = adv
            else:
                days = int(b.get("offset_days") or 0)
                direction = b.get("direction") or "之后"
                offset_expr = str(days) if direction == "之后" else str(-days)
            clean.append(dict(conditions=conds if not is_default else [], depend_row=depend_row,
                              offset_expr=offset_expr, direction=b.get("direction") or "之后",
                              is_default=is_default))
        before = rules_snapshot("标准库", nid)
        con = db(); cur = con.cursor()
        cur.execute("DELETE FROM std_node_rule WHERE std_node_id=?", (nid,))
        for i, b in enumerate(clean):
            cur.execute(
                "INSERT INTO std_node_rule(std_node_id,branch_order,is_default,conditions_json,depend_row,offset_expr,direction,base_is_t0) "
                "VALUES(?,?,?,?,?,?,?,0)",
                (nid, i + 1, 1 if b["is_default"] else 0,
                 json.dumps(b["conditions"], ensure_ascii=False), b["depend_row"], b["offset_expr"], b["direction"]))
        cur.execute("UPDATE std_node SET has_condition=1 WHERE id=?", (nid,))
        # 同步 std_node 的默认依赖展示（非参数化回退用）：取默认分支或首个分支
        default_b = next((b for b in clean if b["is_default"]), None) or (clean[0] if clean else None)
        if default_b:
            off = int(default_b["offset_expr"]) if default_b["offset_expr"].lstrip("-").isdigit() else 0
            cur.execute("UPDATE std_node SET depend_row=?,offset_days=?,base_is_t0=0 WHERE id=?",
                        (default_b["depend_row"], off, nid))
        con.commit(); cur.close(); con.close()
        log_rule_change("标准库", nid, None, "更新规则", before, clean_to_front(clean))
        return redirect(url_for("std_nodes"))

    con = db(); cur = con.cursor()
    cur.execute("SELECT id,action,operator,created_at FROM rule_change_log "
                "WHERE scope='标准库' AND std_node_id=? ORDER BY id DESC LIMIT 20", (nid,))
    logs = [dict(r) for r in cur.fetchall()]; cur.close(); con.close()
    return render_template("edit_std_node_rules.html", node=node, rules=rules,
                           all_nodes=all_nodes, rule_params=rule_params, logs=logs)


# ---------------- 项目级规则：分支清洗（与标准库共用） ----------------
def sanitize_branches(branches):
    clean = []
    for b in branches:
        if not isinstance(b, dict):
            continue
        conds = []
        for cd in b.get("conditions", []):
            if not isinstance(cd, dict):
                continue
            p = cd.get("param"); op = cd.get("op"); v = cd.get("value")
            if not p or op not in ("<=", ">=", ">", "<", "=", "<>"):
                continue
            if v in (None, ""):
                continue
            if p == "topfloor":
                try:
                    v = int(v)
                except Exception:
                    pass
            conds.append({"param": p, "op": op, "value": v})
        is_default = bool(b.get("is_default"))
        depend_row = b.get("depend_row") or None
        adv = (b.get("offset_expr") or "").strip()
        if adv:
            offset_expr = adv
        else:
            days = int(b.get("offset_days") or 0)
            direction = b.get("direction") or "之后"
            offset_expr = str(days) if direction == "之后" else str(-days)
        clean.append(dict(conditions=conds if not is_default else [], depend_row=depend_row,
                          offset_expr=offset_expr, direction=b.get("direction") or "之后",
                          is_default=is_default))
    return clean


def to_front(rs):
    """将 DB 行集（std_node_rule / project_node_rule）转前端分支列表。"""
    out = []
    for r in rs:
        conds = json.loads(r["conditions_json"]) if r["conditions_json"] else []
        oe = r["offset_expr"] or ""
        if oe.lstrip("-").isdigit():
            val = int(oe)
            out.append(dict(conditions=conds, depend_row=r["depend_row"], offset_days=abs(val),
                            direction=("之后" if val >= 0 else "之前"), advanced="", is_default=bool(r["is_default"])))
        else:
            out.append(dict(conditions=conds, depend_row=r["depend_row"], offset_days=0,
                            direction=r["direction"] or "之后", advanced=oe, is_default=bool(r["is_default"])))
    return out


def baseline_vid(pid):
    con = db(); cur = con.cursor()
    cur.execute("SELECT id FROM plan_version WHERE project_id=? AND plan_type='内控' ORDER BY id LIMIT 1", (pid,))
    r = cur.fetchone(); cur.close(); con.close()
    return r["id"] if r else None


def recompute_project_finish(pid, vid, t0, prereq_json):
    """按当前（含项目级 override 的）引擎重算该版本所有节点的 finish_inner（保留 actual 等填报），并回写交付日。"""
    if vid is None:
        return
    eng = engine_for(t0, prereq_json, pid)
    off = eng.compute_offsets()
    con = db(); cur = con.cursor()
    for nid, o in off.items():
        fin = (eng.t0 + datetime.timedelta(days=o)).isoformat() if o is not None else None
        cur.execute("UPDATE plan_node SET finish_inner=? WHERE project_id=? AND version_id=? AND std_node_id=?",
                    (fin, pid, vid, nid))
    d = eng.to_dict(project="")
    cur.execute("UPDATE project SET plan_deliver=? WHERE id=?", (d["delivery_date"], pid))
    con.commit(); cur.close(); con.close()


def log_rule_change(scope, std_node_id, project_id, action, before=None, after=None, operator="代建运营部"):
    """记录标准库 / 项目级规则与固定日期的变更留痕。"""
    con = db(); cur = con.cursor()
    cur.execute(
        "INSERT INTO rule_change_log(scope,std_node_id,project_id,action,before_json,after_json,operator) "
        "VALUES(?,?,?,?,?,?,?)",
        (scope, std_node_id, project_id, action,
         json.dumps(before, ensure_ascii=False) if before is not None else None,
         json.dumps(after, ensure_ascii=False) if after is not None else None, operator))
    con.commit(); cur.close(); con.close()


def rules_snapshot(scope, std_node_id, project_id=None):
    """读取某节点当前生效规则（前端友好格式），用于变更日志 before。"""
    con = db(); cur = con.cursor()
    if scope == "标准库":
        cur.execute("""SELECT branch_order,is_default,conditions_json,depend_row,offset_expr,direction
                       FROM std_node_rule WHERE std_node_id=? ORDER BY branch_order""", (std_node_id,))
    else:
        cur.execute("""SELECT branch_order,is_default,conditions_json,depend_row,offset_expr,direction
                       FROM project_node_rule WHERE project_id=? AND std_node_id=? ORDER BY branch_order""",
                    (project_id, std_node_id))
    rows = cur.fetchall(); cur.close(); con.close()
    return to_front(rows)


def clean_to_front(clean):
    """将 sanitize 后的 clean 分支列表转前端友好格式（供日志 after）。"""
    out = []
    for b in clean:
        oe = b.get("offset_expr") or ""
        if oe.lstrip("-").isdigit():
            val = int(oe)
            out.append(dict(conditions=b.get("conditions", []), depend_row=b.get("depend_row"),
                            offset_days=abs(val), direction="之后" if val >= 0 else "之前",
                            advanced="", is_default=bool(b.get("is_default"))))
        else:
            out.append(dict(conditions=b.get("conditions", []), depend_row=b.get("depend_row"),
                            offset_days=0, direction=b.get("direction") or "之后",
                            advanced=oe, is_default=bool(b.get("is_default"))))
    return out


# ---------------- 项目级编辑节点（弹窗交互）：继承 / 固定日期 / 修改规则 ----------------
@app.route("/project/<int:pid>/node/<int:nid>/edit", methods=["GET", "POST"])
def edit_project_node(pid, nid):
    con = db(); cur = con.cursor()
    cur.execute("SELECT id,excel_row,level,seq,name FROM std_node WHERE id=?", (nid,))
    node = cur.fetchone()
    if not node:
        cur.close(); con.close(); return jsonify(error="node not found"), 404
    cur.execute("SELECT id,name,plan_start,prereq_json FROM project WHERE id=?", (pid,))
    proj = cur.fetchone()
    if not proj:
        cur.close(); con.close(); return jsonify(error="project not found"), 404
    cur.execute("SELECT fixed_date FROM project_node_fixed WHERE project_id=? AND std_node_id=?", (pid, nid))
    fr = cur.fetchone()
    cur.execute("SELECT branch_order,is_default,conditions_json,depend_row,offset_expr,direction "
                "FROM project_node_rule WHERE project_id=? AND std_node_id=? ORDER BY branch_order", (pid, nid))
    prr = cur.fetchall()
    cur.execute("SELECT 1 FROM std_node_rule WHERE std_node_id=? LIMIT 1", (nid,))
    has_rule = bool(cur.fetchone())
    cur.execute("SELECT finish_inner FROM plan_node WHERE project_id=? AND std_node_id=? ORDER BY id DESC LIMIT 1", (pid, nid))
    fin = cur.fetchone()
    con.close()

    if fr:
        mode = "fixed"; fixed_date = fr["fixed_date"]; rules = []
    elif prr:
        mode = "rule"; fixed_date = None; rules = to_front(prr)
    else:
        mode = "inherit"; fixed_date = None
        if has_rule:
            con = db(); cur = con.cursor()
            cur.execute("SELECT branch_order,is_default,conditions_json,depend_row,offset_expr,direction "
                        "FROM std_node_rule WHERE std_node_id=? ORDER BY branch_order", (nid,))
            rules = to_front(cur.fetchall()); con.close()
        else:
            # 普通节点（无参数化分支）：用标准库默认依赖构造单条默认分支，供"修改规则"初始化
            con = db(); cur = con.cursor()
            cur.execute("SELECT depend_row,offset_days FROM std_node WHERE id=?", (nid,))
            dn = cur.fetchone(); con.close()
            if dn and dn["depend_row"] is not None:
                off = int(dn["offset_days"] or 0)
                rules = [dict(conditions=[], depend_row=dn["depend_row"], offset_days=abs(off),
                              direction="之后" if off >= 0 else "之前", offset_expr="", is_default=True)]
            else:
                rules = [dict(conditions=[], depend_row=None, offset_days=0, direction="之后", offset_expr="", is_default=True)]

    if request.method == "POST":
        m = request.form.get("mode", "inherit")
        # 变更前快照（用于日志 before）
        if fr:
            before = {"fixed_date": fr["fixed_date"]}
        elif prr:
            before = to_front(prr)
        else:
            before = rules_snapshot("标准库", nid) if has_rule else {"depend_row": (rules[0]["depend_row"] if rules else None)}
        vid = baseline_vid(pid)
        con = db(); cur = con.cursor()
        if m == "inherit":
            cur.execute("DELETE FROM project_node_rule WHERE project_id=? AND std_node_id=?", (pid, nid))
            cur.execute("DELETE FROM project_node_fixed WHERE project_id=? AND std_node_id=?", (pid, nid))
            log_rule_change("项目", nid, pid, "恢复继承", before, None)
        elif m == "fixed":
            fixed_date = (request.form.get("fixed_date") or "").strip()
            try:
                datetime.date.fromisoformat(fixed_date)
            except Exception:
                con.close(); return jsonify(ok=False, msg="请填写合法的固定日期"), 400
            cur.execute("DELETE FROM project_node_rule WHERE project_id=? AND std_node_id=?", (pid, nid))
            cur.execute("DELETE FROM project_node_fixed WHERE project_id=? AND std_node_id=?", (pid, nid))
            cur.execute("INSERT INTO project_node_fixed(project_id,std_node_id,fixed_date) VALUES(?,?,?)",
                        (pid, nid, fixed_date))
            log_rule_change("项目", nid, pid, "固定日期", before, {"fixed_date": fixed_date})
        elif m == "rule":
            try:
                branches = json.loads(request.form.get("rules_json", "[]"))
            except Exception:
                branches = []
            clean = sanitize_branches(branches)
            cur.execute("DELETE FROM project_node_fixed WHERE project_id=? AND std_node_id=?", (pid, nid))
            cur.execute("DELETE FROM project_node_rule WHERE project_id=? AND std_node_id=?", (pid, nid))
            for i, b in enumerate(clean):
                cur.execute(
                    "INSERT INTO project_node_rule(project_id,std_node_id,branch_order,is_default,conditions_json,depend_row,offset_expr,direction,base_is_t0) "
                    "VALUES(?,?,?,?,?,?,?,?,0)",
                    (pid, nid, i + 1, 1 if b["is_default"] else 0,
                     json.dumps(b["conditions"], ensure_ascii=False), b["depend_row"], b["offset_expr"], b["direction"]))
            log_rule_change("项目", nid, pid, "更新规则", before, clean_to_front(clean))
        else:
            con.close(); return jsonify(ok=False, msg="未知模式"), 400
        con.commit(); con.close()
        con = db(); cur = con.cursor()
        cur.execute("SELECT plan_start,prereq_json FROM project WHERE id=?", (pid,))
        pj = cur.fetchone(); con.close()
        recompute_project_finish(pid, vid, pj["plan_start"], pj["prereq_json"])
        return jsonify(ok=True, mode=m)

    con = db(); cur = con.cursor()
    cur.execute("SELECT id,action,operator,created_at FROM rule_change_log "
                "WHERE scope='项目' AND project_id=? AND std_node_id=? ORDER BY id DESC LIMIT 20", (pid, nid))
    logs = [dict(r) for r in cur.fetchall()]; cur.close(); con.close()
    return jsonify(dict(nid=nid, name=node["name"], level=node["level"], seq=node["seq"],
                        has_rule=has_rule, current_mode=mode, fixed_date=fixed_date,
                        current_date=fin["finish_inner"] if fin else None, rules=rules, logs=logs))


# ---------------- 预警引擎 ----------------
LEVELS = ["里程碑", "一级", "二级", "二级*"]
PLAN_TYPES = ["内控", "考核", "履约"]


@app.route("/alert-rules")
def alert_rules():
    con = db(); cur = con.cursor()
    cur.execute("SELECT id,level,plan_type,threshold_days,notify_target FROM alert_rule ORDER BY plan_type,level")
    rules = [dict(r) for r in cur.fetchall()]
    cur.close(); con.close()
    return render_template("alert_rules.html", rules=rules, levels=LEVELS, plan_types=PLAN_TYPES)


@app.route("/alert-rule/new", methods=["GET", "POST"])
@app.route("/alert-rule/<int:rid>/edit", methods=["GET", "POST"])
def alert_rule_edit(rid=None):
    con = db(); cur = con.cursor()
    if request.method == "POST":
        level = request.form["level"]
        plan_type = request.form["plan_type"]
        threshold_days = int(request.form["threshold_days"])
        notify_target = (request.form.get("notify_target") or "").strip()
        if rid:
            cur.execute(
                "UPDATE alert_rule SET level=?,plan_type=?,threshold_days=?,notify_target=? WHERE id=?",
                (level, plan_type, threshold_days, notify_target, rid))
        else:
            cur.execute(
                "INSERT INTO alert_rule(level,plan_type,threshold_days,notify_target) VALUES(?,?,?,?)",
                (level, plan_type, threshold_days, notify_target))
        con.commit(); cur.close(); con.close()
        return redirect(url_for("alert_rules"))
    rule = None
    if rid:
        cur.execute("SELECT id,level,plan_type,threshold_days,notify_target FROM alert_rule WHERE id=?", (rid,))
        rule = cur.fetchone()
    cur.close(); con.close()
    return render_template("alert_rule_form.html", rule=rule, levels=LEVELS, plan_types=PLAN_TYPES)


@app.route("/alert-rule/<int:rid>/delete", methods=["POST"])
def alert_rule_delete(rid):
    con = db(); cur = con.cursor()
    cur.execute("DELETE FROM alert_record WHERE alert_rule_id=?", (rid,))
    cur.execute("DELETE FROM alert_rule WHERE id=?", (rid,))
    con.commit(); cur.close(); con.close()
    return redirect(url_for("alert_rules"))


@app.route("/project/<int:pid>/compute-alerts", methods=["POST"])
def project_compute_alerts(pid):
    plan_type = request.form.get("plan_type", "内控")
    compute_alerts(pid, plan_type, as_of=TODAY)
    return redirect(url_for("project_alerts", pid=pid))


@app.route("/project/<int:pid>/alerts")
def project_alerts(pid):
    con = db(); cur = con.cursor()
    cur.execute("SELECT id,name FROM project WHERE id=?", (pid,))
    p = cur.fetchone()
    if not p:
        cur.close(); con.close(); return "项目不存在", 404
    cur.execute(
        "SELECT ar.id,ar.plan_node_id,ar.triggered_at,ar.delay_days,ar.message,pn.level,pn.name AS node_name,"
        "pn.status AS node_status,pn.finish_inner "
        "FROM alert_record ar JOIN plan_node pn ON ar.plan_node_id=pn.id "
        "WHERE pn.project_id=? ORDER BY ar.delay_days DESC", (pid,))
    records = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) AS c FROM plan_node WHERE project_id=? AND status<>'正常'", (pid,))
    flagged = cur.fetchone()["c"]
    cur.close(); con.close()
    return render_template("project_alerts.html", p=p, records=records, flagged=flagged,
                           plan_types=PLAN_TYPES, today=TODAY)


@app.route("/alerts")
def alert_center():
    con = db(); cur = con.cursor()
    cur.execute("SELECT id FROM project ORDER BY id")
    pids = [r["id"] for r in cur.fetchall()]
    for pid in pids:
        compute_alerts(pid, "内控", as_of=TODAY)
    cur.execute(
        "SELECT ar.id,ar.plan_node_id,ar.delay_days,ar.message,ar.triggered_at,pn.level,pn.name AS node_name,"
        "pn.status AS node_status,pr.name AS project_name,pr.id AS project_id "
        "FROM alert_record ar JOIN plan_node pn ON ar.plan_node_id=pn.id "
        "JOIN project pr ON pn.project_id=pr.id ORDER BY ar.delay_days DESC")
    records = [dict(r) for r in cur.fetchall()]
    cur.close(); con.close()
    return render_template("alert_center.html", records=records, total=len(records),
                           plan_types=PLAN_TYPES, today=TODAY)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # 注意：公网/预览环境务必 debug=False，避免 Werkzeug 调试器远程代码执行风险
    app.run(host="0.0.0.0", port=port, debug=False)
