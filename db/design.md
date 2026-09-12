# 房地产开发运营计划系统 · 数据库设计说明

> 配套文件：`01_ddl.sql`（建表）、`02_seed.sql`（种子数据，由绿城2026版三级计划 Excel 实测生成）
> 适用范围：住宅类代建项目开发进度计划（MVP / P0）
> 引擎：MySQL 8.0（生产）/ SQLite（自包含预览，发布用）。连接统一走 `db/dbconn.py`，由 `DB_TYPE` 环境变量切换。

---

## 1. 总览

系统数据分两层：**标准层（模板）** 与 **项目层（实例）**。

- **标准层**：`std_node`（标准节点库）、`std_duration`（7 楼型标准期量）、`std_node_dependency`（节点依赖）、`profession`（职能线）、`building_type`（楼型）、`prereq_param`（前置信息参数）。→ 一次初始化，全员复用。
- **项目层**：`project`（项目）、`plan_version`（计划版本/三版）、`plan_node`（项目计划节点）、`alert_rule`/`alert_record`（预警）。→ 每个项目套模板生成。

---

## 2. 实体关系（ER）

```
profession 1──* std_node           building_type 1──* std_duration
prereq_param (参数定义)                  │
                                         └── std_node 1──* std_duration
std_node 1──* std_node_dependency ──* std_node  (自关联: 依赖节点)
project 1──* plan_version 1──* plan_node
std_node 1──* plan_node             profession 1──* plan_node
alert_rule ──* alert_record ──* plan_node
```

---

## 3. 表结构与字段

### 3.1 字典表

| 表 | 关键字段 | 说明 |
|---|---|---|
| `profession` | code, name | 职能线字典（发展/前期/设计/工程/精装修/景观/营销/成本/智能化/客研/客服/运营 + 复合主责） |
| `building_type` | code(BT18/BT4/BT6/BT8/BT11/BT27/BT33), name | 7 种楼型，标准期量维度 |
| `prereq_param` | code, name, options_json | 11 项前置信息参数及可选值 |

### 3.2 标准层

| 表 | 关键字段 | 说明 |
|---|---|---|
| `std_node` | excel_row, level(里程碑/一级/二级/二级*), seq, name, profession_id, deliverable(定义成果), support_doc(支持文件), duration, tmpl_finish_formula, depend_row, offset_days, base_is_t0, has_condition | 标准节点模板（148 条） |
| `std_duration` | std_node_id, building_type_id, std_desc | 某节点在某楼型下的标准期量（985 条） |
| `std_node_dependency` | std_node_id, depend_std_node_id, depend_row, offset_days, direction(之后/之前), base_is_t0, has_condition | 解析 Excel `=Lx±d` 公式所得依赖（141 条） |

### 3.3 项目层

| 表 | 关键字段 | 说明 |
|---|---|---|
| `project` | name, client(委托方), building_type_id, plan_start, plan_deliver, prereq_json(11参数值) | 项目主数据 |
| `plan_version` | project_id, version_no, plan_type(内控/考核/履约), status(草稿/基准), published_at | 三版计划 + 版本 |
| `plan_node` | project_id, version_id, std_node_id, level, seq, name, profession_id, start_inner, finish_inner, **finish_assess, finish_perform**, actual_start, actual_finish, progress_pct, status | 项目计划节点（套模板生成） |
| `alert_rule` | level, plan_type, threshold_days, notify_target | 预警规则（里程碑/一级≥14天，二级/二级*≥7天） |
| `alert_record` | plan_node_id, alert_rule_id, triggered_at, delay_days, message | 预警触发记录 |

---

## 4. Excel → 系统映射

