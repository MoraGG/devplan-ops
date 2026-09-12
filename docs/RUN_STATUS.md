# 房地产开发运营计划系统 · 运行与修复记录

> 状态：**P0 已跑通（2026-09-11）；P1 预警引擎已实现（2026-09-12）**。系统在 x5-pro 沙箱内 Docker MySQL + Flask 上完整可运行。
> 浏览器访问：`http://192.168.2.132:5001`（沙箱主机名 tang-X5-Pro，即 x5-pro 本机）

## 一、运行架构
| 组件 | 说明 |
|---|---|
| Web 服务 | Flask `app.py`，绑定 `0.0.0.0:5001`（避开 5000 媒体服务） |
| 数据库 | Docker 容器 `devplan_mysql`（镜像 `mysql:8.0`，空密码，库名 `dev_plan`，发布 3306 至 `192.168.2.132`） |
| Python | venv `/home/tang/.workbuddy/binaries/python/envs/default`（Flask 3.1.3 + PyMySQL 1.2.0） |
| 代码目录 | `/home/tang/WorkBuddy/2026-09-11-23-13-23/app/` |

## 二、启动 / 停止
```bash
# 启动（需先确保 devplan_mysql 容器在跑）
docker start devplan_mysql 2>/dev/null
cd /home/tang/WorkBuddy/2026-09-11-23-13-23/app
DB_HOST=127.0.0.1 DB_PORT=3306 DB_USER=root DB_PASS= DB_NAME=dev_plan PORT=5001 \
  /home/tang/.workbuddy/binaries/python/envs/default/bin/python3 app.py

# 停止
for p in $(pgrep -f "app.py"); do [ "$p" != "$$" ] && kill "$p"; done
```

## 三、本轮修复清单（让系统从"跑不起来"到"跑通"）
1. **种子数据双重编码（致命）**：原 `docker exec ... mysql < seed.sql` 经 stdin 灌库时客户端未用 UTF-8，中文被双重编码成乱码。改为 `mysql --default-character-set=utf8mb4` 重新灌库后正常。
2. **3 个模板 Jinja 语法损坏（致命）**：`edit_std_node.html` / `edit_project.html` / `prereq_form.html` 中 `{% if X == Y %}selected{% endif %}` 被搅乱成 `%} %}selected{% endif if X="=Y" ...`。已逐个还原为正确 Jinja 语法。
3. **PyMySQL vs SQLite 类型不匹配（致命）**：原代码按 SQLite 语义假设日期是字符串，但 PyMySQL 把 DATE 列返回为 `datetime.date` 对象。`project_detail` 对 `finish_inner` 调 `fromisoformat` 报 "must be str"。已改为兼容 date/str。
4. **`critical_path_json` 查询缺列（致命）**：SELECT 只取 `name,plan_start` 却访问 `p["prereq_json"]`/`p["id"]` → KeyError。已补全 SELECT 字段。

> 注：`dbconn.py` 连接配置被你标记为敏感、未允许我查看/改写；实测其连接字符集工作正常，故未改动。应用层 `?`→`%s` 兼容游标由该文件提供，引擎/路由均正常。

## 四、已验证功能
- [x] 引擎：148 节点读取、拓扑递推偏移、CPM 关键路径、13 里程碑、参数化前置参数解析
- [x] 9 个路由全部 200（看板/新建/编辑项目/项目详情/关键路径API/标准节点库/编辑依赖/编辑规则/项目级继承）
- [x] POST 新建项目 → 建 `project` + `plan_version` + 套模板生成 148 个 `plan_node` + 回写交付日
- [x] 中文全链路无乱码

## 五、已知缺口（P1，按你之前定的优先级）
- **预警逻辑**：✅ 已实现（2026-09-12），见第七节。
- **三版计划**（考核版/履约版）：目前仅生成"内控"版，其余版本无生成逻辑。
- **实际进度填报**：`plan_node.actual_start`/`actual_finish` 等实际字段已有录入入口（预警引擎已按 `actual_finish` 判定），但尚无独立填报页面。
- **`std_node_rule` 种子为空**：参数化分支规则库无种子数据，引擎当前按标准依赖递推，未走规则分支。
- **JSON 中文转义**：`critical-path.json` 用 `jsonify` 默认 `ensure_ascii=True`，中文显示为 `\uXXXX`（功能正常，仅可读性差，建议改 `ensure_ascii=False`）。
- **部分节点偏移为空**：148 个 plan_node 中 102 个有 `finish_inner`，46 个为 NULL（依赖图未连到 T0 主线），预警计算会跳过这些节点。

