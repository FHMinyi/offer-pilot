-- =============================================================================
-- 0001_baseline.sql · 里程碑一目标 schema 基线蓝本
-- -----------------------------------------------------------------------------
-- 【重要】本文件在里程碑一不被任何代码执行。真正建表由
--   app/database.py:init_db() 的 Base.metadata.create_all() 完成。
-- 本文件仅作「未来引入 Alembic 时的迁移基线参考」，方言为 SQLite（PG 通用，
-- 不含专有特性）。字段口径与 app/models.py 的 Mapped 声明一致，以模型为权威。
--
-- 里程碑一完成后共 8 张表 = 现有 5（不在此重复 DDL，由既有模型管理）+ 新增 3。
-- 现有 5：resumes / job_postings / analysis_runs / conversations / saved_jds。
-- 新增 3：journey_states / tasks / check_ins（下方蓝本）。
-- =============================================================================

-- 旅程主表：单用户取最新 active 一行（约定，非约束）。
CREATE TABLE IF NOT EXISTS journey_states (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           VARCHAR(64) NOT NULL DEFAULT 'local',
    profile_type      VARCHAR(16) NOT NULL DEFAULT 'student',   -- B2 四类画像键(F3)
    analysis_run_id   INTEGER,                                   -- FK analysis_runs(id)
    target_role       VARCHAR(255) NOT NULL DEFAULT '',
    signals           JSON,                                      -- B3 多维信号容器
    stage             VARCHAR(32) NOT NULL DEFAULT 'executing',  -- 派生展示标签
    status            VARCHAR(16) NOT NULL DEFAULT 'active',     -- B4 多终态
    persona           VARCHAR(32) NOT NULL DEFAULT 'default',    -- B5
    tone              INTEGER NOT NULL DEFAULT 50,               -- B5 0温柔..100严格
    start_date        DATE,
    planned_weeks     INTEGER NOT NULL DEFAULT 4,
    current_week      INTEGER NOT NULL DEFAULT 1,
    last_replanned_at DATETIME,
    created_at        DATETIME,
    updated_at        DATETIME,
    FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs (id)
);
CREATE INDEX IF NOT EXISTS ix_journey_states_user_id ON journey_states (user_id);
CREATE INDEX IF NOT EXISTS ix_journey_states_analysis_run_id ON journey_states (analysis_run_id);

-- roadmap 物化为可勾选行——闭环核心 + 物化契约锚点。
CREATE TABLE IF NOT EXISTS tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,           -- 稳定主键：CheckIn 引用它
    user_id         VARCHAR(64) NOT NULL DEFAULT 'local',
    journey_id      INTEGER,                                     -- FK journey_states(id)
    analysis_run_id INTEGER NOT NULL,                            -- FK analysis_runs(id)
    week            INTEGER NOT NULL DEFAULT 1,
    order_index     INTEGER NOT NULL DEFAULT 0,                  -- 周内跨 kind 连续序(C3)
    skill_key       VARCHAR(64) NOT NULL DEFAULT '',
    title           TEXT NOT NULL,
    kind            VARCHAR(16) NOT NULL DEFAULT 'learn',        -- learn/deliverable/interview/review
    weight          INTEGER NOT NULL DEFAULT 1,
    status          VARCHAR(16) NOT NULL DEFAULT 'todo',         -- 四态 todo/doing/done/skipped
    planned_date    DATE,
    done_at         DATETIME,
    created_at      DATETIME,
    updated_at      DATETIME,
    FOREIGN KEY (journey_id) REFERENCES journey_states (id),
    FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs (id),
    CONSTRAINT uq_task_run_week_order UNIQUE (analysis_run_id, week, order_index)
);
CREATE INDEX IF NOT EXISTS ix_tasks_user_id ON tasks (user_id);
CREATE INDEX IF NOT EXISTS ix_tasks_journey_id ON tasks (journey_id);
CREATE INDEX IF NOT EXISTS ix_tasks_analysis_run_id ON tasks (analysis_run_id);

-- 每日打卡：同 user_id + date 唯一，upsert；引用 Task.id 稳定主键。
CREATE TABLE IF NOT EXISTS check_ins (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            VARCHAR(64) NOT NULL DEFAULT 'local',
    journey_id         INTEGER,                                  -- FK journey_states(id)
    date               DATE NOT NULL,                            -- 客户端本地自然日
    mood               VARCHAR(16) NOT NULL DEFAULT '',
    note               TEXT NOT NULL DEFAULT '',
    minutes            INTEGER NOT NULL DEFAULT 0,
    completed_task_ids JSON,                                     -- list[int]，引用 tasks.id
    created_at         DATETIME,
    updated_at         DATETIME,
    FOREIGN KEY (journey_id) REFERENCES journey_states (id),
    CONSTRAINT uq_checkin_user_date UNIQUE (user_id, date)
);
CREATE INDEX IF NOT EXISTS ix_check_ins_user_id ON check_ins (user_id);
CREATE INDEX IF NOT EXISTS ix_check_ins_journey_id ON check_ins (journey_id);
CREATE INDEX IF NOT EXISTS ix_check_ins_date ON check_ins (date);
