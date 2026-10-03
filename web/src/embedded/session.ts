import type { Manifest, PanelInfo, RegistryView } from '@/lib/api'
import { VECTOR_PREVIEW, type PreviewMetadata } from '@/lib/previewBudget'
import type { UiMessage } from '@/i18n'
import { useAssetStore } from '@/store/assetStore'
import { useRuntimeAssetStore } from '@/store/runtimeAssetStore'
import { useScriptLibraryStore } from '@/store/scriptLibraryStore'
import { applyDerivedUpdate, useDocumentStore } from '@/store/documentStore'
import { renderKey, svgPayloadBytes, useRenderStore } from '@/store/renderStore'
import { useUiStore } from '@/store/uiStore'
import { newId } from '@/lib/id'
import type { PanelObject, PanelOverride } from '@/types/document'

/**
 * 内嵌会话的通用种子层：把「一张已经渲染好的图」灌进既有 stores，
 * 让画布把它当成一个普通面板。
 *
 * 两个消费方：Codex 的 MCP 画布（`mcp/session.ts`）与浏览器 playground
 * （`playground/`）。它们的区别只在「渲染请求怎么送出去」（tools/call vs
 * Pyodide Worker）——**种进 stores 的东西必须一模一样**，否则拖拽、命中、
 * undo 在两边就不再是同一件事。这层从 MCP 会话里抽出来，就是为了不让
 * 第二个消费方复制一份然后各自漂移。
 *
 * 灌的东西一件不多：assetStore 一条素材、documentStore 一个面板、renderStore
 * 一份「已经画好了」的渲染态。之后的拖拽、命中测试、属性编辑、undo/redo
 * 全部是既有代码在跑。
 */
export interface EmbeddedFigure {
  /** 引擎里的 stem；面板的 fileId 是 `${stem}.pdf`（`embeddedFileIdFor`） */
  stem: string
  /** 素材面板显示的目录/项目标识（playground 里是虚拟工作区） */
  project: string
  /** 产出这张图的脚本名 */
  script: string
  /** 渲染开销档位（渲染看门狗按它分级）；缺省 medium */
  cost?: string
  manifest: Manifest
  svg: string | null
  /** First-frame raster returned in the same MCP response, when selected. */
  previewPngBase64?: string
  /**
   * 这一版的预览表示法（ADR 0022）。缺省按 `vector` 解读；`svg` 为 null 而
   * 引擎给出 `raster` 时，画布走位图显示——**编辑语义一个字都不变**。
   */
  preview?: PreviewMetadata
  renderRevision?: number
  warnings?: string[]
  overrides?: PanelOverride[]
}

export const embeddedFileIdFor = (stem: string) => `${stem}.pdf`

