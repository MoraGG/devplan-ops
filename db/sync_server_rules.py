# -*- coding: utf-8 -*-
"""服务器规则同步（外科式，不 DROP 任何表，保留 project/plan_node 等项目数据）。

背景：本次修复「专项验收早于室外管线」的逻辑倒挂，改了 4 处规则：
  - R116 人货梯拆除：主体封顶 +100 天（原按层数 150/170）
  - R122 配电专项验收：消防验收前 25 天（原前 40 天）→ 非参数化依赖边
  - R124 室外综合管线：外架拆除 +90 天（原 +120）        → 非参数化依赖边
  - R145 项目计划交付：新增"有无户内改造"判断，有改造 +60 天（4→8 分支）

Excel 是规则源头，已随本次提交推送到 GitHub。本脚本在服务器 `git pull` 后：
  1) 调 extract_rules.main() 重建 std_node_rule（DELETE+重插全部参数化节点规则，来自新 Excel）；
  2) 外科 UPDATE 两条非参数化依赖边 R122(-25) / R124(+90) 的 offset；
  3) 顺手把 std_node.tmpl_finish_formula 存档同步成新公式（引擎不直接读，仅一致性）。

注意：extract_rules 只重建 std_node_rule，不碰 std_node_dependency 里的非参数化边，
所以 R122/R124 必须在这里手动修正。切勿改用 load_seed.py——它会 DROP 全库、清空项目。

用法（服务器，DB_TYPE=mysql，依赖 .venv 内 openpyxl/pymysql）：
    cd /home/tang/devplan-ops
    git pull --ff-only origin main
    .venv/bin/python db/sync_server_rules.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import extract_rules  # 复用其 main()：从新 Excel 重建 std_node_rule
from dbconn import get_conn


def main():
    print(">> [1/2] 重建参数化规则 std_node_rule（取自更新后的 Excel）...")
    extract_rules.main()  # DELETE FROM std_node_rule 后按新 L 列公式重插

    print(">> [2/2] 外科修正非参数化依赖边 R122 / R124 ...")
    con = get_conn()
    cur = con.cursor()

    # R122 配电专项验收：相对 L133(消防验收) -25 天
    cur.execute(
        "UPDATE std_node_dependency SET offset_days=-25, direction='之前' "
        "WHERE std_node_id=(SELECT id FROM std_node WHERE excel_row=122) AND depend_row=133"
    )
    ra = cur.rowcount

    # R124 室外综合管线：相对 L112(外架拆除) +90 天
    cur.execute(
        "UPDATE std_node_dependency SET offset_days=90, direction='之后' "
        "WHERE std_node_id=(SELECT id FROM std_node WHERE excel_row=124) AND depend_row=112"
    )
    rb = cur.rowcount

    # R116 人货梯拆除：依赖边偏移同步为 +100（规则已覆盖，仅保一致）
    cur.execute(
        "UPDATE std_node_dependency SET offset_days=100, direction='之后' "
        "WHERE std_node_id=(SELECT id FROM std_node WHERE excel_row=116) AND depend_row=100"
    )
    rc = cur.rowcount

    # tmpl_finish_formula 存档同步（一致性，引擎不直接读）
    cur.execute(
        "UPDATE std_node SET tmpl_finish_formula=%s WHERE excel_row=116",
        ("=IF(前置信息!$B$8<8,'节点计划 (终稿)'!L100+100,'节点计划 (终稿)'!L100+100)",),
    )
    cur.execute("UPDATE std_node SET tmpl_finish_formula=%s WHERE excel_row=122", ("=L133-25",))
    cur.execute("UPDATE std_node SET tmpl_finish_formula=%s WHERE excel_row=124", ("=L112+90",))
    cur.execute(
        "UPDATE std_node SET tmpl_finish_formula=%s WHERE excel_row=145",
        ("=IF(前置信息!$B$10=\"精装\",IF(前置信息!$B$8<=11,IF(前置信息!$B$11=\"有\",'节点计划 (终稿)'!L100+14*30+60,'节点计划 (终稿)'!L100+14*30),IF(前置信息!$B$11=\"有\",'节点计划 (终稿)'!L100+15*30+60,'节点计划 (终稿)'!L100+15*30)),IF(前置信息!$B$8<=11,IF(前置信息!$B$11=\"有\",'节点计划 (终稿)'!L100+11*30+60,'节点计划 (终稿)'!L100+11*30),IF(前置信息!$B$11=\"有\",'节点计划 (终稿)'!L100+12*30+60,'节点计划 (终稿)'!L100+12*30)))",),
    )
    con.commit()
    cur.close()
    con.close()

    print(f"   依赖边更新：R122={ra} 行, R124={rb} 行, R116={rc} 行")
    print("完成。提示：已有项目的 plan_node 需通过应用「重新计算」按新规则刷新。")


if __name__ == "__main__":
    main()
