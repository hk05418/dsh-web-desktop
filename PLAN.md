# dsh-desktop 实施计划

PySide6 桌面管理端：功能与 `pnpm dsh web` 的 Web GUI 齐平。

## 0. 总策略

- **功能齐平 = 直接运行官方 web 前端**（QWebEngineView 即 Chromium，与官方 Electron
  桌面端同源引擎）。PySide6 不重画任何 UI。
- **PySide6 的职责**：① 托管 `dsh web` 进程（启停/重启/日志/健康检查）；
  ② 原生壳（窗口/托盘/菜单/状态栏/设置）；③ 用官方 `/connect` API 做状态探针，
  给托盘/状态栏供数。
- 会话、聊天、流式输出、审批、文件、终端、设置、jobs、schedule、插件管理……
  全部由 web 前端 + web host 完成，桌面端一行协议都不用重写（探针除外，且探针
  只读两个轻量接口）。

## 1. 架构

```
┌──────────────────────────── dsh-desktop (PySide6) ────────────────────────────┐
│ MainWindow                                                                    │
│ ├─ QWebEngineView ──加载──▶ http://127.0.0.1:3080/?token=***                 │
│ │   完整 web UI（browser peer：聊天/流式/审批/文件/终端/设置…）               │
│ ├─ 状态栏 ◀──信号── Probe（/connect cookie + /api/session.list                │
│ │                 + ws /api/remote.mux 的 session/control 流）                │
│ ├─ 托盘（QSystemTrayIcon）、菜单（服务器/视图/帮助）                          │
│ ├─ ServerManager (QProcess) ──拉起──▶ pnpm dsh web --no-open --port 3080      │
│ │   stdout 逐行扫描 "dsh web: <url>/?token=***" → ready 信号                 │
│ │   日志环形缓冲（token 打码）→ LogWindow                                     │
│ └─ Config（~/.config/dsh_desktop/config.json）                                │
└───────────────────────────────────────────────────────────────────────────────┘
          │ loopback HTTP + WS（签名 cookie）
┌───────────────────────────────────────────────────────────────────────────────┐
│ dsh web (Node, ~/deepseek-harness)                                            │
│  服务 web 前端 dist + Host API（/api/*, /api/remote.mux）                     │
│  DSH_HOME 默认 ~/.dsh（与终端里的 web 同一会话库）                             │
└───────────────────────────────────────────────────────────────────────────────┘
```

要点：
- webview 是**浏览器 peer**（`answer` 模式，能回答审批/ask-user）；
- 探针是**独立 API peer**（`interactions=none`，只调一元方法 + 打开生成的
  原始流 `session/control`），两者互不干扰——这是官方
  `/connect` 设计（见
  `.agents/notes/implemented/architecture/2026-10-09-operator-scoped-connect-handshake.zh.md`）。

## 2. 工程结构

```
dsh_desktop/
├── pyproject.toml              # deps: PySide6>=6.8, httpx, websocket-client
├── PLAN.md                     # 本文件
├── src/dsh_desktop/
│   ├── __main__.py             # 入口：QtWebEngine 初始化顺序、单实例
│   ├── app.py                  # QApplication 装配、托盘、主窗口、退出流程
│   ├── config.py               # 配置读写（platforms 目录下的 JSON）
│   ├── server/
│   │   ├── manager.py          # QProcess 生命周期 + 状态机 + 自动重启
│   │   └── capture.py          # 启动行正则、日志打码、健康检查
│   ├── probe/
│   │   ├── connect.py          # GET /connect?token=... → cookie
│   │   ├── rpc.py              # /api 一元调用信封
│   │   └── control.py          # websocket-client 连 /api/remote.mux，
│   │                           # 打开 session/control 流，解析 baseline/projection
│   └── ui/
│       ├── main_window.py      # webview 居中 + 状态栏 + 菜单
│       ├── web_page.py         # QWebEnginePage：外链走系统浏览器、DevTools
│       ├── tray.py             # 托盘图标与菜单
│       ├── log_window.py       # 服务器日志窗口（环形缓冲 + 跟随）
│       └── dialogs.py          # 关闭到后台确认、退出前任务中断确认
└── tests/
    ├── test_capture.py         # 启动行解析、打码
    └── test_rpc.py             # 信封构造/解析（mock httpx）
```

