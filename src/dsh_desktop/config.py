"""Application configuration (JSON under the user config dir)."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

if os.name == "nt":
    # Windows: %APPDATA%\dsh_desktop (per-user Roaming config).
    CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "dsh_desktop"
else:
    # Linux/macOS: $XDG_CONFIG_HOME/dsh_desktop (defaults to ~/.config).
    CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "dsh_desktop"
CONFIG_PATH = CONFIG_DIR / "config.json"


def is_valid_dsh_repo(path: str) -> bool:
    """True if ``path`` is a usable deepseek-harness checkout.

    A valid checkout contains the DSH CLI entry (``apps/cli/src/bin.ts``) — the
    file ``pnpm dsh`` runs. This is specific to deepseek-harness (a plain
    ``package.json`` is not enough).
    """
    from pathlib import Path

    p = Path(path)
    if not p.is_dir():
        return False
    return (p / "apps" / "cli" / "src" / "bin.ts").is_file()


@dataclass
class Config:
    # Where `pnpm dsh web` is launched from (the deepseek-harness checkout).
    repo_dir: str = str(Path.home() / "deepseek-harness")
    # Server command (argv[0] + args); `--no-open --port <port>` is appended.
    # On Windows, pnpm is a batch script (pnpm.cmd), not pnpm.exe.
    server_command: list[str] = field(
        default_factory=lambda: (
            ["pnpm.cmd", "dsh", "web"] if os.name == "nt" else ["pnpm", "dsh", "web"]
        )
    )
    # 0 = let the OS pick a free port.
    port: int = 0
    auto_start_server: bool = True
    auto_restart_on_crash: bool = True
    # Force CPU rendering (no GPU). Default is platform-aware: True on Linux
    # (GPU-less machines fail the Vulkan/GBM probe and the software-rendering
    # fallback can leave a region unpainted), False on Windows/macOS (GPU
    # rendering works). A user can override in config.json.
    disable_gpu: bool = field(
        default_factory=lambda: os.name == "posix" and sys.platform == "linux"
    )
    hide_to_tray: bool = True
    zoom: float = 1.0
    # Editor used to open config files (e.g. "emacs", "code", "vim"). Empty =
    # fall back to the system default (QDesktopServices.openUrl), which may show
    # an "Open With…" dialog if no default app is associated with the file type.
    editor: str = ""
    # Attach mode: paste the whole `dsh web: http://.../?token=...` line (or a
    # plain URL carrying ?token=) to attach to an externally started server.
    attach_line: str = ""

    @classmethod
    def load(cls) -> "Config":
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
