"""Minimal pystray test - does a tray icon appear?"""
import sys, os, traceback, time

try:
    import pystray
    from PIL import Image, ImageDraw
    print("pystray and PIL imported OK")
except Exception as e:
    print(f"Import error: {e}")
    sys.exit(1)

# Create a simple 64x64 icon
def make_icon(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=color)
    return img

# Log to file for debugging
log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tray_debug.log")
def log(msg):
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    print(msg)

log("=== Starting tray test ===")
log(f"Python: {sys.version}")
log(f"Running from: {os.getcwd()}")

try:
    # Create icon
    icon_img = make_icon((255, 50, 50))
    log("Icon image created")

    def on_quit(icon, item):
        log("Quit clicked")
        icon.stop()

    icon = pystray.Icon(
        "test_traffic_light",
        icon_img,
        "TEST - Red Light",
        menu=pystray.Menu(
            pystray.MenuItem("Quit", on_quit),
        )
    )
    log("pystray.Icon created OK")

    # Try to run
    log("Calling icon.run() - if you see this, check system tray overflow area (^)")
    log("IMPORTANT: Click the ^ arrow in taskbar to find hidden icons!")
    icon.run()
    log("icon.run() returned normally")

except Exception as e:
    log(f"ERROR: {e}")
    log(traceback.format_exc())
