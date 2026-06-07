"""演示数据播种脚本（G1：为录制 demo / 截图准备一份「活」的状态）。

把一份样例简历 + 两条 JD 跑一次完整分析（默认规则模式零配置、确定性；若 backend/.env
已配置 LLM 则自动走 LLM），物化为可勾选任务，模拟若干天打卡与完成，并触发一次动态再规划，
使「我的进度」看板与「执行计划」页立刻有真实可录制的内容（含完成率环、7 天热力、
阶段步骤条、今日任务、节奏洞察）。

用法（在仓库根目录）：
    ./scripts/seed-demo.sh
或（在 backend 目录）：
    .venv/bin/python seed_demo.py

注意：这是开发/演示工具，会清空当前库中 user_id='local' 的「旅程 / 任务 / 打卡」三张
状态表并重建一条干净的演示旅程。**简历与历史分析不清理，每次运行会新增一条历史分析记录**
（即「历史」列表会逐次增多；如需彻底清空，删除 backend/offerpilot.db 即可）。请勿在生产库运行。
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete

from app.database import SessionLocal, init_db
from app.models import (
    AnalysisRun,
    CheckIn,
    InterviewLog,
    JourneyState,
    MasteryCheck,
    Resume,
    Task,
    _utcnow,
)
from app.services import pipeline
from app.services.interview import extract_blind_spots, reweight_from_blind_spots
from app.services.journey import ensure_journey
from app.services.materialize import materialize_tasks
from app.services.replan import replan_journey

DEMO_USER = "local"

DEMO_RESUME = """李雷
邮箱：lilei@example.com 电话：13900000000

教育背景
某大学 软件工程 本科 大三在读 2022-2026
主修：数据结构、操作系统、Web 开发、数据库原理

项目经历
课程作业管理系统（个人）
使用 Vue3 + Vite 搭建前端，实现作业发布、提交与批改列表。
负责全部前端页面与状态管理，调用后端 REST 接口完成增删改查。

校园活动报名平台（三人团队）
使用 HTML、CSS、JavaScript 开发活动列表与报名表单。
参与接口联调，处理表单校验与基础的响应式布局。

专业技能
熟悉 HTML、CSS、JavaScript
了解 Vue、组件化开发
使用过 Git 进行版本管理
"""

DEMO_JDS = [
    """前端开发实习生
岗位职责
负责 Web 前端页面开发与维护
参与公司组件库与中后台系统建设
任职要求
熟练掌握 HTML、CSS、JavaScript
熟悉 Vue 或 React 框架
熟练使用 TypeScript 者优先
了解 Webpack/Vite 等构建工具
本科及以上，计算机相关专业，大三/大四，能实习 3 天/周以上
加分项：了解 Node.js、单元测试、Git 协作
""",
    """前端实习生（Vue 方向）
