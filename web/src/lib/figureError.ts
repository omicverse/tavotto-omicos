/** First-party presentation only. Never modifies server diagnostics or user data. */
export type FigureErrorCode =
  | 'FIGURE_START_FAILED' | 'FIGURE_SESSION_EXITED' | 'FIGURE_BUNDLE_MISSING'
  | 'FIGURE_BUNDLE_CORRUPT' | 'FIGURE_BUNDLE_INTEGRITY' | 'FIGURE_MCP_INSTALL_FAILED'
  | 'FIGURE_BRIDGE_CONNECT_FAILED' | 'FIGURE_NETWORK_OFFLINE' | 'FIGURE_RENDER_FAILED'
  | 'FIGURE_SCRIPT_FAILED' | 'FIGURE_PROJECT_INCOMPATIBLE' | 'FIGURE_ENVIRONMENT_FAILED'
  | 'FIGURE_OPERATION_FAILED' | 'FIGURE_TARGET_CHANGED'
export interface FigureFailure { readonly code: FigureErrorCode; readonly raw: string }
export type FigureErrorContext = 'start' | 'exit' | 'bundle' | 'mcp-install' | 'bridge'
  | 'network' | 'render' | 'script' | 'project' | 'environment' | 'operation' | 'target'

// Static text only: no interpolated file paths, exception strings or server names.
const catalog: Record<FigureErrorCode, readonly [string, string, string, string]> = {
  FIGURE_START_FAILED: ['工作台未能启动', '关闭失败会话后重新打开；若仍失败，展开详情并联系支持。', 'The workbench could not start', 'Close the failed session and open it again. If it fails again, open details and contact support.'],
  FIGURE_SESSION_EXITED: ['工作台会话意外退出', '重新打开工作台并恢复已保存文档；未保存的修改请先检查恢复提示。', 'The workbench session exited unexpectedly', 'Reopen the workbench and restore the saved document. Check the recovery notice for unsaved changes.'],
  FIGURE_BUNDLE_MISSING: ['自带运行包缺失或不可读取', '修复 OmicOS 安装并恢复随版本提供的运行包，再重新打开；不会下载公共替代包。', 'The bundled runtime is missing or unreadable', 'Repair the OmicOS installation and restore its bundled runtime, then reopen. No public replacement is downloaded.'],
  FIGURE_BUNDLE_CORRUPT: ['自带运行包损坏或结构无效', '使用当前 OmicOS 版本的完整运行包修复安装；不要修改校验值。', 'The bundled runtime is damaged or invalid', 'Repair the installation with the complete runtime for this OmicOS version. Do not change the verification values.'],
  FIGURE_BUNDLE_INTEGRITY: ['运行包完整性校验失败', '停止使用此运行包，从可信安装介质恢复当前版本后重试；不要绕过校验。', 'Runtime integrity verification failed', 'Stop using this bundle. Restore the current version from trusted installation media and retry. Do not bypass verification.'],
  FIGURE_MCP_INSTALL_FAILED: ['AI 图形工具安装失败', '检查可用磁盘空间和包缓存权限，再点击“启用图形工具”重试。', 'AI figure-tool installation failed', 'Check available disk space and package-cache permissions, then retry Enable figure tools.'],
  FIGURE_BRIDGE_CONNECT_FAILED: ['AI 图形工具连接失败', '确认内核和工作台仍在运行，然后重新连接图形工具。', 'The AI figure-tool connection failed', 'Confirm the kernel and workbench are running, then reconnect the figure tools.'],
  FIGURE_NETWORK_OFFLINE: ['工作台连接中断', '恢复所选内核的连接后重试；不要切换内核来覆盖原项目。', 'The workbench connection was interrupted', 'Restore the selected kernel connection and retry. Do not switch kernels to overwrite the original project.'],
  FIGURE_RENDER_FAILED: ['图形渲染失败', '保留当前文档；检查项目运行环境后点击重新渲染。', 'Figure rendering failed', 'Keep the current document. Check its runtime environment and retry rendering.'],
  FIGURE_SCRIPT_FAILED: ['绘图脚本执行失败', '查看详情定位脚本错误，在项目环境中修复后重新运行；不会自动覆盖源脚本。', 'The plotting script failed', 'Use details to locate the script error, fix it in the project environment, and rerun. The source is not overwritten automatically.'],
  FIGURE_PROJECT_INCOMPATIBLE: ['项目或文件无法打开', '保留原文件；检查格式、版本和引用素材，必要时从原版本重新导出项目。', 'The project or file could not be opened', 'Keep the original file. Check its format, version, and referenced assets; re-export from the original version if needed.'],
  FIGURE_ENVIRONMENT_FAILED: ['项目运行环境不可用', '在项目环境设置中选择有效解释器，验证依赖后重试。', 'The project runtime is unavailable', 'Select a valid interpreter in project environment settings, verify dependencies, and retry.'],
  FIGURE_OPERATION_FAILED: ['工作台操作失败', '保留当前文档并重试该操作；若仍失败，展开详情并联系支持。', 'The workbench operation failed', 'Keep the current document and retry the operation. If it still fails, open details and contact support.'],
  FIGURE_TARGET_CHANGED: ['运行目标已改变', '返回原内核继续编辑，或为新内核显式打开项目；原会话不会自动迁移。', 'The runtime target changed', 'Return to the original kernel or explicitly open a project on the new kernel. The old session is not moved automatically.'],
}
const contexts: Record<FigureErrorContext, FigureErrorCode> = {
  start:'FIGURE_START_FAILED', exit:'FIGURE_SESSION_EXITED', bundle:'FIGURE_BUNDLE_CORRUPT',
  'mcp-install':'FIGURE_MCP_INSTALL_FAILED', bridge:'FIGURE_BRIDGE_CONNECT_FAILED',
  network:'FIGURE_NETWORK_OFFLINE', render:'FIGURE_RENDER_FAILED', script:'FIGURE_SCRIPT_FAILED',
  project:'FIGURE_PROJECT_INCOMPATIBLE', environment:'FIGURE_ENVIRONMENT_FAILED',
  operation:'FIGURE_OPERATION_FAILED', target:'FIGURE_TARGET_CHANGED',
}
export function diagnosticText(value: unknown): string {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object') {
    const v = value as Record<string, unknown>
    if (typeof v.rawDiagnostic === 'string') return v.rawDiagnostic
    if (typeof v.raw === 'string') return v.raw
    if (value instanceof Error) return value.stack || value.message
    if (v.key === 'literal' && v.values && typeof (v.values as {text?: unknown}).text === 'string') return (v.values as {text: string}).text
  }
  if (value === undefined) return ''
  try { return JSON.stringify(value, null, 2) ?? String(value) }
  catch { return String(value) } // original object remains owned by its caller
}
export function figureFailure(value: unknown, context: FigureErrorContext = 'operation'): FigureFailure {
  const raw = diagnosticText(value)
  const explicit = value && typeof value === 'object' ? (value as { code?: unknown }).code : null
  if (typeof explicit === 'string' && Object.prototype.hasOwnProperty.call(catalog, explicit)) {
    return Object.freeze({ code: explicit as FigureErrorCode, raw })
  }
  // Compatibility classification, NOT replacement/sanitisation. Raw is unchanged.
  let code = contexts[context]
  if (/SHA256 mismatch|source.build.*mismatch|FIGURE_BUNDLE_INTEGRITY/i.test(raw)) code='FIGURE_BUNDLE_INTEGRITY'
  else if (/bundle is missing|bundle.*unreadable|FIGURE_BUNDLE_MISSING/i.test(raw)) code='FIGURE_BUNDLE_MISSING'
  else if (/invalid zip|invalid archive|central directory|bad zip|FIGURE_BUNDLE_CORRUPT/i.test(raw)) code='FIGURE_BUNDLE_CORRUPT'
  else if (/exited unexpectedly|Tavotto exited|FIGURE_SESSION_EXITED/i.test(raw)) code='FIGURE_SESSION_EXITED'
  else if (/Failed to fetch|NetworkError|ERR_CONNECTION|Load failed|network.*(offline|disconnected)/i.test(raw)) code='FIGURE_NETWORK_OFFLINE'
  else if (['script', 'render', 'operation'].includes(context) && /script_error|script_failed|Traceback \(most recent call last\)|panel script/i.test(raw)) code='FIGURE_SCRIPT_FAILED'
  return Object.freeze({ code, raw })
}
export function figureErrorCopy(code: FigureErrorCode, locale: string) {
  const zh=locale.startsWith('zh'), row=catalog[code]
  return { product:zh?'OmicOS 图形工作台':'OmicOS Figure Studio', title:row[zh?0:2], next:row[zh?1:3],
    details:zh?'详情／复制给支持':'Details / copy for support', copy:zh?'复制原始诊断':'Copy raw diagnostics',
    download:zh?'保存诊断文件':'Save diagnostics', copied:zh?'已复制原文':'Raw diagnostics copied',
    copyFailed:zh?'复制不可用；请保存诊断文件。':'Copy is unavailable. Save the diagnostic file instead.',
    warning:zh?'诊断可能包含路径或敏感信息，请检查后再分享。':'Diagnostics may contain paths or sensitive information. Review before sharing.' }
}