## 六、数据库重建（如需重灌）
```bash
cd /home/tang/WorkBuddy/2026-09-11-23-13-23/project_learn/drive
docker exec -i devplan_mysql mysql -uroot -e "DROP DATABASE IF EXISTS dev_plan; CREATE DATABASE dev_plan DEFAULT CHARSET utf8mb4;"
{ echo "SET FOREIGN_KEY_CHECKS=0;"; cat 5YdA11oW1h9fxCmDn9c6P3.sql; } | docker exec -i devplan_mysql mysql -uroot --default-character-set=utf8mb4 dev_plan
docker exec -i devplan_mysql mysql -uroot --default-character-set=utf8mb4 dev_plan < Ol6qvexDn9DZHBbCWLx1VV.sql
```
（DDL 外键顺序交叉，必须用 `SET FOREIGN_KEY_CHECKS=0` 前缀，否则第 76 行报 "referenced table project" 而中断后续建表。）

## 七、预警引擎（2026-09-12 新增）

### 数据模型（既有表，本次接入代码）
- `alert_rule(level, plan_type, threshold_days, notify_target)`：按「节点层级 × 计划版本(内控/考核/履约)」设延期阈值。**启动时若表为空自动写入默认规则**：里程碑/一级 ≥14 天、二级/二级* ≥7 天（内控版）。
- `alert_record(plan_node_id, alert_rule_id, triggered_at, delay_days, message)`：预警触发记录。

### 引擎逻辑（`engine.py`）
- `compute_alerts(project_id, plan_type="内控", as_of=None)`：对项目该版本每个 `plan_node`，取计划完成日 `P`（考核→`finish_assess`，履约→`finish_perform`，均回退 `finish_inner`），参考日 `ref` = 有 `actual_finish` 则用实际完成日、否则用 `as_of`（业务当前日）；偏差 `dev=(ref−P).days ≥ threshold_days` 即命中，写 `alert_record` 并把节点 `status` 置「延期」（实报滞后/已逾期）或「预警」（临近）。重算前先清空该版本旧记录、重置状态，反映最新状态。
- `ensure_default_alert_rules()`：空表时灌默认规则。

### 新增路由（`app.py`）
| 路由 | 方法 | 作用 |
|---|---|---|
| `/alert-rules` | GET | 规则列表 |
| `/alert-rule/new`、`/alert-rule/<id>/edit` | GET/POST | 新增/编辑规则 |
| `/alert-rule/<id>/delete` | POST | 删除规则（连带其预警记录） |
| `/project/<pid>/compute-alerts` | POST | 触发该项目某版本预警计算 |
| `/project/<pid>/alerts` | GET | 项目级预警中心 |
| `/alerts` | GET | 全局预警中心（进入即按业务当前日重算所有项目内控版） |

### 新增模板 / 交互
- `alert_rules.html`、`alert_rule_form.html`、`project_alerts.html`、`alert_center.html`
- 导航新增「预警中心」；项目看板新增「预警项」KPI 与卡片预警徽标；项目详情新增「预警中心（N）」「重新计算预警」工具栏。
- `style.css` 补充 `.toolbar/.badge.b-alert/.lvtag.lv-*/.lnk/.btn-ghost/.warn-t` 等样式。

### 实测结论（已跑通）
- 默认 4 条规则自动写入；规则增/改/删 HTTP 全 302/200 正常。
- 给项目 1 的两个节点补 `actual_finish`（里程碑晚 19 天、二级晚 14 天）后：命中 **2 条预警**，`plan_node.status` 2 个置「延期」，项目页/全局页均正确渲染偏差与说明文案，中文零乱码，Flask 日志无异常。
- 说明：项目 1 仅开工 10 天时自然计算 **0 命中**（早期节点偏差未达 7/14 天阈值），属正确行为——阈值内不算逾期。

> 演示数据：项目 1 的 plan_node id=13（经营策划会）、id=7（精装设计单位选择及合同签订）已写入演示用 `actual_finish`。如需清空：`UPDATE plan_node SET actual_finish=NULL WHERE id IN (7,13);` 再重算即可。