| Excel（绿城2026版三级计划） | 系统 | 备注 |
|---|---|---|
| 类别=里程碑/一级/二级/三级 | level=里程碑/一级/二级/**二级\*** | 三级→二级*（已与用户确认） |
| A/B/C 序号列 | seq（层级内序号） | 二级* 序号为空，按行序 |
| 项目开发节点名称 | name | |
| 主责专业 | profession_id | 含复合主责 |
| 内控开始/完成（G/I） | start_inner/finish_inner | 内控版 |
| 考核版完成（J） | finish_assess | 考核版（P1 填） |
| 履约版完成（K） | finish_perform | 履约版（P1 填） |
| 计划模板工期完成时间（L，公式） | tmpl_finish_formula + 解析为 dependency | 相对工期引擎来源 |
| M~S（7 楼型期量） | std_duration | 标准工期库（**仅作参考展示，绝不参与工期计算**） |
| 定义/成果/支持文件（T/U） | deliverable/support_doc | |
| 前置信息表（11 项） | prereq_param + project.prereq_json | 期量选取依据 |

---

## 5. 相对工期引擎算法（MVP 复刻 Excel 公式）

> ⚠️ **计算唯一数据源（硬性边界）**：工期引擎**只读取 `std_node_dependency`（来自 Excel L 列公式）**，绝对不读取 M~S 列「集团标准期量描述」的文字。M~S 落入 `std_duration` 表，**仅用于参考展示与人工比对，不参与任何排程计算**。

Excel 中每个节点完成时间 = `依赖节点时间 ± 偏移天数`，公式为 `=L{行}±{天}`，如：
- `=L6+30` → 依赖第 6 行（T0 项目启动），之后 30 天
- `=L82-150` → 依赖第 82 行（样板区开放），**之前** 150 天

**系统实现步骤**：
1. 设项目基准日 `plan_start`（T0）。
2. 对每个节点，查 `std_node_dependency`：若 `base_is_t0=1` → 锚点=plan_start；否则锚点=依赖节点已算出的完成时间。
3. `完成时间 = 锚点 + offset_days`（offset 负=之前）。
4. 按依赖拓扑顺序递推（std_node_dependency 已构无环 DAG，可拓扑排序）。
5. 含 `has_condition=1` 的节点（如按地上层数选期量）在 MVP 先取主分支，P2 做参数化分支。

> `depend_row` 保留 Excel 行号便于追溯；`depend_std_node_id` 为解析后指向的依赖节点主键。

---

## 6. 三版计划与预警

- **三版**：`plan_version.plan_type ∈ {内控,考核,履约}`，同一项目可发三套版本；MVP 先填内控版，考核/履约版字段预留。
- **预警**：定时任务比对 `plan_node.finish_inner`（或对应版完成时间）与 `actual_finish`，偏差天数 ≥ `alert_rule.threshold_days` 则写 `alert_record` 并通知。默认里程碑/一级≥14 天、二级/二级*≥7 天。

---

## 7. 种子数据规模（来自 Excel 实测）

| 对象 | 数量 |
|---|---|
| 标准节点 std_node | 148（里程碑13 / 一级40 / 二级89 / 二级*6） |
| 职能线 profession | 17 |
| 楼型 building_type | 7 |
| 前置信息参数 prereq_param | 11 |
| 标准期量 std_duration | 985 |
| 节点依赖 std_node_dependency | 141（其中基于 T0 的 17） |

---

## 8. 相对工期规则的可配置与演进（应对"规则以后要调整"）

相对工期规则**不硬编码在代码里**，而是作为**数据**存放在标准层，因此"改规则"= 改数据/后台配置，无需发版。

| 机制 | 做法 |
|---|---|
| **规则数据化** | 每个节点的「依赖谁 + 偏移多少天 + 是否基于 T0」存在 `std_node_dependency`，引擎读数据计算。调整即改这张表。 |
| **标准库后台可编辑** | 运营部在「标准节点库」管理后台直接增删改节点、改依赖与偏移，保存即生效于后续新建项目。 |
| **参数化分支** | `has_condition=1` 的节点（如按地上层数选期量）升级为规则表：`rule_condition(参数, 运算符, 值) → offset`，由 `prereq_json` 驱动，不再写死 IF。 |
| **标准库版本化** | `std_node` / `std_node_dependency` 增加 `version_no` + `effective_from`，规则调整产生新版本；**已发布的项目计划（plan_node）不受影响**（项目层已快照）。 |
| **历史可追溯** | 每次标准库变更记录操作日志，可回滚到某版本。 |
| **与项目层解耦** | 新建项目时"套模板"把标准节点 + 依赖**复制到项目层 plan_node**；之后标准库再改，不影响已建项目，除非主动"重新套用/对比"。 |

> 调整流程示例：运营部发现"样板区开放"应提前 10 天 → 在后台把该节点 offset 由 -150 改为 -160 → 保存 → 新建项目自动生效；历史项目保持原值，需重算的可手动触发"重套模板"。

## 9. 相对工期引擎模块（已落地验证）

`db/engine.py` —— 真正的系统组件，**经 `dbconn` 读库计算**（默认 SQLite，设 `DB_TYPE=mysql` 切回生产 MySQL），非一次性脚本。

| 方法 | 职责 |
|---|---|
| `compute_offsets(t0)` | 拓扑递推每个节点「相对 T0 偏移天数」；T0 锚点（被 `base_is_t0` 依赖指向的节点）偏移=0。**仅用公式依赖**，不碰 `std_duration`。 |
| `critical_path()` | CPM：自交付节点沿单一依赖回溯主干，再在相邻主干节点间补入落在时间段内、且位于该依赖路径上的中间节点，得到完整关键路径。 |
| `to_dict()` | 输出结构化数据（KPI + 关键路径 + 13 里程碑 + 引擎说明），供前端渲染。 |
| `apply_to_project(project_id, version_id)` | 「套模板」：把 std_node + 依赖计算出的日期写入项目层 `plan_node`（148 行）。 |

**配套脚本**：
- `db/load_seed.py` —— 参数化直插标准库（避开字符串转义，推荐作为 `02_seed.sql` 的可执行替代）。
- `db/import_and_verify.py` —— 执行 DDL + 种子并校验计数（可重跑，先清空再建）。
- `db/gen_critical_path.py` —— 调 `engine.to_dict()` 生成 `../prototype/critical_path.html`，数据 100% 来自库。

**验证结果（MySQL 8.0 实测）**：std_node 148 / std_duration 985 / std_node_dependency 141；套模板写入 plan_node 148 行；示例项目关键路径 = 项目启动→正负零→主体封顶→交付，总工期 **14.8 个月**（2026-07-14 → 2027-10-01）。

## 10. 运行方式

```bash
# 1. 起库（Docker）
docker run -d --name devplan_mysql -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=devplan123 -e MYSQL_DATABASE=dev_plan mysql:8.0
# 2. 灌标准库（参数化直插，推荐）
python3.11 db/load_seed.py
# 3. 跑引擎 / 生成视图
python3.11 db/engine.py            # 打印关键路径
python3.11 db/gen_critical_path.py # 生成 prototype/critical_path.html
```

> 依赖：`pymysql`（`pip3 install pymysql`）。示例项目与版本为验证用样例数据。

## 11. Web 管理后台（Flask · MVP 已实现）

代码位于 `/workspace/app/`，可直接运行的管理后台，所有数据经 `dbconn` 读取（默认 SQLite 自包含，可切 MySQL），关键路径由 `engine.py` 实时计算。

| 路由 | 页面 | 说明 |
|---|---|---|
| `/` | 项目经营看板 | 多项目 KPI + 卡片列表（T0/交付/总工期/关键路径节点数/下一里程碑） |
| `/project/<id>` | 项目详情 | 关键路径 spine + 13 里程碑 + 四级节点(里程碑/一级/二级/二级*) + 距今天数 |
| `/project/new` | 新建项目 | 录入基础信息 → 自动套模板生成四级计划（调 `apply_to_project`） |
| `/project/<id>/critical-path.json` | 关键路径 API | 供前端/第三方复用 |
| `/std-nodes` | 标准节点库 | 148 节点按层级列出「依赖+偏移」即相对工期规则 |
| `/std-node/<id>/edit` | 编辑节点规则 | 改依赖/偏移即改规则；`depend_row → depend_std_node_id` 同步落库，引擎重算即生效 |

**运行**：`cd /workspace/app && python3.11 app.py` → http://127.0.0.1:5000（默认 SQLite 自包含；生产部署设 `DB_TYPE=mysql` 连自带 MySQL）
**演示数据**：`python3.11 app/seed_demo.py`（生成 3 个差异化 T0 的代建项目，已内置）。

## 12. 下一步

1. 预警定时任务：比对 `finish_*` 与 `actual_finish`，触发 `alert_record`（规则见需求文档 14/7 天阈值）。
2. 参数化期量（前置参数驱动工期）：**已实现**，见第 14 章。把 29 个 `has_condition` 节点解析为 `std_node_rule` 规则表，引擎按项目 `prereq_json` 求值选分支。
3. 标准库版本化落库（`version_no` + `effective_from` + 操作日志）。
4. 投资测算对接：P1 复用本项目计划节点数据（导出/接口）。

## 13. 自包含（SQLite）与公网预览发布

沙箱「发布为应用」通道**不支持外部服务依赖（MySQL/Redis 等）**，只接受单端口自包含应用。因此预览/演示版本采用 SQLite 自包含，生产部署仍用 MySQL。

- **连接层**：`db/dbconn.py` 统一 `get_conn()`。`DB_TYPE=sqlite`（默认）→ 读 `db/devplan.db`；`DB_TYPE=mysql` → 连 `127.0.0.1:3306/dev_plan`。两种模式返回游标均支持 `r["列"]` 字典式访问与赋值。
- **数据迁移**：`db/migrate_to_sqlite.py` 把现有 MySQL 全量迁到 `devplan.db`（表结构 + 数据，类型做 SQLite 兼容映射），重跑会重建该文件。
- **发布命令**（沙箱内执行，生成带访问控制的公网链接）：
  ```bash
  node <skill>/scripts/publish.js --dir /workspace --language python \
    --start-cmd "cd /workspace/app && python3.11 app.py" --port 5000
  ```
  `app.py` 读取 `PORT` 环境变量监听 `0.0.0.0`，且 `debug=False`（公网安全，避免 Werkzeug 调试器 RCE）。
- **生产部署**：自备服务器装 MySQL 8.0，设 `DB_TYPE=mysql` 并填 `dbconn.py` 的 `MYSQL` 连接信息，用 `gunicorn` 等 WSGI 服务器托管 `app.py` 即可，业务代码无需改动。

## 14. 参数化期量（前置参数驱动工期）✅ 已实现

**问题**：原 `std_node_dependency`（来自 Excel L 列 `=Lx±d`）只存了固定间隔，引擎对所有项目算出相同总工期（且当初提取公式时只取了首个数字，丢失了 `+N` 与 `*N` 项，导致 14.8 个月的错误结果）。实际上 Excel L 列有 **29 条公式带 `IF(前置信息!$B$x...)` 条件分支**，直接引用前置参数（地上最高层数/开发贷/交付形式/户内改造/外立面），不同参数应得出不同计划。

**数据真相**（已与 Excel 自身缓存计算值逐节点核对一致）：
- Excel L 列条件公式引用 `前置信息!$B$8~$B$12` → 映射 `prereq_param` id 7/8/9/10/11（topfloor/devloan/delivery/interior/facade）。其余 6 个前置参数在 L 列未被引用，维持"仅记录"。
- 例如 `L145 项目计划交付 = IF(B10="精装", IF(B8<=11, L100+14*30, L100+15*30), IF(B8<=11, L100+11*30, L100+12*30))`、`L100 主体结构封顶 = L98+10+12+(B8-2)*5`。绿城模板对默认参数（B8=16/精装）本身排程约 32 个月——旧版 14.8 月是提取 bug，非模板值。

**机制**：
- `db/extract_rules.py`：从 Excel「节点计划 (终稿)」L 列解析 29 条条件公式 → 扁平化为 68 个分支，写入 `std_node_rule(std_node_id, branch_order, is_default, conditions_json, depend_row, offset_expr, direction, base_is_t0)`。
  - 递归展开 `IF/AND/嵌套IF`；`else` 分支对条件取反（op 翻转）。
  - 结果表达式拆出依赖行 `L{r}` 与偏移项；含 `(B8-2)*5` 等参数项时保留为可求值表达式 `offset_expr`（变量名用 param code，如 `topfloor`）。
  - 结果为 `""` 表示该参数组合下节点不排程（`depend_row=NULL`）。
- 引擎 `RelativeDateEngine(t0, prereq_json)`：`_load` 载入 `std_node_rule`；`resolve(prereq_json)` 按项目前置参数逐节点选首条命中分支，把参数化节点解析为具体生效边（算术分支代入 `topfloor` 求值），覆盖 `self.deps`；`compute_offsets`/关键路径复用既有拓扑与 CPM 算法（顶点格式不变）。
- 应用层：`app.py` 在详情/看板/JSON/新建/编辑时把项目 `prereq_json` 传入引擎；编辑项目若改了 T0 **或前置参数**，自动重算交付日并重新生成计划节点。

**效果**：三个示例项目（18F精装 / 27F精装有贷 / 11F毛坯）总工期分别为 **32.4 / 33.9 / 27.2 个月**，且毛坯项目批量内装类节点按公式判为空（不排程）。`std_nodes` 页对已参数化节点标注"含参数化分支"，依赖显示节点名称而非行号。

**新增文件**：`db/extract_rules.py`（规则提取，可重跑）、`db/01_ddl.sql` 含 `std_node_rule`、演示数据 `app/seed_demo.py` 已内置差异化前置参数。
