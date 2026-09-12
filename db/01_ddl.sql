-- =========================================================
-- 房地产开发运营计划系统 · 数据库设计（DDL）
-- 基于《远建2026版三级计划（绿城基础含公式）》实测结构生成
-- 引擎: MySQL 8.0 (亦可改 PostgreSQL)
-- =========================================================

CREATE DATABASE IF NOT EXISTS dev_plan DEFAULT CHARSET utf8mb4;
USE dev_plan;


-- 职能线字典
CREATE TABLE profession (
  id INT PRIMARY KEY AUTO_INCREMENT, code VARCHAR(32) NOT NULL UNIQUE,
  name VARCHAR(64) NOT NULL, remark VARCHAR(128)
) ENGINE=InnoDB;

-- 楼型（标准期量维度）
CREATE TABLE building_type (
  id INT PRIMARY KEY AUTO_INCREMENT, code VARCHAR(16) NOT NULL UNIQUE, name VARCHAR(64) NOT NULL
) ENGINE=InnoDB;

-- 前置信息/项目参数定义
CREATE TABLE prereq_param (
  id INT PRIMARY KEY AUTO_INCREMENT, code VARCHAR(32) NOT NULL UNIQUE,
  name VARCHAR(64) NOT NULL, options_json TEXT
) ENGINE=InnoDB;

-- 标准节点库（模板，来自 Excel 节点计划）
CREATE TABLE std_node (
  id INT PRIMARY KEY AUTO_INCREMENT, excel_row INT,
  level ENUM('里程碑','一级','二级','二级*') NOT NULL, seq INT,
  name VARCHAR(160) NOT NULL, profession_id INT,
  deliverable TEXT, support_doc TEXT, duration INT,
  tmpl_finish_formula VARCHAR(255), depend_row INT, offset_days INT,
  base_is_t0 TINYINT DEFAULT 0, has_condition TINYINT DEFAULT 0,
  version_no INT DEFAULT 1,
  FOREIGN KEY (profession_id) REFERENCES profession(id)
) ENGINE=InnoDB;

-- 标准期量（7 楼型 × 节点）
CREATE TABLE std_duration (
  id INT PRIMARY KEY AUTO_INCREMENT, std_node_id INT NOT NULL, building_type_id INT NOT NULL,
  std_desc VARCHAR(160),
  FOREIGN KEY (std_node_id) REFERENCES std_node(id),
  FOREIGN KEY (building_type_id) REFERENCES building_type(id),
  UNIQUE (std_node_id, building_type_id)
) ENGINE=InnoDB;

-- 标准节点依赖（解析 Excel 公式）
CREATE TABLE std_node_dependency (
  id INT PRIMARY KEY AUTO_INCREMENT, std_node_id INT NOT NULL,
  depend_std_node_id INT, depend_row INT, offset_days INT,
  base_is_t0 TINYINT DEFAULT 0, direction ENUM('之后','之前') DEFAULT '之后',
  has_condition TINYINT DEFAULT 0,
  version_no INT DEFAULT 1, is_active TINYINT DEFAULT 1, effective_from DATE,
  FOREIGN KEY (std_node_id) REFERENCES std_node(id),
  FOREIGN KEY (depend_std_node_id) REFERENCES std_node(id)
) ENGINE=InnoDB;

-- 参数化规则分支：从 Excel L 列 IF(前置信息!$B$x...) 公式解析而来。
-- 每个参数化节点有多条分支，每条分支 = 一组前置参数条件 -> (依赖行, 偏移表达式)。
-- 引擎套模板时按项目 prereq_json 逐节点选首条命中分支，得到该项目的实际工期边。
-- version_no / is_active / effective_from：标准库版本化（仅生效版本 is_active=1 参与计算）。
CREATE TABLE std_node_rule (
  id INT PRIMARY KEY AUTO_INCREMENT, std_node_id INT NOT NULL,
  branch_order INT NOT NULL, is_default TINYINT DEFAULT 0,
  conditions_json TEXT,          -- JSON 数组: [{param,op,value}], 多条件 AND
  depend_row INT,                -- 命中分支的依赖节点 excel_row; NULL=该参数组合下节点不排程
  offset_expr VARCHAR(255),      -- 偏移表达式, 如 "10+12+(topfloor-2)*5" / "14*30" / "-130"; NULL=不排程
  direction ENUM('之后','之前') DEFAULT '之后',
  base_is_t0 TINYINT DEFAULT 0,
  version_no INT DEFAULT 1,
  is_active TINYINT DEFAULT 1,
  effective_from DATE,
  FOREIGN KEY (std_node_id) REFERENCES std_node(id)
) ENGINE=InnoDB;

-- 项目级参数化规则分支（override）：单个项目对标准库规则的自定义覆盖。
-- 引擎套模板时优先取本表；若不存在则该节点回退到 std_node_rule（标准库）。
CREATE TABLE project_node_rule (
  id INT PRIMARY KEY AUTO_INCREMENT, project_id INT NOT NULL,
  std_node_id INT NOT NULL, branch_order INT NOT NULL, is_default TINYINT DEFAULT 0,
  conditions_json TEXT,             -- JSON 数组: [{param,op,value}], 多条件 AND
  depend_row INT,                   -- 命中分支的依赖节点 excel_row; NULL=该参数组合下节点不排程
  offset_expr VARCHAR(255),         -- 偏移表达式, 如 "(topfloor-2)*5" / "-130"; NULL=不排程
  direction ENUM('之后','之前') DEFAULT '之后',
  base_is_t0 TINYINT DEFAULT 0,
  FOREIGN KEY (project_id) REFERENCES project(id),
  FOREIGN KEY (std_node_id) REFERENCES std_node(id)
) ENGINE=InnoDB;

