import { FigureError } from '@/components/FigureError'
import { CommandPalette } from '@/components/CommandPalette'
import { MarkTools } from '@/components/TopBar'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Download, LoaderCircle, Redo2, Undo2, ShieldCheck, ShieldQuestionMark, TriangleAlert } from '@/components/ui/icons'
import { ICON_SIZE } from '@/components/ui/Icon'
import { Checkbox } from '@/components/ui/Checkbox'
import { Select } from '@/components/ui/Select'
import { CanvasStage } from '@/canvas/CanvasStage'
import { CanvasTabs } from '@/components/CanvasTabs'
import { Inspector } from '@/components/inspector/Inspector'
import { LeftPanel } from '@/components/left/LeftPanel'
import { LeftRail } from '@/components/left/LeftRail'
import { useEngineSync } from '@/hooks/useEngineSync'
import { t as translate, type UiMessage } from '@/i18n'
import { cn } from '@/lib/utils'
import { useDocumentStore } from '@/store/documentStore'
import { usePanelRender } from '@/store/renderStore'
import { useUiStore } from '@/store/uiStore'
import type { CanvasObject, PanelObject } from '@/types/document'
import { useAssetStore } from '@/store/assetStore'
import type { AppsBridge } from './appsBridge'
import { sessionIdFor, unwrap, type OpenFigureResult, type PreflightPayload } from './session'

/**
 * Codex 内嵌的 Tavotto 画布。
 *
 * 这个组件本身**不做任何图形编辑逻辑**——拖拽、命中测试、shift 锁向、吸附、
 * 属性表单、撤销重做全部由 `CanvasStage` / `Inspector` / 既有 stores
 * 承担，与 Tavotto 桌面版跑的是同一份代码。这里只负责三件事：
 *
 *   1. 顶部把「按哪套规范、多大、预检怎么样、有没有还没画上的改动、渲染错了没」
 *      摆出来（用户在别人的界面里，看不到 Tavotto 的状态栏）；
 *   2. 预检 / 导出这两个动作转成 `tools/call`；
 *   3. 拿不出结构化控件的属性，如实说「这条得回代码改」，而不是造一个点了没用的开关。
 */
