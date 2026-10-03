# tavotto-omicos — OmicOS Figure Studio runtime (modified Tavotto)

This repository is the **complete corresponding source** of the figure-workbench
runtime that ships inside [OmicOS](https://omicos.cn) as “OmicOS 图形工作台 /
OmicOS Figure Studio”. It is a **modified version of [Tavotto](https://github.com/Tavotto/Tavotto)**
and it is distributed under the **same licence as upstream: AGPL-3.0-only**.

OmicOS publishes it here so that anyone who interacts with that workbench — locally
or over a network — can obtain, study, modify and redistribute its source, as
AGPL-3.0 sections 5 and 13 require. The OmicOS desktop application shows a link to
this repository at the bottom of the canvas editor.

| | |
| --- | --- |
| Base | `Tavotto/Tavotto` @ [`eb14049`](https://github.com/Tavotto/Tavotto/tree/eb1404942ad60a776403fd4a9d3c85459bc5a8b0) (upstream 0.15.0) |
| This runtime | `0.15.1` |
| Licence | AGPL-3.0-only — unchanged from upstream (`LICENSE`) |
| Modifications | see [`MODIFICATIONS.md`](MODIFICATIONS.md); the diff is this repository's own history on top of the base commit |
| Building | see [`BUILD.md`](BUILD.md) |

## What this is not

- **Not an endorsement by, or an official release of, upstream Tavotto.** Upstream's
  visual brand assets and product marks are removed from this tree; see
  [`TRADEMARKS.md`](TRADEMARKS.md). AGPL grants copyright permissions, not trademark
  rights.
- **Not a statement about the rest of OmicOS.** OmicOS's own host application is a
  separate program with its own terms; publishing this runtime's source says nothing
  about anything else.
- **Third-party dependencies keep their own licences.** This tree's dependency set
  (including the PDF backend) is unchanged in kind from upstream; consult each
  component's own licence and notices.

## 中文说明

本仓库是 OmicOS 桌面应用内「图形工作台」运行时的**完整对应源码**。它是
[Tavotto](https://github.com/Tavotto/Tavotto) 的**修改版**，沿用上游的
**AGPL-3.0-only** 许可发布。任何与该工作台交互的人都可以据此取得、研究、修改和再分发
它的源码（AGPL-3.0 第 5、13 条）。OmicOS 的画布编辑器页面底部给出本仓库链接。

上游基线 `eb14049`（0.15.0），本运行时版本 `0.15.1`；改动清单见
`MODIFICATIONS.md`，构建方法见 `BUILD.md`。上游的品牌标识已从本树移除——AGPL 授予的是
著作权许可，不包含商标权。