export function seedEmbeddedSession(
  fig: EmbeddedFigure,
  historyLabel: UiMessage,
): { panelId: string; fileId: string } {
  const [wMm, hMm] = fig.manifest.size_mm
  const fileId = embeddedFileIdFor(fig.stem)
  const overrides = fig.overrides ?? []

  const info: PanelInfo = {
    id: fileId,
    name: fig.stem,
    folder: fig.project,
    kind: 'pdf',
    native_w_mm: wMm,
    native_h_mm: hMm,
    mtime: 0,
    script: fig.script,
    cost: fig.cost ?? 'medium',
    preview_url: fig.previewPngBase64
      ? `data:image/png;base64,${fig.previewPngBase64}`
      : fig.svg
        ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(fig.svg)}`
        : null,
  }
  useAssetStore.setState({
    byId: { [fileId]: info },
    panels: [info],
    figuresDir: fig.project,
    loaded: true,
    loading: false,
    error: null,
  })
  // The MCP iframe has no HTTP project endpoint.  Keep the real opened figure
  // in the ordinary asset store while marking the runtime list as loaded so
  // AssetBrowser does not issue a cross-origin request.
  useRuntimeAssetStore.setState({ assets: [], assetsLoading: false, assetsError: null })
  const script = fig.script.trim()
  if (script) {
    const registryView: RegistryView = {
      source: 'mcp-session',
      scripts: {
        [script]: { entry: 'main', cost: fig.cost ?? 'medium', notes: '', stems: [fig.stem] },
      },
      candidates: [],
      conflicts: {},
      all_scripts: [{
        script,
        registered: true,
        static_stems: [fig.stem],
        entry_candidates: ['main'],
        reason: 'registered',
        can_probe: false,
      }],
    }
    useScriptLibraryStore.setState({ view: registryView, loading: false, loaded: true, error: null })
  } else {
    useScriptLibraryStore.setState({ view: null, loading: false, loaded: true, error: null })
  }

  const panelId = newId('o')
  const panel: PanelObject = {
    id: panelId,
    type: 'panel',
    x: 0,
    y: 0,
    w: wMm,
    h: hMm,
    fileId,
    fileKind: 'pdf',
    nativeW: wMm,
    nativeH: hMm,
    script: fig.script,
    cost: fig.cost,
    overrides,
  }

  const store = useDocumentStore.getState()
  store.commit(historyLabel, (d) => {
    d.name = fig.stem
    // 页面就是这张图自己的尺寸：内嵌画布编辑的是**一张图**，不是拼版
    d.page = { w: wMm, h: hMm }
    d.objects = [panel]
    d.guides = []
  })
  // 打开动作不该出现在撤销栈里（用户的第一次撤销要回到「刚打开的样子」）
  useDocumentStore.setState({ past: [], future: [], dirty: false })

  const key = renderKey(fileId, [])
  useRenderStore.setState({
    byKey: {
      [key]: {
        fileId,
        rev: fig.renderRevision ?? 1,
        manifest: fig.manifest,
        svg: fig.svg ? prepareEmbeddedSvg(fig.svg) : null,
        // 种子这一份也要记账：内嵌画布的第一帧同样是驻留的 SVG payload，
        // 漏记的话它对预算隐形（而它恰恰是**唯一**能显示的那一份，见
        // renderStore 的 pin 规则——latest 指着它，所以它永远不会被驱逐）
        svgBytes: fig.svg ? svgPayloadBytes(fig.svg, fig.preview ?? VECTOR_PREVIEW) : 0,
        svgEvicted: false,
        svgSeq: 0,
        preview: fig.preview ?? VECTOR_PREVIEW,
        status: 'ready',
        error: null,
        code: '',
        module: '',
      projectEnv: null,
      dependencyRepair: null,
        traceback: '',
        warnings: fig.warnings ?? [],
        timings: {},
        stale: false,
        lastPatches: JSON.stringify(overrides),
        wantPatches: JSON.stringify(overrides),
        previewDpi: null,
      },
    },
    // 文件级跟踪位：显示必须走引擎产物，而不是并不存在的 /api/render
    tracked: { [fileId]: true },
    latest: { [fileId]: key },
    building: {},
  })

  // 直接进图内编辑态：内嵌画布存在的全部理由就是改图里的元素
  useUiStore.getState().setElementPanel(panelId)
  return { panelId, fileId }
}

/** Append a complete sibling Tavotto session to the current real composition. */
export function appendEmbeddedSession(
  fig: EmbeddedFigure,
  _historyLabel: UiMessage,
): { panelId: string; fileId: string } {
  const [wMm, hMm] = fig.manifest.size_mm
  const fileId = embeddedFileIdFor(fig.stem)
  const overrides = fig.overrides ?? []
  const info: PanelInfo = {
    id: fileId,
    name: fig.stem,
    folder: fig.project,
    kind: 'pdf',
    native_w_mm: wMm,
    native_h_mm: hMm,
    mtime: 0,
    script: fig.script || undefined,
    cost: fig.cost ?? 'medium',
    preview_url: fig.previewPngBase64
      ? `data:image/png;base64,${fig.previewPngBase64}`
      : fig.svg
        ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(fig.svg)}`
        : null,
  }
  useAssetStore.setState((s) => ({
    byId: { ...s.byId, [fileId]: info },
    panels: s.panels.some((p) => p.id === fileId) ? s.panels : [...s.panels, info],
    figuresDir: fig.project,
    loaded: true,
    loading: false,
    error: null,
  }))

  const script = fig.script.trim()
  if (script) {
    useScriptLibraryStore.setState((s) => {
      const view = s.view ?? { source: 'mcp-session', scripts: {}, candidates: [], conflicts: {}, all_scripts: [] }
      const existing = view.scripts[script]
      const allScripts = view.all_scripts.filter((entry) => entry.script !== script)
      const current = view.all_scripts.find((entry) => entry.script === script)
      allScripts.push({
        script,
        registered: true,
        static_stems: Array.from(new Set([...(current?.static_stems ?? []), fig.stem])),
        entry_candidates: current?.entry_candidates?.length ? current.entry_candidates : ['main'],
        reason: 'registered',
        can_probe: false,
      })
      return {
        view: {
          ...view,
          scripts: {
            ...view.scripts,
            [script]: {
              entry: existing?.entry ?? 'main',
              cost: existing?.cost ?? fig.cost ?? 'medium',
              notes: existing?.notes ?? '',
              stems: Array.from(new Set([...(existing?.stems ?? []), fig.stem])),
            },
          },
          all_scripts: allScripts,
        },
        loaded: true,
        loading: false,
        error: null,
      }
    })
  }

  const panelId = newId('o')
  const doc = useDocumentStore.getState().doc
  const right = doc.objects.reduce((x, o) => Math.max(x, o.x + o.w), 0)
  const panel: PanelObject = {
    id: panelId,
    type: 'panel',
    x: right + 8,
    y: 0,
    w: wMm,
    h: hMm,
    fileId,
    fileKind: 'pdf',
    nativeW: wMm,
    nativeH: hMm,
    script: fig.script || undefined,
    cost: fig.cost,
    overrides,
  }
  // Hydration is a load operation, not a user edit: no fake undo step or dirty flag.
  applyDerivedUpdate({
    doc: {
      ...doc,
      objects: [...doc.objects, panel],
      page: {
        w: Math.max(doc.page.w, panel.x + panel.w),
        h: Math.max(doc.page.h, panel.y + panel.h),
      },
    },
  })

  const key = renderKey(fileId, overrides)
  useRenderStore.setState((s) => ({
    byKey: {
      ...s.byKey,
      [key]: {
        fileId,
        rev: fig.renderRevision ?? 1,
        manifest: fig.manifest,
        svg: fig.svg ? prepareEmbeddedSvg(fig.svg) : null,
        svgBytes: fig.svg ? svgPayloadBytes(fig.svg, fig.preview ?? VECTOR_PREVIEW) : 0,
        svgEvicted: false,
        svgSeq: 0,
        preview: fig.preview ?? VECTOR_PREVIEW,
        status: 'ready',
        error: null,
        code: '',
        module: '',
        projectEnv: null,
        dependencyRepair: null,
        traceback: '',
        warnings: fig.warnings ?? [],
        timings: {},
        stale: false,
        lastPatches: JSON.stringify(overrides),
        wantPatches: JSON.stringify(overrides),
        previewDpi: null,
      },
    },
    tracked: { ...s.tracked, [fileId]: true },
    latest: { ...s.latest, [fileId]: key },
  }))
  return { panelId, fileId }
}

