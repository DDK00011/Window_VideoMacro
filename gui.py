"""AutoClicker GUI - production-ready 버전 (단일 / 다중 좌표 / 이미지 인식 모드).

기능:
- 클릭 좌표 모드: 단일(N회) / 다중(좌표 리스트 순차) / 이미지(매번 locateOnScreen)
- 마우스 위치 라이브 미리보기 (200ms)
- 시작 시점: 상대(지금부터 N시간 N분) / 절대(오늘 HH:MM)
- 클릭 종류: 좌클릭 / 우클릭 / 더블클릭
- 클릭 횟수 / 간격(초)
- 자동 절전 방지 (Windows ctypes SetThreadExecutionState)
- 사운드 알림 (winsound, 시작 직전 / 완료 시 beep)
- 진행 Progress Bar (1분 단위 → 마지막 10초 1초 단위)
- 프로파일 JSON 저장/자동 로드
- DPI awareness (다중 모니터 / 배율 다를 때 좌표 정확성)
- 키보드 단축키 (Ctrl+Enter 시작 / Esc 중단 / F8 캡처)
- fail-safe / 입력 검증 / 워커 스레드 / 안전 종료
"""

import ctypes
import datetime as dt
import json
import os
import sys
import threading
import time
import tkinter as tk
from importlib.util import find_spec
from tkinter import ttk, messagebox, filedialog


def _set_dpi_awareness() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_set_dpi_awareness()


try:
    import pyautogui
except ImportError:
    print("[오류] pyautogui가 설치되어 있지 않습니다.")
    print("       pip install -r requirements.txt")
    sys.exit(1)

# Optional dependency detection — find_spec avoids actual import,
# so static analyzers won't flag unused/missing-module errors.
HAS_PILLOW = find_spec("PIL") is not None
HAS_CV2 = find_spec("cv2") is not None
HAS_KEYBOARD = find_spec("keyboard") is not None

try:
    import winsound  # type: ignore
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False


pyautogui.FAILSAFE = True

PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "autoclicker_profile.json",
)

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

IS_WINDOWS = sys.platform.startswith("win")

HOVER_STABILIZATION_SEC = 0.3


def prevent_sleep(enable: bool) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        if enable:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )
        else:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        return True
    except Exception:
        return False


def beep(freq: int = 1000, ms: int = 200) -> None:
    if HAS_WINSOUND and IS_WINDOWS:
        try:
            winsound.Beep(freq, ms)
            return
        except Exception:
            pass
    try:
        sys.stdout.write("\a")
        sys.stdout.flush()
    except Exception:
        pass


def find_image_on_screen(path: str, confidence: float = 0.9):
    """화면 전체에서 이미지를 검색해 중앙 좌표를 반환.

    Pillow 가 필수, opencv 가 있으면 confidence 기반 매칭 사용.
    못 찾으면 None.
    """
    if not HAS_PILLOW:
        return None
    try:
        if HAS_CV2:
            return pyautogui.locateCenterOnScreen(path, confidence=confidence)
        return pyautogui.locateCenterOnScreen(path)
    except Exception:
        # PyAutoGUI 0.9.x: ImageNotFoundException, or generic exception.
        return None


