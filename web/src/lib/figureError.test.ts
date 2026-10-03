import { beforeEach, describe, expect, it, vi } from 'vitest'
import { diagnosticText, figureFailure, figureErrorCopy, mountFigureError } from './figureError'

beforeEach(() => { document.body.replaceChildren(); vi.restoreAllMocks() })
describe('structured user errors, original support evidence', () => {
  const cases = [
    ['start', 'Tavotto unable to start', 'FIGURE_START_FAILED'],
    ['exit', 'Tavotto exited: signal 9', 'FIGURE_SESSION_EXITED'],
    ['bundle', 'OmicOS Figure Studio bundle is missing or unreadable (Tavotto source)', 'FIGURE_BUNDLE_MISSING'],
    ['bundle', 'invalid zip Tavotto original', 'FIGURE_BUNDLE_CORRUPT'],
    ['bundle', 'SHA256 mismatch Tavotto', 'FIGURE_BUNDLE_INTEGRITY'],
    ['mcp-install', 'Tavotto MCP install failed\r\nTraceback (most recent call last)', 'FIGURE_MCP_INSTALL_FAILED'],
    ['bridge', 'Tavotto bridge closed', 'FIGURE_BRIDGE_CONNECT_FAILED'],
    ['network', 'Failed to fetch Tavotto', 'FIGURE_NETWORK_OFFLINE'],
    ['render', 'Tavotto raster renderer failed', 'FIGURE_RENDER_FAILED'],
    ['script', 'Tavotto panel script failed', 'FIGURE_SCRIPT_FAILED'],
    ['project', 'Tavotto old unsupported schema', 'FIGURE_PROJECT_INCOMPATIBLE'],
  ] as const
  for (const [context,raw,code] of cases) it(`classifies ${code} without mutating original text`, () => {
    const failure=figureFailure(raw,context)
    expect(failure).toEqual({code,raw})
    for (const locale of ['zh-CN','en-US']) expect(JSON.stringify(figureErrorCopy(code,locale))).not.toMatch(/tavotto|塔沃托/i)
  })
  it('keeps long CRLF, markup and final bytes, with no HTML execution', () => {
    const raw='Tavotto\r\n<img src=x onerror="window.BAD=1">\n'+ 'x'.repeat(150000)+'\r\nEND\0'
    const root=document.createElement('div');document.body.append(root)
    const el=mountFigureError(root);el.setFailure(figureFailure(raw,'script'),'en-US')
    expect(el.querySelector('details')!.open).toBe(false)
    expect(el.querySelector('pre')!.textContent).toBe(raw)
    expect(el.querySelector('img')).toBeNull()
    expect(diagnosticText(raw)).toBe(raw)
  })
  it('retains raw evidence and disclosure state on locale changes; new failures close it', () => {
    const root=document.createElement('div');document.body.append(root)
    const el=mountFigureError(root);const f=figureFailure('Tavotto unchanged','start');el.setFailure(f,'en-US')
    el.querySelector('details')!.open=true
    el.setFailure(f,'zh-CN');expect(el.querySelector('details')!.open).toBe(true)
    expect(el.querySelector('pre')!.textContent).toBe(f.raw)
    el.setFailure(figureFailure('new failure','start'),'zh-CN');expect(el.querySelector('details')!.open).toBe(false)
  })
  it('copies exact original payload and reports clipboard rejection honestly', async () => {
    const writeText=vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText}})
    const root=document.createElement('div');document.body.append(root);const el=mountFigureError(root)
    const raw='Tavotto\r\n塔沃托\noriginal ';el.setFailure(figureFailure(raw),'en-US')
    el.querySelector<HTMLButtonElement>('[data-copy-diagnostics]')!.click();await vi.waitFor(()=>expect(writeText).toHaveBeenCalledWith(raw))
    await vi.waitFor(()=>expect(el.querySelector('[role=status]')!.textContent).toContain('copied'))
    writeText.mockRejectedValue(new Error('Tavotto clipboard error'))
    el.querySelector<HTMLButtonElement>('[data-copy-diagnostics]')!.click()
    await vi.waitFor(()=>expect(el.querySelector('[role=status]')!.textContent).toContain('unavailable'))
    expect(el.querySelector('[role=status]')!.textContent).not.toContain('Tavotto')
  })
  it('falls back to the user-gesture-bound document copy command', async () => {
    const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
    const execCommandDescriptor = Object.getOwnPropertyDescriptor(document, 'execCommand')
    const execCommand = vi.fn(() => true)
    try {
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
      Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand })
      const root=document.createElement('div');document.body.append(root);const el=mountFigureError(root)
      const raw='legacy clipboard fallback';el.setFailure(figureFailure(raw),'en-US')
      el.querySelector<HTMLButtonElement>('[data-copy-diagnostics]')!.click()
      await vi.waitFor(() => expect(el.querySelector('[role=status]')!.textContent).toContain('copied'))
      expect(execCommand).toHaveBeenCalledWith('copy')
    } finally {
      if (clipboardDescriptor) Object.defineProperty(navigator, 'clipboard', clipboardDescriptor)
      else Reflect.deleteProperty(navigator, 'clipboard')
      if (execCommandDescriptor) Object.defineProperty(document, 'execCommand', execCommandDescriptor)
      else Reflect.deleteProperty(document, 'execCommand')
    }
  })
  it('uses raw HTTP payload rather than Error.stack and treats unknown codes as unknown', () => {
    const e=Object.assign(new Error('short summary'), {rawDiagnostic:'{"error":"Tavotto"}\r\n',code:'not-a-public-code'})
    expect(diagnosticText(e)).toBe(e.rawDiagnostic)
    expect(figureFailure(e).code).toBe('FIGURE_OPERATION_FAILED')
  })
})
