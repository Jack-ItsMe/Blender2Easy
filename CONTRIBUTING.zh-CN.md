# 参与贡献

[English](CONTRIBUTING.md) · [返回首页](README.zh-CN.md)

欢迎通过可复现的问题报告、文档改进、平台验证、小范围修复或示例帮助改进 Blender2Easy。不必从大型代码改动开始。

## 从这里开始

1. 先查看[已有问题](https://github.com/Jack-ItsMe/Blender2Easy/issues)，确认是否已有相关工作。已有问题可以补充环境、复现步骤或验证结果，避免重复提交。
2. 新增较大能力或明显改变行为前，先开 issue 讨论用户任务、改动范围和验证方法。小修复可以直接提交拉取请求（PR）。
3. 公开贡献采用 fork、分支和 PR 流程：先将仓库 fork 到自己的账号，再在自己的分支上修改。通过 fork 提交 PR 不需要本仓库的直接写入权限。

将 `YOUR-USERNAME` 替换为自己的 GitHub 用户名，并使用描述改动的分支名：

```sh
git clone https://github.com/YOUR-USERNAME/Blender2Easy.git
cd Blender2Easy
git switch -c fix/short-description
python -m pip install -r skills/blender2easy/scripts/requirements.txt
```

完成一项聚焦的改动并运行相关检查后，将提交推送到自己的 fork，再向本仓库的默认分支发起 PR。说明原问题、修改后的行为和验证证据；如有关联 issue，请附上链接。范围清楚的小 PR 更方便审阅和讨论。

## 报告问题或验证平台

请提供：

- 操作系统、Python、Blender、浏览器版本，以及 `animation.py doctor` 的输出。
- 执行的命令或给 Agent 的请求、预期行为和实际结果。
- 最小可分享项目或复现步骤；视觉问题可附截图。
- 问题发生在浏览器预览、Blender 渲染、已保存反馈还是导出结果中。

删除私人文件路径、凭据及无权再分发的资产。能够复现问题的小场景通常比缺少说明的大型 `.blend` 更有帮助。

如果尝试了一个新的运行环境，请使用[平台验证表单](https://github.com/Jack-ItsMe/Blender2Easy/issues/new?template=platform-check.yml)。记录精确版本，并区分自动测试、实际打开浏览器预览和实际检查 Blender 渲染。CI 通过不能单独证明该平台的交互与渲染流程已完整验证。

## 修改代码

先阅读[快速开始](docs/getting-started.zh-CN.md)。在仓库副本中开发；已安装技能是另一份独立副本。

| 位置 | 用途 |
| --- | --- |
| `skills/blender2easy/SKILL.md` | Agent 入口和参考文档路由 |
| `skills/blender2easy/scripts/` | CLI、制作流程、诊断、反馈契约及可选 MCP |
| `skills/blender2easy/editor/` | 本地服务和浏览器界面 |
| `skills/blender2easy/references/` | 各操作的说明和数据格式 |
| `skills/blender2easy/vendor/bas/` | 保留署名的上游源码和本地改编 |
| `docs/` | 用户指南和演示素材 |

让改动聚焦于可复现的问题。涉及界面时，附上桌面和窄屏宽度下的前后截图，并检查受影响的英文、简体中文和繁体中文界面。

需要保留的工作流边界：

- 查看、拾取和测量不能修改模型。
- 调整任务只能修改其声明的字段，并拒绝过期的源文件或反馈身份。
- 浏览器显示是近似预览；最终 Blender 输出和诊断证据需要单独检查。
- 保留现有资产来源和与本次修改无关的已确认属性。
- 仅在记录的输入及文件仍然有效时复用缓存结果。

使用 Python 3.11+ 和 Node.js 22+ 运行仓库检查：

```sh
python scripts/check.py --require-node
```

默认测试不启动 Blender。`--python-only` 仅运行 Python 测试；未使用 `--require-node` 时，找不到 Node 会跳过前端检查。可选参数 `--with-blender` 运行一个小型 Blender 集成场景；安装 `skills/blender2easy/scripts/requirements-mcp.txt` 后，`--with-mcp` 可运行 SDK 集成检查。

还应使用小场景实际操作受影响的 CLI 命令或反馈流程。涉及几何、动画或渲染时，检查真实 Blender 输出。说明运行了什么、哪些通过、哪些跳过以及哪些尚未验证。少量帧可以回答问题时，不必执行昂贵的完整渲染。

## 文档和上游代码

用户可见的功能和限制应在中英文 README 中保持一致。标明截图或视频是预览、准备好的示例还是最终渲染；不要把成功编码或数值检查等同于视觉正确。

BAS 随包文件的上游哈希及本地改动记录在 [PROVENANCE.json](skills/blender2easy/vendor/bas/PROVENANCE.json) 中。修改这些文件时保留署名，并更新对应的 provenance 记录。与修复无关的上游升级请单独提交。

## 提交 PR 前

- 保持改动范围集中，解释行为变化，并在适用时关联已有 issue。
- 列出验证命令、结果和跳过或未检查的路径。仅修改文档时检查链接与命令即可，无需运行无关的渲染。
- 附上必要的界面截图、语言和屏幕宽度检查，并更新受影响的中英文文档。
- 不提交私人路径、凭据、本地项目和生成的缓存；保留第三方署名和 provenance 记录。