class AutoClickerApp:
    """예약 클릭 GUI (단일 / 다중 / 이미지 모드)."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("AutoClicker")
        self.root.geometry("600x1020")
        self.root.minsize(600, 820)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.running = False
        self.cancel_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self._sleep_block_active = False
        self.multi_coords: list[tuple[int, int]] = []
        self._keyboard_module = None
        self._global_hotkeys_active = False

        self._build_ui()
        self._show_intro()
        self._on_coord_mode_change()
        self._on_schedule_mode_change()
        self._start_mouse_preview()
        self._try_load_profile_on_start()

        self.root.bind("<Control-Return>", lambda e: self.start())
        self.root.bind("<Escape>", lambda e: self.cancel())
        self.root.bind("<F8>", lambda e: self.capture_position())

    # =========================================================
    # UI construction
    # =========================================================

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 4}

        # --- Live mouse preview ---
        preview_frame = ttk.LabelFrame(self.root, text="현재 마우스 위치 (실시간)")
        preview_frame.pack(fill="x", **pad)
        self.mouse_preview_var = tk.StringVar(value="x=?, y=?")
        ttk.Label(
            preview_frame, textvariable=self.mouse_preview_var,
            font=("Consolas", 12), foreground="#444",
        ).pack(padx=8, pady=4, anchor="w")

        # --- Coordinate (single / multi / image mode) ---
        coord_frame = ttk.LabelFrame(self.root, text="클릭 좌표")
        coord_frame.pack(fill="x", **pad)

        mode_row = ttk.Frame(coord_frame)
        mode_row.pack(fill="x", padx=4, pady=2)
        ttk.Label(mode_row, text="모드:").pack(side="left")
        self.coord_mode = tk.StringVar(value="single")
        ttk.Radiobutton(
            mode_row, text="단일 좌표",
            variable=self.coord_mode, value="single",
            command=self._on_coord_mode_change,
        ).pack(side="left", padx=4)
        ttk.Radiobutton(
            mode_row, text="다중 좌표",
            variable=self.coord_mode, value="multi",
            command=self._on_coord_mode_change,
        ).pack(side="left", padx=4)
        ttk.Radiobutton(
            mode_row, text="이미지 검색",
            variable=self.coord_mode, value="image",
            command=self._on_coord_mode_change,
        ).pack(side="left", padx=4)

        # Single coord frame
        self.single_frame = ttk.Frame(coord_frame)
        ttk.Label(self.single_frame, text="x:").grid(row=0, column=0, padx=4, pady=4, sticky="e")
        self.x_var = tk.StringVar(value="500")
        ttk.Entry(self.single_frame, textvariable=self.x_var, width=10).grid(row=0, column=1, padx=4)
        ttk.Label(self.single_frame, text="y:").grid(row=0, column=2, padx=4, pady=4, sticky="e")
        self.y_var = tk.StringVar(value="500")
        ttk.Entry(self.single_frame, textvariable=self.y_var, width=10).grid(row=0, column=3, padx=4)
        ttk.Button(
            self.single_frame, text="3초 후 현재 마우스 좌표 캡처",
            command=self.capture_position,
        ).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")

        # Multi coord frame
        self.multi_frame = ttk.Frame(coord_frame)
        list_panel = ttk.Frame(self.multi_frame)
        list_panel.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.coord_listbox = tk.Listbox(list_panel, height=8, font=("Consolas", 10))
        self.coord_listbox.pack(side="left", fill="both", expand=True)
        list_scroll = ttk.Scrollbar(list_panel, command=self.coord_listbox.yview)
        list_scroll.pack(side="right", fill="y")
        self.coord_listbox["yscrollcommand"] = list_scroll.set

        btn_panel = ttk.Frame(self.multi_frame)
        btn_panel.pack(side="left", fill="y", padx=4, pady=4)
        ttk.Button(btn_panel, text="현재 좌표 추가", width=15,
                   command=self.multi_add_current).pack(fill="x", pady=2)
        ttk.Button(btn_panel, text="3초 후 캡처 추가", width=15,
                   command=self.multi_capture_add).pack(fill="x", pady=2)

        xy_row = ttk.Frame(btn_panel)
        xy_row.pack(fill="x", pady=2)
        self.multi_x_var = tk.StringVar(value="500")
        self.multi_y_var = tk.StringVar(value="500")
        ttk.Entry(xy_row, textvariable=self.multi_x_var, width=6).pack(side="left")
        ttk.Entry(xy_row, textvariable=self.multi_y_var, width=6).pack(side="left", padx=(2, 0))
        ttk.Button(btn_panel, text="x,y 직접 추가", width=15,
                   command=self.multi_add_xy).pack(fill="x", pady=2)

        ttk.Separator(btn_panel, orient="horizontal").pack(fill="x", pady=4)
        ttk.Button(btn_panel, text="선택 삭제", width=15,
                   command=self.multi_remove).pack(fill="x", pady=2)
        ttk.Button(btn_panel, text="↑ 위로", width=15,
                   command=lambda: self.multi_move(-1)).pack(fill="x", pady=2)
        ttk.Button(btn_panel, text="↓ 아래로", width=15,
                   command=lambda: self.multi_move(+1)).pack(fill="x", pady=2)
        ttk.Button(btn_panel, text="전체 삭제", width=15,
                   command=self.multi_clear).pack(fill="x", pady=2)

        # Image mode frame
        self.image_frame = ttk.Frame(coord_frame)

        path_row = ttk.Frame(self.image_frame)
        path_row.pack(fill="x", padx=4, pady=2)
        ttk.Label(path_row, text="이미지 파일:").pack(side="left")
        self.image_path_var = tk.StringVar(value="")
        ttk.Entry(path_row, textvariable=self.image_path_var).pack(
            side="left", fill="x", expand=True, padx=4
        )
        ttk.Button(path_row, text="찾아보기", command=self.image_browse).pack(side="left")

        conf_row = ttk.Frame(self.image_frame)
        conf_row.pack(fill="x", padx=4, pady=2)
        ttk.Label(conf_row, text="정확도:").pack(side="left")
        self.confidence_var = tk.StringVar(value="0.9")
        ttk.Entry(conf_row, textvariable=self.confidence_var, width=8).pack(side="left", padx=4)
        cv2_note = "  (0.7~1.0, opencv-python 권장)" if HAS_CV2 else "  (opencv 미설치 — 정확 매칭만 가능)"
        ttk.Label(conf_row, text=cv2_note).pack(side="left")

        retry_row = ttk.Frame(self.image_frame)
        retry_row.pack(fill="x", padx=4, pady=2)
        self.image_retry_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            retry_row, text="찾을 때까지 재시도",
            variable=self.image_retry_var,
        ).pack(side="left")
        ttk.Label(retry_row, text="  최대 시간(초):").pack(side="left")
        self.image_retry_timeout_var = tk.StringVar(value="30")
        ttk.Entry(retry_row, textvariable=self.image_retry_timeout_var, width=6).pack(side="left", padx=4)

        ttk.Button(
            self.image_frame, text="지금 화면에서 검색 (테스트)",
            command=self.image_test_search,
        ).pack(fill="x", padx=4, pady=4)

        self.image_status_var = tk.StringVar(value="(검색 결과 없음)")
        ttk.Label(
            self.image_frame, textvariable=self.image_status_var,
            font=("Consolas", 10), foreground="#444",
        ).pack(fill="x", padx=4, pady=2)

        # --- Schedule ---
        sched_frame = ttk.LabelFrame(self.root, text="시작 시점")
        sched_frame.pack(fill="x", **pad)
        self.schedule_mode = tk.StringVar(value="relative")

        rel_row = ttk.Frame(sched_frame)
        rel_row.pack(fill="x", padx=4, pady=2)
        ttk.Radiobutton(
            rel_row, text="상대 (지금부터)",
            variable=self.schedule_mode, value="relative",
            command=self._on_schedule_mode_change,
        ).pack(side="left")
        ttk.Label(rel_row, text="  시간:").pack(side="left")
        self.hours_var = tk.StringVar(value="2")
        self.hours_entry = ttk.Entry(rel_row, textvariable=self.hours_var, width=5)
        self.hours_entry.pack(side="left", padx=2)
        ttk.Label(rel_row, text="분:").pack(side="left")
        self.minutes_var = tk.StringVar(value="0")
        self.minutes_entry = ttk.Entry(rel_row, textvariable=self.minutes_var, width=5)
        self.minutes_entry.pack(side="left", padx=2)

        abs_row = ttk.Frame(sched_frame)
        abs_row.pack(fill="x", padx=4, pady=2)
        ttk.Radiobutton(
            abs_row, text="절대 (오늘 HH:MM, 지난 시각이면 내일)",
            variable=self.schedule_mode, value="absolute",
            command=self._on_schedule_mode_change,
        ).pack(side="left")
        ttk.Label(abs_row, text="  시:").pack(side="left")
        self.abs_hour_var = tk.StringVar(value="17")
        self.abs_hour_entry = ttk.Entry(abs_row, textvariable=self.abs_hour_var, width=5)
        self.abs_hour_entry.pack(side="left", padx=2)
        ttk.Label(abs_row, text="분:").pack(side="left")
        self.abs_min_var = tk.StringVar(value="30")
        self.abs_min_entry = ttk.Entry(abs_row, textvariable=self.abs_min_var, width=5)
        self.abs_min_entry.pack(side="left", padx=2)

        # --- Click setting ---
        click_frame = ttk.LabelFrame(self.root, text="클릭 설정")
        click_frame.pack(fill="x", **pad)

        type_row = ttk.Frame(click_frame)
        type_row.pack(fill="x", padx=4, pady=2)
        ttk.Label(type_row, text="종류:").pack(side="left")
        self.click_type = tk.StringVar(value="left")
        for label, val in [("좌클릭", "left"), ("우클릭", "right"), ("더블클릭", "double")]:
            ttk.Radiobutton(
                type_row, text=label, variable=self.click_type, value=val,
            ).pack(side="left", padx=4)

        cnt_row = ttk.Frame(click_frame)
        cnt_row.pack(fill="x", padx=4, pady=2)
        ttk.Label(cnt_row, text="횟수 (단일/이미지):").pack(side="left")
        self.count_var = tk.StringVar(value="6")
        ttk.Entry(cnt_row, textvariable=self.count_var, width=8).pack(side="left", padx=4)
        ttk.Label(cnt_row, text="  간격(초):").pack(side="left")
        self.interval_var = tk.StringVar(value="0.2")
        ttk.Entry(cnt_row, textvariable=self.interval_var, width=8).pack(side="left", padx=4)
        ttk.Label(cnt_row, text="  (다중: 좌표 간 간격)").pack(side="left")

        # --- Options ---
        opt_frame = ttk.LabelFrame(self.root, text="옵션")
        opt_frame.pack(fill="x", **pad)
        self.prevent_sleep_var = tk.BooleanVar(value=IS_WINDOWS)
        cb1 = ttk.Checkbutton(
            opt_frame, text="자동 절전 방지 (Windows 전용)",
            variable=self.prevent_sleep_var,
        )
        cb1.pack(anchor="w", padx=4)
        if not IS_WINDOWS:
            cb1.state(["disabled"])
        self.sound_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opt_frame, text="사운드 알림 (시작 직전 / 완료 시 beep)",
            variable=self.sound_var,
        ).pack(anchor="w", padx=4)
        self.global_hotkey_var = tk.BooleanVar(value=False)
        cb_hotkey = ttk.Checkbutton(
            opt_frame,
            text="글로벌 핫키 (창 포커스 없어도 F8/Esc/Ctrl+Enter)",
            variable=self.global_hotkey_var,
            command=self._toggle_global_hotkey,
        )
        cb_hotkey.pack(anchor="w", padx=4)
        if not HAS_KEYBOARD:
            cb_hotkey.state(["disabled"])

        # --- Action buttons ---
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", **pad)
        self.start_btn = ttk.Button(btn_frame, text="예약 시작", command=self.start)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=4)
        self.cancel_btn = ttk.Button(btn_frame, text="중단", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", expand=True, fill="x", padx=4)

        prof_frame = ttk.Frame(self.root)
        prof_frame.pack(fill="x", **pad)
        ttk.Button(prof_frame, text="설정 저장",
                   command=self.save_profile).pack(side="left", expand=True, fill="x", padx=4)
        ttk.Button(prof_frame, text="설정 불러오기",
                   command=self.load_profile).pack(side="left", expand=True, fill="x", padx=4)

        # --- Status + progress ---
        self.status_var = tk.StringVar(value="준비됨")
        ttk.Label(
            self.root, textvariable=self.status_var,
            foreground="blue", font=("Segoe UI", 11, "bold"),
        ).pack(fill="x", **pad)
        self.progress = ttk.Progressbar(self.root, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=10, pady=2)

        # --- Log ---
        log_frame = ttk.LabelFrame(self.root, text="로그")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=10, state="disabled", wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scroll.pack(side="right", fill="y", pady=4)
        self.log_text["yscrollcommand"] = scroll.set

    # =========================================================
    # Lifecycle / helpers
    # =========================================================

    def _show_intro(self) -> None:
        self._log("[안전 안내] 마우스를 화면 모서리로 이동하면 즉시 중단됩니다 (fail-safe).")
        self._log("[단축키] Ctrl+Enter = 시작, Esc = 중단, F8 = 좌표 캡처 (창 포커스 시)")
        if not IS_WINDOWS:
            self._log("[안내] Windows 가 아니므로 자동 절전 방지는 비활성화됩니다.")
        if not HAS_WINSOUND:
            self._log("[안내] winsound 미지원 환경입니다 (사운드는 ASCII bell 로 대체).")
        if not HAS_PILLOW:
            self._log("[안내] Pillow 미설치 — 이미지 검색 모드 사용 불가. pip install Pillow")
        if not HAS_CV2:
            self._log("[안내] opencv-python 미설치 — 이미지 검색은 정확 매칭만 가능 (confidence 무시).")
        if not HAS_KEYBOARD:
            self._log("[안내] keyboard 미설치 — 글로벌 핫키 사용 불가. pip install keyboard (Windows 관리자 권한 권장)")
        self._log("")

    def on_close(self) -> None:
        if self.running:
            if not messagebox.askyesno("확인", "예약 클릭이 진행 중입니다. 종료하시겠습니까?"):
                return
            self.cancel_event.set()
        self._set_sleep_block(False)
        self._unbind_global_hotkeys(silent=True)
        self.root.destroy()

    def _toggle_global_hotkey(self) -> None:
        """글로벌 핫키 체크박스 핸들러 — keyboard 라이브러리로 등록/해제."""
        if self.global_hotkey_var.get():
            if not HAS_KEYBOARD:
                messagebox.showerror(
                    "의존성 누락",
                    "keyboard 라이브러리가 필요합니다.\n\npip install keyboard\n\n"
                    "Windows 에서는 관리자 권한으로 실행해야 동작합니다.",
                )
                self.global_hotkey_var.set(False)
                return
            try:
                if self._keyboard_module is None:
                    import keyboard  # type: ignore[import-not-found]
                    self._keyboard_module = keyboard
                kb = self._keyboard_module
                kb.add_hotkey("f8", lambda: self.root.after(0, self.capture_position))
                kb.add_hotkey("esc", lambda: self.root.after(0, self.cancel))
                kb.add_hotkey("ctrl+enter", lambda: self.root.after(0, self.start))
                self._global_hotkeys_active = True
                self._log("[글로벌 핫키] 활성화 (F8 캡처 / Esc 중단 / Ctrl+Enter 시작)")
            except Exception as e:
                messagebox.showerror(
                    "핫키 등록 실패",
                    f"{type(e).__name__}: {e}\n\n"
                    "Windows 에서는 관리자 권한으로 실행해야 할 수 있습니다.",
                )
                self.global_hotkey_var.set(False)
                self._global_hotkeys_active = False
        else:
            self._unbind_global_hotkeys(silent=False)

    def _unbind_global_hotkeys(self, silent: bool = False) -> None:
        """등록된 글로벌 핫키 모두 해제."""
        if self._keyboard_module is None or not self._global_hotkeys_active:
            return
        try:
            self._keyboard_module.unhook_all()
        except Exception:
            pass
        self._global_hotkeys_active = False
        if not silent:
            self._log("[글로벌 핫키] 비활성화")

    def _log(self, msg: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _ui(self, fn, *args, **kwargs) -> None:
        self.root.after(0, lambda: fn(*args, **kwargs))

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _set_progress(self, pct: float) -> None:
        self.progress["value"] = max(0.0, min(100.0, pct))

    @staticmethod
    def _fmt(seconds: float) -> str:
        s = max(0, int(round(seconds)))
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h}시간 {m}분 {sec}초"

    @staticmethod
    def _click_type_label(t: str) -> str:
        return {"left": "좌클릭", "right": "우클릭", "double": "더블클릭"}.get(t, t)

    def _on_coord_mode_change(self) -> None:
        self.single_frame.pack_forget()
        self.multi_frame.pack_forget()
        self.image_frame.pack_forget()
        mode = self.coord_mode.get()
        if mode == "single":
            self.single_frame.pack(fill="x", padx=4, pady=2)
        elif mode == "multi":
            self.multi_frame.pack(fill="both", expand=False, padx=4, pady=2)
        else:
            self.image_frame.pack(fill="x", padx=4, pady=2)

    def _on_schedule_mode_change(self) -> None:
        if self.schedule_mode.get() == "relative":
            self.hours_entry.config(state="normal")
            self.minutes_entry.config(state="normal")
            self.abs_hour_entry.config(state="disabled")
            self.abs_min_entry.config(state="disabled")
        else:
            self.hours_entry.config(state="disabled")
            self.minutes_entry.config(state="disabled")
            self.abs_hour_entry.config(state="normal")
            self.abs_min_entry.config(state="normal")

    def _set_sleep_block(self, enable: bool) -> None:
        if enable == self._sleep_block_active:
            return
        if prevent_sleep(enable):
            self._sleep_block_active = enable
            self._log("[옵션] 자동 절전 방지 " + ("활성화" if enable else "해제"))

    # =========================================================
    # Live mouse preview
    # =========================================================

    def _start_mouse_preview(self) -> None:
        try:
            x, y = pyautogui.position()
            self.mouse_preview_var.set(f"x={x}, y={y}")
        except Exception:
            self.mouse_preview_var.set("(좌표 조회 실패)")
        self.root.after(200, self._start_mouse_preview)

    # =========================================================
    # Multi-coord operations
    # =========================================================

    def _refresh_multi_listbox(self) -> None:
        self.coord_listbox.delete(0, "end")
        for i, (x, y) in enumerate(self.multi_coords, 1):
            self.coord_listbox.insert("end", f"{i:>3}번  x={x:>6}, y={y:>6}")

    def _append_multi(self, x: int, y: int) -> None:
        self.multi_coords.append((x, y))
        self._refresh_multi_listbox()
        self._log(f"[좌표 추가] {len(self.multi_coords)}번  ({x}, {y})")

    def multi_add_current(self) -> None:
        if self.running:
            return
        try:
            x, y = pyautogui.position()
        except Exception as e:
            messagebox.showerror("오류", f"좌표 조회 실패: {e}")
            return
        self._append_multi(int(x), int(y))

    def multi_capture_add(self) -> None:
        if self.running:
            return

        def worker():
            for i in range(3, 0, -1):
                self._ui(self._set_status, f"좌표 캡처: {i}초 후...")
                time.sleep(1)
            try:
                x, y = pyautogui.position()
            except Exception as e:
                self._ui(self._log, f"[오류] {e}")
                return
            self._ui(self._append_multi, int(x), int(y))
            self._ui(self._set_status, f"좌표 추가: ({x}, {y})")

        threading.Thread(target=worker, daemon=True).start()

    def multi_add_xy(self) -> None:
        if self.running:
            return
        try:
            x = int(self.multi_x_var.get())
            y = int(self.multi_y_var.get())
        except ValueError:
            messagebox.showerror("입력 오류", "x, y 는 정수여야 합니다.")
            return
        self._append_multi(x, y)

    def multi_remove(self) -> None:
        sel = self.coord_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        del self.multi_coords[idx]
        self._refresh_multi_listbox()
        if self.multi_coords:
            new_sel = min(idx, len(self.multi_coords) - 1)
            self.coord_listbox.selection_set(new_sel)

    def multi_move(self, direction: int) -> None:
        sel = self.coord_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        new_idx = idx + direction
        if 0 <= new_idx < len(self.multi_coords):
            self.multi_coords[idx], self.multi_coords[new_idx] = (
                self.multi_coords[new_idx],
                self.multi_coords[idx],
            )
            self._refresh_multi_listbox()
            self.coord_listbox.selection_set(new_idx)

    def multi_clear(self) -> None:
        if not self.multi_coords:
            return
        if messagebox.askyesno("확인", f"{len(self.multi_coords)}개 좌표를 모두 삭제하시겠습니까?"):
            self.multi_coords.clear()
            self._refresh_multi_listbox()

    # =========================================================
    # Image mode operations
    # =========================================================

    def image_browse(self) -> None:
        if self.running:
            return
        path = filedialog.askopenfilename(
            title="이미지 파일 선택",
            filetypes=[
                ("이미지", "*.png *.jpg *.jpeg *.bmp *.gif"),
                ("모든 파일", "*.*"),
            ],
        )
        if path:
            self.image_path_var.set(path)
            self.image_status_var.set(f"선택: {os.path.basename(path)}")

    def image_test_search(self) -> None:
        if self.running:
            return
        path = self.image_path_var.get().strip()
        if not path:
            messagebox.showerror("입력 오류", "이미지 파일을 먼저 선택하세요.")
            return
        if not os.path.exists(path):
            messagebox.showerror("입력 오류", f"파일이 없습니다:\n{path}")
            return
        if not HAS_PILLOW:
            messagebox.showerror("의존성 누락", "Pillow 가 필요합니다. pip install Pillow")
            return
        try:
            confidence = float(self.confidence_var.get())
        except ValueError:
            confidence = 0.9
        self.image_status_var.set("검색 중...")
        self._log(f"[이미지 검색] {path}  confidence={confidence}")
        threading.Thread(
            target=self._do_image_search,
            args=(path, confidence),
            daemon=True,
        ).start()

    def _do_image_search(self, path: str, confidence: float) -> None:
        pos = find_image_on_screen(path, confidence)
        if pos is None:
            self._ui(self.image_status_var.set, "이미지를 찾을 수 없습니다")
            self._ui(self._log, "[이미지 검색] 실패: 매칭 없음")
        else:
            self._ui(self.image_status_var.set, f"찾음: x={pos.x}, y={pos.y}")
            self._ui(self._log, f"[이미지 검색] 찾음: x={pos.x}, y={pos.y}")

    # =========================================================
    # Input validation
    # =========================================================

    def _validate_inputs(self):
        try:
            interval = float(self.interval_var.get())
        except ValueError:
            messagebox.showerror("입력 오류", "간격은 숫자여야 합니다.")
            return None
        if interval < 0:
            messagebox.showerror("입력 오류", "간격은 0 이상이어야 합니다.")
            return None

        mode = self.coord_mode.get()
        coords: list[tuple[int, int]] = []
        single_count = 1
        image_path = ""
        confidence = 0.9

        if mode == "single":
            try:
                x = int(self.x_var.get())
                y = int(self.y_var.get())
                count = int(self.count_var.get())
            except ValueError:
                messagebox.showerror("입력 오류", "좌표/횟수는 정수여야 합니다.")
                return None
            if count < 1:
                messagebox.showerror("입력 오류", "클릭 횟수는 1 이상이어야 합니다.")
                return None
            coords = [(x, y)]
            single_count = count
        elif mode == "multi":
            if not self.multi_coords:
                messagebox.showerror("입력 오류", "다중 좌표 모드는 최소 1개 좌표가 필요합니다.")
                return None
            coords = list(self.multi_coords)
        else:  # image
            if not HAS_PILLOW:
                messagebox.showerror("의존성 누락", "이미지 모드에는 Pillow 가 필요합니다.\npip install Pillow")
                return None
            image_path = self.image_path_var.get().strip()
            if not image_path:
                messagebox.showerror("입력 오류", "이미지 파일을 선택하세요.")
                return None
            if not os.path.exists(image_path):
                messagebox.showerror("입력 오류", f"파일이 없습니다:\n{image_path}")
                return None
            try:
                confidence = float(self.confidence_var.get())
            except ValueError:
                messagebox.showerror("입력 오류", "정확도는 숫자여야 합니다.")
                return None
            if not (0.1 <= confidence <= 1.0):
                messagebox.showerror("입력 오류", "정확도는 0.1~1.0 범위여야 합니다.")
                return None
            try:
                count = int(self.count_var.get())
            except ValueError:
                count = 1
            if count < 1:
                count = 1
            single_count = count
            try:
                retry_timeout = float(self.image_retry_timeout_var.get())
            except ValueError:
                messagebox.showerror("입력 오류", "재시도 최대 시간은 숫자여야 합니다.")
                return None
            if retry_timeout < 0:
                retry_timeout = 0.0

        # Schedule.
        sched_mode = self.schedule_mode.get()
        if sched_mode == "relative":
            try:
                hours = int(self.hours_var.get())
                minutes = int(self.minutes_var.get())
            except ValueError:
                messagebox.showerror("입력 오류", "시간/분은 정수여야 합니다.")
                return None
            if hours < 0 or minutes < 0:
                messagebox.showerror("입력 오류", "시간/분은 0 이상이어야 합니다.")
                return None
            total = hours * 3600 + minutes * 60
            schedule_label = f"지금부터 {hours}시간 {minutes}분 뒤"
        else:
            try:
                ah = int(self.abs_hour_var.get())
                am = int(self.abs_min_var.get())
            except ValueError:
                messagebox.showerror("입력 오류", "절대 시각은 정수여야 합니다.")
                return None
            if not (0 <= ah <= 23 and 0 <= am <= 59):
                messagebox.showerror("입력 오류", "시는 0~23, 분은 0~59 범위여야 합니다.")
                return None
            now = dt.datetime.now()
            target = now.replace(hour=ah, minute=am, second=0, microsecond=0)
            if target <= now:
                target += dt.timedelta(days=1)
            total = int((target - now).total_seconds())
            schedule_label = f"{target.strftime('%Y-%m-%d %H:%M')} (약 {self._fmt(total)} 후)"

        return {
            "coord_mode": mode,
            "coords": coords,
            "count": single_count,
            "interval": interval,
            "total": total,
            "schedule_label": schedule_label,
            "click_type": self.click_type.get(),
            "image_path": image_path,
            "confidence": confidence,
            "image_retry": (mode == "image" and self.image_retry_var.get()),
            "image_retry_timeout": (
                float(self.image_retry_timeout_var.get())
                if mode == "image" and self.image_retry_timeout_var.get().strip()
                else 30.0
            ),
        }

    # =========================================================
    # Actions
    # =========================================================

    def capture_position(self) -> None:
        if self.running:
            messagebox.showinfo("진행 중", "예약 클릭 진행 중에는 캡처할 수 없습니다.")
            return
        if self.coord_mode.get() == "multi":
            self.multi_capture_add()
            return
        if self.coord_mode.get() == "image":
            self._log("[F8] 이미지 모드에서는 좌표 캡처가 의미 없습니다.")
            return

        def worker():
            for i in range(3, 0, -1):
                self._ui(self._set_status, f"좌표 캡처: {i}초 후...")
                self._ui(self._log, f"  좌표 캡처 {i}...")
                time.sleep(1)
            try:
                x, y = pyautogui.position()
            except Exception as e:
                self._ui(self._log, f"[오류] 좌표 조회 실패: {e}")
                return
            self._ui(self.x_var.set, str(x))
            self._ui(self.y_var.set, str(y))
            self._ui(self._set_status, f"좌표 캡처 완료: ({x}, {y})")
            self._ui(self._log, f"[좌표 캡처] x={x}, y={y}")

        threading.Thread(target=worker, daemon=True).start()

    def start(self) -> None:
        if self.running:
            return
        params = self._validate_inputs()
        if params is None:
            return

        if params["coord_mode"] == "single":
            x, y = params["coords"][0]
            coord_summary = f"좌표: ({x}, {y})  ×  {params['count']}회"
        elif params["coord_mode"] == "multi":
            coord_summary = f"다중 좌표 {len(params['coords'])}개 순차"
        else:
            coord_summary = (
                f"이미지 검색: {os.path.basename(params['image_path'])}  ×  {params['count']}회"
                f"  (confidence={params['confidence']})"
            )

        confirm_msg = (
            f"{coord_summary}\n"
            f"시작:        {params['schedule_label']}\n"
            f"클릭 종류:   {self._click_type_label(params['click_type'])}\n"
            f"간격:        {params['interval']}초\n"
            f"절전 방지:   {'ON' if self.prevent_sleep_var.get() else 'OFF'}\n"
            f"사운드 알림: {'ON' if self.sound_var.get() else 'OFF'}\n\n"
            f"이대로 실행하시겠습니까?"
        )
        if not messagebox.askyesno("확인", confirm_msg):
            return

        self.running = True
        self.cancel_event.clear()
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self._set_progress(0)
        self._log("")
        self._log(f"[시작] {params['schedule_label']} → {coord_summary}")

        if self.prevent_sleep_var.get():
            self._set_sleep_block(True)

        self.worker_thread = threading.Thread(
            target=self._run_schedule, args=(params,), daemon=True,
        )
        self.worker_thread.start()

    def cancel(self) -> None:
        if self.running:
            self.cancel_event.set()
            self._log("[중단 요청] 사용자가 중단을 요청했습니다.")

    # =========================================================
    # Worker
    # =========================================================

    def _run_schedule(self, p: dict) -> None:
        try:
            ok = self._countdown(p["total"])
            if not ok:
                self._ui(self._log, "[중단] 카운트다운 중 취소")
                self._ui(self._set_status, "중단됨")
                self._ui(self._set_progress, 0)
                return

            if self.sound_var.get():
                beep(1000, 200)

            self._do_clicks(p)
            if self.cancel_event.is_set():
                return

            if self.sound_var.get():
                beep(1500, 300)

            self._ui(self._set_progress, 100)
            self._ui(self._set_status, "완료")
        except pyautogui.FailSafeException:
            self._ui(self._log, "[중단] fail-safe 트리거 (마우스가 화면 모서리)")
            self._ui(self._set_status, "fail-safe 중단")
        except Exception as e:
            self._ui(self._log, f"[오류] {type(e).__name__}: {e}")
            self._ui(self._set_status, "오류 발생")
        finally:
            self.running = False
            if self._sleep_block_active:
                self._ui(self._set_sleep_block, False)
            self._ui(self.start_btn.config, state="normal")
            self._ui(self.cancel_btn.config, state="disabled")

    def _do_clicks(self, p: dict) -> None:
        click_type = p["click_type"]
        coords = p["coords"]
        count = p["count"]
        interval = p["interval"]

        if p["coord_mode"] == "single":
            x, y = coords[0]
            self._ui(self._set_status, "마우스 이동 중...")
            self._ui(self._log, f"[이동] ({x}, {y}) 로 마우스 이동")
            pyautogui.moveTo(x, y, duration=1)
            time.sleep(HOVER_STABILIZATION_SEC)
            for i in range(1, count + 1):
                if self.cancel_event.is_set():
                    self._ui(self._log, f"[중단] {i - 1}/{count} 회 후 중단")
                    self._ui(self._set_status, "중단됨")
                    return
                self._click_at(x, y, click_type)
                self._ui(self._log, f"  {self._click_type_label(click_type)} {i}/{count}")
                if i < count:
                    time.sleep(interval)
            self._ui(self._log, f"[완료] {count}회 {self._click_type_label(click_type)}")

        elif p["coord_mode"] == "multi":
            n = len(coords)
            self._ui(self._log, f"[다중 좌표 시작] {n}개 좌표 순차 클릭")
            for i, (x, y) in enumerate(coords, 1):
                if self.cancel_event.is_set():
                    self._ui(self._log, f"[중단] {i - 1}/{n} 후 중단")
                    self._ui(self._set_status, "중단됨")
                    return
                self._ui(self._set_status, f"클릭 {i}/{n}: ({x}, {y})")
                before = pyautogui.position()
                self._ui(self._log, f"[{i}/{n}] target=({x},{y}) before=({before.x},{before.y})")
                pyautogui.moveTo(x, y, duration=0.5)
                after_move = pyautogui.position()
                dx = after_move.x - x
                dy = after_move.y - y
                if dx == 0 and dy == 0:
                    self._ui(self._log, f"   moved -> ({after_move.x},{after_move.y})  [OK]")
                else:
                    self._ui(self._log, f"   moved -> ({after_move.x},{after_move.y})  delta=({dx:+},{dy:+})  [WARN]")
                time.sleep(HOVER_STABILIZATION_SEC)
                self._click_at(x, y, click_type)
                self._ui(self._log, f"   {self._click_type_label(click_type)} 완료")
                if i < n:
                    time.sleep(interval)
            self._ui(self._log, f"[완료] {n}개 좌표 클릭 처리됨")

        else:  # image
            path = p["image_path"]
            confidence = p["confidence"]
            retry_until_found = p.get("image_retry", False)
            retry_timeout = p.get("image_retry_timeout", 30.0)
            mode_desc = (
                f"retry until found ({retry_timeout:.0f}s)"
                if retry_until_found else "single attempt"
            )
            self._ui(self._log, f"[이미지 모드 시작] {path}  count={count}  conf={confidence}  {mode_desc}")
            for i in range(1, count + 1):
                if self.cancel_event.is_set():
                    self._ui(self._log, f"[중단] {i - 1}/{count} 후 중단")
                    self._ui(self._set_status, "중단됨")
                    return
                self._ui(self._set_status, f"이미지 검색 {i}/{count}...")
                pos = self._find_image_with_retry(
                    path, confidence, retry_until_found, retry_timeout, i, count,
                )
                if pos is None:
                    self._ui(self._log, f"[{i}/{count}] 이미지 매칭 실패 -> skip")
                    if i < count:
                        time.sleep(interval)
                    continue
                self._ui(self._log, f"[{i}/{count}] 매칭 위치: ({pos.x}, {pos.y})")
                pyautogui.moveTo(pos.x, pos.y, duration=0.5)
                time.sleep(HOVER_STABILIZATION_SEC)
                self._click_at(int(pos.x), int(pos.y), click_type)
                self._ui(self._log, f"   {self._click_type_label(click_type)} 완료")
                if i < count:
                    time.sleep(interval)
            self._ui(self._log, f"[완료] 이미지 모드 {count}회 시도 완료")

    def _find_image_with_retry(
        self, path: str, confidence: float,
        retry_until_found: bool, retry_timeout: float,
        idx: int = 0, total: int = 0,
    ):
        """이미지 검색. retry_until_found=True 면 timeout 까지 0.5초 간격 재시도."""
        if not retry_until_found:
            return find_image_on_screen(path, confidence)
        deadline = time.monotonic() + retry_timeout
        last_log = 0.0
        while not self.cancel_event.is_set():
            pos = find_image_on_screen(path, confidence)
            if pos is not None:
                return pos
            now = time.monotonic()
            if now >= deadline:
                return None
            if now - last_log >= 5:
                elapsed = retry_timeout - (deadline - now)
                self._ui(
                    self._log,
                    f"[{idx}/{total}] 매칭 검색 중... ({elapsed:.0f}/{retry_timeout:.0f}초)",
                )
                last_log = now
            time.sleep(0.5)
        return None

    @staticmethod
    def _click_at(x: int, y: int, click_type: str) -> None:
        if click_type == "right":
            pyautogui.rightClick(x, y)
        elif click_type == "double":
            pyautogui.doubleClick(x, y)
        else:
            pyautogui.click(x, y)

    def _countdown(self, total: int) -> bool:
        if total <= 0:
            return True
        deadline = time.monotonic() + total
        last_minute_bucket = -1
        last_progress_int = -1

        while True:
            if self.cancel_event.is_set():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 10:
                break
            elapsed = total - remaining
            pct = (elapsed / total) * 100 if total > 0 else 0.0
            if int(pct) != last_progress_int:
                self._ui(self._set_progress, pct)
                last_progress_int = int(pct)
            bucket = int(remaining // 60)
            if bucket != last_minute_bucket:
                self._ui(self._set_status, f"남은 시간: {self._fmt(remaining)}")
                self._ui(self._log, f"[남은 시간] {self._fmt(remaining)}")
                last_minute_bucket = bucket
            time.sleep(min(1.0, max(0.0, remaining - 10)))

        self._ui(self._log, "[클릭 직전] 마지막 10초 카운트다운")
        seconds_left = int(round(max(0.0, deadline - time.monotonic())))
        for s in range(seconds_left, 0, -1):
            if self.cancel_event.is_set():
                return False
            if time.monotonic() >= deadline:
                break
            elapsed = total - (deadline - time.monotonic())
            pct = (elapsed / total) * 100 if total > 0 else 0.0
            self._ui(self._set_progress, pct)
            self._ui(self._set_status, f"클릭까지 {s}초")
            self._ui(self._log, f"  클릭까지 {s}초...")
            target = deadline - (s - 1)
            delay = target - time.monotonic()
            if delay > 0:
                end = time.monotonic() + delay
                while time.monotonic() < end:
                    if self.cancel_event.is_set():
                        return False
                    time.sleep(min(0.1, end - time.monotonic()))
        return True

    # =========================================================
    # Profile
    # =========================================================

    def _collect_profile(self) -> dict:
        return {
            "coord_mode": self.coord_mode.get(),
            "x": self.x_var.get(),
            "y": self.y_var.get(),
            "multi_coords": list(self.multi_coords),
            "image_path": self.image_path_var.get(),
            "confidence": self.confidence_var.get(),
            "image_retry": self.image_retry_var.get(),
            "image_retry_timeout": self.image_retry_timeout_var.get(),
            "schedule_mode": self.schedule_mode.get(),
            "hours": self.hours_var.get(),
            "minutes": self.minutes_var.get(),
            "abs_hour": self.abs_hour_var.get(),
            "abs_min": self.abs_min_var.get(),
            "click_type": self.click_type.get(),
            "count": self.count_var.get(),
            "interval": self.interval_var.get(),
            "prevent_sleep": self.prevent_sleep_var.get(),
            "sound": self.sound_var.get(),
            "global_hotkey": self.global_hotkey_var.get(),
        }

    def _apply_profile(self, p: dict) -> None:
        self.coord_mode.set(p.get("coord_mode", "single"))
        self.x_var.set(str(p.get("x", "500")))
        self.y_var.set(str(p.get("y", "500")))
        loaded_coords = p.get("multi_coords", [])
        try:
            self.multi_coords = [(int(x), int(y)) for x, y in loaded_coords]
        except Exception:
            self.multi_coords = []
        self._refresh_multi_listbox()
        self.image_path_var.set(p.get("image_path", ""))
        self.confidence_var.set(str(p.get("confidence", "0.9")))
        self.image_retry_var.set(bool(p.get("image_retry", False)))
        self.image_retry_timeout_var.set(str(p.get("image_retry_timeout", "30")))
        self.schedule_mode.set(p.get("schedule_mode", "relative"))
        self.hours_var.set(str(p.get("hours", "2")))
        self.minutes_var.set(str(p.get("minutes", "0")))
        self.abs_hour_var.set(str(p.get("abs_hour", "17")))
        self.abs_min_var.set(str(p.get("abs_min", "30")))
        self.click_type.set(p.get("click_type", "left"))
        self.count_var.set(str(p.get("count", "6")))
        self.interval_var.set(str(p.get("interval", "0.2")))
        self.prevent_sleep_var.set(bool(p.get("prevent_sleep", IS_WINDOWS)))
        self.sound_var.set(bool(p.get("sound", True)))
        # Restore global hotkey state if it was previously active.
        want_hotkey = bool(p.get("global_hotkey", False)) and HAS_KEYBOARD
        if want_hotkey != self.global_hotkey_var.get():
            self.global_hotkey_var.set(want_hotkey)
            if want_hotkey:
                self._toggle_global_hotkey()
        self._on_coord_mode_change()
        self._on_schedule_mode_change()

    def save_profile(self) -> None:
        try:
            with open(PROFILE_PATH, "w", encoding="utf-8") as f:
                json.dump(self._collect_profile(), f, ensure_ascii=False, indent=2)
            self._log(f"[프로파일] 저장 완료 → {PROFILE_PATH}")
            messagebox.showinfo("저장 완료", f"설정을 저장했습니다.\n{PROFILE_PATH}")
        except Exception as e:
            messagebox.showerror("저장 실패", str(e))

    def load_profile(self) -> None:
        if not os.path.exists(PROFILE_PATH):
            messagebox.showinfo("없음", "저장된 설정이 없습니다.")
            return
        try:
            with open(PROFILE_PATH, encoding="utf-8") as f:
                p = json.load(f)
            self._apply_profile(p)
            self._log(f"[프로파일] 불러옴 ← {PROFILE_PATH}")
        except Exception as e:
            messagebox.showerror("불러오기 실패", str(e))

    def _try_load_profile_on_start(self) -> None:
        if not os.path.exists(PROFILE_PATH):
            return
        try:
            with open(PROFILE_PATH, encoding="utf-8") as f:
                p = json.load(f)
            self._apply_profile(p)
            self._log("[프로파일] 시작 시 자동 적용됨")
        except Exception:
            pass


def main() -> None:
    root = tk.Tk()
    AutoClickerApp(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
