# 房地产开发运营计划系统（代建三级计划管理）

面向代建公司「代建运营部」的住宅开发进度计划管理 Web 后台：以**相对工期引擎**驱动四级计划体系
（里程碑 / 一级 / 二级 / 二级\*），支持参数化分支、项目级规则覆盖、固定日期特例、规则变更留痕与**延期预警**。

> 规则来源：《远建2026版三级计划（绿城基础含公式）.xlsx》；需求见 `docs/需求规格说明书_v0.2.md`；
> 库设计见 `db/design.md`；运行与修复记录见 `docs/RUN_STATUS.md`。

---

## 功能概览

| 模块 | 说明 |
|---|---|
| 标准节点库 | 148 节点（里程碑13 / 一级40 / 二级89 / 二级\*6）全量排列，可编辑依赖与参数化分支规则 |
| 项目计划 | 多项目管理，按 T0 + 前置参数由引擎推算各节点计划日期 |
| 相对工期引擎 | 节点日期 = 依赖节点 ± 偏移天数；支持 `IF(前置参数)` 分支按项目参数自动选路 |
| 项目级覆盖（三模式） | 继承标准库 / 固定日期 / 修改规则——所有节点均可改规则 |
| 规则变更留痕 | 标准库与项目级每次变更写入 `rule_change_log`，页面可查变更历史 |
| 预警中心 | 按「层级 × 版本」阈值（里程碑/一级≥14天、二级/二级\*≥7天）比对计划与实际，生成 `alert_record` |
| 关键路径视图 | CPM 自交付节点回溯主干，标注关键节点 |

---

## 快速开始

### 方式一：本地（SQLite，零配置）

```bash
pip install -r requirements.txt
cd app && python app.py            # 默认 DB_TYPE=sqlite，读 db/devplan.db
# 打开 http://127.0.0.1:5000
```

`db/devplan.db` 已含标准节点库、80 条参数化规则与演示项目，**开箱即用，请勿重建**。
若要重建，须先跑 `db/load_seed.py` 灌标准库，再跑 `db/extract_rules.py` 从 Excel 提取参数化规则
（`db/02_seed.sql` 里**没有** `std_node_rule` 数据，重建会全部丢失）。

### 方式二：服务器（MySQL，生产）

```bash
export DB_TYPE=mysql DB_HOST=127.0.0.1 DB_PORT=3306 DB_USER=root DB_PASS= DB_NAME=dev_plan
export PORT=5001
cd app && python app.py
```

数据库连接参数**全部来自环境变量**，代码内不留明文口令。

---

## 目录结构

```
app/
  app.py            # Flask 主应用（16 路由：项目/标准库/规则/变更日志/预警中心）
  seed_demo.py      # 演示项目数据生成
  templates/        # Jinja2 模板（含 alert_*.html 预警模板）
  static/style.css
db/
  dbconn.py         # 连接层：DB_TYPE 切换 SQLite / MySQL，游标兼容 r["列"] 字典访问
  engine.py         # RelativeDateEngine 相对工期引擎 + compute_alerts 预警引擎
  extract_rules.py  # 从 Excel L 列 IF 公式提取参数化分支规则
  load_seed.py      # 参数化直插标准库（推荐作为 02_seed.sql 的可执行替代）
  extract_rules.py  # 从 Excel L 列 IF 公式提取参数化分支规则
  backup_mysql.py   # 重建/迁移前全库备份（导出 MySQL 方言 SQL 到 db/_backup/）
  check_coverage.py # 排程覆盖度体检：统计 148 节点中拿不到日期的节点
  import_and_verify.py / gen_critical_path.py / migrate_to_sqlite.py / regen_seed.py
  01_ddl.sql        # MySQL 版表结构
  02_seed.sql       # 标准节点库种子（不含 std_node_rule）
  design.md         # 数据库设计说明
  devplan.db        # SQLite 自包含库（含 80 条参数化规则，开箱即用）
docs/               # 需求文档 v0.1/v0.2、运行记录、截图
template/           # 远建2026版三级计划 Excel（规则源头）
prototype/          # 早期关键路径原型
tests/              # test_tier_a.py 分层测试
deploy/             # systemd 用户服务 + 一键部署脚本
```

---

## 部署（服务器）

服务器：`tang@192.168.2.132`（Ubuntu 22.04），端口 **5001**，数据库用 Docker 容器 `devplan_mysql`。

```bash
# 首次
git clone https://github.com/MoraGG/devplan-ops.git /home/tang/devplan-ops
cd /home/tang/devplan-ops && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
mkdir -p ~/.config/systemd/user
cp deploy/devplan-ops.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now devplan-ops.service

# 之后每次更新
bash /home/tang/devplan-ops/deploy/deploy.sh
```

访问 `http://192.168.2.132:5001`。

---

## 开发流程

**单一真相源 = GitHub 仓库**（`https://github.com/MoraGG/devplan-ops`）。

```
本地改代码 → git commit → git push → 服务器 bash deploy/deploy.sh（pull + 重启）
```

- 本地开发用 SQLite（`DB_TYPE=sqlite`），秒级起服务、无需容器；
- 服务器运行用 MySQL（`DB_TYPE=mysql`），配置由 systemd 注入；
- 两者共用同一套 `app.py` / `engine.py`，靠 `dbconn.py` 屏蔽差异。

---

## 已知缺口（待办）

- 三版计划（考核版 / 履约版）：目前仅生成「内控」版，其余版本无生成逻辑
- 实际进度填报：`actual_start` / `actual_finish` 已有字段与预警判定，但无独立填报页面
- 标准库版本化：`std_node` 有 `version_no` 字段，但尚无按版本回看 / 一键回滚
- `critical-path.json` 的 `jsonify` 默认 `ensure_ascii=True`，中文显示为 `\uXXXX`（功能正常，可读性差）
- 部分节点偏移为空（依赖图未连到 T0 主线），预警计算会跳过
