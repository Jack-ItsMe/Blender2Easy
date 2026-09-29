# 快速开始

[English](getting-started.md) · [返回首页](../README.zh-CN.md)

## 1. 准备环境

需要 Python、Blender 和支持 WebGL 的浏览器。本文档使用能够读写项目文件、执行本地命令的 Codex 宿主。浏览器负责预览和反馈，不包含 Agent 或大语言模型。

当前已验证 Windows；源码包含 macOS/Linux 的部分路径和发现逻辑，但这两个平台尚未验证。首次使用不需要 MCP，它使用单独的依赖配置。

已检查的 Windows 环境为 **Python 3.12.14、Blender 5.2.1 LTS、FFmpeg 7.1**。这是验证过的组合，不代表所有更早或更新版本都已兼容。

将仓库克隆到你自己的任意目录，后续始终使用同一个 Python 环境：

```sh
git clone https://github.com/Jack-ItsMe/Blender2Easy.git
cd Blender2Easy
python -m pip install -r skills/blender2easy/scripts/requirements.txt
python skills/blender2easy/scripts/animation.py doctor
```

如果本机命令是 `python3`，统一替换即可。可以使用虚拟环境隔离依赖，但 Agent 后续也要使用该环境的解释器。

依赖文件安装 Pillow 和 imageio-ffmpeg，不安装 Blender。`doctor` 只读检查 Python、工具路径、版本及就绪状态；缺少依赖时返回退出码 2。

找不到 Blender 或 FFmpeg 时，可加入 `PATH`，设置 `ANIMATION_BLENDER` / `ANIMATION_FFMPEG`，或给支持覆盖路径的命令传入本机可执行文件：

```sh
python skills/blender2easy/scripts/animation.py doctor --blender "/absolute/path/to/blender"
```

请替换为真实路径。`preview`、`run` 等制作命令也支持 `--blender` 和 `--ffmpeg`。

## 2. 安装技能

在仓库根目录运行：

```sh
python scripts/install.py
```

设置了 `CODEX_HOME` 时，默认安装到 `CODEX_HOME/skills/blender2easy`；否则为 `~/.codex/skills/blender2easy`。也可以手动将完整的 `skills/blender2easy` 文件夹复制到该位置，保留 scripts、references、assets 和 vendor 等子目录。

安装脚本默认不会覆盖已有安装。使用 `--replace` 会先在技能目录之外保留完整备份，再替换；如存在旧版 `object-animation`，旧目录也会移入备份。`--dest /path/to/skills` 指定其他**技能父目录**，脚本会在其中创建 `blender2easy`。

执行 `--replace` 前，请先停止使用旧安装的编辑器、渲染和 MCP 进程。旧安装内的 `editor/projects` 项目与缓存会保留在输出的备份路径中，不会自动合并到新目录。之后可用明确的项目路径和 `--workspace` 重新打开，或在停服后转移工作区。原本存放在技能安装目录之外的项目仍在原位置。

源码仓库和已安装副本彼此独立，修改其中一份不会自动同步到另一份。在能够发现已安装技能的 Codex 对话中，通过 `$blender2easy` 调用。

安装技能不会配置模型、启用 MCP 或安装 Blender 插件；宿主仍需要文件与命令访问能力。

## 3. 从一个小任务开始

> 使用 $blender2easy 制作一段带铰链的盒子打开动画。先准备初稿，再让我通过局部预览判断打开角度和停留时间。出最终视频前，先检查 Blender 预览画面。

Agent 应先准备场景，再打开预览。你可以调整已开放的控件，或标记要修改的位置并提交。提交内容先保存在本地，仍需 Agent 读取和应用；如果它已经结束本轮，回到同一对话说“继续处理我保存的反馈”即可。

## 4. 单独体验命令行

以下命令从仓库根目录运行，创建一个入门项目：

```sh
python skills/blender2easy/scripts/animation.py init work/box-demo --template box
python skills/blender2easy/scripts/animation.py validate work/box-demo/project.json
python skills/blender2easy/scripts/animation.py editor work/box-demo/project.json --open
```

`init` 要求目标目录不存在或为空。编辑器命令会持续运行；执行后续命令时另开终端，或先按 Ctrl+C 停止服务。默认地址为 `http://127.0.0.1:8766`。未创建调整任务时，页面只供查看。

先渲染几帧实际的 Blender 画面，再生成完整视频：

```sh
python skills/blender2easy/scripts/animation.py preview work/box-demo/project.json --shot opening --frames 1,24,48
python skills/blender2easy/scripts/animation.py run work/box-demo/project.json --shot opening
python skills/blender2easy/scripts/animation.py verify work/box-demo/project.json --shot opening
```

命令通过 JSON 返回图片、视频和检查记录的实际路径。`verify` 检查最近一次交付，不代表后续尚未渲染的修改。不要同时对同一块 GPU 发起多个渲染任务。

构建、报告和缓存保存在项目的 `.animation` 下。再次 `run` 可以复用有效帧；保留这些文件便于续作。修改项目后，旧视频不会自动成为新版交付。

## 常见问题

**页面提示没有需要调整的内容。** 没有 Agent 创建的调整任务时，这是正常行为。可以先查看模型；需要控件时，让 Agent 围绕一个具体问题创建局部预览。

**8766 端口被占用。** 启动时使用 `--port 8770 --open`，或使用 Agent 返回的链接。不同端口的浏览器显示设置独立保存。

**预览与 Blender 不一致。** 浏览器使用近似显示；原生场景被导出为预览网格，不能完整复现任意材质、约束与效果。最终判断请检查 Blender 画面。

**提交后对话没有继续。** 反馈已保存，但不能自动唤醒结束本轮的 Agent。返回同一对话，让它继续读取反馈。

**宿主找不到技能。** 确认安装目录下直接包含 `SKILL.md`，宿主会读取这个技能位置，而且使用的 Python 环境有依赖。也可先从仓库直接运行 CLI，排查环境问题。

精确命令和格式见[工作流程](../skills/blender2easy/references/workflow.md)、[反馈契约](../skills/blender2easy/references/review.md)及[可选 MCP](../skills/blender2easy/references/mcp.md)。