## 3. 关键设计

### 3.1 ServerManager（QProcess 托管）

- 启动命令：`pnpm dsh web --no-open --port <port>`，cwd = `~/deepseek-harness`
  （`pnpm dsh web` 即根 package.json 的 script：
  `node --import tsx/esm apps/cli/src/bin.ts web`）。
- 端口策略：**默认固定 3080**（与现有习惯一致；签名 cookie 绑定 authority，
  同端口重启后旧 cookie 仍有效，QWebEngine profile 里的 cookie 可直接复用）；
  可配置 `--port 0` 随机端口。
- stdout 逐行扫描：
  `^dsh web: (https?://\S+?)/\?token=(\S+)$` → 发出 `ready(base, token)`。
- 状态机：`stopped → starting → ready → (stopped | crashed)`。
  - 启动超时（60s 内无 ready 行）→ 报错 + 展示日志尾部；
  - 崩溃（意外退出码）→ 按策略指数退避自动重启（1s/2s/4s/…30s 上限），
    手动停止不重启；
  - 停止：`terminate()`（SIGTERM），5s 未退 → `kill()`。
- 健康检查：每 15s `GET /`（无 cookie，期望 401=活着；连接拒绝=死）。
- 日志：环形缓冲（如 5000 行），所有出现 `token=` 的行打码（token 是敏感输出，
  官方诊断也刻意不复读它）。
- attach 模式（兜底）：服务器已由终端启动时，用户在设置里粘贴
  `dsh web: http://.../?token=*** 整行，桌面端只做 webview + 探针，
  不托管进程。

### 3.2 Webview（功能齐平的核心）

- `QWebEngineView` + 自定义 `QWebEnginePage`：
  - 加载 `ready` 给出的 token URL（303 换 cookie 是标准浏览器行为，自动完成）；
  - `acceptNavigationRequest`：`WebBrowserLink` 且目标非 loopback →
    `QDesktopServices.openUrl` 交系统浏览器，阻止在 webview 内跳走；
  - `setDeveloperToolsAvailable(True)`，菜单提供 DevTools/刷新/缩放（Ctrl+= 等）；
  - `createWindow` 返回 None（不弹子窗口，链接一律走系统浏览器）。
- 引擎问题预案：
  - Linux 系统库：按 PySide6 文档安装（libnss3、libasound2t64、libxkbcommon0、
    libgbm1、libpango-1.0-0、libcups2 等）；
  - GPU 异常：`QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`（可配置项）。
- M0 冒烟门槛（先做这个，过了再铺壳）：
  1. 页面加载出登录/工作区；2. 新建会话发消息，流式输出正常；
  3. 触发一次审批/ask-user 并回答；4. 打开文件侧栏看一个文件。

### 3.3 Probe（原生状态探针，只读）

- `GET {base}/connect?token=***&interactions=none`（`follow_redirects=False`，
  期望 302 + `Set-Cookie`），取 `name=value` 段作为后续所有请求的 cookie。
- 一元调用：`POST {base}/api/<ns.method>`，JSON 信封
  `{"type":"client-request","rpcId":<uuid>,"method":<ns.method>,"payload":{"args":{...}}}`，
  响应 `{"type":"server-response","result":{"ok":true,"value":...}}`。
  首选调 `session/list`（会话总数）。
- 实时状态：websocket-client 连
  `ws://127.0.0.1:PORT/api/remote.mux`（header 带 cookie），发
  `{"type":"open","streamId":"ctl","endpoint":"session/control","payload":{"args":{}}}`；
  收 `{"type":"item","streamId":"ctl","value":{type:"baseline"|"projection",...}}`，
  统计 running/idle 会话数 → Qt 信号 → 状态栏/托盘 tooltip。
- 生命周期纪律（协议规定）：**一条 WS 拥有整个 API peer**——socket 关闭后
  cookie 作废，必须重新 `/connect`。探针内部实现
  `断线 → 重新 connect → 重开流` 循环；服务器重启/换端口 → 全量重来。
- 线程模型：httpx 调用与 WS 读循环各放一个 QThread（或单线程跑 websocket-client
  的阻塞读），结果只经 Qt 信号回主线程。

