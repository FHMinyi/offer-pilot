"""技能本体 v0.1（呼应 PRD §7.3 / §8）。

每个技能节点包含：
- key:      规范化唯一标识
- name:     展示名
- category: 所属大类
- aliases:  同义词 / 写法变体（用于归一化匹配，含中英文）
- learn:    学习任务模板（用于生成学习路线）
- check:    自检 / 验收方式（“如何知道自己学会了”）

设计为纯数据，便于后续替换为数据库表或图谱。MVP 先做树状 + 别名表。
"""

from __future__ import annotations

# 技能大类（用于结果分组与技能图谱展示）
CATEGORIES = [
    "前端",
    "后端",
    "AI / 大模型",
    "工程化",
    "计算机基础",
    "算法",
    "通用",
    "软技能",
]

# 核心技能节点表
SKILLS: list[dict] = [
    # -------------------- 前端 --------------------
    {
        "key": "html",
        "name": "HTML",
        "category": "前端",
        "aliases": ["html", "html5", "语义化"],
        "learn": ["梳理语义化标签与表单元素", "完成一个无障碍可访问的静态页面"],
        "check": "能独立写出结构清晰、语义化良好的页面",
    },
    {
        "key": "css",
        "name": "CSS",
        "category": "前端",
        "aliases": ["css", "css3", "flex", "flexbox", "grid", "响应式", "scss", "less", "tailwind"],
        "learn": ["掌握 Flex/Grid 布局", "实现一套响应式页面并处理常见兼容问题"],
        "check": "能不借助框架还原中等复杂度的设计稿",
    },
    {
        "key": "javascript",
        "name": "JavaScript",
        "category": "前端",
        "aliases": ["javascript", "js", "es6", "es2015", "ecmascript", "事件循环", "event loop", "闭包", "原型链", "promise"],
        "learn": ["吃透闭包/原型链/this 指向", "理解事件循环与微任务宏任务", "用 Promise/async 重写一段回调代码"],
        "check": "能讲清事件循环并手写 Promise 简版实现",
    },
    {
        "key": "typescript",
        "name": "TypeScript",
        "category": "前端",
        "aliases": ["typescript", "ts", "类型体操", "泛型"],
        "learn": ["掌握接口/泛型/联合类型", "为现有 JS 项目逐步补全类型"],
        "check": "能为一个中等模块设计合理且无 any 的类型",
    },
    {
        "key": "vue",
        "name": "Vue",
        "category": "前端",
        "aliases": ["vue", "vue3", "vue2", "composition api", "响应式", "vue router", "pinia", "vuex"],
        "learn": ["掌握 Composition API 与响应式原理", "用 Vue Router + Pinia 完成一个多页面应用"],
        "check": "能讲清 Vue 响应式原理并独立搭建中型应用",
    },
    {
        "key": "react",
        "name": "React",
        "category": "前端",
        "aliases": ["react", "hooks", "jsx", "redux", "next.js", "nextjs"],
        "learn": ["掌握函数组件与常用 Hooks", "理解渲染与依赖更新机制"],
        "check": "能讲清 Hooks 闭包陷阱并独立搭建中型应用",
    },
    {
        "key": "browser",
        "name": "浏览器原理",
        "category": "前端",
        "aliases": ["浏览器", "渲染原理", "重排", "重绘", "回流", "http缓存", "跨域", "cors"],
        "learn": ["梳理从输入 URL 到页面渲染的全过程", "整理浏览器缓存与跨域方案"],
        "check": "能完整讲清渲染流程与常见性能优化点",
    },
    # -------------------- 后端 --------------------
    {
        "key": "java",
        "name": "Java",
        "category": "后端",
        "aliases": ["java", "jvm", "juc", "并发编程", "集合框架"],
        "learn": ["巩固集合框架与并发(JUC)", "理解 JVM 内存模型与 GC"],
        "check": "能讲清 HashMap 原理与线程安全方案",
    },
    {
        "key": "spring",
        "name": "Spring / Spring Boot",
        "category": "后端",
        "aliases": ["spring", "spring boot", "springboot", "spring mvc", "ioc", "aop", "mybatis"],
        "learn": ["理解 IoC/AOP 核心机制", "用 Spring Boot 搭建一套带分层的 REST 服务"],
        "check": "能讲清 Bean 生命周期并独立搭建后端服务",
    },
    {
        "key": "python",
        "name": "Python",
        "category": "后端",
        "aliases": ["python", "py", "fastapi", "flask", "django"],
        "learn": ["巩固语言特性与常用标准库", "用 FastAPI/Flask 搭建一套 REST 服务"],
        "check": "能独立用 Python 搭建并部署一个后端服务",
    },
    {
        "key": "nodejs",
        "name": "Node.js",
        "category": "后端",
        "aliases": ["node", "node.js", "nodejs", "express", "koa", "nest", "nestjs"],
        "learn": ["理解事件循环与异步 I/O", "用 Express/Nest 搭建一套接口服务"],
        "check": "能独立用 Node 实现一组带鉴权的接口",
    },
    {
        "key": "go",
        "name": "Go",
        "category": "后端",
        "aliases": ["golang", "goroutine", "gin"],  # 不含裸 "go"，避免误匹配
        "learn": ["掌握 goroutine 与 channel", "用 Gin 搭建一套服务"],
        "check": "能讲清并发模型并独立写一个并发安全的服务",
    },
    {
        "key": "rest_api",
        "name": "REST API 设计",
        "category": "后端",
        "aliases": ["restful", "rest api", "接口设计", "openapi", "swagger"],
        "learn": ["梳理 REST 资源建模与状态码规范", "为现有项目补全接口文档"],
        "check": "能设计出风格一致、可解释的接口",
    },
    # -------------------- AI / 大模型 --------------------
    {
        "key": "llm_app",
        "name": "大模型/LLM 应用",
        "category": "AI / 大模型",
        "aliases": ["llm", "大模型", "大语言模型", "gpt", "chatgpt", "openai api", "claude", "通义", "文心", "推理 api"],
        "learn": ["掌握调用 LLM API 与提示设计", "做一个基于 LLM 的小应用（问答/总结）"],
        "check": "能讲清 LLM 应用的基本链路与常见坑（幻觉/上下文窗口/成本）",
    },
    {
        "key": "prompt_engineering",
        "name": "Prompt 工程",
        "category": "AI / 大模型",
        "aliases": ["prompt", "提示工程", "提示词", "few-shot", "思维链", "cot", "结构化输出"],
        "learn": ["练习 few-shot / CoT / 结构化输出", "为一个任务系统化迭代提示词"],
        "check": "能稳定地把任务提示工程化并评估效果",
    },
    {
        "key": "agent_dev",
        "name": "AI Agent 开发",
        "category": "AI / 大模型",
        "aliases": ["agent", "ai agent", "智能体", "function calling", "工具调用", "tool use", "react 框架", "多智能体", "autogpt"],
        "learn": ["理解 Agent 的工具调用/规划/记忆机制", "用框架搭一个能调用工具的 Agent"],
        "check": "能设计并实现一个稳定的工具调用 Agent 闭环",
    },
    {
        "key": "langchain",
        "name": "LangChain / LangGraph",
        "category": "AI / 大模型",
        "aliases": ["langchain", "langgraph", "llamaindex", "llama index", "langsmith", "编排框架"],
        "learn": ["掌握 LangChain/LangGraph 的链与图编排", "用其搭建一个可控的多步流程"],
        "check": "能用编排框架实现并调试一个多步 LLM 流程",
    },
    {
        "key": "rag",
        "name": "RAG 检索增强",
        "category": "AI / 大模型",
        "aliases": ["rag", "检索增强", "retrieval augmented", "知识库问答", "embedding", "向量检索", "重排", "rerank", "召回"],
        "learn": ["搭建 切分→Embedding→检索→生成 的 RAG 流程", "优化召回与重排提升答案质量"],
        "check": "能独立搭建并评估一个 RAG 问答系统",
    },
    {
        "key": "vector_db",
        "name": "向量数据库",
        "category": "AI / 大模型",
        "aliases": ["向量数据库", "向量库", "vector db", "vector database", "qdrant", "milvus", "pinecone", "chroma", "faiss", "weaviate", "pgvector"],
        "learn": ["掌握向量索引与相似度检索", "用一个向量库支撑 RAG 的检索层"],
        "check": "能选型并用向量库支撑检索场景",
    },
    {
        "key": "mcp",
        "name": "MCP 协议",
        "category": "AI / 大模型",
        "aliases": ["mcp", "model context protocol"],
        "learn": ["理解 MCP 的能力暴露与调用方式", "实现一个简单的 MCP server/client"],
        "check": "能讲清 MCP 的定位并接入一个工具",
    },
    {
        "key": "ml_basics",
        "name": "机器学习/深度学习基础",
        "category": "AI / 大模型",
        "aliases": ["机器学习", "深度学习", "pytorch", "tensorflow", "transformer", "神经网络", "微调", "fine-tuning", "lora", "huggingface", "hugging face"],
        "learn": ["补齐神经网络与 Transformer 基础", "用 PyTorch/HuggingFace 跑通一次训练或微调"],
        "check": "能讲清 Transformer 核心思想并完成一次微调实践",
    },
    # -------------------- 计算机基础 --------------------
    {
        "key": "database",
        "name": "关系型数据库",
        "category": "计算机基础",
        "aliases": ["mysql", "postgresql", "postgres", "sql", "关系型数据库", "索引", "事务", "redis", "mongodb"],
        "learn": ["掌握索引/事务/隔离级别", "针对慢查询做一次实战优化"],
        "check": "能讲清索引失效场景并做查询优化",
    },
    {
        "key": "network",
        "name": "计算机网络",
        "category": "计算机基础",
        "aliases": ["tcp", "udp", "http", "https", "tcp/ip", "网络", "三次握手", "网络协议"],
        "learn": ["梳理 TCP/IP 与 HTTP/HTTPS", "整理三次握手/四次挥手与常见面试点"],
        "check": "能完整讲清 HTTPS 建连与 TCP 可靠性机制",
    },
    {
        "key": "os",
        "name": "操作系统",
        "category": "计算机基础",
        "aliases": ["操作系统", "进程", "线程", "内存管理", "死锁"],
        "learn": ["梳理进程/线程/协程区别", "整理内存管理与调度机制"],
        "check": "能讲清进程线程区别与常见同步原语",
    },
    # -------------------- 算法 --------------------
    {
        "key": "algorithm",
        "name": "数据结构与算法",
        "category": "算法",
        "aliases": ["算法", "数据结构", "leetcode", "刷题", "动态规划", "dp", "二叉树", "排序"],
        "learn": ["按专题刷题：数组/链表/树/DP", "每周复盘高频题并整理模板"],
        "check": "能在限定时间内独立写出中等难度题",
    },
    # -------------------- 工程化 --------------------
    {
        "key": "git",
        "name": "Git",
        "category": "工程化",
        "aliases": ["git", "github", "版本控制", "gitlab"],
        "learn": ["掌握分支/合并/冲突解决", "规范化提交与 PR 流程"],
        "check": "能独立处理分支冲突并维护清晰提交历史",
    },
    {
        "key": "docker",
        "name": "Docker / 容器化",
        "category": "工程化",
        "aliases": ["docker", "容器", "容器化", "k8s", "kubernetes", "compose"],
        "learn": ["掌握镜像构建与多阶段构建", "用 Docker Compose 编排本项目"],
        "check": "能为自己的项目写出可用的 Dockerfile",
    },
    {
        "key": "build_tools",
        "name": "前端工程化",
        "category": "工程化",
        "aliases": ["vite", "webpack", "构建", "打包", "eslint", "ci/cd", "ci", "cd"],
        "learn": ["理解模块化与构建流程", "为项目配置 lint 与基础 CI"],
        "check": "能独立配置并优化项目构建流程",
    },
    {
        "key": "linux",
        "name": "Linux",
        "category": "工程化",
        "aliases": ["linux", "shell", "bash", "命令行", "服务器"],
        "learn": ["掌握常用命令与 Shell 脚本", "在云服务器上完成一次部署"],
        "check": "能独立排查常见服务器问题",
    },
    # -------------------- 软技能 --------------------
    {
        "key": "communication",
        "name": "沟通与协作",
        "category": "软技能",
        "aliases": ["沟通", "团队协作", "协作能力", "表达能力"],
        "learn": ["梳理项目里的协作经历并量化产出", "练习用 STAR 法讲项目"],
        "check": "能用 STAR 结构清晰讲清一段经历",
    },
]

# 技能图谱树（PRD §8，先树状再升级图谱）
SKILL_TREE: dict = {
    "前端": ["html", "css", "javascript", "typescript", "vue", "react", "browser", "build_tools"],
    "后端": ["java", "spring", "python", "nodejs", "go", "rest_api"],
    "AI / 大模型": [
        "llm_app", "prompt_engineering", "agent_dev", "langchain", "rag", "vector_db", "mcp", "ml_basics",
    ],
    "计算机基础": ["database", "network", "os"],
    "算法": ["algorithm"],
    "工程化": ["git", "docker", "linux"],
    "软技能": ["communication"],
}

# 按 key 建立索引，供其他模块使用
SKILL_BY_KEY: dict[str, dict] = {s["key"]: s for s in SKILLS}
