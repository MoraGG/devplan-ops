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
- **三版计划（考核版/履约版）**：✅ 已完成（2026-09-12 部署，见第八节）。内控/考核/履约三版由 `generate_version` 懒生成，`finish_inner` 作各版规范计划完成日；考核=内控+`buffer_kh` 天、履约=内控+`buffer_ly` 天（项目级期量裕度，默认 0）。
- **实际进度填报**：✅ 已完成（2026-09-12 部署，见第八节）。`/project/<pid>/fill` 逐节点填报 `actual_start/actual_finish/progress_pct`，同一事实同步写三版并刷新三版预警；`/project/<pid>/compare` 三版并排对比含 kh/ly/af 偏差高亮。
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

## 八、执行跟踪闭环（2026-09-12 部署）

> 状态：**已上线（192.168.2.132:5001）**。把"计划只生成不跟踪"补成闭环：① 实际进度逐节点填报 → ② 计划/实际偏差自动预警 → ③ 内控/考核/履约三版一键生成并同屏对比（代建管控特色交付物）。适用前提：单人使用、暂不启用审批流。

### 代码提交
| commit | 内容 |
|---|---|
| `027d603` | feat: 执行跟踪闭环（实际进度填报 + 三版计划生成/对比）。DDL 加 `project.buffer_kh/buffer_ly`；引擎 `apply_to_project` 写入 `finish_inner`、引擎 `compute_alerts` 统一取 `finish_inner`；app 新增 `generate_version/regenerate_all_versions/ensure_all_versions/save_actual/compare_rows`；新增路由 `/project/<pid>/fill`、`/project/<pid>/compare`；新增模板 `project_fill.html`、`project_compare.html`；`project_detail` 支持 `?v=` 版本切换 + 工具栏入口。 |
| `6b66826` | fix: 重生成版本前先删 `alert_record`，避免 MySQL 外键 1451（见下方"部署踩坑"）。 |
| `abff7b8` | chore: `.gitignore` 忽略中继脚本/补丁/SQLite 备份副本（含口令，禁止入库）。 |

### 部署链路（绕开 GitHub TLS）
本地 GitHub 直推可达；服务器 `192.168.2.132` 经 `git pull` GitHub 因 TLS 握手失败不可达，故采用中继：
1. 本地 `git format-patch -1 HEAD --stdout > _relay.mbox` → SFTP 上传至服务器 `/home/tang/devplan-ops/_relay.mbox`；
2. 服务器本地 `git -c user.name=devplan -c user.email=devplan@local am _relay.mbox`（不依赖 GitHub）；
3. 服务器 `.venv/bin/python3 db/init_buffer.py` 跑 MySQL 迁移（`buffer_kh/buffer_ly` 列，幂等）；
4. `systemctl --user restart devplan-ops.service` 重启，健康检查 `curl /` 返回 200。

> 注：服务器 `.venv` 路径带点（`/home/tang/devplan-ops/.venv`），系统 `python3` 缺 PyMySQL，迁移必须用 `.venv` 解释器；`git am` 需注入 committer 身份（否则报 identity unknown）。

### 部署踩坑（重要）
- **MySQL 外键 1451（仅 MySQL 复现，SQLite 不报错）**：`regenerate_all_versions` → `generate_version` 在 `DELETE FROM plan_node` 前未清理子表 `alert_record`（`alert_record.plan_node_id` 外键约束 `plan_node.id`），MySQL 严格 FK 直接报 `IntegrityError: (1451, Cannot delete or update a parent row)`。`6b66826` 修复为：删 plan_node 前先 `DELETE FROM alert_record WHERE plan_node_id IN (SELECT id FROM plan_node WHERE project_id=? AND version_id=?)`。本地 SQLite 默认关闭 FK 强制，故此前验证（py_compile + 副本库 10 项检查）未能暴露，必须在 MySQL 上回归。
- **三版一致性（buffer=0 时本应完全相等）**：旧项目（1/2/3）在创建时已生成"内控"版 plan_node（旧代码/旧 T0），闭环上线后 `ensure_all_versions` 只补"考核/履约"两版、不重算"内控"，导致 内控 max finish_inner（如 2029-08-29）≠ 考核/履约（2029-10-28）。已对所有项目执行 `regenerate_all_versions` 统一重生成，复测 内控=考核=履约、偏差非0节点数=0、每版 148 节点、alert_record 重新生成（14 条）。