/** Copy from an MCP App iframe even when async Clipboard API is unavailable.
 * WebView2 and sandboxed srcdoc frames can reject navigator.clipboard while
 * still allowing the user-gesture-bound legacy copy command. */
function copyWithDocumentCommand(text: string): boolean {
  if (typeof document.execCommand !== 'function') return false
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0;'
  document.body.appendChild(area)
  area.focus()
  area.select()
  try {
    return document.execCommand('copy')
  } finally {
    area.remove()
  }
}

async function copyDiagnosticText(text: string): Promise<void> {
  // Keep the first attempt synchronous so the user gesture survives inside
  // WebView2/srcdoc frames where Clipboard API permission is unavailable.
  if (copyWithDocumentCommand(text)) return
  if (typeof navigator.clipboard?.writeText === 'function') {
    await navigator.clipboard.writeText(text)
    return
  }
  throw new Error('clipboard unavailable')
}

/** Framework-independent, light-DOM error component. No hidden brand filtering. */
export class FigureErrorElement extends HTMLElement {
  private failure: FigureFailure = Object.freeze({code:'FIGURE_OPERATION_FAILED',raw:''})
  private locale = 'en'
  setFailure(failure: FigureFailure, locale: string): void {
    const same = this.failure.code === failure.code && this.failure.raw === failure.raw
    const expanded = same && !!this.querySelector('details')?.open
    this.failure=failure; this.locale=locale
    this.render(expanded)
  }
  connectedCallback(): void { this.render(false) }
  private render(expanded: boolean): void {
    const c=figureErrorCopy(this.failure.code,this.locale)
    this.replaceChildren()
    this.dataset.figureUserError=this.failure.code
    this.style.cssText='display:block;max-width:100%;font:inherit;line-height:1.55;overflow-wrap:anywhere;color:var(--oc-danger,var(--color-danger,#b0443a));'
    const title=document.createElement('span'); title.style.fontWeight='600'; title.textContent=`${c.product} · ${c.title}`
    const code=document.createElement('code');code.dataset.figureErrorCode='';code.textContent=this.failure.code;code.style.cssText='display:block;font-size:11px;'
    const next=document.createElement('span');next.textContent=c.next;next.style.display='block'
    const details=document.createElement('details');details.open=expanded;details.dataset.rawDiagnostics=''
    const summary=document.createElement('summary');summary.textContent=c.details;summary.style.cursor='pointer'
    const warning=document.createElement('span');warning.textContent=c.warning;warning.style.display='block'
    const pre=document.createElement('pre');pre.dataset.diagnosticRaw='';pre.textContent=this.failure.raw
    pre.style.cssText='max-height:240px;max-width:100%;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;color:var(--oc-txt,var(--color-ink,#243028));background:var(--oc-surface,var(--color-surface,#fafafa));padding:8px;'
    const status=document.createElement('span');status.setAttribute('role','status');status.style.display='block'
    const copy=document.createElement('button');copy.type='button';copy.textContent=c.copy;copy.dataset.copyDiagnostics=''
    copy.onclick=async()=>{try{await copyDiagnosticText(this.failure.raw);status.textContent=c.copied}catch{status.textContent=c.copyFailed}}
    const download=document.createElement('button');download.type='button';download.textContent=c.download;download.dataset.saveDiagnostics=''
    download.onclick=()=>{const u=URL.createObjectURL(new Blob([this.failure.raw],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=u;a.download='omicos-figure-diagnostics.txt';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}
    for(const b of [copy,download])b.style.cssText='margin:4px 8px 4px 0;padding:4px 8px;border:1px solid var(--oc-border,#aaa);border-radius:var(--radius-btn,6px);background:var(--oc-surface,#fff);color:var(--oc-txt,#243028);cursor:pointer;font:inherit;'
    details.append(summary,warning,pre,copy,download,status)
    this.append(title,code,next,details)
  }
}
export function mountFigureError(container: HTMLElement): FigureErrorElement {
  if (!customElements.get('omicos-figure-error')) customElements.define('omicos-figure-error', FigureErrorElement)
  const element=document.createElement('omicos-figure-error') as FigureErrorElement
  container.appendChild(element);return element
}