/**
 * Register a figure returned while refreshing an already-open host project as
 * a material only. Unlike appendEmbeddedSession this deliberately does not
 * create a document panel, change the page size, or select the object. The
 * user can insert it from the materials card when they choose.
 */
export function registerEmbeddedMaterial(fig: EmbeddedFigure): { fileId: string } {
  const [wMm, hMm] = fig.manifest.size_mm
  const fileId = embeddedFileIdFor(fig.stem)
  const info: PanelInfo = {
    id: fileId,
    name: fig.stem,
    folder: fig.project,
    kind: 'pdf',
    native_w_mm: wMm,
    native_h_mm: hMm,
    mtime: 0,
    script: fig.script || undefined,
    cost: fig.cost ?? 'medium',
    preview_url: fig.previewPngBase64
      ? `data:image/png;base64,${fig.previewPngBase64}`
      : fig.svg
        ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(fig.svg)}`
        : null,
  }
  useAssetStore.setState((s) => ({
    byId: { ...s.byId, [fileId]: info },
    panels: s.panels.some((p) => p.id === fileId) ? s.panels : [...s.panels, info],
    figuresDir: fig.project,
    loaded: true,
    loading: false,
    error: null,
  }))
  const script = fig.script.trim()
  if (script) {
    useScriptLibraryStore.setState((s) => {
      const view = s.view ?? { source: 'mcp-session', scripts: {}, candidates: [], conflicts: {}, all_scripts: [] }
      const existing = view.scripts[script]
      const current = view.all_scripts.find((entry) => entry.script === script)
      return {
        view: {
          ...view,
          scripts: {
            ...view.scripts,
            [script]: {
              entry: existing?.entry ?? 'main',
              cost: existing?.cost ?? fig.cost ?? 'medium',
              notes: existing?.notes ?? '',
              stems: Array.from(new Set([...(existing?.stems ?? []), fig.stem])),
            },
          },
          all_scripts: [
            ...view.all_scripts.filter((entry) => entry.script !== script),
            {
              script,
              registered: true,
              static_stems: Array.from(new Set([...(current?.static_stems ?? []), fig.stem])),
              entry_candidates: current?.entry_candidates?.length ? current.entry_candidates : ['main'],
              reason: 'registered',
              can_probe: false,
            },
          ],
        },
        loaded: true,
        loading: false,
        error: null,
      }
    })
  }
  return { fileId }
}

/**
 * matplotlib 的 SVG 自带 pt 单位的 width/height，去掉后配合
 * preserveAspectRatio=none 才能精确铺满面板框。与 renderStore 里那份同源
 * ——种子数据也必须过同一道处理，否则第一帧与之后每一帧的尺寸口径不同。
 */
export function prepareEmbeddedSvg(text: string): string {
  return text.replace(/<svg([^>]*)>/, (_m, attrs: string) => {
    const cleaned = attrs.replace(/\s(?:width|height)="[^"]*"/g, '')
    return `<svg${cleaned} preserveAspectRatio="none" style="width:100%;height:100%;display:block">`
  })
}
