#!/usr/bin/env python3
"""渲染 worker 子进程（系统 python3，需 matplotlib 科学栈）。

跑一个 fig 脚本一次，把产出的 Figure 常驻内存（live-figure 会话），
之后通过 stdin/stdout 的 JSON 行协议接受指令。**两套信封并存**：

* **协议 v1**（带 `protocol_version` 字段，`pool.py` 走这条）：

      {"protocol_version":1,"request_id":"r-…","worker_generation":3,
       "render_revision":17,"cmd":"render","stem":"Fig1",
       "canonical_patch_hash":"sha256:…","payload":{"patches":[…]}}

  命令：ping / build / render / render_png / preview_png / export /
  cancel / shutdown。generation、revision、hash **worker 只回显不理解**
  （校验归 supervisor）。build / render / export 的成功响应带 `timings`
  （毫秒，见 `_TIMED_COMMANDS`）。完整契约见
  `docs/adr/0003-worker-protocol-v1.md`。

* **legacy**（无 `protocol_version`）：老的扁平信封，行为一字不改——
  手工 `echo '{"cmd":"build"}' | python worker.py …` 调试时用的就是它。

      {"cmd":"build"}                                → 导入脚本、跑入口、捕获全部 Figure
      {"cmd":"override","stem":s,"patches":[...]}    → 应用全量 override，重导出预览 SVG
      {"cmd":"export","stem":s,"patches":[...],
       "path":p,"format":"pdf","dpi":600}            → 全质量导出（供 PyMuPDF 合成）
      {"cmd":"ping"} / {"cmd":"shutdown"}

安全措施：
  * cwd 切到沙盒目录——fig6/fig7 等脚本的相对路径写出/glob 删除不会碰真实 figures 目录
  * 拦截 Figure.savefig 与 paper_style.save（import 脚本前安装）——build 期间不写任何图文件
  * 脚本的 stdout 重定向到 stderr，保证协议通道干净
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import importlib
import importlib.abc
import json
import os
import re
import runpy
import shutil
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import matplotlib  # noqa: E402 —— 必须在 sys.path 注入之后

matplotlib.use("Agg")
import matplotlib.figure as mfigure  # noqa: E402

# Figure 捕获策略（savefig stem 怎么取、跑完之后还活着的 pyplot Figure 怎么
# 补进来、相对路径只读回退）与浏览器 playground **共用同一份实现**。抄一份
# 进来的话，同一个脚本会在两个入口里产出不同的 stem——前端按 stem 索引一切。
import figcapture  # noqa: E402

_OMICOOS_COLUMN_SEM = re.compile(r"\b([A-Za-z_]\w*)\.sem\b(?!\s*\()")
_WINDOWS_EXTENDED_PATH = re.compile(r"\\\\\?\\(?=[A-Za-z]:|UNC\\)")


def _normalize_managed_source(source: str) -> str:
    """Repair portability hazards in generated OmicOS replay sources.

    Core-generated scripts may contain both ordinary drive-letter paths and
    Windows extended paths (``\\\\?\\G:\\...``).  ``os.path.relpath`` rejects
    that pair as different mounts even though they refer to the same drive.
    Normalize the generated source before compiling it, while leaving ordinary
    user scripts untouched.
    """
    if not source.startswith("# OmicOS managed figure source v1"):
        return source
    # Match only a prefix followed by an actual drive/UNC path.  A generated
    # source may itself contain ``src.replace("\\\\?\\", "")``; a blind
    # string replacement would corrupt that valid Python literal.
    normalized = _WINDOWS_EXTENDED_PATH.sub("", source)
    if ".sem" in normalized and re.search(r"[\"']sem[\"']\s*:", normalized):
        normalized = _OMICOOS_COLUMN_SEM.sub(r'\1["sem"]', normalized)
    return normalized


# Figure 到手之后的编辑语义（instrument / manifest / override / 渲染 / 导出 /
# 快照还原）与**信封语义**都不是 safe worker 私有的：native bridge（ADR 0020）
# 在用户自己的进程里跑用户的脚本，捕获到 Figure 之后走的必须是同一份实现。
# 抄一份过去就是第二份 manifest builder + 第二套协议语义——总纲原则 1 明令
# 禁止，而分叉的表现是同一张图在两条入口里 gid 不一样（数据级错位）。
import figsession  # noqa: E402
import wireproto  # noqa: E402

#: 本 worker 的常驻会话。`_patched_savefig` 是模块级函数（要顶掉
#: `Figure.savefig` 这个类属性），拿不到 Worker 实例，只能走模块级引用。
SESSION: "SafeSession | None" = None

_intercept = True
_REAL_SAVEFIG = mfigure.Figure.savefig

#: 协议常量的唯一出处在 `wireproto`；这里 re-export 是为了「手工 echo 一条
#: 请求进来调试」时不必知道模块拆分（`worker.PROTOCOL_VERSION` 是老口径）。
PROTOCOL_VERSION = wireproto.PROTOCOL_VERSION
V1_COMMANDS = wireproto.V1_COMMANDS
ProtocolError = wireproto.ProtocolError
_ms = figsession.ms_since


#: 与 OmicVerse 兼容垫片相关的**唯一**触发点。垫片只改 `ov.pl.marker_heatmap`，
#: 而 `omicverse.pl` 是 OmicVerse 的懒加载子包：装了 OmicVerse 的分析环境里
#: import 它要 10–30 秒（scipy.stats / anndata / 一整个绘图栈）。此前 build 无
#: 条件先 import 一遍，于是**每一张普通 matplotlib 图**的冷启动都替 OmicVerse
#: 付这笔钱（实测 12.4 s / 12.9 s 的 build 全在这里，脚本本身 19 ms）。
#: 现在只在 `omicverse.pl` **真的被脚本 import 完成之后**再打垫片：
#: 一个 meta_path 后置钩子，找到真正的 spec、让真 loader 跑完 exec_module、
#: 随后立刻安装垫片并把自己摘掉。没 import 过 OmicVerse 的脚本一分钱不付；
#: 进程里已经 import 过的（sitecustomize 之类）当场打，钩子不装。
_OMICVERSE_PL = "omicverse.pl"


class _OmicverseCompatHook(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self) -> None:
        self._real_loader = None

    def find_spec(self, fullname, path=None, target=None):
        if fullname != _OMICVERSE_PL:
            return None
        for finder in sys.meta_path:
            if finder is self:
                continue
            find = getattr(finder, "find_spec", None)
            if find is None:
                continue
            spec = find(fullname, path, target)
            if spec is not None and spec.loader is not None:
                self._real_loader = spec.loader
                spec.loader = self
                return spec
        return None

    def create_module(self, spec):
        create = getattr(self._real_loader, "create_module", None)
        return create(spec) if create is not None else None

    def exec_module(self, module):
        try:
            self._real_loader.exec_module(module)
        finally:
            with contextlib.suppress(ValueError):
                sys.meta_path.remove(self)
        _install_omicverse_compat()


def _install_omicverse_compat_lazily() -> None:
    """装钩子，或者（已经 import 过时）当场打垫片；绝不主动 import OmicVerse。"""
    if _OMICVERSE_PL in sys.modules:
        _install_omicverse_compat()
        return
    if any(isinstance(f, _OmicverseCompatHook) for f in sys.meta_path):
        return
    sys.meta_path.insert(0, _OmicverseCompatHook())


def _engine_identity() -> dict:
    """`ping` 里报的引擎身份。独立发行包的构建脚本会在旁边放一份 `_build.json`
    （名字、版本、基线提交）；源码树里没有这份文件，就只报解释器与 matplotlib。"""
    info = {"python": sys.version.split()[0], "matplotlib": matplotlib.__version__}
    marker = HERE / "_build.json"
    try:
        data = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
    except (OSError, ValueError):
        data = {}
    for key in ("engine", "engine_version", "base_commit"):
        value = data.get(key)
        if isinstance(value, str) and value:
            info[key] = value
    return info


def _install_omicverse_compat() -> None:
    """Keep common OmicVerse plots renderable in the managed worker.

    OmicVerse's ``marker_heatmap`` has two portability traps: recent releases
    require PyComplexHeatmap, which is not part of every analysis environment,
    and they return without drawing when ``groupby`` is omitted.  Historical
    OmicOS figures commonly pass a marker dictionary whose keys are the
    AnnData row labels instead.  The compatibility path infers that grouping
    and falls back to a regular Matplotlib heatmap when the optional backend is
    unavailable.  It deliberately patches only this public helper; all other
    OV functions keep their original behavior.
    """
    try:
        import numpy as np
        import omicverse as ov
        import pandas as pd
    except Exception:  # noqa: BLE001 - OV is optional for ordinary Matplotlib scripts
        return
    plotting = getattr(ov, "pl", None)
    original = getattr(plotting, "marker_heatmap", None)
    if not callable(original) or getattr(original, "__omicos_compat__", False):
        return

    def _dense(value):
        if hasattr(value, "toarray"):
            value = value.toarray()
        return np.asarray(value, dtype=float)

    def _groups(adata, marker_genes_dict, groupby):
        if not isinstance(marker_genes_dict, dict) or not marker_genes_dict:
            return adata, groupby
        labels = [str(label) for label in marker_genes_dict]
        if groupby:
            return adata, groupby
        try:
            index = [str(value) for value in adata.obs.index]
        except Exception:  # noqa: BLE001
            return adata, groupby
        # A marker dictionary keyed by the rows is the unambiguous form.  Do
        # not guess for arbitrary AnnData objects with unrelated row labels.
        if len(index) != len(labels) or set(index) != set(labels):
            return adata, groupby
        try:
            copy = adata.copy()
            key = "__omicos_marker_group"
            copy.obs[key] = pd.Categorical(index, categories=labels, ordered=True)
            return copy, key
        except Exception:  # noqa: BLE001
            return adata, groupby

    def _fallback(
        adata,
        marker_genes_dict=None,
        groupby=None,
        color_map="RdBu_r",
        use_raw=True,
        standard_scale="var",
        expression_cutoff=0.0,
        bbox_to_anchor=(5, -0.5),
        figsize=(8, 4),
        spines=False,
        fontsize=12,
        show_rownames=True,
        show_colnames=True,
        save_path=None,
        ax=None,
    ):
        del bbox_to_anchor  # retained for signature compatibility
        if not isinstance(marker_genes_dict, dict) or not marker_genes_dict or not groupby:
            return None
        source = getattr(adata, "raw", None) if use_raw else None
        source = source if source is not None else adata
        names = [str(value) for value in getattr(source, "var_names", ())]
        lookup = {name: i for i, name in enumerate(names)}
        genes = []
        for values in marker_genes_dict.values():
            genes.extend(
                [str(values)] if isinstance(values, str) else [str(value) for value in values]
            )
        genes = [gene for gene in genes if gene in lookup]
        if not genes:
            return None
        matrix = _dense(source.X)
        if matrix.ndim == 1:
            matrix = matrix.reshape(-1, 1)
        columns = [lookup[gene] for gene in genes]
        matrix = matrix[:, columns]
        values = [str(value) for value in adata.obs[groupby]]
        labels = [str(label) for label in marker_genes_dict]
        means, fractions = [], []
        for label in labels:
            mask = np.asarray([value == label for value in values], dtype=bool)
            subset = matrix[mask]
            means.append(np.nanmean(subset, axis=0) if subset.size else np.zeros(len(genes)))
            fractions.append(
                np.mean(subset > expression_cutoff, axis=0) if subset.size else np.zeros(len(genes))
            )
        means = np.nan_to_num(np.asarray(means, dtype=float))
        fractions = np.nan_to_num(np.asarray(fractions, dtype=float))
        if standard_scale == "var":
            low = means.min(axis=0, keepdims=True)
            span = means.max(axis=0, keepdims=True) - low
            means = np.divide(means - low, span, out=np.zeros_like(means), where=span > 0)
        elif standard_scale == "group":
            low = means.min(axis=1, keepdims=True)
            span = means.max(axis=1, keepdims=True) - low
            means = np.divide(means - low, span, out=np.zeros_like(means), where=span > 0)
        if ax is None:
            import matplotlib.pyplot as plt

            _, ax = plt.subplots(figsize=figsize)
        fig = ax.figure
        image = ax.imshow(means, aspect="auto", cmap=color_map)
        ax.set_xticks(range(len(genes)))
        ax.set_yticks(range(len(labels)))
        ax.set_xticklabels(genes if show_colnames else [], rotation=90, fontsize=fontsize)
        ax.set_yticklabels(labels if show_rownames else [], fontsize=fontsize)
        ax.tick_params(length=0)
        for spine in ax.spines.values():
            spine.set_visible(bool(spines))
        # Keep the fraction information visible without introducing a custom
        # artist family that the manifest cannot edit.
        for row in range(len(labels)):
            for col in range(len(genes)):
                if fractions[row, col] > 0:
                    ax.add_patch(
                        __import__("matplotlib").patches.Rectangle(
                            (col - 0.5, row - 0.5),
                            1,
                            1,
                            fill=False,
                            edgecolor="white",
                            linewidth=0.35,
                            alpha=float(fractions[row, col]),
                        )
                    )
        fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
        fig.tight_layout()
        if save_path is not None:
            fig.savefig(save_path, dpi=300, bbox_inches="tight")
        return fig, ax

    def compat_marker_heatmap(adata, marker_genes_dict=None, groupby=None, *args, **kwargs):
        adapted, inferred_groupby = _groups(adata, marker_genes_dict, groupby)
        try:
            result = original(
                adapted,
                marker_genes_dict=marker_genes_dict,
                groupby=inferred_groupby,
                *args,
                **kwargs,
            )
            if result is not None:
                return result
        except (ImportError, ModuleNotFoundError) as exc:
            if "PyComplexHeatmap" not in str(exc):
                raise
        if inferred_groupby:
            return _fallback(adapted, marker_genes_dict, inferred_groupby, *args, **kwargs)
        return None

    compat_marker_heatmap.__omicos_compat__ = True
    plotting.marker_heatmap = compat_marker_heatmap


class SafeSession(figsession.LiveFigureSession):
    """safe 档的 LiveFigureSession：引擎自己写盘时摘掉 savefig 拦截。

    build 期间脚本一个图文件都不写（沙盒纪律），但引擎自己的预览 SVG /
    PNG / 导出必须写得出去——`_real_output()` 就是那个窗口。native bridge
    的 savefig 本来就是透传，它用基类那个什么都不做的上下文。
    """

    def real_output(self):
        return _real_output()


def _patched_savefig(self, fname, *args, **kwargs):
    """通用兜底：raw fig.savefig 的脚本也被捕获；同 stem 的 pdf/png 只记一次。"""
    if not _intercept:
        return _REAL_SAVEFIG(self, fname, *args, **kwargs)
    stem = figcapture.savefig_stem(fname)
    if stem and SESSION is not None:
        SESSION.add_figure(stem, self, figcapture.SOURCE_SAVEFIG)
    return None


@contextlib.contextmanager
def _real_output():
    global _intercept
    # Recovered OmicOS scripts may install their own Figure.savefig filter to
    # keep only the selected source stem. Engine-owned preview/render/export
    # writes use cache paths or file-like buffers, so temporarily restore the
    # worker's native method while the engine writes its result.
    previous_savefig = mfigure.Figure.savefig
    _intercept = False
    mfigure.Figure.savefig = _REAL_SAVEFIG
    try:
        yield
    finally:
        mfigure.Figure.savefig = previous_savefig
        _intercept = True


class Worker(wireproto.V1Handler):
    """safe 档执行侧：**怎么把用户脚本跑起来**（沙盒 / 守卫 / argv / 拦截）。

    Figure 到手之后的一切交给 `SafeSession`（`figsession`），信封分派交给
    `wireproto.V1Handler`——两者都与 native bridge 共用同一份实现。
    """

    def __init__(self, args):
        global SESSION
        self.script = Path(args.script).resolve()
        self.figures_dir = Path(args.figures_dir).resolve()
        self.out_dir = Path(args.out_dir).resolve()
        self.sandbox = Path(args.sandbox).resolve()
        #: 脚本的工作目录（ADR 0047）：默认就是沙盒；`--cwd` 给了就是脚本
        #: 自己所在的目录。写入边界的**参照**始终是沙盒 / 图库目录，守卫不变。
        self.workdir = Path(args.cwd).resolve() if getattr(args, "cwd", None) else None
        self.entry = args.entry
        self.preview_dpi = args.preview_dpi
        self.built = False
        #: pyplot 兜底因上限丢掉的张数（0 = 一张没丢）。build 响应带出去。
        self.dropped_figures = 0
        #: 每张捕获 Figure 的结构化描述（figcapture.CapturedFigureDescriptor
        #: 的 payload，捕获顺序）。**build 那一刻算好钉死**：fingerprint 里的
        #: 脚本内容哈希必须是「实际被执行的那份」，之后脚本再被改，本会话
        #: 跑的还是旧代码（watcher 会作废会话，这里不追新）。
        self._descriptor_cache: list[dict] = []
        SESSION = SafeSession(self.out_dir, self.preview_dpi)
        super().__init__(SESSION)

    # ---------------- build ----------------
    def _run_tolerant_top_level(self):
        """在 OmicOS 历史脚本中跳过失败的独立探针语句，继续到正式出图段。

        一些对话会把多段「探测 OmicVerse API」代码和最终作图代码拼进同一个
        ``.py``。探测段引用了未定义的临时变量时，普通 Python 语义会让整个文件
        在正式 ``savefig`` 之前停止。这里只作为一次受限的 NameError 恢复：先按
        正常语义执行；只有 NameError 才进入这里，按顶层语句隔离执行，并把每个
        被跳过的异常写入 worker 日志。语法错误、缺依赖、文件错误等仍然原样失败，
        不猜测数据，也不改写用户脚本。
        """
        source = self.script.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(self.script))
        future = []
        rest = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                future.append(node)
            else:
                rest.append(node)
        guarded = []
        for node in rest:
            guarded.append(
                ast.Try(
                    body=[node],
                    handlers=[
                        ast.ExceptHandler(
                            type=ast.Name(id="Exception", ctx=ast.Load()),
                            name="_omicos_compat_exc",
                            body=[
                                ast.Expr(
                                    value=ast.Call(
                                        func=ast.Name(id="_omicos_compat_log", ctx=ast.Load()),
                                        args=[ast.Name(id="_omicos_compat_exc", ctx=ast.Load())],
                                        keywords=[],
                                    )
                                )
                            ],
                        )
                    ],
                    orelse=[],
                    finalbody=[],
                )
            )
        module = ast.Module(body=future + guarded, type_ignores=[])
        ast.fix_missing_locations(module)
        namespace = {
            "__name__": "__main__",
            "__file__": str(self.script),
            "__cached__": None,
            "__doc__": None,
            "__loader__": None,
            "__package__": None,
            "__spec__": None,
        }

        def _log(exc):
            print(
                f"[compat] 跳过历史脚本中的独立语句: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

        namespace["_omicos_compat_log"] = _log
        try:
            from matplotlib.patches import FancyArrowPatch
        except Exception:
            pass
        else:
            namespace["FancyArrowPatch"] = FancyArrowPatch
        exec(compile(module, str(self.script), "exec"), namespace, namespace)
        return namespace

    def build(self, timings: dict | None = None) -> dict:
        """跑一次用户脚本，把产出的 Figure 全部收进内存。

        `timings` 非空时填两个数：`script_build_ms` 是整个 build（脚本 +
        instrument + 每个 stem 的首次预览），`script_exec_ms` 只是用户脚本
        自己那一段。两者分开是因为它们的改法完全不同——前者大头在用户的
        计算里（我们无能为力），差额才是引擎自己的开销。
        """
        t_build = time.perf_counter()
        if self.built:
            return self._stems_summary()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.sandbox.mkdir(parents=True, exist_ok=True)
        # cwd：默认沙盒（写入边界）；项目级开关打开时是脚本自己所在的目录——
        # 脚本用相对路径找数据（exists / glob / C++ 读取器）的唯一成立形态。
        os.chdir(self.workdir or self.sandbox)
        # 图库根先进 sys.path（脚本 import 同目录的 paper_style / 数据模块），
        # 脚本自己所在目录再插到最前——面板脚本放 panels/ 子目录时，
        # 只加图库根会让 import_module(stem) 直接 ModuleNotFoundError。
        sys.path.insert(0, str(self.figures_dir))
        if self.script.parent != self.figures_dir:
            sys.path.insert(0, str(self.script.parent))

        # 删除守卫：fig6 用绝对路径删“过期输出”（ROOT/figures/...），沙盒 cwd
        # 挡不住，这里直接拒绝任何指向真实图库目录的删除（渲染用不到删除）
        real_figs = self.figures_dir
        real_unlink = Path.unlink

        def _guarded_unlink(p, missing_ok=False):
            try:
                if p.resolve().is_relative_to(real_figs):
                    print(f"[guard] 跳过删除真实图库文件: {p}", file=sys.stderr)
                    return None
            except OSError:
                pass
            return real_unlink(p, missing_ok=missing_ok)

        Path.unlink = _guarded_unlink

        # 同一条守卫扩到 os / shutil 的删除与改名（`os.remove` / `os.unlink` /
        # `os.rmdir` / `os.rename` / `os.replace` / `shutil.rmtree` /
        # `shutil.move`）：`Path.unlink` 只是其中一个入口，脚本写
        # `os.remove("stale.png")` 一样是删真实图库里的文件——沙盒 cwd 下相对
        # 路径落在沙盒里无害，绝对路径与「在脚本目录里运行」（ADR 0047）时的
        # 相对路径就直接指向项目。判据一条：**真身落在真实图库里就跳过**。
        # 带 `dir_fd` 的调用（rmtree 内部）不判——顶层 rmtree 已经拦过了。
        # 覆盖：脚本用 open('w') / np.save / C++ 写入器**改写**已有文件不拦，
        # 那是它自己的输出（文案如实说「已有同名文件会被脚本改写」）。
        def _inside_real(path) -> bool:
            try:
                return Path(os.fspath(path)).resolve().is_relative_to(real_figs)
            except (OSError, TypeError, ValueError):
                return False

        def _guard_delete(name, real_fn):
            def guarded(path, *a, **kw):
                if "dir_fd" not in kw and _inside_real(path):
                    print(f"[guard] 跳过 {name} 真实图库文件: {path}", file=sys.stderr)
                    return None
                return real_fn(path, *a, **kw)

            return guarded

        os.remove = _guard_delete("删除", os.remove)
        os.unlink = _guard_delete("删除", os.unlink)
        os.rmdir = _guard_delete("删除目录", os.rmdir)
        os.rename = _guard_delete("改名", os.rename)
        os.replace = _guard_delete("改名", os.replace)
        shutil.rmtree = _guard_delete("删除目录树", shutil.rmtree)
        shutil.move = _guard_delete("移动", shutil.move)

        # 写入守卫：脚本的 write_caption 等用绝对路径 write_text 写真实图库
        # （fig9 的 *_caption.txt），沙盒 cwd 拦不住；导出走 savefig 不受影响
        real_write_text = Path.write_text

        def _guarded_write_text(p, *a, **kw):
            try:
                if p.resolve().is_relative_to(real_figs):
                    print(f"[guard] 跳过写入真实图库文件: {p}", file=sys.stderr)
                    return 0
            except OSError:
                pass
            return real_write_text(p, *a, **kw)

        Path.write_text = _guarded_write_text

        # 相对路径**只读**回退：cwd 在沙盒里，而 `pd.read_csv("data.csv")` 这类
        # 写法在 `python figure.py` 下是天经地义的。只读、只在沙盒里确实没有
        # 这个文件时、且换算后仍落在图库内才生效——写/删/改一个字节都不经过
        # 它，沙盒作为**写入**边界完全没有松动（语义与理由见 figcapture）。
        if self.workdir is None:
            figcapture.install_relative_read_fallback(
                str(self.script.parent), str(self.figures_dir)
            )
        # cwd 已经是脚本目录时不装回退：相对路径本来就指向项目，回退只会在
        # 「沙盒里有同名文件」这种不可能的前提上多一层看不见的改道。

        # 拦截必须发生在 import 脚本之前（多数脚本 from paper_style import save）
        mfigure.Figure.savefig = _patched_savefig
        # paper_style 是某些图库的私有方言，不是引擎的依赖：没有就跳过，
        # 靠 _patched_savefig 这条通用兜底捕获。曾经这里是无保护的 import，
        # 任何不带 paper_style.py 的图库都会以 ModuleNotFoundError 开局。
        try:
            import paper_style  # noqa: PLC0415
        except ImportError:
            pass
        else:
            # 与 `_patched_savefig` 同一条来源记账：paper_style.save 是显式
            # 「保存这张图」，来源就是 savefig（以前这里不记来源，靠读取端
            # `.get(stem, SOURCE_SAVEFIG)` 兜底——结果一样，现在是显式的）。
            paper_style.save = lambda fig, stem, outdir="figures": SESSION.add_figure(
                stem, fig, figcapture.SOURCE_SAVEFIG
            )

        # OmicVerse is an optional analysis dependency.  The narrow
        # marker_heatmap shim is installed the moment the script finishes
        # importing `omicverse.pl` (post-import hook) — never eagerly, because
        # importing OmicVerse costs 10–30 s and most figures never touch it.
        _install_omicverse_compat_lazily()

        # 脚本看到的 argv 必须是它自己的，不是 worker 的。不换的话
        # `sys.argv[1:]` 拿到的是 --script/--out-dir/--entry 这串内部参数，
        # 按参数命名输出的脚本会存出一堆叫 "--entry" 的图（试运行探测时
        # 当场撞见过）。真跑 `python fig.py` 时 argv 就只有脚本自己。
        sys.argv = [str(self.script)]

        t_script = time.perf_counter()
        script_namespace = None
        with contextlib.redirect_stdout(sys.stderr):
            if self.entry == "__main__":
                try:
                    source_text = self.script.read_text(encoding="utf-8")
                    normalized = _normalize_managed_source(source_text)
                    if normalized != source_text:
                        namespace = {
                            "__name__": "__main__",
                            "__file__": str(self.script),
                            "__cached__": None,
                            "__doc__": None,
                            "__loader__": None,
                            "__package__": None,
                            "__spec__": None,
                        }
                        exec(
                            compile(normalized, str(self.script), "exec", dont_inherit=True),
                            namespace,
                            namespace,
                        )
                        script_namespace = namespace
                    else:
                        script_namespace = runpy.run_path(str(self.script), run_name="__main__")
                except NameError:
                    # 只对未定义临时变量做一次恢复；其它异常仍保持原有失败语义。
                    print(
                        "[compat] 普通执行因 NameError 中断，重试独立顶层语句",
                        file=sys.stderr,
                    )
                    self.session.capture.clear()
                    self.session.capture_source.clear()
                    _plt = sys.modules.get("matplotlib.pyplot")
                    if _plt is not None:
                        _plt.close("all")
                    script_namespace = self._run_tolerant_top_level()
            else:
                module = importlib.import_module(self.script.stem)
                getattr(module, self.entry)()
        script_ms = _ms(t_script)

        # pyplot 兜底：从不 savefig 的脚本（`plt.plot(...); plt.show()` 这种
        # AI 最常写的形态）也要能用。**与浏览器 playground 同一份策略**——
        # 抄一份进来的话同一个脚本会在两个入口产出不同的 stem。
        #
        # 只在脚本真的 import 过 pyplot 时才问它：没 import 过就不可能有 pyplot
        # figure，而在这里 import 一次要白付几十毫秒（还会给纯 OO API 的脚本
        # 凭空建一个 figure 管理器）。
        fallback_base = (
            figcapture.managed_fallback_stem(self.script, self.figures_dir)
            or self.script.stem
        )
        _plt = sys.modules.get("matplotlib.pyplot")
        if _plt is not None:
            fallback, dropped = figcapture.collect_pyplot_figures(
                self.session.capture, fallback_base, _plt
            )
            for stem in fallback:
                self.session.capture_source[stem] = figcapture.SOURCE_PYPLOT
            if dropped:
                # 丢了就说，绝不静默：用户会数图。
                print(
                    f"[capture] 脚本留下的 pyplot Figure 超过 "
                    f"{figcapture.MAX_PYPLOT_FALLBACK} 张上限，"
                    f"未捕获 {dropped} 张（显式 savefig 的不受此限）",
                    file=sys.stderr,
                )
                self.dropped_figures = dropped

        if script_namespace is not None:
            collect_namespace = getattr(figcapture, "collect_namespace_figures", None)
            if collect_namespace is None:
                fallback, dropped = ([], 0)
            else:
                fallback, dropped = collect_namespace(
                    self.session.capture,
                    fallback_base,
                    script_namespace,
                    lambda value: isinstance(value, mfigure.Figure),
                )
            for stem in fallback:
                self.session.capture_source[stem] = figcapture.SOURCE_PYPLOT
            if dropped:
                print(
                    f"[capture] 命名空间中的 Figure 超过上限，未捕获 {dropped} 张",
                    file=sys.stderr,
                )
                self.dropped_figures += dropped

        self.session.instrument_all()
        self._descriptor_cache = self._build_descriptors()
        self.built = True
        if timings is not None:
            timings["script_exec_ms"] = script_ms
            timings["script_build_ms"] = _ms(t_build)
        return self._stems_summary()

    def _build_descriptors(self) -> list[dict]:
        """每张捕获 Figure 的统一描述——**语义全在 figcapture，这里只是装配**。

        与浏览器 playground 的 load 响应共用同一份工厂（对拍用例在
        `test_compat_capture_parity.py`）。原始产物只对 savefig 来源的 stem
        查（pyplot 捕获的图从没存过盘，磁盘上碰巧同名的文件不是它的原件，
        工厂对「pyplot + 产物」直接抛）。
        """
        try:
            rel = self.script.relative_to(self.figures_dir).as_posix()
        except ValueError:  # 脚本不在图库下（防御，不该发生）
            rel = self.script.name
        try:
            script_bytes = self.script.read_bytes()
        except OSError:
            script_bytes = b""
        fingerprint = figcapture.source_fingerprint(
            script_bytes,
            script=rel,
            entry=self.entry,
            profile=figcapture.PROFILE_SAFE,
            target_kind="script",
            argv=(),
            passthrough_savefig=False,
            matplotlib_version=matplotlib.__version__,
        )
        return self.session.descriptors(
            script=rel,
            entry=self.entry,
            execution_profile=figcapture.PROFILE_SAFE,
            source_fingerprint=fingerprint,
            project_root=str(self.figures_dir),
        )

    def _stems_summary(self) -> dict:
        # `source` 是加字段，不升协议版本（ADR 0003 §1：两侧容忍未知字段）。
        return self.session.stems_summary(self.dropped_figures)

    def _render(
        self, stem: str, timings: dict | None = None, preview_dpi: int | None = None
    ) -> dict:
        """导出预览 SVG + 重建 manifest（语义在 `figsession`，这里只是老名字）。"""
        return self.session.render(stem, timings, preview_dpi)

    # ---------------- legacy 信封（无 protocol_version） ----------------
    def handle(self, req: dict) -> dict:
        """老的扁平协议。**响应形状一字不改**——手工调试与旧调用方靠它。"""
        cmd = req.get("cmd")
        if cmd == "ping":
            return {"ok": True}
        if cmd == "shutdown":
            raise SystemExit(0)
        if cmd == "build":
            return {"ok": True, **self.build()}
        if not self.built:
            self.build()

        stem = req.get("stem", "")
        states = self.session.states
        if stem not in states:
            return {"ok": False, "error": f"stem 不存在: {stem}", "known": sorted(states)}

        if cmd == "override":
            return {"ok": True, **self.session.do_render(stem, req.get("patches", []))}
        if cmd == "preview_png":
            return {
                "ok": True,
                **self.session.do_preview_png(
                    stem,
                    req.get("patches", []),
                    int(req.get("width", 400)),
                    str(req.get("tag", "p")),
                ),
            }
        if cmd == "render_png":
            return {"ok": True, **self.session.do_render_png(stem, int(req.get("width", 800)))}
        if cmd == "export":
            return {
                "ok": True,
                **self.session.do_export(
                    stem,
                    req.get("patches", []),
                    req["path"],
                    req.get("format", "pdf"),
                    int(req.get("dpi", 600)),
                ),
            }

        return {"ok": False, "error": f"未知指令: {cmd}"}

    # ---------------- 协议 v1 ----------------
    def ensure_built(self, timings: dict | None = None) -> None:
        """按需 build；用户脚本炸了报 script_error（重试没有意义）。

        `timings` 一路传下去：冷启动的 render 里 `script_build_ms` 才是那几十秒
        的去向，不带上的话响应里只剩几毫秒的 apply/draw，读数与用户的体感完全
        对不上。

        build 里除了跑脚本还有 mkdir / 预览 SVG 落盘，理论上也会因磁盘问题
        失败——这里**一律归到 script_error**：绝大多数是脚本自己的问题，
        而把两者分开需要猜 traceback 的来源，猜错比归错更难排查。
        真正的原因永远在 `error.traceback` 里原样带着。
        （`missing_dependency` 由父进程按 traceback 正则单独识别，先于 code。）
        """
        if self.built:
            return
        try:
            self.build(timings)
        except Exception as exc:  # noqa: BLE001 — 转成结构化错误，进程不退出
            raise ProtocolError(
                "script_error",
                f"脚本执行失败: {exc}",
                retryable=False,
                traceback_text=traceback.format_exc(),
            ) from exc

    def ping_info(self) -> dict:
        """`ping` 报引擎身份（加字段不升版；分派逻辑在 `wireproto.V1Handler`）。"""
        return _engine_identity()

    def build_result(self, timings: dict) -> dict:
        """v1 build 响应的 body（分派逻辑在 `wireproto.V1Handler`）。

        `descriptors` 是加字段，不升协议版本（ADR 0003 §1）；**只在 v1
        出现**，legacy 信封的形状一字不改（与 `timings` 同一条纪律）。
        """
        return {**self._stems_summary(), "descriptors": self._descriptor_cache}


def _json_default(o):
    try:
        return float(o)
    except (TypeError, ValueError):
        return str(o)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--figures-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--sandbox", required=True)
    # ADR 0047：给了就把 cwd 切到这里（脚本目录）而不是沙盒；沙盒仍是写入边界的参照
    ap.add_argument("--cwd", default=None)
    ap.add_argument("--entry", default="main")
    ap.add_argument("--preview-dpi", type=int, default=200)

    # 协议管道钉死 UTF-8。Windows 的默认 stdio 编码跟着系统区域走（常是
    # cp1252/cp936），而回应里 ensure_ascii=False——中文标签、µ、⁻¹ 这类字符
    # 一出现就 UnicodeEncodeError 把 worker 整个打死，表现为「worker 无响应」。
    # errors="replace" 是最后一道保险：宁可某个字符显示成 ? 也不能让会话崩掉。
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    worker = Worker(ap.parse_args())

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError as exc:
            # 连信封都解析不出来，无从判断对方说的是哪套协议：按 v1 的错误
            # 形状回（request_id 只能是 null），至少 code 是可读的。
            resp = wireproto.v1_error({}, ProtocolError("bad_request", f"JSON 解析失败: {exc}"))
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        try:
            resp = wireproto.respond(worker, req, legacy=worker.handle)
        except SystemExit:
            break
        except Exception as exc:  # noqa: BLE001 — 结构化返回，进程不退出
            resp = {"ok": False, "error": str(exc), "traceback": traceback.format_exc()}
        # `allow_nan=False`：**NaN / Infinity 不是 JSON**（RFC 8259），
        # 而 Python 的 `json.dumps` 默认会把它们当字面量写出去、`json.loads`
        # 也照收——于是 Python 渲染池一路绿灯，而 workerd（Rust serde_json）
        # 严格拒收整帧、报「往协议管道里写了非 JSON 的内容」并重启会话。
        # 同一份响应，两条控制面两个结果，而症状指向的是「协议错乱」，
        # 与真实原因（某个包围盒是 inf）毫不相干。
        #
        # 几何那一层已经有总闸（`manifest._finite_geometry`），这里是**底线**：
        # 将来别处再漏一个非有限值时，它变成一条**结构化错误**（两条控制面
        # 表现一致、说得出是哪个字段），而不是一条只在其中一条上炸的坏帧。
        try:
            line = json.dumps(resp, ensure_ascii=False, default=_json_default, allow_nan=False)
        except ValueError as exc:
            line = json.dumps(
                {
                    "ok": False,
                    "code": "non_finite_response",
                    "error": f"响应里有非有限数值，无法编成合法 JSON: {exc}",
                    "request_id": (req or {}).get("request_id") if isinstance(req, dict) else None,
                },
                ensure_ascii=False,
            )
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
