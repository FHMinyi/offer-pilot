# backend/migrations · 迁移基线蓝本（里程碑一过渡设施）

> **本目录在里程碑一不被任何代码执行。** 建表仍由 `app/database.py:init_db()` 的
> `Base.metadata.create_all()` 负责（只建缺失表、绝不 ALTER 旧表）。本目录只放
> 「未来引入 Alembic 时的迁移基线蓝本」+ 由 `app/db_guard.py:verify_schema()`
> 做的零成本一致性告警。

## 为什么本期不引 Alembic

里程碑一全是**纯新增表**（`journey_states` / `tasks` / `check_ins`），`create_all`
零摩擦即可建好；Alembic 的唯一刚需（给已存在表加 NOT NULL 外键 /
`batch_alter_table`）本期不存在。提前引入它反而会：

- 与 `tests/conftest.py` 的 `lifespan + create_all` 建表路径冲突；
- 把 SQLite ↔ PostgreSQL 双环境迁移风险提前到不需要的时候。

故 Alembic 连同「给旧 5 表回填 user_id 列」一并推迟到**里程碑三**。

## 里程碑三接入剧本（预写）

1. 引入 Alembic，以 `0001_baseline.sql` 描述的 8 表结构作为首条迁移基线。
2. 把 `db_guard.MILESTONE1_TABLES` 期望清单转为 Alembic 的一致性校验。
3. 给旧 5 表（resumes / job_postings / analysis_runs / conversations / saved_jds）
   加 `user_id` 列并一次性回填（`'local'` / device-id → 真实 users.id），
   幂等 ALTER 蓝本届时补到本目录。

## 文件

- `0001_baseline.sql` — 里程碑一目标 schema 的 DDL 蓝本（**注释/参考，不执行**）。