### 3.4 原生壳行为（对齐官方桌面端的语义）

- 关闭主窗口 = **隐藏到托盘**（任务不中断），首次隐藏前弹一次确认；
  托盘双击 = 显示窗口；托盘右键 = 显示 / 启动·停止服务器 / 日志 / 退出。
- **退出**：先问探针"有几个会话在跑"——0 个直接退；>0 弹原生确认框
  （"正在运行的任务将中断"）；探针不可用按"有任务"处理。
- 单实例：`QLockFile`（`QDir.tempPath()/dsh-desktop.lock`），重复启动时聚焦已有窗口。
- 开机自启（可选）：systemd user unit 或 .desktop，后置。

## 4. 依赖与运行

```toml
[project]
requires-python = ">=3.12"
dependencies = ["PySide6>=6.8", "httpx>=0.27", "websocket-client>=1.8"]
[project.scripts]
dsh-desktop = "dsh_desktop.__main__:main"
```

- 开发运行：`uv run dsh-desktop`（仓库已在 `~/deepseek-harness` 且 web dist 已构建）。
- 打包（M4，可选）：PyInstaller 6.x + PySide6 QtWebEngine 支持成熟但产物
  150–300MB；自用阶段不必打。

## 5. 里程碑

| # | 内容 | 验收 | 预估 |
|---|---|---|---|
| M0 | webview 冒烟：20 行脚本加载 token URL | 聊天流式 + 审批 + 文件侧栏正常 | 0.5–1d |
| M1 | ServerManager + 主窗口 + 菜单 + 状态栏 | 启动即自动拉起服务器并显示 UI；停止/重启可用 | 1–2d |
| M2 | 托盘、关闭到后台、退出确认、日志窗、设置、单实例 | 全流程可日用 | 2–3d |
| M3 | Probe（/connect + control 流） | 状态栏/托盘实时显示会话与运行数 | 1–2d |
| M4 | 打磨/打包/自启（可选） | — | 视情况 |

## 6. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| QtWebEngine 与 web 前端兼容（实验性 worker-preview 等边角） | 预览类功能降级 | M0 门槛；核心流（聊天/流式/审批）基于标准 Web 技术，预期无碍 |
| 内部线协议随版本变化 | 探针失效 | 探针是只读增强项，失效不影响主功能；解析做容错 + 明确报错 |
| pnpm/node 冷启动慢 | 启动等待 | 60s 启动超时 + 状态栏"启动中"进度 |
| 双服务器争用（终端一个 + 桌面一个） | 同端口冲突；同 DSH_HOME 下 live 会话只属于一个进程 | 桌面端默认接管 3080，启动前探测端口占用并提示先停终端实例；attach 模式兜底 |
| token 泄露到日志/截图 | 安全 | 日志打码；token 不落盘（只内存）；QWebEngine profile cookie 存本机 |
| GPU/无头环境 | webview 白屏 | 配置 `--disable-gpu`；M0 在本机验证 |
| **同进程第二个 QWebEngineView 触发主视图左上角白块**（无 GPU 软件渲染下双渲染上下文互相干扰合成） | 主视图左上角一大块白色盖住侧栏/内容 | **已定位并修复**：DevTools 视图改为懒创建（用户首次打开"开发者工具"时才创建第二个 view，关闭时 `deleteLater` 销毁）。启动时进程内只保留一个渲染上下文。诊断脚本见 `scripts/diag_whiteblock.py` + `scripts/diag_harness.py`（特性开关 + 抓屏 + 左上角深色像素占比二分） |
| **venv PySide6（PyPI wheel）缺 fcitx5 输入法插件**（`platforminputcontexts/libfcitx5platforminputcontextplugin.so`），X11 下无法输入中文 | webview 里 fcitx5 候选框不出现、无法输入中文 | **已定位并修复**：版本对齐（PySide6 == 系统 qt6-base 主.次版本）后从系统 Qt 拷插件入 venv；`app.py` 启动时 `_ensure_fcitx5_plugin()` 幂等自检自动补插件。详见 §6.2 |

## 6.1 白块根因排查记录（2026-10-18）

