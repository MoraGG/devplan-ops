# -*- coding: utf-8 -*-
"""从 Excel「节点计划 (终稿)」L 列公式解析出参数化规则，写入 std_node_rule。

背景：L 列 29+ 条公式带 IF(前置信息!$B$x...) 条件分支，直接引用前置参数
（地上最高层数/开发贷/交付形式/户内改造/外立面）。这些分支决定"不同前置参数
→ 不同工期"。本脚本把每条公式扁平化为若干分支 (conditions -> 结果表达式)，
结构化存储，供引擎按项目 prereq_json 求值。

解析策略（针对本模板已知公式形态，非通用 Excel 解析器）：
  - IF(c,t,f) 递归展开；嵌套 IF 的结果也递归；
  - AND(a,b) 拆为多条 AND 条件；else 分支对条件取反（op 翻转）；
  - 结果表达式：提取依赖行 L{r} 与偏移项；含 (B8-2)*5 等参数项时保留为
    可求值表达式 offset_expr（变量名用 param code，如 topfloor）。
  - 结果为 "" 表示该参数组合下节点不排程（depend_row=None）。
"""
import os
import sys
import re
import json
import warnings

sys.path.insert(0, os.path.dirname(__file__))
from dbconn import get_conn

import openpyxl

EXCEL = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     "远建2026版三级计划（绿城基础含公式）.xlsx")

# 前置信息!$B$col -> param code
PARAM_COL = {8: "topfloor", 9: "devloan", 10: "delivery", 11: "interior", 12: "facade"}
NEG = {"<=": ">", ">=": "<", ">": "<=", "<": ">=", "=": "<>", "<>": "="}


def split_top(s):
    """按顶层逗号切分（忽略括号内逗号）。"""
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1; cur += ch
        elif ch == ")":
            depth -= 1; cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip() != "":
        parts.append(cur)
    return parts


def parse_condition(s):
    """单个条件表达式 -> 条件 dict 列表（AND 拆多条）。"""
    s = s.strip()
    m = re.match(r"^AND\((.*)\)$", s, re.I)
    if m:
        return [c for inner in split_top(m.group(1)) for c in parse_condition(inner)]
    m = re.match(r"^前置信息!\$B\$(\d+)\s*(<=|>=|<>|<|>|=)\s*\"?([^\")]*)\"?$", s)
    if not m:
        raise ValueError(f"无法解析条件: {s!r}")
    col, op, val = int(m.group(1)), m.group(2), m.group(3)
    if col not in PARAM_COL:
        raise ValueError(f"未映射的参数列 B${col}: {s!r}")
    val = int(val) if re.fullmatch(r"-?\d+", val) else val
    return [{"param": PARAM_COL[col], "op": op, "value": val}]


def negate(conds):
    return [dict(c, op=NEG[c["op"]]) for c in conds]


def parse_result(expr):
    """结果表达式 -> (depend_row, offset_expr) 或 (None, None) 表示空。"""
    expr = expr.strip()
    if expr == '""' or expr == "":
        return None, None
    expr = re.sub(r"'[^']*'!", "", expr)  # 去掉 '表名'! 前缀
    m = re.match(r"^L(\d+)(.*)$", expr)
    if not m:
        raise ValueError(f"结果表达式无 L 依赖: {expr!r}")
    row = int(m.group(1))
    rest = re.sub(r"前置信息!\$B\$8", "topfloor", m.group(2))
    # 拆出带符号的项（数值或参数括号项；括号项可带 *N 倍率，如 (topfloor-2)*5）
    terms = re.findall(r"[+-]?(?:\(\s*topfloor[^)]*\)(?:\*\d+)?|\d+(?:\*\d+)?)", rest)
    offset_expr = "".join(terms).lstrip("+")
    if offset_expr == "":
        offset_expr = "0"
    return row, offset_expr


def parse_if(s, conds, out):
    """递归展开 IF(c,t,f)。c 为 AND 条件列表。

    关键：对 AND 条件取反(进入 FALSE/else 分支)时，NOT(AND(a,b)) = OR(NOT a, NOT b)，
    应当展开为多条【独立】分支(OR)，而非把取反后的子条件合并进同一分支当 AND。
    否则像 =IF(B8<=4,...,IF(AND(B8>11,B8<27),...,else)) 的 else(B8<=11 或 B8>=27)
    会被错判为 B8<=11 且 B8>=27（矛盾），导致该区间节点永不排程。
    """
    assert s[:2].upper() == "IF"
    inner = s[2:].lstrip("(").rstrip(")")
    args = split_top(inner)
    if len(args) != 3:
        raise ValueError(f"IF 参数数异常: {s!r}")
    cond, t, f = (a.strip() for a in args)
    c = parse_condition(cond)            # 本分支(TRUE)需满足的 AND 条件
    parse_node(t, conds + c, out)
    neg = negate(c)                      # 取反后进入 FALSE 分支
    if len(neg) <= 1:
        parse_node(f, conds + neg, out)
    else:
        # AND 取反 = OR：每个取反子条件独立成一支
        for term in neg:
            parse_node(f, conds + [term], out)


