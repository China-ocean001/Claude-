#!/usr/bin/env python3
"""
Claude Code 系统托盘红绿灯 —— Windows 版
通过系统托盘图标实时显示 Claude Code 会话状态：
- 绿灯常亮：会话进行中
- 黄灯闪烁：需要确认（等待权限）
- 红灯常亮：会话结束
"""
import json
import sys
import os
import shutil
import atexit
import signal
import time
import threading
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("请先安装依赖: pip install pystray Pillow")
    sys.exit(1)

# ---------- 配置 ----------
BASE_DIR = os.path.expanduser("~/.claude/traffic_light")
STATE_DIR = BASE_DIR
CONFIG_PATH = os.path.expanduser("~/.claude/settings.json")
BACKUP_PATH = os.path.join(BASE_DIR, "settings_backup.json")
SELECTED_FILE = os.path.join(BASE_DIR, "selected_project")
BLINK_INTERVAL = 0.5
TRAY_ICON_SIZE = 64
TRAFFIC_MARKER = "traffic_light_app"

# ---------- 图标生成 ----------
def create_tray_icon(colors):
    """创建 64x64 系统托盘图标（三个圆形灯垂直排列）"""
    size = TRAY_ICON_SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = 4
    spacing = (size - 2 * margin) // 3
    centers = [
        (size // 2, margin + spacing // 2),
        (size // 2, size // 2),
        (size // 2, size - margin - spacing // 2),
    ]
    radius = spacing // 2 - 4
    off_color = (60, 60, 60)

    for i, (cx, cy) in enumerate(centers):
        color = colors[i] if colors[i] else off_color
        r, g, b = color
        glow_color = (min(r + 40, 255), min(g + 40, 255), min(b + 40, 255))
        draw.ellipse(
            [cx - radius - 1, cy - radius - 1, cx + radius + 1, cy + radius + 1],
            fill=glow_color
        )
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=color
        )
        highlight_r = max(radius // 3, 2)
        draw.ellipse(
            [cx - highlight_r, cy - radius + highlight_r,
             cx + highlight_r, cy - radius + highlight_r * 3],
            fill=(255, 255, 255, 100)
        )

    return img

# ---------- 状态文件操作 ----------
def get_state_file(project_name=None):
    if project_name is None:
        project_name = get_selected_project()
    return os.path.join(STATE_DIR, f"{project_name}.state")

def get_selected_project():
    try:
        if Path(SELECTED_FILE).exists():
            return Path(SELECTED_FILE).read_text().strip()
    except Exception:
        pass
    projects = list_active_projects()
    return projects[0] if projects else "default"

def set_selected_project(project_name):
    try:
        Path(SELECTED_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(SELECTED_FILE).write_text(project_name)
    except Exception:
        pass

def list_active_projects():
    try:
        Path(STATE_DIR).mkdir(parents=True, exist_ok=True)
        return sorted(f.stem for f in Path(STATE_DIR).glob("*.state"))
    except Exception:
        return []

# ---------- 配置备份/还原 ----------
def backup_config():
    if Path(CONFIG_PATH).exists():
        try:
            # 只在首次运行时备份（保护原始配置不被覆盖）
            if not Path(BACKUP_PATH).exists():
                shutil.copy2(CONFIG_PATH, BACKUP_PATH)
                print(f"已备份原始配置: {BACKUP_PATH}")
            else:
                print(f"备份已存在，跳过: {BACKUP_PATH}")
            return True
        except Exception as e:
            print(f"备份配置失败: {e}")
    return True

def restore_config():
    if Path(BACKUP_PATH).exists():
        try:
            shutil.copy2(BACKUP_PATH, CONFIG_PATH)
            Path(BACKUP_PATH).unlink()
            print(f"已还原原始配置: {CONFIG_PATH}")
        except Exception as e:
            print(f"还原配置失败: {e}")
    if Path(STATE_DIR).exists():
        try:
            shutil.rmtree(STATE_DIR)
            print(f"已清理状态目录: {STATE_DIR}")
        except Exception:
            pass
    if Path(SELECTED_FILE).exists():
        try:
            Path(SELECTED_FILE).unlink()
        except Exception:
            pass

# ---------- Hook 配置 ----------
def _is_traffic_hook(entry):
    return any(TRAFFIC_MARKER in h.get("command", "") for h in entry.get("hooks", []))

def _make_hook_entry(command, matcher=""):
    return {"matcher": matcher, "hooks": [{"type": "command", "command": command}]}

def configure_hooks():
    Path(CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(STATE_DIR).mkdir(parents=True, exist_ok=True)
    backup_config()

    config = {}
    if Path(CONFIG_PATH).exists():
        try:
            config = json.loads(Path(CONFIG_PATH).read_text())
        except Exception:
            config = {}

    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}

    def _hook_cmd(state):
        marker = f"# {TRAFFIC_MARKER}"
        # Python-based hook - cross-platform, no bash dependency
        return (
            f'python -c "'
            f'import os,pathlib;'
            f'p=pathlib.Path(os.environ.get(\\"CLAUDE_PROJECT_DIR\\",os.getcwd())).name;'
            f'd=os.path.expanduser(\\"~/.claude/traffic_light\\");'
            f'os.makedirs(d,exist_ok=True);'
            f'open(os.path.join(d,p+\\".state\\"),\\"w\\").write(\\"{state}\\")'
            f'" {marker}'
        )

    permission_tools = "Bash|Write|Edit|NotebookEdit|WebFetch"
    desired = {
        "SessionStart":       [_make_hook_entry(_hook_cmd("red"))],
        "UserPromptSubmit":   [_make_hook_entry(_hook_cmd("green"))],
        "PermissionRequest":  [_make_hook_entry(_hook_cmd("yellow"))],
        "PostToolUse":        [_make_hook_entry(_hook_cmd("green"), matcher=permission_tools)],
        "Stop":               [_make_hook_entry(_hook_cmd("red"))],
        "SessionEnd":         [_make_hook_entry(_hook_cmd("red"))],
    }

    for hook_name, new_entries in desired.items():
        existing = hooks.get(hook_name, [])
        if not isinstance(existing, list):
            existing = []
        cleaned = [e for e in existing if not _is_traffic_hook(e)]
        cleaned.extend(new_entries)
        hooks[hook_name] = cleaned
        print(f"已设置 hook: {hook_name}")

    config["hooks"] = hooks
    try:
        Path(CONFIG_PATH).write_text(json.dumps(config, indent=2, sort_keys=True))
        print(f"Claude Code 配置已更新: {CONFIG_PATH}")
    except Exception as e:
        print(f"写入配置失败: {e}")

def remove_hooks():
    if not Path(CONFIG_PATH).exists():
        print("未找到 settings.json")
        return
    try:
        config = json.loads(Path(CONFIG_PATH).read_text())
    except Exception:
        print("读取 settings.json 失败")
        return
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        return
    removed = False
    for hook_name in list(hooks.keys()):
        existing = hooks[hook_name]
        if not isinstance(existing, list):
            continue
        cleaned = [e for e in existing if not _is_traffic_hook(e)]
        if len(cleaned) != len(existing):
            removed = True
            if cleaned:
                hooks[hook_name] = cleaned
            else:
                del hooks[hook_name]
    if removed:
        config["hooks"] = hooks
        Path(CONFIG_PATH).write_text(json.dumps(config, indent=2, sort_keys=True))
        print(f"已移除 hooks: {CONFIG_PATH}")
    else:
        print("没有找到需要移除的 hooks")

# ---------- 系统托盘应用 ----------
COLORS = {
    "red":    (255, 50, 50),
    "yellow": (255, 200, 0),
    "green":  (50, 200, 50),
}

class TrafficLightApp:
    """Windows 系统托盘红绿灯 — 简化版，icon.run() 在主线程"""

    def __init__(self):
        self.state = "red"
        self.blink_on = True
        self.selected_project = get_selected_project()
        self.running = True

        # 初始图标
        image = self._make_image()
        self.icon = pystray.Icon(
            "claude_traffic_light",
            image,
            "Claude Code - 已结束",
            menu=self._build_menu(),
        )

    def _make_image(self):
        off = None
        if self.state == "green":
            colors = (off, off, COLORS["green"])
        elif self.state == "yellow":
            yc = COLORS["yellow"] if self.blink_on else off
            colors = (off, yc, off)
        else:
            colors = (COLORS["red"], off, off)
        return create_tray_icon(colors)

    def _update_icon(self):
        if self.icon and self.icon.visible:
            self.icon.icon = self._make_image()
            titles = {
                "green": "Claude Code - 进行中",
                "yellow": "Claude Code - 等待确认",
                "red": "Claude Code - 已结束",
            }
            self.icon.title = titles.get(self.state, "Claude Code 红绿灯")

    def _build_menu(self):
        projects = list_active_projects()
        project_items = []
        for p in projects:
            project_items.append(pystray.MenuItem(
                p, self._select_project(p),
                checked=lambda proj=p: proj == self.selected_project,
                radio=True,
            ))

        if project_items:
            project_menu = pystray.Menu(*project_items)
        else:
            project_menu = pystray.Menu(
                pystray.MenuItem("(无活跃项目)", None, enabled=False))

        return pystray.Menu(
            pystray.MenuItem("选择项目", project_menu),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"当前: {self.selected_project}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("绿灯 - 进行中", None, enabled=False),
            pystray.MenuItem("黄灯 - 等待确认", None, enabled=False),
            pystray.MenuItem("红灯 - 已结束", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._quit),
        )

    def _select_project(self, name):
        def cb(icon, item):
            self.selected_project = name
            set_selected_project(name)
            self.state = "red"
            self.blink_on = True
            self._update_icon()
            icon.menu = self._build_menu()
        return cb

    def _quit(self, icon, item):
        self.running = False
        icon.stop()

    def _check_and_update(self):
        """检查状态文件并更新显示"""
        # 读状态文件
        sf = get_state_file(self.selected_project)
        try:
            if Path(sf).exists():
                content = Path(sf).read_text().strip().lower()
                if content in ("green", "yellow", "red") and content != self.state:
                    self.state = content
                    self.blink_on = True
            else:
                if self.state != "red":
                    self.state = "red"
        except Exception:
            pass

        # 闪烁（仅黄灯时）
        if self.state == "yellow":
            self.blink_on = not self.blink_on

        # 更新图标
        self._update_icon()

        # 定期刷新菜单
        if not hasattr(self, '_menu_tick'):
            self._menu_tick = 0
        self._menu_tick += 1
        if self._menu_tick % 4 == 0:  # 每 4 个 tick ≈ 2 秒
            try:
                if self.icon and self.icon.visible:
                    self.icon.menu = self._build_menu()
            except Exception:
                pass

    def run(self):
        """直接在主线程运行 pystray，用 setup 回调启动后台轮询"""
        # 启动后台轮询线程（daemon 线程更新 icon 属性是线程安全的）
        def poll_loop():
            while self.running:
                self._check_and_update()
                time.sleep(BLINK_INTERVAL)

        poll_thread = threading.Thread(target=poll_loop, daemon=True)
        poll_thread.start()

        # pystray 主循环（阻塞，在主线程运行）
        self.icon.run()

# ---------- 入口 ----------
def main():
    print("=" * 50)
    print("  Claude Code Red/Green Light - Windows")
    print("=" * 50)
    print()

    if len(sys.argv) > 1 and sys.argv[1] == "--clean":
        print("Cleaning hooks...")
        remove_hooks()
        restore_config()
        print("Done!")
        return

    print("Configuring Claude Code hooks...")
    configure_hooks()
    print()

    atexit.register(lambda: print("\nCleaning...") or restore_config())

    def handler(sig, frame):
        print("\nShutting down...")
        restore_config()
        sys.exit(0)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    print("Starting system tray traffic light...")
    print("(Right-click tray icon for menu)")
    print()

    app = TrafficLightApp()
    app.run()

if __name__ == "__main__":
    main()