### 已验证（线上 MySQL）
- [x] 新路由 GET：项目详情（默认内控 / `?v=考核` / `?v=履约`）、`/project/<pid>/compare`、`/project/<pid>/fill`、`/alerts` 全部 200，页面命中"内控/考核/履约/实际进度/三版对比/偏差/计划完成"关键字。
- [x] 3 个项目均存在 内控/考核/履约 三个 `plan_version`；每版 148 个 `plan_node`（`finish_inner` 145 个有值，3 个锚点节点为 NULL 符合预期）。
- [x] buffer=0 时三版 `finish_inner` 完全相等；`kh_diff/ly_diff` 全 0。
- [x] `alert_record` 在重生成后正确重建（14 条），预警链路贯通。

### 待办
- 服务器 `git am` 产生的提交哈希（如 `1b727f9`/`842a60b`）与 GitHub 主线（`027d603`/`6b66826`）内容等价但哈希不同；待服务器可直连 GitHub 时，在服务器执行 `git fetch origin && git reset --hard origin/main` 使三方哈希一致（功能已一致，仅历史哈希差异）。
- 如需把执行跟踪闭环打包为可复用技能/规范，见工作区 memory。

## 九、项目级固定日期失效 bug（2026-09-14 修复）

> 状态：**已修复并上线（192.168.2.132:5001）**。commit `8501f10`，对柳林项目 pid=4 已 `regenerate_all_versions(4)` 重算验证。

### 现象（用户报告）
柳林项目把"完成整体正负零施工"（std_node_id=95，excel_row=98）改为固定日期 `2027-04-30` 后：
- 该节点三版 `plan_node.finish_inner` 全为 `NULL`；
- 下游依赖节点（depend_row=98）`std_node_id=96`（主体达到 1/2 层高）、`97`（主体结构封顶）三版 `finish_inner` 也全为 `NULL`。
- `project_node_fixed` 落库正确（`fixed_date=2027-04-30`），问题在引擎计算阶段。

### 根因
`db/engine.py` `compute_offsets()` 注入项目级固定日期偏移：
```python
for nid, ds in self.project_fixed.items():
    try:
        offset[nid] = (datetime.date.fromisoformat(ds) - self.t0).days   # ← 仅对字符串正确
    except Exception:
        pass
```
MySQL 经 PyMySQL 返回的 `DATE` 列是 `datetime.date` 对象（**非字符串**）。`datetime.date.fromisoformat(<date对象>)` 抛 `TypeError`，被 `except Exception: pass` 吞掉 → 固定日期偏移**未注入** → 该节点 `offset=None` → `resolve()` 已对该节点 `continue`（不参与依赖推导），于是整条下游拓扑递推全为 `None`，节点及关联节点全部丢日期。

### 修复
改用引擎内已定义的 `_as_date(ds)`（同时兼容 `datetime.date` 对象与字符串，与第三节第 3 条同源坑）：
```python
for nid, ds in self.project_fixed.items():
    fd = _as_date(ds)
    if fd is not None:
        offset[nid] = (fd - self.t0).days
```
`_as_date(v)`：`if isinstance(v, datetime.date): return v` → 对 MySQL 的 date 对象直接返回，不再走 `fromisoformat`。

### 部署与验证
- 本地 `git commit` + `git push origin main`（→ `8501f10`）。
- 服务器：因 `origin` 为裸 `https://github.com/...`（无 PAT），改为带 PAT 的 origin URL 后 `git fetch origin main && git reset --hard origin/main`（HEAD=8501f10）；`systemctl --user restart devplan-ops.service`（`active`）。
- 服务器 `.venv` 执行 `from app.app import regenerate_all_versions; regenerate_all_versions(4)` 重算三版。
- 验证（柳林 pid=4，buffer_kh=buffer_ly=30）：
  | 版本 | 95 完成整体正负零施工 | 96 主体达到1/2层高 | 97 主体结构封顶 |
  |---|---|---|---|
  | 内控 | 2027-04-30 ✓ | 2027-06-19 | 2027-06-16 |
  | 考核 | 2027-05-30 | 2027-07-19 | 2027-07-16 |
  | 履约 | 2027-05-30 | 2027-07-19 | 2027-07-16 |
  节点 95 精确锚定固定日期；96/97 日期恢复非 NULL（其最终日期由"最大前驱+偏移"决定，被晚于 95 的另一条依赖链主导，符合拓扑-MAX 语义）。

### 附带观察（非本次 bug，供参考）
柳林 pid=4 每版 148 节点中有 **14 个 `finish_inner` 为 NULL**：其中 3 个（代建合同签订/取得国土证/联合验收完成）与项目 1 一致，属基线不可排程锚点；**另外 11 个「批量内装」节点（60/67/68/105/106/114/115/118/124/128/134）为 NULL，是项目 4 前置参数（prereq_json）未激活内装分支所致，与节点 95 不在同一依赖链，不受本 bug 影响**。若柳林需排内装计划，应补填对应前置参数后重算。
