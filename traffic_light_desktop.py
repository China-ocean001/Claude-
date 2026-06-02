#!/usr/bin/env python3
"""
Claude Code 桌面悬浮红绿灯 —— Windows 版
始终置顶的桌面小窗口，实时显示 Claude Code 会话状态：
- 绿灯常亮：会话进行中
- 黄灯闪烁：需要确认（等待权限）
- 红灯常亮：会话结束

纯 tkinter 实现，无需额外依赖。
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

# ---------- 配置 ----------
BASE_DIR = os.path.expanduser("~/.claude/traffic_light")
STATE_DIR = BASE_DIR
CONFIG_PATH = os.path.expanduser("~/.claude/settings.json")
BACKUP_PATH = os.path.join(BASE_DIR, "settings_backup.json")
SELECTED_FILE = os.path.join(BASE_DIR, "selected_project")
BLINK_INTERVAL = 0.5
TRAFFIC_MARKER = "traffic_light_app"

# 窗口尺寸
WIN_W = 130
WIN_H = 260
LIGHT_R = 30          # 灯球半径
LIGHT_SPACING = 68    # 灯球间距


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
            if not Path(BACKUP_PATH).exists():
                shutil.copy2(CONFIG_PATH, BACKUP_PATH)
                print(f"Backed up original config: {BACKUP_PATH}")
            return True
        except Exception as e:
            print(f"Backup failed: {e}")
    return True


def restore_config():
    if Path(BACKUP_PATH).exists():
        try:
            shutil.copy2(BACKUP_PATH, CONFIG_PATH)
            Path(BACKUP_PATH).unlink()
            print(f"Restored original config: {CONFIG_PATH}")
        except Exception:
            pass
    if Path(STATE_DIR).exists():
        try:
            shutil.rmtree(STATE_DIR)
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
        # 用 Python 执行，跨平台兼容（不依赖 bash/cmd）
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
        print(f"Hook set: {hook_name}")

    config["hooks"] = hooks
    try:
        Path(CONFIG_PATH).write_text(json.dumps(config, indent=2, sort_keys=True))
        print(f"Claude Code config updated: {CONFIG_PATH}")
    except Exception as e:
        print(f"Write config failed: {e}")


def remove_hooks():
    if not Path(CONFIG_PATH).exists():
        print("settings.json not found")
        return
    try:
        config = json.loads(Path(CONFIG_PATH).read_text())
    except Exception:
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
        print(f"Hooks removed: {CONFIG_PATH}")
    else:
        print("No hooks to remove")


# ---------- 桌面悬浮窗 ----------
class TrafficLightOverlay:
    """桌面悬浮红绿灯 — 精美版"""

    # 亮灯颜色 (fill, glow)
    LIGHTS = {
        "red":    {"on": "#FF2D2D", "off": "#3A0000", "glow_on": "#FF6060", "glow_off": "#1A0000"},
        "yellow": {"on": "#FFB800", "off": "#3A2A00", "glow_on": "#FFD060", "glow_off": "#1A1200"},
        "green":  {"on": "#2ECC40", "off": "#003A08", "glow_on": "#60E670", "glow_off": "#001A04"},
    }

    def __init__(self):
        import tkinter as tk

        self.tk = tk
        self.state = "red"
        self.blink_on = True
        self.running = True
        self.auto_mode = True  # 默认自动跟随模式
        self.selected_project = self._find_most_active() or "default"
        self.drag_x = self.drag_y = 0

        # 窗口
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", "#010101")
        self.root.configure(bg="#010101")
        scr_w = self.root.winfo_screenwidth()
        scr_h = self.root.winfo_screenheight()
        self.root.geometry(f"{WIN_W}x{WIN_H}+{scr_w - WIN_W - 20}+{scr_h // 2 - WIN_H // 2}")

        # 画布
        self.canvas = tk.Canvas(
            self.root, width=WIN_W, height=WIN_H,
            bg="#010101", highlightthickness=0, bd=0, cursor="hand2",
        )
        self.canvas.pack()

        # --- 绘制静态背景 ---
        # 卡片背景（圆角矩形）
        pad = 8
        self.canvas.create_rounded_rect(pad, pad, WIN_W - pad, WIN_H - pad,
                                          radius=16, fill="#1C1C1E", outline="#3A3A3C", width=1)
        # 标题
        self.canvas.create_text(WIN_W // 2, 20, text="Claude", fill="#888",
                                 font=("Segoe UI", 8, "bold"))

        # 三个灯的底座（深色凹槽）
        self.light_bases = []
        self.light_glows = []
        self.light_bulbs = []
        self.light_highlights = []
        self.light_labels = []
        labels = ["红", "黄", "绿"]

        for i in range(3):
            cy = 52 + i * LIGHT_SPACING
            # 凹槽（暗色圆环底）
            base = self.canvas.create_oval(
                WIN_W // 2 - LIGHT_R - 4, cy - LIGHT_R - 4,
                WIN_W // 2 + LIGHT_R + 4, cy + LIGHT_R + 4,
                fill="#111113", outline="#2A2A2C", width=1,
            )
            self.light_bases.append(base)
            # 光晕（外圈柔光）
            glow = self.canvas.create_oval(
                WIN_W // 2 - LIGHT_R - 2, cy - LIGHT_R - 2,
                WIN_W // 2 + LIGHT_R + 2, cy + LIGHT_R + 2,
                fill="#1A0000", outline="", tags=f"glow_{i}",
            )
            self.light_glows.append(glow)
            # 主灯球
            bulb = self.canvas.create_oval(
                WIN_W // 2 - LIGHT_R, cy - LIGHT_R,
                WIN_W // 2 + LIGHT_R, cy + LIGHT_R,
                fill="#3A0000", outline="", tags=f"bulb_{i}",
            )
            self.light_bulbs.append(bulb)
            # 高光（左上角亮点）
            hl = self.canvas.create_oval(
                WIN_W // 2 - LIGHT_R + 8, cy - LIGHT_R + 6,
                WIN_W // 2 - LIGHT_R + 20, cy - LIGHT_R + 18,
                fill="#FFFFFF", outline="", stipple="gray25", tags=f"hl_{i}",
            )
            self.light_highlights.append(hl)
            # 标签
            lbl = self.canvas.create_text(WIN_W // 2, cy + LIGHT_R + 13,
                                           text=labels[i], fill="#555",
                                           font=("Segoe UI", 7, "bold"),
                                           tags=f"lbl_{i}")
            self.light_labels.append(lbl)

        # 底部状态文字
        self.status_text = self.canvas.create_text(
            WIN_W // 2, WIN_H - 14,
            text="Idle",
            fill="#666",
            font=("Segoe UI", 8),
        )

        # --- 事件绑定 ---
        self.canvas.bind("<Button-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<Button-3>", self._right_click)
        # 鼠标悬停效果
        self.canvas.bind("<Enter>", lambda e: self.canvas.config(cursor="hand2"))

        self._update_display()

    # --- 圆角矩形辅助 ---
    @staticmethod
    def _create_rounded_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
        """在 canvas 上画圆角矩形"""
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)

    # Monkey-patch the method onto Canvas so we can use it easily
    def _get_light_colors(self, pos):
        """返回 (fill, glow, highlight_opacity)"""
        if pos == 0:    # red
            key = "red"
            active = (self.state == "red")
        elif pos == 1:  # yellow
            key = "yellow"
            active = (self.state == "yellow" and self.blink_on)
        else:           # green
            key = "green"
            active = (self.state == "green")

        cfg = self.LIGHTS[key]
        which = "on" if active else "off"
        return cfg[which], cfg[f"glow_{which}"], (1.0 if active else 0.15)

    def _update_display(self):
        """刷新所有灯和状态文字"""
        status_label = "空闲"
        for i in range(3):
            fill, glow, hl_opacity = self._get_light_colors(i)
            self.canvas.itemconfig(self.light_bulbs[i], fill=fill)
            self.canvas.itemconfig(self.light_glows[i], fill=glow)
            alpha = "gray25" if hl_opacity > 0.5 else "gray12" if hl_opacity > 0.1 else ""
            self.canvas.itemconfig(self.light_highlights[i],
                                    fill="#FFFFFF" if hl_opacity > 0.5 else "#333333",
                                    stipple=alpha)

            if i == 0 and self.state == "red":
                self.canvas.itemconfig(self.light_labels[i], fill="#FF6060")
                status_label = "等待中"
            elif i == 1 and self.state == "yellow":
                clr = "#FFD060" if self.blink_on else "#3A2A00"
                self.canvas.itemconfig(self.light_labels[i], fill=clr)
                status_label = "需确认"
            elif i == 2 and self.state == "green":
                self.canvas.itemconfig(self.light_labels[i], fill="#60E670")
                status_label = "运行中"
            else:
                self.canvas.itemconfig(self.light_labels[i], fill="#555")

        self.canvas.itemconfig(self.status_text, text=status_label,
                                fill="#AAA" if status_label == "运行中" else "#666")

    def _start_drag(self, event):
        self.drag_x = event.x
        self.drag_y = event.y

    def _on_drag(self, event):
        x = self.root.winfo_x() + event.x - self.drag_x
        y = self.root.winfo_y() + event.y - self.drag_y
        self.root.geometry(f"+{x}+{y}")

    def _right_click(self, event):
        menu = self.tk.Menu(self.root, tearoff=0)

        # 自动模式开关
        auto_label = "[自动] 跟随活跃终端" if self.auto_mode else "[手动] 固定项目"
        menu.add_command(
            label=auto_label,
            command=self._toggle_auto,
            foreground="#4FC3F7" if self.auto_mode else "#888",
        )

        menu.add_command(
            label=f"当前项目: {self.selected_project}",
            state="disabled",
            foreground="#AAA",
        )

        menu.add_separator()

        projects = list_active_projects()
        if projects:
            proj_menu = self.tk.Menu(menu, tearoff=0)
            for p in projects:
                mark = " [当前]" if p == self.selected_project else ""
                proj_menu.add_command(
                    label=f"  {p}{mark}",
                    command=lambda name=p: self._switch_project(name),
                )
            menu.add_cascade(label="切换项目", menu=proj_menu)
        else:
            menu.add_command(label="(无活跃项目)", state="disabled")

        menu.add_command(label="+ 手动添加项目", command=self._manual_project)

        removable = [p for p in projects if p != self.selected_project]
        if removable:
            del_menu = self.tk.Menu(menu, tearoff=0)
            for p in removable:
                del_menu.add_command(
                    label=f"  {p}",
                    command=lambda name=p: self._delete_project(name),
                )
            menu.add_cascade(label="- 删除项目", menu=del_menu)

        menu.add_separator()
        menu.add_command(label="退出", command=self._quit)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _manual_project(self):
        """手动输入项目名"""
        dialog = self.tk.Toplevel(self.root)
        dialog.title("添加项目")
        dialog.geometry("240x100")
        dialog.attributes("-topmost", True)
        dialog.configure(bg="#1C1C1E")
        dialog.overrideredirect(True)

        wx = self.root.winfo_x()
        wy = self.root.winfo_y()
        dialog.geometry(f"+{wx - 55}+{wy + WIN_H + 5}")

        self.tk.Label(dialog, text="输入项目名称:",
                       bg="#1C1C1E", fg="#CCC",
                       font=("Microsoft YaHei", 9)).pack(pady=(10, 2))

        entry = self.tk.Entry(dialog, bg="#2C2C2E", fg="#FFF",
                               insertbackground="#FFF", relief="flat",
                               font=("Microsoft YaHei", 10))
        entry.pack(padx=12, pady=4, fill="x")
        entry.focus_set()

        def do_add():
            name = entry.get().strip()
            if name:
                sf = get_state_file(name)
                Path(sf).parent.mkdir(parents=True, exist_ok=True)
                if not Path(sf).exists():
                    Path(sf).write_text("red")
                self._switch_project(name)
            dialog.destroy()

        entry.bind("<Return>", lambda e: do_add())
        dialog.bind("<FocusOut>", lambda e: dialog.destroy())
        dialog.bind("<Escape>", lambda e: dialog.destroy())

    def _delete_project(self, name):
        """删除项目状态文件"""
        sf = get_state_file(name)
        try:
            Path(sf).unlink(missing_ok=True)
        except Exception:
            pass

    def _find_most_active(self):
        """找到最近更新的项目（按状态文件修改时间排序）"""
        projects = list_active_projects()
        if not projects:
            return None
        best = None
        best_time = 0
        for p in projects:
            sf = get_state_file(p)
            try:
                mtime = Path(sf).stat().st_mtime
                if mtime > best_time:
                    best_time = mtime
                    best = p
            except Exception:
                pass
        return best

    def _switch_project(self, name):
        self.selected_project = name
        self.auto_mode = False  # 手动切换后关闭自动模式
        set_selected_project(name)
        self.state = "red"
        self.blink_on = True
        self._update_display()

    def _toggle_auto(self):
        """切换自动/手动模式"""
        self.auto_mode = not self.auto_mode
        if self.auto_mode:
            active = self._find_most_active()
            if active:
                self.selected_project = active
            self.state = "red"
            self.blink_on = True
        self._update_display()

    def _quit(self):
        self.running = False
        self.root.destroy()

    def check_state(self):
        if self.auto_mode:
            # 自动模式：跟随最近活跃的项目
            active = self._find_most_active()
            if active and active != self.selected_project:
                self.selected_project = active
                set_selected_project(active)

        sf = get_state_file(self.selected_project)
        try:
            if Path(sf).exists():
                c = Path(sf).read_text().strip().lower()
                if c in ("green", "yellow", "red") and c != self.state:
                    self.state = c
                    self.blink_on = True
            else:
                if self.state != "red":
                    self.state = "red"
        except Exception:
            pass

    def blink(self):
        if self.state == "yellow":
            self.blink_on = not self.blink_on

    def run(self):
        def poll():
            while self.running:
                try:
                    self.check_state()
                    self.blink()
                    self.root.after(0, self._update_display)
                except Exception:
                    pass
                time.sleep(BLINK_INTERVAL)

        threading.Thread(target=poll, daemon=True).start()
        self.root.mainloop()


# Monkey-patch: 给 Canvas 加圆角矩形方法
import tkinter as tk
def _rounded_rect(canvas, x1, y1, x2, y2, radius, **kwargs):
    pts = [x1+radius, y1, x2-radius, y1, x2, y1, x2, y1+radius,
           x2, y2-radius, x2, y2, x2-radius, y2, x1+radius, y2,
           x1, y2, x1, y2-radius, x1, y1+radius, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kwargs)
tk.Canvas.create_rounded_rect = _rounded_rect


# ---------- 入口 ----------
def main():
    print("=" * 50)
    print("  Claude Code 红绿灯 - 桌面悬浮窗")
    print("=" * 50)
    print()

    if len(sys.argv) > 1 and sys.argv[1] == "--clean":
        print("正在清理 hooks...")
        remove_hooks()
        restore_config()
        print("完成！")
        return

    print("正在配置 Claude Code hooks...")
    configure_hooks()
    print()

    atexit.register(lambda: print("\n清理...") or restore_config())

    def handler(sig, frame):
        print("\n正在退出...")
        restore_config()
        sys.exit(0)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    print("启动桌面悬浮窗...")
    print("拖拽移动 | 右键菜单")
    print()

    app = TrafficLightOverlay()
    app.run()


if __name__ == "__main__":
    main()