岗位职责
开发与维护公司中后台管理系统
与设计、后端协作完成需求落地
任职要求
扎实的 HTML/CSS/JavaScript 基础
熟悉 Vue3 与组件化开发
了解状态管理（Pinia/Vuex）
熟悉 Git 工作流
加分项：TypeScript、可视化图表、性能优化
""",
]


def _wipe_state(db) -> None:
    """只清空闭环状态表里的演示用户数据，保留简历与历史分析。"""
    db.execute(delete(MasteryCheck).where(MasteryCheck.user_id == DEMO_USER))
    db.execute(delete(InterviewLog).where(InterviewLog.user_id == DEMO_USER))
    db.execute(delete(CheckIn).where(CheckIn.user_id == DEMO_USER))
    db.execute(delete(Task).where(Task.user_id == DEMO_USER))
    db.execute(delete(JourneyState).where(JourneyState.user_id == DEMO_USER))
    db.commit()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        _wipe_state(db)

        # 1) 跑一次完整分析（引擎取决于 backend/.env：默认规则、已配置则用 LLM）
        outcome = pipeline.run_analysis(DEMO_RESUME, DEMO_JDS, "前端实习", 4)
        resume = Resume(
            raw_text=DEMO_RESUME, structured=outcome["resume"], source_type="paste"
        )
        db.add(resume)
        db.flush()
        run = AnalysisRun(
            resume_id=resume.id,
            job_ids=[],
            target_role="前端实习",
            weeks=4,
            match_score=outcome["result"]["match_score"],
            result=outcome["result"],
            engine=outcome["engine"],
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        # 2) 旅程 + 物化任务；start_date 提前 5 天，制造「逾期任务」以演示动态再规划
        journey = ensure_journey(db, run, DEMO_USER)
        today = date.today()
        journey.start_date = today - timedelta(days=5)
        journey.stage = "executing"
        db.commit()
        tasks = materialize_tasks(db, run, DEMO_USER, journey)

        # 3) 模拟进度：完成第 1 周前 3 个任务
        done_ids: list[int] = []
        for t in sorted(tasks, key=lambda x: (x.week, x.order_index)):
            if t.week == 1 and len(done_ids) < 3:
                t.status = "done"
                t.done_at = _utcnow()
                done_ids.append(t.id)
        db.commit()

        # 4) 模拟最近几天打卡（今天/昨天/前天连续 + 4 天前，制造 streak 与热力空档）；
        #    今天的打卡挂上已完成任务 id，让「打卡」与「任务完成」两套数据自洽。
        for delta in (0, 1, 2, 4):
            d = today - timedelta(days=delta)
            db.add(
                CheckIn(
                    user_id=DEMO_USER,
                    journey_id=journey.id,
                    date=d,
                    mood="fire" if delta == 0 else "good",
                    minutes=60,
                    completed_task_ids=done_ids if delta == 0 else [],
                )
            )
        db.commit()

        # 5) 触发一次动态再规划（结算）：顺延逾期 + 重组日程 + 写 signals → 看板「节奏洞察」
        replan_journey(db, journey, today=today, settle=True)

        # 6) 模拟一次面经复盘 → 盲区回灌（F1）：让「今日任务」出现 🎯 重点任务
        iv_content = "面试被问到 TypeScript 泛型和 React Hooks 原理，答得磕磕绊绊。"
        spots = extract_blind_spots(iv_content, run)
        rw = reweight_from_blind_spots(db, journey, spots, today=today)
        for s in spots:
            s["matched"] = s["skill_key"] in rw["matched_keys"]
        db.add(
            InterviewLog(
                user_id=DEMO_USER,
                journey_id=journey.id,
                analysis_run_id=run.id,
                company="某互联网公司",
                role="前端实习",
                content=iv_content,
                blind_spots=spots,
            )
        )
        db.commit()

        # 7) 模拟一次「掌握度判定」（费曼/出题闭环）：把某个已完成的 learn 任务升级为
        #    mastered ⭐，让「我的进度」看板的「真掌握率」非零、可录制 demo。
        mastered_task = next(
            (t for t in tasks if t.kind == "learn" and t.status == "done"), None
        )
        if mastered_task is not None:
            mastered_task.mastery = "mastered"
            mastered_task.mastered_at = _utcnow()
            db.add(
                MasteryCheck(
                    user_id=DEMO_USER,
                    journey_id=journey.id,
                    analysis_run_id=run.id,
                    task_id=mastered_task.id,
                    mode="feynman",
                    user_input="组件就是把界面拆成可复用的小块，props 父传子、state 管自身数据……",
                    verdict="good",
                    passed=True,
                    feedback="讲清了组件化与单向数据流；能再说说 state 何时触发重渲染会更完整。",
                    followup_questions=["state 更新为什么是异步批量的？"],
                    engine="rule",
                )
            )
            db.commit()

        print("✅ 演示数据已就绪：")
        print(f"   analysis_run_id = {run.id}（engine={outcome['engine']}）")
        print(f"   journey_id      = {journey.id}  start_date={journey.start_date}")
        print(f"   tasks           = {len(tasks)}  done={len(done_ids)}")
        print(f"   signals         = {journey.signals}")
        print(f"   面经盲区回灌      = {len(rw['boosted'])} 条任务标为重点（盲区 {len(spots)} 个）")
        if mastered_task is not None:
            print(f"   掌握度判定        = 任务「{mastered_task.title[:20]}」升级为 mastered ⭐")
        print()
        print("启动前后端后访问：")
        print(f"   /plan/{run.id}    执行计划（今日任务 + 结算重排 + 每日打卡）")
        print("   /dashboard        我的进度（完成率环 + 7 天热力 + 阶段步骤条）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