-- 项目级固定日期覆盖（抛弃规则，直接指定绝对完成日期）：单个项目对任意节点的特例调整。
-- 引擎套模板时若本表存在 (project_id,std_node_id)，则该节点偏移被强制为 (fixed_date - T0)，忽略公式与规则。
CREATE TABLE project_node_fixed (
  id INT PRIMARY KEY AUTO_INCREMENT, project_id INT NOT NULL,
  std_node_id INT NOT NULL, fixed_date DATE NOT NULL,
  FOREIGN KEY (project_id) REFERENCES project(id),
  FOREIGN KEY (std_node_id) REFERENCES std_node(id),
  UNIQUE (project_id, std_node_id)
) ENGINE=InnoDB;

-- 规则变更日志（标准库 / 项目级 规则与固定日期的修改留痕，便于审计与回退）
CREATE TABLE rule_change_log (
  id INT PRIMARY KEY AUTO_INCREMENT,
  scope VARCHAR(16) NOT NULL DEFAULT '标准库',   -- '标准库' / '项目'
  std_node_id INT NOT NULL,
  project_id INT,
  action VARCHAR(32) NOT NULL,                    -- '更新规则' / '恢复继承' / '固定日期' / '取消固定' / '初始导入' / '版本回滚'
  before_json TEXT,
  after_json TEXT,
  operator VARCHAR(64) DEFAULT '代建运营部',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_id) REFERENCES project(id),
  FOREIGN KEY (std_node_id) REFERENCES std_node(id),
  INDEX idx_rcl_node (std_node_id),
  INDEX idx_rcl_proj (project_id)
) ENGINE=InnoDB;

-- 项目
CREATE TABLE project (
  id INT PRIMARY KEY AUTO_INCREMENT, name VARCHAR(160) NOT NULL, client VARCHAR(160),
  building_type_id INT, plan_start DATE, plan_deliver DATE,
  status VARCHAR(16) DEFAULT '进行中', prereq_json TEXT,
  FOREIGN KEY (building_type_id) REFERENCES building_type(id)
) ENGINE=InnoDB;

-- 计划版本
CREATE TABLE plan_version (
  id INT PRIMARY KEY AUTO_INCREMENT, project_id INT NOT NULL, version_no INT NOT NULL,
  plan_type ENUM('内控','考核','履约') NOT NULL, status ENUM('草稿','基准') DEFAULT '草稿',
  published_at DATETIME,
  FOREIGN KEY (project_id) REFERENCES project(id)
) ENGINE=InnoDB;

-- 项目计划节点（套模板生成）
CREATE TABLE plan_node (
  id INT PRIMARY KEY AUTO_INCREMENT, project_id INT NOT NULL, version_id INT NOT NULL,
  std_node_id INT, level ENUM('里程碑','一级','二级','二级*') NOT NULL, seq INT,
  name VARCHAR(160) NOT NULL, profession_id INT,
  start_inner DATE, finish_inner DATE, finish_assess DATE, finish_perform DATE,
  actual_start DATE, actual_finish DATE, progress_pct INT DEFAULT 0,
  status ENUM('正常','预警','延期') DEFAULT '正常',
  FOREIGN KEY (project_id) REFERENCES project(id),
  FOREIGN KEY (version_id) REFERENCES plan_version(id),
  FOREIGN KEY (std_node_id) REFERENCES std_node(id),
  FOREIGN KEY (profession_id) REFERENCES profession(id)
) ENGINE=InnoDB;

-- 预警规则
CREATE TABLE alert_rule (
  id INT PRIMARY KEY AUTO_INCREMENT, level ENUM('里程碑','一级','二级','二级*'),
  plan_type ENUM('内控','考核','履约'), threshold_days INT NOT NULL, notify_target VARCHAR(160)
) ENGINE=InnoDB;

-- 预警记录
CREATE TABLE alert_record (
  id INT PRIMARY KEY AUTO_INCREMENT, plan_node_id INT NOT NULL, alert_rule_id INT,
  triggered_at DATETIME, delay_days INT, message VARCHAR(255),
  FOREIGN KEY (plan_node_id) REFERENCES plan_node(id)
) ENGINE=InnoDB;

-- 标准库规则版本目录（版本化：每次「发布版本」/「回滚」生成一条记录，对应整库规则快照）
CREATE TABLE std_rule_version (
  id INT PRIMARY KEY AUTO_INCREMENT,
  version_no INT NOT NULL UNIQUE,
  name VARCHAR(120),                       -- 版本名，如「2026Q3 管线调整」
  note VARCHAR(255),                       -- 备注 / 变更说明
  effective_from DATE,                     -- 该版本从哪天起对新项目生效
  operator VARCHAR(64) DEFAULT '代建运营部',
  source_version_no INT,                   -- 回滚时记录源自哪个版本
  change_summary TEXT,                     -- 本次发布改了哪些节点（摘要）
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