现象：完整应用主视图左上角固定一块白色矩形盖住内容；冒烟脚本（单 view）无此问题。

排查路径（逐步排除）：
1. `grab()`（Qt 渲染层）抓图完整无白块，X11 `import -window root` 抓屏有白块 → 白块在**合成/上屏层**，非页面渲染问题。
2. 浏览器（同为 Chromium）渲染同一页面完美 → 非页面/CSS 问题，是 QtWebEngine 嵌入特有。
3. `--disable-gpu` / `--disable-gpu-compositing` / 尺寸抖动 / 缩放抖动 / show-after-URL 均无效。
4. 特性开关二分（`diag_harness.py`）：menu/status/page/probe/tray/zoom 单独或组合都无白块；**只要存在第二个 QWebEngineView（哪怕隐藏、哪怕普通页）立即复现白块**。

结论：无 GPU 软件渲染下，同进程第二个 Chromium 渲染上下文会干扰第一个 view 的合成，导致左上角白块。修复 = DevTools 懒创建（启动时单上下文）。

## 6.2 中文输入（fcitx5）根因与修复记录（2026-10-18）

现象：webview 里无法输入中文（fcitx5 候选框完全不出现）；浏览器/firefox 等正常。

排查路径：
1. 环境变量正常（`QT_IM_MODULE=fcitx` / `XMODIFIERS=@im=fcitx` / `GTK_IM_MODULE=fcitx`），fcitx5 进程与 D-Bus 正常 → 排除环境/输入法本身。
2. 改 `QT_IM_MODULE=fcitx5`、`LANG=zh_CN.UTF-8` 均无效 → 排除环境变量方向（已回退）。
3. 关键发现（对照 LYZNote 同款问题文档 `~/code/python/LYZNote/linux下不能输入中文解决方法.md`）：**venv 的 PySide6（PyPI wheel）的 `Qt/plugins/platforminputcontexts/` 里没有 `libfcitx5platforminputcontextplugin.so`**，只有 compose/ibus/virtualkeyboard。系统 Qt 有。
4. 原理：X11 下 Qt6 的 fcitx5 输入走 **platforminputcontexts 插件机制**（Wayland 走 text-input 协议、不需要插件）。缺插件 → xcb 平台无 IM 上下文 → 无法输入。

结论与修复：
- 版本核对：venv PySide6 **6.12.0** == 系统 `qt6-base` **6.12.0**（主.次一致，插件 ABI 可加载；不一致则需先升级 PySide6 对齐）。
- 从系统 Qt 拷贝插件到 venv：
  `cp /usr/lib/qt6/plugins/platforminputcontexts/libfcitx5platforminputcontextplugin.so .venv/lib/python3.12/site-packages/PySide6/Qt/plugins/platforminputcontexts/`
- 验证：`QT_DEBUG_PLUGINS=1` 看到 `libfcitx5platforminputcontextplugin.so ... Got keys QList("fcitx","fcitx5")` 即加载成功。
- **防丢失**：`app.py` 启动时调 `_ensure_fcitx5_plugin()`（幂等）——插件缺失时自动从系统 Qt 补回，venv 重建后无需手动 cp。

维护提示：Arch `pacman -Syu` 升级系统 Qt 后若中文输入失效，先比 `pacman -Q qt6-base` 与 venv PySide6 版本，对齐后重拷新插件（旧插件 ABI 不兼容）。

## 6.3 Windows 跨平台适配（2026-10-18）

目标：不止能在本机（Linux/X11）用，也要能在 Windows 上跑。逐点适配：

