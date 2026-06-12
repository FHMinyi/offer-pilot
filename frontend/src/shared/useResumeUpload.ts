// PDF 简历上传 + 拖拽状态机（从 ChatView.vue 抽出）：
//   · ingestResumeFile：校验 PDF → uploadResume 解析 → 经 onResumeText 写回调用方；
//     文件框选择与拖拽放入共用同一处理；
//   · dragOver / onDrag*：拖文件到输入区的视觉状态机（计数器避免子元素
//     dragenter/dragleave 造成的闪烁；仅对「文件」拖拽响应）。
// 提示反馈（flash）与解析文本落点（onResumeText）由调用方注入，本文件不碰组件状态。

import { ref } from 'vue'
import { uploadResume } from '../api/client'

export interface ResumeUploadDeps {
  /** 解析成功回调：把简历全文写入调用方的 context（如 context.resume_text）。 */
  onResumeText: (text: string) => void
  /** 轻量浮层提示（成功 / 失败反馈），由调用方提供。 */
  flash: (msg: string, isError?: boolean) => void
}

export function useResumeUpload(deps: ResumeUploadDeps) {
  // ---------- PDF 上传 ----------
  const uploading = ref(false)

  // 统一的简历文件处理：校验 PDF → 上传解析 → 经回调写回简历文本。
  async function ingestResumeFile(file: File): Promise<void> {
    if (uploading.value) return
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
    if (!isPdf) {
      deps.flash('目前仅支持 PDF 简历，其它格式请粘贴文本', true)
      return
    }
    uploading.value = true
    try {
      const resume = await uploadResume(file)
      deps.onResumeText(resume.raw_text)
      deps.flash(`已添加简历「${file.name}」`)
    } catch (err) {
      deps.flash(err instanceof Error ? err.message : '简历解析失败，请重试', true)
    } finally {
      uploading.value = false
    }
  }

  // ---------- 拖拽上传 ----------
  // 拖动文件到 composer 时，输入区扩大并提示「松开以上传简历」。
  // 用计数器避免子元素 dragenter/dragleave 造成的闪烁。
  const dragOver = ref(false)
  let dragDepth = 0

  // 仅对「文件」拖拽响应（忽略选中文本等拖拽）。
  function isFileDrag(e: DragEvent): boolean {
    return Array.from(e.dataTransfer?.types ?? []).includes('Files')
  }

  function onDragEnter(e: DragEvent): void {
    if (!isFileDrag(e)) return
    e.preventDefault()
    dragDepth += 1
    dragOver.value = true
  }

  function onDragOver(e: DragEvent): void {
    if (!isFileDrag(e)) return
    e.preventDefault() // 必须阻止默认才能触发 drop
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
  }

  function onDragLeave(e: DragEvent): void {
    if (!isFileDrag(e)) return
    dragDepth -= 1
    if (dragDepth <= 0) {
      dragDepth = 0
      dragOver.value = false
    }
  }

  async function onDrop(e: DragEvent): Promise<void> {
    if (!isFileDrag(e)) return
    e.preventDefault()
    dragDepth = 0
    dragOver.value = false
    const file = e.dataTransfer?.files?.[0]
    if (file) await ingestResumeFile(file)
  }

  return { uploading, ingestResumeFile, dragOver, onDragEnter, onDragOver, onDragLeave, onDrop }
}
