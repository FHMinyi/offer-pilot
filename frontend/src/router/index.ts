import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

// 三个核心视图采用动态 import 懒加载，降低首屏体积
const routes: RouteRecordRaw[] = [
  {
    // 对话式主界面：产品新门面，取代旧的表单式新建分析页
    // 路由名仍保留 'new'，以兼容历史/结果页中指向 { name: 'new' } 的返回入口
    path: '/',
    name: 'new',
    component: () => import('../views/ChatView.vue'),
  },
  {
    path: '/result/:id',
    name: 'result',
    component: () => import('../views/ResultView.vue'),
    props: true, // 将路由参数 id 作为 prop 传入视图
  },
  {
    path: '/history',
    name: 'history',
    component: () => import('../views/HistoryView.vue'),
  },
  {
    // 会话回看页（只读）：展示某段完整对话历史
    path: '/conversation/:id',
    name: 'conversation',
    component: () => import('../views/ConversationView.vue'),
    props: true, // 将路由参数 id 作为 prop 传入视图
  },
  {
    // 活计划页：某次分析物化出的可勾选任务 + 今日打卡（里程碑一闭环）
    path: '/plan/:runId',
    name: 'plan',
    component: () => import('../views/PlanView.vue'),
    props: true, // runId = analysis_run_id
  },
  {
    // 进度看板：完成度 / streak / 周进度 / 阶段
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('../views/DashboardView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  // 切换路由时滚动回顶部
  scrollBehavior() {
    return { top: 0 }
  },
})

export default router
