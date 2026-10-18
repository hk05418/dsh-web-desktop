# dsh-desktop

DeepSeek Harness（DSH）的桌面管理端：PySide6 + QWebEngineView 嵌入真实 web 前端，
与浏览器对等（聊天/流式/审批/预览全功能），并原生托管 `dsh web` 服务器进程
（启动/停止/重启/日志/托盘/单实例）。

> 本项目是 [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)
> 的桌面客户端。它本身不含 DSH 后端，而是托管并嵌入 DSH 的 web 前端。
> DSH 的用法/功能说明见其
> [中文 README](https://github.com/deepseek-ai/deepseek-harness/blob/master/README.zh.md)。

## 前置条件

dsh-desktop 需要一个**已就绪的 deepseek-harness 检出**来运行 `dsh web` 服务器，
请先完成 DSH 的初始化：

1. 安装 [Node.js](https://nodejs.org)（v18+）与 pnpm：`npm i -g pnpm`
2. 克隆并初始化 deepseek-harness：
   ```bash
   git clone https://github.com/deepseek-ai/deepseek-harness.git ~/deepseek-harness
   cd ~/deepseek-harness
   pnpm install          # 按 DSH 中文 README 完成初始化（依赖/配置等）
   ```
   详见 [DSH 中文 README](https://github.com/deepseek-ai/deepseek-harness/blob/master/README.zh.md)。
3. 确认能手动跑起来：`pnpm dsh web`（能起服务即就绪）。

> **检出目录可任意放置**（不必在 `~` 下，Windows 放 D 盘也行）。桌面端默认
> 从 `~/deepseek-harness` 启动服务器；放在别处时，有两种方式告诉桌面端：
>
> - **首次运行自动检测**：启动时若 `repo_dir` 不是有效检出（缺
>   `apps/cli/src/bin.ts`），会弹窗让你用文件选择器选目录，自动写回配置。
> - **随时改**：菜单 **服务器 → 设置 DSH 目录…**，选目录后自动保存并重启服务器。
>
> 也可直接改配置 `repo_dir` 字段（见下文「配置」）。

## 从源码运行

```bash
uv sync
uv run dsh-desktop
```

启动后桌面端会自动在 `repo_dir`（默认 `~/deepseek-harness`）里跑
`pnpm dsh web --no-open --port <端口>` 并嵌入其 web 前端。

## 配置

- Linux/macOS: `~/.config/dsh_desktop/config.json`
- Windows: `%APPDATA%\dsh_desktop\config.json`

首次运行用默认值（随机端口、CPU 渲染、自动启动服务器）。字段：

| 字段 | 说明 |
|---|---|
| `repo_dir` | deepseek-harness 检出目录（默认 `~/deepseek-harness`，可任意位置；无效时启动会弹窗选择，或菜单「服务器 → 设置 DSH 目录…」） |
| `server_command` | 服务器命令（Windows 自动用 `pnpm.cmd`） |
| `port` | 0=随机端口；设 3080 可接管终端实例 |
| `auto_start_server` | 启动应用时自动启动服务器 |
| `auto_restart_on_crash` | 服务器崩溃自动重启 |
| `disable_gpu` | 强制 CPU 渲染（Linux 默认 true，Windows 默认 false） |
| `hide_to_tray` | 关窗缩到托盘 |
| `zoom` | webview 初始缩放 |
| `editor` | 打开配置文件用的编辑器（如 emacs/code），空=系统默认 |
| `attach_line` | attach 模式：粘贴 `dsh web: http://.../?token=...` 行 |

## 打包产物（GitHub Actions，Nuitka）

推 tag（如 `v0.1.0`）自动构建三平台并发 Release：

- `dsh-desktop-windows-x64.zip` — 目录包（`dsh-desktop\dsh-desktop.exe` 启动；
  onedir 模式，QtWebEngine 更可靠。如需单文件可本地 `--onefile` 构建）
- `dsh-desktop-linux-x64.tar.gz` — 目录包（`dsh-desktop/dsh-desktop` 可执行；
  含 `dsh-desktop.desktop` 应用菜单入口 + `dsh-desktop.png` 鲸鱼图标）
- `dsh-desktop-macos.zip` — `dsh-desktop.app`

**运行前提**（打包只含桌面端，不含 node/pnpm/DSH，需先完成上文「前置条件」）：
1. 安装 [Node.js](https://nodejs.org) + `npm i -g pnpm`
2. 检出并初始化 deepseek-harness：
   `git clone https://github.com/deepseek-ai/deepseek-harness.git ~/deepseek-harness`
   （Windows: `C:\Users\<你>\deepseek-harness`，然后 `pnpm install`）
3. 解压运行：
   - Windows：解压后双击 `dsh-desktop\dsh-desktop.exe`
   - Linux：`tar xzf ... && ./dsh-desktop/dsh-desktop`
   - macOS：解压后打开 `dsh-desktop.app`

### Linux 加入应用菜单（可选）

包内附 `dsh-desktop.desktop`（鲸鱼图标入口）。解压到某目录（如 `~/dsh-desktop`）后：

```bash
# 把 Exec/Icon 改成你的实际路径，再装到用户应用目录
sed -e "s|^Exec=.*|Exec=$HOME/dsh-desktop/dsh-desktop|" \
    -e "s|^Icon=.*|Icon=$HOME/dsh-desktop/dsh-desktop.png|" \
    dsh-desktop/dsh-desktop.desktop > ~/.local/share/applications/dsh-desktop.desktop
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

之后在应用菜单里就能找到「dsh-desktop」（鲸鱼图标）。

## 本地构建（Nuitka）

```bash
uv sync --no-dev
uv pip install nuitka ordered-set zstandard
# Linux standalone 额外需要 patchelf：
uv pip install patchelf        # 或 sudo pacman -S patchelf / apt install patchelf
uv run python scripts/build_nuitka.py
# 产物在 dist/（dsh-desktop-<平台>-<架构>.zip / .tar.gz）
```

脚本按当前平台自动识别打包方式（Windows 单文件 .exe / Linux 目录包 /
macOS .app），并自动打成分发压缩包。`--onefile` 可出单文件（Windows/Linux），
`--dry-run` 只打印 Nuitka 命令。

Nuitka 用 `pyside6` 插件自动收集 Qt 库/插件/资源（含 QtWebEngine）；
Linux 构建机若装有系统 fcitx5 插件会一并打包，否则应用首次启动时
从用户系统 Qt 自动补（见 PLAN.md §6.2）。

> GitHub Actions（`.github/workflows/build.yml`）在三个平台 runner 上跑同一脚本，
> 推 tag（如 `v0.1.0`）自动发 Release。

## 开发

```bash
uv run pytest tests/ -q
```

架构与里程碑见 [PLAN.md](PLAN.md)（含白块根因 §6.1、中文输入根因 §6.2、
Windows 适配 §6.3）。