export function McpApp({
  bridge,
  open,
  panelId,
}: {
  bridge: AppsBridge
  open: OpenFigureResult
  panelId: string | null
}) {
  // 既有的引擎同步器：文档一变就按策略重渲染。传输层已经换成 MCP 了，
  // 这里一行都不用改
  useEngineSync()

  const objects = useDocumentStore((s) => s.doc.objects)
  const page = useDocumentStore((s) => s.doc.page)
  const doc = useDocumentStore((s) => s.doc)
  const assets = useAssetStore((s) => s.byId)
  const panel = objects.find((o): o is PanelObject => o.id === panelId && o.type === 'panel')
  const canUndo = useDocumentStore((s) => s.past.length > 0)
  const canRedo = useDocumentStore((s) => s.future.length > 0)
  const undo = useDocumentStore((s) => s.undo)
  const redo = useDocumentStore((s) => s.redo)
  const leftOpen = useUiStore((s) => s.leftOpen)
  const rightOpen = useUiStore((s) => s.rightOpen)

  // Keep the latest document available to the unmount flush below. The
  // debounced effect handles ordinary edits; this ref closes the gap when a
  // user immediately returns to Figure Studio after the last edit.
  const latestDoc = useRef(doc)
  latestDoc.current = doc

  // MCP 会话绕过桌面版 App 的布局初始化。等 hydration 把首个 panel 装进
  // document 后再打开官方 Inspector；过早设置会被 session restore 的布局快照覆盖。
  const inspectorInitialized = useRef(false)
  useEffect(() => {
    if (inspectorInitialized.current || !panel) return
    inspectorInitialized.current = true
    if (!useUiStore.getState().rightOpen) useUiStore.getState().setRightTab('properties')
  }, [panel])

  // usePanelRender 接受 null（面板还没到位时不该造一个假对象骗它）
  const render = usePanelRender(panel)
  const rendering = render?.status === 'rendering'
  const renderError = render?.status === 'error' ? render.error : null
  // 「有改动还没画上」：文档里的 overrides 与最近画成功的那一版不一致
  const pending =
    !!panel && JSON.stringify(panel.overrides) !== (render?.lastPatches ?? '[]')

  const [preflight, setPreflight] = useState<PreflightPayload | null>(open.preflight ?? null)
  const [preflightStale, setPreflightStale] = useState(false)
  const [busy, setBusy] = useState<'preflight' | 'export' | null>(null)
  const [notice, setNotice] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  const [confirmForced, setConfirmForced] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [exportFormats, setExportFormats] = useState<string[]>(['pdf', 'png'])
  const [exportDpi, setExportDpi] = useState('600')
  const sessionId = open.blank ? '' : (sessionIdFor(open.stem + '.pdf') ?? open.session_id)

  // The iframe can be destroyed when the user returns to the Figure Studio
  // project list. Persist the host composition outside browser storage so a
  // later open restores Figure 1, positions, annotations and dimensions.
  useEffect(() => {
    if (!open.blank || !open.project) return
    const state = useDocumentStore.getState().buildProject()
    const timer = window.setTimeout(() => {
      void bridge.callTool('tavotto_save_canvas', {
        project_path: open.project,
        state,
      }).catch(() => {
        // A transient host restart must not interrupt editing; the next edit
        // retries the same durable snapshot.
      })
    }, 400)
    return () => window.clearTimeout(timer)
  }, [bridge, doc, open.blank, open.project])

  useEffect(() => {
    if (!open.blank || !open.project) return
    return () => {
      void bridge.callTool('tavotto_save_canvas', {
        project_path: open.project,
        state: useDocumentStore.getState().buildProject() ?? latestDoc.current,
      }).catch(() => {
        // The next open will still show the last durable snapshot if the
        // host is restarting while the iframe is being closed.
      })
    }
  }, [bridge, open.blank, open.project])

  // 改过图之后旧的预检结论就不作数了——**标成过期而不是留着**，
  // 留着的话用户会拿一份属于上一版的「通过」去导出
  const lastPatches = render?.lastPatches
  const firstRun = useRef(true)
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false
      return
    }
    setPreflightStale(true)
    setConfirmForced(false)
  }, [lastPatches])

  const runPreflight = useCallback(async () => {
    if (open.blank) return
    setBusy('preflight')
    setNotice(null)
    try {
      const body = unwrap(await bridge.callTool('tavotto_preflight', { session_id: sessionId }))
      setPreflight(body as unknown as PreflightPayload)
      setPreflightStale(false)
    } catch (err) {
      setNotice({ tone: 'bad', text: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy(null)
    }
  }, [bridge, sessionId, open.blank])

  const runExport = useCallback(
    async (formats: string[], dpi = 600) => {
      if (open.blank && objects.length === 0) return
      setBusy('export')
      setNotice(null)
      try {
        const canvasObjects = objects.map((object) => canvasExportObject(object, assets))
        const request = open.blank
          ? {
              scope: 'canvas',
              page_w_mm: page.w,
              page_h_mm: page.h,
              objects: canvasObjects,
              formats,
              dpi,
              stem: 'Figure_1',
              out_dir: `${open.project}/exports`,
              transparent: !!page.transparent,
            }
          : {
              session_id: sessionId,
              formats,
              dpi,
              explicit_confirm: confirmForced,
            }
        const body = unwrap(
          await bridge.callTool('tavotto_export', request),
        )
        const files = (body.files as { path: string }[]) ?? []
        setPreflight((body.preflight as PreflightPayload) ?? preflight)
        setPreflightStale(false)
        setNotice({ tone: 'ok', text: mc('exported', { files: files.map((f) => f.path).join('、') }) })
        // 这句是**发给 Codex 的对话内容**，不是界面文案：它进的是聊天记录，
        // 语言该跟着那边的对话走，不该被这个 webview 的界面语言改写
        bridge.sendMessage(`我在画布里改完并导出了 ${open.stem}：${files.map((f) => f.path).join('、')}`)
      } catch (err) {
        setNotice({ tone: 'bad', text: err instanceof Error ? err.message : String(err) })
      } finally {
        setBusy(null)
      }
    },
    [bridge, sessionId, confirmForced, open.stem, open.project, preflight, open.blank, objects, assets, page],
  )

  // 手势结束后画布尺寸可能变了：告诉 host 一声（inline 模式下它据此调高度）
  useEffect(() => {
    bridge.notifySize()
  }, [bridge, panel?.w, panel?.h])

  const counts = preflight?.counts ?? {}
  const needsConfirm =
    !!preflight
    && ((preflight.errors ?? []).length > 0 || (preflight.not_verifiable ?? []).length > 0)

  return (
    <div className="flex h-full w-full flex-col bg-bg text-ink">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
        <span className="truncate text-base font-medium">{open.stem}</span>
        <span className="shrink-0 rounded-sm bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-ink-3">
          {open.profile?.profile_id ?? 'blank'}{open.profile?.profile_version ? ` v${open.profile.profile_version}` : ''}
        </span>
        <span className="shrink-0 font-mono text-xs text-ink-3">
          {translate('measure.mmSize', {
            w: (panel?.w ?? 150).toFixed(1),
            h: (panel?.h ?? 100).toFixed(1),
          })}
        </span>

        <span className="mx-1 h-4 w-px bg-border" />
        <IconButton label={translate('topbar.undo', { ns: 'workspace' })} disabled={!canUndo} onClick={() => undo()}>
          <Undo2 size={ICON_SIZE.md} />
        </IconButton>
        <IconButton label={translate('topbar.redo', { ns: 'workspace' })} disabled={!canRedo} onClick={() => redo()}>
          <Redo2 size={ICON_SIZE.md} />
        </IconButton>

        <MarkTools />

        <span className="flex-1" />

        <RenderState rendering={rendering} pending={pending} error={renderError} />
        <PreflightPill
          counts={counts}
          stale={preflightStale}
          loading={busy === 'preflight'}
          disabled={open.blank}
          onClick={() => void runPreflight()}
        />
        <button
          className="flex h-7 shrink-0 items-center gap-1.5 rounded-sm bg-ink px-2.5 text-xs text-white disabled:opacity-40"
          disabled={(open.blank && objects.length === 0) || busy != null || pending || (needsConfirm && !confirmForced)}
          title={
            pending
              ? mc('exportPendingTitle')
              : needsConfirm && !confirmForced
                ? mc('exportBlockedTitle')
                : undefined
          }
          onClick={() => setExportOpen(true)}
        >
          {busy === 'export' ? <LoaderCircle size={ICON_SIZE.sm} className="animate-spin" /> : <Download size={ICON_SIZE.sm} />}
          {mc('export')}
        </button>
      </header>

      {needsConfirm && (
        <label className="flex shrink-0 items-start gap-1.5 border-b border-border bg-danger-subtle px-3 py-1.5 text-xs text-ink-2">
          <Checkbox
            checked={confirmForced}
            onChange={(e) => setConfirmForced(e.target.checked)}
            className="mt-0.5"
          />
          {/* 两种情况各是一句完整的话，不拼字符串（英文从句位置与中文不同） */}
          <span>
            {preflight!.not_verifiable.length > 0
              ? mc('confirmBoth', {
                  errors: preflight!.errors.length,
                  notVerifiable: preflight!.not_verifiable.length,
                })
              : mc('confirmErrors', { errors: preflight!.errors.length })}
          </span>
        </label>
      )}

      {notice && (
        <p
          className={cn(
            'shrink-0 truncate border-b border-border px-3 py-1.5 text-xs',
            notice.tone === 'ok' ? 'text-ink-2' : 'text-danger',
          )}
        >
          {notice.tone === 'ok' ? notice.text : <FigureError error={notice.text} context="bridge" />}
        </p>
      )}

      {open.blank && (
        <p className="shrink-0 border-b border-border bg-surface-2 px-3 py-1.5 text-xs text-ink-2">
          {translate('mcp.blankCanvasHint', {
            ns: 'dialogs',
            defaultValue: '这是一个空白 Tavotto 画布。请从素材栏添加图形；添加对象后即可导出。',
          })}
      </p>
      )}

      {exportOpen && (
        <ExportPanel
          formats={exportFormats}
          dpi={exportDpi}
          busy={busy === 'export'}
          onToggle={(format) => setExportFormats((current) => current.includes(format) ? current.filter((item) => item !== format) : [...current, format])}
          onDpi={setExportDpi}
          onCancel={() => setExportOpen(false)}
          onExport={() => {
            setExportOpen(false)
            void runExport(exportFormats.length ? exportFormats : ['pdf', 'png'], Number(exportDpi))
          }}
        />
      )}

      <div className="relative flex min-h-0 flex-1 bg-bg">
        {/* MCP 画布仍然使用同一套 Tavotto 工作台侧栏：素材、画布、图层、图内
            元素和问题面板都是真实 store / action，不是静态演示。MCP 会话没有
            HTTP 项目端点，种子素材由 embedded/session.ts 注入，之后对图层的
            选择、排序、隐藏和锁定继续走既有 documentStore。 */}
        <LeftRail />
        {leftOpen && <LeftPanel />}
        {/* CanvasStage 的根是 `flex-1`：**外面必须是 flex 容器**，否则它在普通
            block 父级里高度塌成 0，画布连同面板被 overflow-hidden 整块裁掉
            ——DOM 还在、getBoundingClientRect 还有值，只是既画不出来也点不中
            （e2e/mcp-canvas.spec.ts 的第一版就撞在这上面） */}
        <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
          <CanvasTabs />
          <div className="relative flex min-h-0 min-w-0 flex-1">
            <CanvasStage />
          </div>
        </div>
        {rightOpen && <Inspector />}
      </div>
      <CommandPalette />
    </div>
  )
}

function canvasExportObject(object: CanvasObject, assets: Record<string, import('@/lib/api').PanelInfo>): Record<string, unknown> {
  const base = { type: object.type, x_mm: object.x, y_mm: object.y, w_mm: object.w, h_mm: object.h, rotation_deg: object.rotationDeg ?? 0 }
  if (object.type === 'panel') {
    const asset = assets[object.fileId]
    return {
      ...base,
      id: object.fileId,
      source_path: asset?.source_path,
      rotation: object.rotation ?? 0,
      crop: object.crop,
      opacity: object.opacity,
      flip_h: object.flipH,
      flip_v: object.flipV,
    }
  }
  if (object.type === 'text') {
    return { ...base, text: object.text, size_pt: object.sizePt, font_family: object.fontFamily, interpretation: object.interpretation, bold: object.bold, italic: object.italic, color: object.color, align: object.align, underline: object.underline, line_height: object.lineHeight, padding_mm: object.padding, bg: object.bg, border_color: object.borderColor, border_pt: object.borderPt }
  }
  if (object.type === 'arrow') {
    return { ...base, start: object.start, end: object.end, stroke_pt: object.strokePt, color: object.color, head: object.head, head_start: object.headStart, head_end: object.headEnd, dash: object.dash }
  }
  return { ...base, shape: object.shape, stroke_pt: object.strokePt, color: object.color, fill: object.fill, dash: object.dash, start: object.start, end: object.end, sides: object.sides, corner_radius_mm: object.cornerRadius }
}

function ExportPanel({
  formats,
  dpi,
  busy,
  onToggle,
  onDpi,
  onCancel,
  onExport,
}: {
  formats: string[]
  dpi: string
  busy: boolean
  onToggle: (format: string) => void
  onDpi: (dpi: string) => void
  onCancel: () => void
  onExport: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" role="dialog" aria-label={mc('export')}>
      <div className="w-80 rounded-md border border-border bg-surface p-4 shadow-pop">
        <h2 className="mb-3 text-sm font-medium">{mc('exportCanvas')}</h2>
        <div className="mb-3 flex flex-col gap-2 text-xs">
          {['pdf', 'png', 'tiff'].map((format) => (
            <label key={format} className="flex items-center gap-2">
              <Checkbox checked={formats.includes(format)} onChange={() => onToggle(format)} />
              <span>{format.toUpperCase()}</span>
            </label>
          ))}
        </div>
        <label className="mb-4 flex items-center justify-between text-xs">
          <span>{mc('dpi')}</span>
          <Select
            value={dpi}
            onChange={onDpi}
            options={['300', '600', '900', '1200'].map((value) => ({ value, label: value }))}
            ariaLabel={mc('dpi')}
            className="w-24"
          />
        </label>
        <div className="flex justify-end gap-2">
          <button className="rounded border border-border px-3 py-1 text-xs" onClick={onCancel}>{mc('cancel')}</button>
          <button className="rounded bg-ink px-3 py-1 text-xs text-white disabled:opacity-40" disabled={busy || formats.length === 0} onClick={onExport}>{mc('export')}</button>
        </div>
      </div>
    </div>
  )
}

function IconButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string
  disabled?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm text-ink-2 hover:bg-surface-2 disabled:opacity-40"
    >
      {children}
    </button>
  )
}

