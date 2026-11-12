"""Прозрачное click-through окно с прицелом (Win32 layered window, без инъекций в игры)."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSlot
from PyQt5.QtGui import QImage

# Win32 constants
WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST     = 0x00000008
WS_EX_TOOLWINDOW  = 0x00000080
WS_EX_NOACTIVATE  = 0x08000000
WS_POPUP          = 0x80000000
ULW_ALPHA         = 0x00000002
AC_SRC_OVER       = 0x00
AC_SRC_ALPHA      = 0x01
SW_SHOWNOACTIVATE = 4
SW_HIDE           = 0
SWP_NOSIZE        = 0x0001
SWP_NOMOVE        = 0x0002
SWP_NOZORDER      = 0x0004
SWP_NOACTIVATE    = 0x0010
HWND_TOPMOST      = -1
BI_RGB            = 0
DIB_RGB_COLORS    = 0
MONITORINFOF_PRIMARY = 1
EVENT_SYSTEM_FOREGROUND  = 0x0003
EVENT_SYSTEM_MINIMIZEEND = 0x0017
WINEVENT_OUTOFCONTEXT    = 0x0000
WINEVENT_SKIPOWNPROCESS  = 0x0002

ZBID_UIACCESS     = 2

TOPMOST_INTERVAL_MS = 2000
FOREGROUND_RECHECK_MS = 300  # повтор после смены окна: игра может перебить z-порядок не сразу

_user32 = ctypes.WinDLL("user32")
_gdi32 = ctypes.WinDLL("gdi32")
_kernel32 = ctypes.WinDLL("kernel32")


class _BmpHeader(ctypes.Structure):
    _fields_ = [
        ('biSize',          ctypes.c_uint32),
        ('biWidth',         ctypes.c_int32),
        ('biHeight',        ctypes.c_int32),
        ('biPlanes',        ctypes.c_uint16),
        ('biBitCount',      ctypes.c_uint16),
        ('biCompression',   ctypes.c_uint32),
        ('biSizeImage',     ctypes.c_uint32),
        ('biXPelsPerMeter', ctypes.c_int32),
        ('biYPelsPerMeter', ctypes.c_int32),
        ('biClrUsed',       ctypes.c_uint32),
        ('biClrImportant',  ctypes.c_uint32),
    ]


class _Point(ctypes.Structure):
    _fields_ = [('x', ctypes.c_int32), ('y', ctypes.c_int32)]


class _Size(ctypes.Structure):
    _fields_ = [('cx', ctypes.c_int32), ('cy', ctypes.c_int32)]


class _Blend(ctypes.Structure):
    _fields_ = [
        ('BlendOp',             ctypes.c_uint8),
        ('BlendFlags',          ctypes.c_uint8),
        ('SourceConstantAlpha', ctypes.c_uint8),
        ('AlphaFormat',         ctypes.c_uint8),
    ]


class _MonitorInfoEx(ctypes.Structure):
    _fields_ = [
        ('cbSize',    wintypes.DWORD),
        ('rcMonitor', wintypes.RECT),
        ('rcWork',    wintypes.RECT),
        ('dwFlags',   wintypes.DWORD),
        ('szDevice',  ctypes.c_wchar * 32),
    ]


_WndProcType = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM,
)
_MonitorEnumProc = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
    ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
)
_WinEventProcType = ctypes.WINFUNCTYPE(
    None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
    wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD,
)


def _setup_prototypes() -> None:
    u, g = _user32, _gdi32
    u.GetDC.argtypes = [wintypes.HWND]
    u.GetDC.restype = wintypes.HDC
    u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    u.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HANDLE, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    u.CreateWindowExW.restype = wintypes.HWND
    u.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    u.DefWindowProcW.restype = ctypes.c_ssize_t
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    ]
    u.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(_Point), ctypes.POINTER(_Size),
        wintypes.HDC, ctypes.POINTER(_Point), wintypes.DWORD,
        ctypes.POINTER(_Blend), wintypes.DWORD,
    ]
    u.DestroyWindow.argtypes = [wintypes.HWND]
    u.EnumDisplayMonitors.argtypes = [
        wintypes.HDC, ctypes.c_void_p, _MonitorEnumProc, wintypes.LPARAM,
    ]
    u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfoEx)]
    u.SetWinEventHook.argtypes = [
        wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, _WinEventProcType,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    ]
    u.SetWinEventHook.restype = wintypes.HANDLE
    u.UnhookWinEvent.argtypes = [wintypes.HANDLE]
    g.CreateCompatibleDC.argtypes = [wintypes.HDC]
    g.CreateCompatibleDC.restype = wintypes.HDC
    g.CreateDIBSection.argtypes = [
        wintypes.HDC, ctypes.POINTER(_BmpHeader), ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
    ]
    g.CreateDIBSection.restype = wintypes.HANDLE
    g.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    g.SelectObject.restype = wintypes.HANDLE
    g.DeleteObject.argtypes = [wintypes.HANDLE]
    g.DeleteDC.argtypes = [wintypes.HDC]
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE


_setup_prototypes()


# ----------------------------------------------------------------------
# Мониторы
# ----------------------------------------------------------------------

@dataclass
class MonitorInfo:
    index: int
    left: int
    top: int
    right: int
    bottom: int
    primary: bool

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    @property
    def label(self) -> str:
        s = f"Монитор {self.index + 1} — {self.width}×{self.height}"
        return s + (" (основной)" if self.primary else "")


def list_monitors() -> list[MonitorInfo]:
    """Список мониторов в физических пикселях; основной — первым."""
    found: list[tuple[int, int, int, int, bool]] = []

    @_MonitorEnumProc
    def _cb(hmon, hdc, lprc, lparam):
        info = _MonitorInfoEx()
        info.cbSize = ctypes.sizeof(_MonitorInfoEx)
        if _user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            found.append((r.left, r.top, r.right, r.bottom,
                          bool(info.dwFlags & MONITORINFOF_PRIMARY)))
        return True

    try:
        _user32.EnumDisplayMonitors(None, None, _cb, 0)
    except Exception:
        found.clear()
    if not found:  # запасной вариант — только основной экран
        w = _user32.GetSystemMetrics(0) or 1920
        h = _user32.GetSystemMetrics(1) or 1080
        found.append((0, 0, w, h, True))
    found.sort(key=lambda m: not m[4])  # стабильно: основной первым
    return [MonitorInfo(i, *m) for i, m in enumerate(found)]


# ----------------------------------------------------------------------
# Окно
# ----------------------------------------------------------------------

class CrosshairOverlay(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._hwnd: Optional[int] = None
        self._bgra: Optional[bytes] = None
        self._w = 0
        self._h = 0
        self._ox = 0
        self._oy = 0
        self._monitor = 0
        self._user_visible = True   # пользовательское состояние (toggle)
        self._temp_hidden = False   # временное скрытие (ПКМ)
        self._shown = False
        self._in_uiaccess_band = False
        self._create_window()

        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(TOPMOST_INTERVAL_MS)
        self._topmost_timer.timeout.connect(self._reassert_topmost)
        self._topmost_timer.start()

        self._win_event_hook = None
        self._install_foreground_hook()

    def _install_foreground_hook(self) -> None:
        """Поднимаем прицел наверх сразу, как только активируется другое окно (например, игра)."""

        @_WinEventProcType
        def _on_event(hook, event, hwnd, id_obj, id_child, thread, time_ms):
            if event not in (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MINIMIZEEND):
                return
            try:
                self._reassert_topmost()
                QTimer.singleShot(FOREGROUND_RECHECK_MS, self._reassert_topmost)
            except Exception:
                pass

        self._win_event_ref = _on_event  # держим ссылку, иначе callback соберёт GC
        # Out-of-context хук: события приходят в этот (GUI) поток через цикл сообщений Qt.
        self._win_event_hook = _user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MINIMIZEEND, None, _on_event,
            0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        ) or None

    def _create_window(self) -> None:
        hinstance = _kernel32.GetModuleHandleW(None)

        @_WndProcType
        def _proc(hwnd, msg, wp, lp):
            return _user32.DefWindowProcW(hwnd, msg, wp, lp)

        self._proc_ref = _proc  # держим ссылку

        class _WC(ctypes.Structure):
            _fields_ = [
                ('cbSize',        ctypes.c_uint),
                ('style',         ctypes.c_uint),
                ('lpfnWndProc',   _WndProcType),
                ('cbClsExtra',    ctypes.c_int),
                ('cbWndExtra',    ctypes.c_int),
                ('hInstance',     wintypes.HINSTANCE),
                ('hIcon',         wintypes.HANDLE),
                ('hCursor',       wintypes.HANDLE),
                ('hbrBackground', wintypes.HANDLE),
                ('lpszMenuName',  wintypes.LPCWSTR),
                ('lpszClassName', wintypes.LPCWSTR),
                ('hIconSm',       wintypes.HANDLE),
            ]

        wc = _WC()
        wc.cbSize = ctypes.sizeof(_WC)
        wc.lpfnWndProc = _proc
        wc.hInstance = hinstance
        wc.lpszClassName = "XhairWin32_v5"
        _user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
        _user32.RegisterClassExW(ctypes.byref(wc))

        ex = (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST |
              WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        self._hwnd = None
        self._in_uiaccess_band = False

        # Сначала пробуем создать окно в band UIAccess (нужен exe с uiAccess=true)
        try:
            create_in_band = getattr(_user32, "CreateWindowInBand", None)
            if create_in_band is not None:
                create_in_band.argtypes = [
                    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                    wintypes.HWND, wintypes.HANDLE, wintypes.HINSTANCE, wintypes.LPVOID,
                    wintypes.DWORD,
                ]
                create_in_band.restype = wintypes.HWND
                hwnd = create_in_band(
                    ex, "XhairWin32_v5", "", WS_POPUP,
                    0, 0, 64, 64, None, None, hinstance, None, ZBID_UIACCESS,
                )
                if hwnd:
                    self._hwnd = hwnd
                    self._in_uiaccess_band = True
        except Exception:
            self._hwnd = None
            self._in_uiaccess_band = False

        if not self._hwnd:
            self._hwnd = _user32.CreateWindowExW(
                ex, "XhairWin32_v5", "", WS_POPUP,
                0, 0, 64, 64, None, None, hinstance, None,
            )

        # Диагностика: читаем реальный band окна
        try:
            get_band = getattr(_user32, "GetWindowBand", None)
            if get_band is not None and self._hwnd:
                get_band.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
                get_band.restype = wintypes.BOOL
                band = wintypes.DWORD(0)
                if get_band(self._hwnd, ctypes.byref(band)) and band.value == ZBID_UIACCESS:
                    self._in_uiaccess_band = True
        except Exception:
            pass

    @property
    def in_uiaccess_band(self) -> bool:
        return self._in_uiaccess_band

    # --- видимость ---

    def _apply_visibility(self) -> None:
        if not self._hwnd:
            return
        want = self._user_visible and not self._temp_hidden and self._bgra is not None
        if want and not self._shown:
            _user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
            self._shown = True
            self._push()
        elif not want and self._shown:
            _user32.ShowWindow(self._hwnd, SW_HIDE)
            self._shown = False

    def set_user_visible(self, visible: bool) -> None:
        self._user_visible = bool(visible)
        self._apply_visibility()

    def set_temp_hidden(self, hidden: bool) -> None:
        self._temp_hidden = bool(hidden)
        self._apply_visibility()

    @property
    def is_shown(self) -> bool:
        return self._shown

    # --- картинка ---

    def set_image(self, image: QImage, offset_x: int = 0, offset_y: int = 0,
                  monitor_index: int = 0) -> None:
        """Принимает готовый QImage (ARGB32 premultiplied), смещение и номер монитора."""
        img = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self._w, self._h = img.width(), img.height()
        ptr = img.constBits()
        ptr.setsize(img.sizeInBytes())
        self._bgra = bytes(ptr) if self._w > 0 and self._h > 0 else None
        self._ox, self._oy = int(offset_x), int(offset_y)
        self._monitor = int(monitor_index)
        self._apply_visibility()
        if self._shown:
            self._push()

    def _position(self) -> tuple[int, int]:
        mons = list_monitors()
        m = mons[self._monitor] if 0 <= self._monitor < len(mons) else mons[0]
        cx, cy = m.center
        return cx + self._ox - self._w // 2, cy + self._oy - self._h // 2

    def _push(self) -> None:
        """Отправляет BGRA-данные в Windows через UpdateLayeredWindow (попиксельная альфа)."""
        if not self._hwnd or self._bgra is None:
            return
        w, h = self._w, self._h
        screen_dc = _user32.GetDC(None)
        mem_dc = _gdi32.CreateCompatibleDC(screen_dc)

        bmi = _BmpHeader()
        bmi.biSize = ctypes.sizeof(_BmpHeader)
        bmi.biWidth = w
        bmi.biHeight = -h  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = BI_RGB

        bits = ctypes.c_void_p()
        hbmp = _gdi32.CreateDIBSection(
            mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0,
        )
        if not hbmp or not bits:
            _gdi32.DeleteDC(mem_dc)
            _user32.ReleaseDC(None, screen_dc)
            return

        ctypes.memmove(bits, self._bgra, w * h * 4)
        old = _gdi32.SelectObject(mem_dc, hbmp)

        x, y = self._position()
        _user32.SetWindowPos(self._hwnd, None, x, y, w, h, SWP_NOACTIVATE | SWP_NOZORDER)

        blend = _Blend(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        _user32.UpdateLayeredWindow(
            self._hwnd, screen_dc,
            ctypes.byref(_Point(x, y)), ctypes.byref(_Size(w, h)),
            mem_dc, ctypes.byref(_Point(0, 0)), 0,
            ctypes.byref(blend), ULW_ALPHA,
        )

        _gdi32.SelectObject(mem_dc, old)
        _gdi32.DeleteObject(hbmp)
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(None, screen_dc)

    @pyqtSlot()
    def _reassert_topmost(self) -> None:
        """Раз в ~2 с возвращаем окно наверх (игры иногда перебивают z-порядок)."""
        if self._hwnd and self._shown:
            _user32.SetWindowPos(
                self._hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )

    def close(self) -> None:
        if self._win_event_hook:
            _user32.UnhookWinEvent(self._win_event_hook)
            self._win_event_hook = None
        if self._hwnd:
            _user32.DestroyWindow(self._hwnd)
            self._hwnd = None
            self._shown = False