| 点 | Linux | Windows | 处理 |
|---|---|---|---|
| fcitx5 中文输入插件 | 需要（venv PySide6 缺，启动自检 `_ensure_fcitx5_plugin` 从系统 Qt 补） | 不需要（OS 提供 IME） | `_ensure_fcitx5_plugin` 加 `sys.platform != "linux"` 守卫，非 Linux 直接 return |
| GPU 渲染 | 无 GPU 机器需 `--disable-gpu`（软件渲染白块风险） | 有 GPU，正常硬件渲染 | `Config.disable_gpu` 默认值平台感知：Linux 默认 `True`、Windows/macOS 默认 `False`（`field(default_factory=...)`）；用户可在 config.json 覆盖 |
| 服务器命令 | `pnpm dsh web` | `pnpm` 是批处理脚本 `pnpm.cmd`（非 pnpm.exe） | 默认 `server_command` 平台感知（Windows 用 `pnpm.cmd`）；`ServerManager._command()` 额外把裸 `pnpm` 归一化为 `pnpm.cmd`（兼容旧配置） |
| 配置路径 | `~/.config/dsh_desktop/config.json`（`$XDG_CONFIG_HOME`） | `%APPDATA%\dsh_desktop\config.json` | `config.py` 的 `CONFIG_DIR` 平台感知（`os.name == "nt"` 走 `%APPDATA%`） |
| 托盘右键菜单 | CWM 托盘原生菜单不触发 Qt 动作 → 手动 `Context` 激活 + Qt 菜单 | 原生托盘菜单正常触发 | `tray.py` 平台感知：Windows 用 `setContextMenu`，Linux 用手动 `Context` 弹 Qt 菜单 |
| dsh-web 配置路径 | `~/.dsh/profiles/web/cordis.patch.yml` | `C:\Users\<u>\.dsh\profiles\web\cordis.patch.yml` | `Path.home()` 跨平台，无需改 |
| 编辑器 | config `editor`（如 emacs） | config `editor`（如 notepad/code） | 用户按平台在 config.json 设 `editor`；`QProcess.startDetached` 跨平台 |

重启遮罩（跨平台）：`QWebEngineView` 是原生表面，Qt 控件无法叠在其上，故用
`QStackedWidget`（page0=webview、page1=占位层"服务器重启中…"）切换。服务器状态
`STARTING` 且窗口已可见（重启而非首次启动）时切到占位层，`READY` 时切回 webview，
避免重启期间 webview 里 "connection lost, retry #N" 闪烁。

## 6.4 Nuitka 打包（2026-10-18）

用 Nuitka（非 PyInstaller）打包三平台：Windows 单文件 .exe / Linux 目录包 /
macOS .app。构建脚本 `scripts/build_nuitka.py`（参考 LYZNote 同名脚本，平台自动
识别 + 前置检查 + 后处理打包），GitHub Actions（`.github/workflows/build.yml`）
在三个 runner 上跑同一脚本，推 tag 自动发 Release。

关键坑（Nuitka 4.3.1 + PySide6）：
1. **选项名**：`--enable-plugins=pyside6`（非 `--enable-plugin`/`--plugin-enable`）；
   `--include-data-files=`（非 `--include-data-file`）；**无 `--include-path`**——
   靠 `PYTHONPATH=src` 让 Nuitka 经 sys.path 解析 `dsh_desktop` 包。
2. **Linux standalone 需要 patchelf**（`uv pip install patchelf` 或系统包）。
3. **fcitx5 插件路径**（最隐蔽）：Nuitka pyside6 插件把 Qt 插件收集到
   `PySide6/qt-plugins/`（非 `PySide6/Qt/plugins/`），且运行时
   `QCoreApplication.setLibraryPaths([<bundle>/PySide6/qt-plugins])` 是**替换**
   （唯一搜索路径）。故 fcitx5 插件必须放 `PySide6/qt-plugins/platforminputcontexts/`
   才能被找到（`QT_DEBUG_PLUGINS=1` 验证：`checking directory .../qt-plugins/
   platforminputcontexts` → `Found metadata ... "fcitx","fcitx5"`）。
   构建脚本 `--include-data-files` 目标已对齐；运行时 `_ensure_fcitx5_plugin`
   按"`PySide6/qt-plugins` 目录存在即为 Nuitka 布局，否则 venv `Qt/plugins`"
   确定唯一活跃路径（`__compiled__` 标记在 Nuitka 4.x 不可靠，弃用）。

## 7. 约定

- 服务器进程归桌面端独占管理（attach 模式除外）；不追求同时管两个实例。
- DSH_HOME 默认 `~/.dsh`，与终端 web 共享会话库（会话列表互通；live 会话互斥
  属正常行为）。
- 桌面端不解析、不缓存 web 页面内容；一切 UI 数据以 web 前端为准，探针仅取
  聚合状态。
