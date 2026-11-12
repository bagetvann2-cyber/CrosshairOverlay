import sys
import ctypes
from PyQt5.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QAction, QActionGroup, QMessageBox,
)
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt5.QtCore import Qt

import storage
from overlay import CrosshairOverlay
from control import ControlPanel
from hotkeys import HotkeyManager, RmbWatcher

MUTEX_NAME = "CrosshairOverlayMutex_2025"


def set_dpi_awareness() -> None:
    """Per-monitor DPI awareness до создания QApplication (чтобы координаты были физическими)."""
    try:
        ok = ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        if ok:
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def _prepare_qt() -> None:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def check_single_instance():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == 183:
        _prepare_qt()
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "CrosshairOverlay", "Еблан тупой оно уже включено")
        sys.exit(1)
    return mutex


def make_tray_icon():
    size = 32
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    mid = size // 2
    pen_color = QColor(0, 220, 80)
    p.setPen(pen_color)
    p.setBrush(Qt.NoBrush)
    p.drawLine(mid, 2, mid, size - 2)
    p.drawLine(2, mid, size - 2, mid)
    p.drawEllipse(mid - 7, mid - 7, 14, 14)
    p.end()
    return QIcon(pm)


def main():
    set_dpi_awareness()
    _mutex = check_single_instance()  # держим ссылку чтобы mutex не освободился до выхода

    _prepare_qt()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    cfg = storage.load_config()
    overlay = CrosshairOverlay()
    control = ControlPanel(cfg)
    hotkeys = HotkeyManager()
    rmb = RmbWatcher()

    # --- Связи ---
    control.overlay_update.connect(overlay.set_image)
    control.visibility_changed.connect(overlay.set_user_visible)

    def on_rmb_enabled(enabled: bool) -> None:
        rmb.set_enabled(enabled)
        if not enabled:
            overlay.set_temp_hidden(False)

    control.hide_on_rmb_changed.connect(on_rmb_enabled)
    rmb.state_changed.connect(overlay.set_temp_hidden)

    def apply_hotkeys() -> None:
        keys = {i: p.hotkey for i, p in enumerate(cfg.profiles) if p.hotkey}
        errors = hotkeys.apply(cfg.hotkeys.get("toggle", ""), cfg.hotkeys.get("next", ""),
                               cfg.hotkeys.get("prev", ""), keys)
        control.set_hotkey_errors(errors)

    control.hotkeys_changed.connect(apply_hotkeys)
    hotkeys.toggle_pressed.connect(control.toggle_overlay)
    hotkeys.next_pressed.connect(control.next_profile)
    hotkeys.prev_pressed.connect(control.prev_profile)
    hotkeys.profile_pressed.connect(control.select_profile)

    # --- Трей ---
    tray = QSystemTrayIcon(make_tray_icon(), app)
    tray.setToolTip("CrosshairOverlay" + ("" if overlay.in_uiaccess_band else " (обычный режим)"))

    tray_menu = QMenu()
    act_show = QAction("Показать настройки")
    act_show.triggered.connect(control.show_window)
    act_toggle = QAction("Показать/скрыть прицел")
    act_toggle.triggered.connect(control.toggle_overlay)
    profiles_menu = QMenu("Прицелы")
    profile_group = QActionGroup(profiles_menu)
    profile_group.setExclusive(True)

    def rebuild_profiles_menu() -> None:
        profiles_menu.clear()
        for i, p in enumerate(cfg.profiles):
            a = profiles_menu.addAction(p.name)
            a.setCheckable(True)
            a.setChecked(i == cfg.active)
            profile_group.addAction(a)
            a.triggered.connect(lambda _c=False, idx=i: control.select_profile(idx))

    control.profiles_changed.connect(rebuild_profiles_menu)
    rebuild_profiles_menu()

    act_quit = QAction("Выйти")
    act_quit.triggered.connect(app.quit)
    tray_menu.addAction(act_show)
    tray_menu.addMenu(profiles_menu)
    tray_menu.addAction(act_toggle)
    tray_menu.addSeparator()
    tray_menu.addAction(act_quit)
    tray.setContextMenu(tray_menu)
    tray.activated.connect(
        lambda reason: control.show_window() if reason == QSystemTrayIcon.DoubleClick else None
    )
    tray.show()

    def on_quit() -> None:
        control.flush_save()
        hotkeys.clear()
        overlay.close()

    app.aboutToQuit.connect(on_quit)

    # Начальное состояние: картинка -> видимость -> клавиши
    control.refresh_all()
    control.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