/** 渲染态：正在画 / 有改动没画上 / 画失败了。三者都必须看得见。 */
function RenderState({
  rendering,
  pending,
  error,
}: {
  rendering: boolean
  pending: boolean
  error: UiMessage | null
}) {
  if (error) {
    return (
      <span className="flex shrink-0 items-center gap-1 text-xs text-danger"
            title={mc('renderFailed')}>
        <TriangleAlert size={ICON_SIZE.sm} />
        <FigureError error={error} context="render" />
      </span>
    )
  }
  if (rendering) {
    return (
      <span className="flex shrink-0 items-center gap-1 text-xs text-ink-3">
        <LoaderCircle size={ICON_SIZE.sm} className="animate-spin" />
        {mc('rendering')}
      </span>
    )
  }
  if (pending) {
    return (
      <span className="flex shrink-0 items-center gap-1 text-xs text-ink-3">
        <LoaderCircle size={ICON_SIZE.sm} />
        {mc('pending')}
      </span>
    )
  }
  return (
    <span className="flex shrink-0 items-center gap-1 text-xs text-ink-3">
      <Check size={ICON_SIZE.sm} />
      {mc('synced')}
    </span>
  )
}

function PreflightPill({
  counts,
  stale,
  loading,
  disabled,
  onClick,
}: {
  counts: Record<string, number>
  stale: boolean
  loading: boolean
  disabled?: boolean
  onClick: () => void
}) {
  const err = counts.error ?? 0
  const warn = counts.warn ?? 0
  const nv = counts.not_verifiable ?? 0
  const clean = err + warn + nv === 0
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'flex h-7 shrink-0 items-center gap-1.5 rounded-sm border px-2 text-xs',
        stale
          ? 'border-border bg-surface-2 text-ink-3'
          : err
            ? 'border-danger/40 text-danger'
            : 'border-border text-ink-2',
      )}
      title={stale ? mc('pillStaleTitle') : mc('pillTitle')}
    >
      {loading ? (
        <LoaderCircle size={ICON_SIZE.sm} className="animate-spin" />
      ) : err ? (
        <TriangleAlert size={ICON_SIZE.sm} />
      ) : nv ? (
        <ShieldQuestionMark size={ICON_SIZE.sm} />
      ) : (
        <ShieldCheck size={ICON_SIZE.sm} />
      )}
      {stale
        ? mc('pillStale')
        : clean
          ? mc('pillClean')
          : mc('pillCounts', { errors: err, warnings: warn, notVerifiable: nv })}
    </button>
  )
}

/** MCP 画布这一屏的文案都在 `dialogs:mcp.*` 下 */
const mc = (key: string, values?: Record<string, unknown>) =>
  translate(`mcp.${key}`, { ns: 'dialogs', ...(values ?? {}) })