def parse_node(s, conds, out):
    s = s.strip()
    if s[:2].upper() == "IF":
        parse_if(s, conds, out)
        return
    if s == '""' or s == "":
        out.append({"conditions": conds, "depend_row": None, "offset_expr": None})
        return
    row, off = parse_result(s)
    out.append({"conditions": conds, "depend_row": row, "offset_expr": off})


def parse_formula(formula):
    s = formula[1:] if formula.startswith("=") else formula
    s = s.strip()
    out = []
    parse_node(s, [], out)
    return out


def main():
    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(EXCEL, data_only=False)
    ws = wb["节点计划 (终稿)"]
    HDR = 3

    con = get_conn()
    cur = con.cursor()
    # 建表（按 DB 类型）
    import os as _os
    dbtype = _os.environ.get("DB_TYPE", "sqlite")
    if dbtype == "mysql":
        cur.execute("""CREATE TABLE IF NOT EXISTS std_node_rule (
            id INT AUTO_INCREMENT PRIMARY KEY, std_node_id INT NOT NULL,
            branch_order INT NOT NULL, is_default TINYINT DEFAULT 0,
            conditions_json TEXT, depend_row INT, offset_expr VARCHAR(255),
            direction VARCHAR(8), base_is_t0 TINYINT DEFAULT 0)""")
    else:
        cur.execute("""CREATE TABLE IF NOT EXISTS std_node_rule (
            id INTEGER PRIMARY KEY AUTOINCREMENT, std_node_id INTEGER NOT NULL,
            branch_order INTEGER NOT NULL, is_default INTEGER DEFAULT 0,
            conditions_json TEXT, depend_row INTEGER, offset_expr TEXT,
            direction TEXT, base_is_t0 INTEGER DEFAULT 0)""")
    cur.execute("DELETE FROM std_node_rule")
    con.commit()

    # excel_row -> id
    cur.execute("SELECT id, excel_row, name FROM std_node")
    row_to_id = {r["excel_row"]: r["id"] for r in cur.fetchall()}
    id_to_name = {r["id"]: r["name"] for r in cur.fetchall()}

    total_nodes = 0
    total_branches = 0
    skipped = []
    for r in range(HDR + 1, ws.max_row + 1):
        name = ws.cell(row=r, column=5).value
        formula = ws.cell(row=r, column=12).value
        if not isinstance(formula, str) or not formula.startswith("="):
            continue
        if "前置信息" not in formula:
            continue  # 非参数化，沿用 std_node_dependency 默认
        if r not in row_to_id:
            skipped.append((r, name, "excel_row 无对应节点"))
            continue
        nid = row_to_id[r]
        try:
            branches = parse_formula(formula)
        except Exception as e:
            skipped.append((r, name, f"解析失败: {e}"))
            continue
        # 标记默认分支（末支或条件为空）
        for i, b in enumerate(branches):
            is_default = 1 if (i == len(branches) - 1 and not b["conditions"]) else 0
            direction = None
            if b["offset_expr"] is not None:
                try:
                    v = eval(b["offset_expr"], {"__builtins__": {}}, {"topfloor": 18})
                    direction = "之后" if v >= 0 else "之前"
                except Exception:
                    direction = "之后"
            cur.execute(
                "INSERT INTO std_node_rule(std_node_id,branch_order,is_default,conditions_json,depend_row,offset_expr,direction,base_is_t0) "
                "VALUES(?,?,?,?,?,?,?,0)",
                (nid, i + 1, is_default, json.dumps(b["conditions"], ensure_ascii=False),
                 b["depend_row"], b["offset_expr"], direction))
            total_branches += 1
        total_nodes += 1
    con.commit()
    cur.close(); con.close()

    print(f"参数化节点数: {total_nodes}   分支总数: {total_branches}")
    if skipped:
        print("跳过/异常:")
        for s in skipped:
            print("  ", s)


if __name__ == "__main__":
    main()
