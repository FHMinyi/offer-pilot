-- =============================================================================
-- 0002_interview_logs.sql · 轨道 F1 面经复盘表蓝本
-- -----------------------------------------------------------------------------
-- 【重要】本文件不被任何代码执行。真正建表由 app/database.py:init_db() 的
--   Base.metadata.create_all() 完成。本文件仅作「未来引入 Alembic 时的迁移参考」，
--   方言 SQLite（PG 通用）。字段口径与 app/models.py:InterviewLog 一致，以模型为权威。
--
-- F1（碰壁期闭环）新增 1 张表：interview_logs。
-- 闭环：面经文本 → 盲区(blind_spots) → 权重回灌到匹配的 Task。
-- =============================================================================

CREATE TABLE IF NOT EXISTS interview_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         VARCHAR(64) NOT NULL DEFAULT 'local',
    journey_id      INTEGER,                                     -- FK journey_states(id)
    analysis_run_id INTEGER,                                     -- FK analysis_runs(id)
    company         VARCHAR(255) NOT NULL DEFAULT '',
    role            VARCHAR(255) NOT NULL DEFAULT '',            -- 面试岗位/方向
    content         TEXT NOT NULL,                               -- 面经/复盘原文
    blind_spots     JSON,                                        -- list[{skill_key,skill_name,severity,evidence,matched}]
    created_at      DATETIME,
    updated_at      DATETIME,
    FOREIGN KEY (journey_id) REFERENCES journey_states (id),
    FOREIGN KEY (analysis_run_id) REFERENCES analysis_runs (id)
);
CREATE INDEX IF NOT EXISTS ix_interview_logs_user_id ON interview_logs (user_id);
CREATE INDEX IF NOT EXISTS ix_interview_logs_journey_id ON interview_logs (journey_id);
CREATE INDEX IF NOT EXISTS ix_interview_logs_analysis_run_id ON interview_logs (analysis_run_id);
