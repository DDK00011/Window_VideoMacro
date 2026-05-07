"""AutoClicker GUI - production-ready 버전.

기능:
- 클릭 좌표 입력 + "3초 후 마우스 좌표 캡처" 버튼
- 마우스 위치 라이브 미리보기 (200ms)
- 시작 시점: 상대(지금부터 N시간 N분) / 절대(오늘 HH:MM)
- 클릭 종류: 좌클릭 / 우클릭 / 더블클릭
- 클릭 횟수 / 간격(초)
- 자동 절전 방지 (Windows ctypes SetThreadExecutionState)
- 사운드 알림 (winsound, 시작 직전 / 완료 시 beep)
- 진행 Progress Bar (1분 단위 → 마지막 10초 1초 단위)
- 프로파일 JSON 저장/자동 로드
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
from tkinter import ttk, messagebox

try:
    import pyautogui
except ImportError:
    print("[오류] pyautogui가 설치되어 있지 않습니다.")
    print("       pip install -r requirements.txt")
    sys.exit(1)

# Optional Windows audio.
try:
    import winsound  # type: ignore
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False


pyautogui.FAILSAFE = True

# Profile path: same folder as this script.
PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "autoclicker_profile.json",
)

# Windows execution-state flags (kernel32.SetThreadExecutionState).
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

IS_WINDOWS = sys.platform.startswith("win")


def prevent_sleep(enable: bool) -> bool:
    """Windows 에서 절전/디스플레이 꺼짐을 막는다.

    enable=True  → 시스템/디스플레이 active 유지.
    enable=False → 원복 (기본 동작).
    Windows 가 아니거나 호출 실패 시 False 반환.
    """
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
    """가능하면 winsound 로 비프음을 낸다. 실패 시 ASCII bell."""
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


class AutoClickerApp:
    """예약 클릭 GUI 애플리케이션 (production-ready)."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("AutoClicker")
        self.root.geometry("520x820")
        self.root.minsize(520, 720)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Runtime state.
        self.running = False
        self.cancel_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self._sleep_block_active = False

        self._build_ui()
        self._show_intro()
        self._on_mode_change()
        self._start_mouse_preview()
        self._try_load_profile_on_start()

        # Keyboard shortcuts (창 포커스 시 동작).
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
            preview_frame,
            textvariable=self.mouse_preview_var,
            font=("Consolas", 12),
            foreground="#444",
        ).pack(padx=8, pady=4, anchor="w")

        # --- Coordinate ---
        coord_frame = ttk.LabelFrame(self.root, text="클릭 좌표")
        coord_frame.pack(fill="x", **pad)
        ttk.Label(coord_frame, text="x:").grid(row=0, column=0, padx=4, pady=4, sticky="e")
        self.x_var = tk.StringVar(value="500")
        ttk.Entry(coord_frame, textvariable=self.x_var, width=10).grid(row=0, column=1, padx=4)
        ttk.Label(coord_frame, text="y:").grid(row=0, column=2, padx=4, pady=4, sticky="e")
        self.y_var = tk.StringVar(value="500")
        ttk.Entry(coord_frame, textvariable=self.y_var, width=10).grid(row=0, column=3, padx=4)
        ttk.Button(
            coord_frame,
            text="3초 후 현재 마우스 좌표 캡처",
            command=self.capture_position,
        ).grid(row=1, column=0, columnspan=4, padx=4, pady=6, sticky="ew")

        # --- Schedule ---
        sched_frame = ttk.LabelFrame(self.root, text="시작 시점")
        sched_frame.pack(fill="x", **pad)
        self.schedule_mode = tk.StringVar(value="relative")

        rel_row = ttk.Frame(sched_frame)
        rel_row.pack(fill="x", padx=4, pady=2)
        ttk.Radiobutton(
            rel_row, text="상대 (지금부터)",
            variable=self.schedule_mode, value="relative",
            command=self._on_mode_change,
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
            command=self._on_mode_change,
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
        ttk.Label(cnt_row, text="횟수:").pack(side="left")
        self.count_var = tk.StringVar(value="6")
        ttk.Entry(cnt_row, textvariable=self.count_var, width=8).pack(side="left", padx=4)
        ttk.Label(cnt_row, text="  간격(초):").pack(side="left")
        self.interval_var = tk.StringVar(value="0.2")
        ttk.Entry(cnt_row, textvariable=self.interval_var, width=8).pack(side="left", padx=4)

        # --- Options ---
        opt_frame = ttk.LabelFrame(self.root, text="옵션")
        opt_frame.pack(fill="x", **pad)
        self.prevent_sleep_var = tk.BooleanVar(value=IS_WINDOWS)
        cb1 = ttk.Checkbutton(
            opt_frame, text="자동 절전 방지 (Windows 전용)", variable=self.prevent_sleep_var,
        )
        cb1.pack(anchor="w", padx=4)
        if not IS_WINDOWS:
            cb1.state(["disabled"])
        self.sound_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opt_frame, text="사운드 알림 (시작 직전 / 완료 시 beep)", variable=self.sound_var,
        ).pack(anchor="w", padx=4)

        # --- Action buttons ---
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", **pad)
        self.start_btn = ttk.Button(btn_frame, text="예약 시작", command=self.start)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=4)
        self.cancel_btn = ttk.Button(btn_frame, text="중단", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", expand=True, fill="x", padx=4)

        prof_frame = ttk.Frame(self.root)
        prof_frame.pack(fill="x", **pad)
        ttk.Button(prof_frame, text="설정 저장", command=self.save_profile).pack(side="left", expand=True, fill="x", padx=4)
        ttk.Button(prof_frame, text="설정 불러오기", command=self.load_profile).pack(side="left", expand=True, fill="x", padx=4)

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
    # Lifecycle
    # =========================================================

    def _show_intro(self) -> None:
        self._log("[안전 안내] 마우스를 화면 모서리로 이동하면 즉시 중단됩니다 (fail-safe).")
        self._log("[단축키] Ctrl+Enter = 시작, Esc = 중단, F8 = 좌표 캡처 (창 포커스 시)")
        if not IS_WINDOWS:
            self._log("[안내] Windows 가 아니므로 자동 절전 방지는 비활성화됩니다.")
        if not HAS_WINSOUND:
            self._log("[안내] winsound 미지원 환경입니다 (사운드는 ASCII bell 로 대체).")
        self._log("")

    def on_close(self) -> None:
        """창 닫기 핸들러 — 진행 중이면 확인 후 종료, 절전 차단 해제."""
        if self.running:
            if not messagebox.askyesno("확인", "예약 클릭이 진행 중입니다. 종료하시겠습니까?"):
                return
            self.cancel_event.set()
        self._set_sleep_block(False)
        self.root.destroy()

    # =========================================================
    # Helpers
    # =========================================================

    def _log(self, msg: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _ui(self, fn, *args, **kwargs) -> None:
        """워커 스레드에서 UI 갱신을 main thread 로 디스패치."""
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

    def _on_mode_change(self) -> None:
        """상대/절대 라디오 변경 시 입력 칸 활성화 토글."""
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
        """자동 절전 방지 토글 (메인 스레드에서만 호출)."""
        if enable == self._sleep_block_active:
            return
        if prevent_sleep(enable):
            self._sleep_block_active = enable
            self._log("[옵션] 자동 절전 방지 " + ("활성화" if enable else "해제"))

    # =========================================================
    # Live mouse preview
    # =========================================================

    def _start_mouse_preview(self) -> None:
        """200ms 마다 현재 마우스 좌표를 라벨에 갱신한다 (재귀 after)."""
        try:
            x, y = pyautogui.position()
            self.mouse_preview_var.set(f"x={x}, y={y}")
        except Exception:
            self.mouse_preview_var.set("(좌표 조회 실패)")
        self.root.after(200, self._start_mouse_preview)

    # =========================================================
    # Input validation
    # =========================================================

    def _validate_inputs(self):
        """모든 입력을 검증해 dict 반환. 오류 시 None."""
        try:
            x = int(self.x_var.get())
            y = int(self.y_var.get())
            count = int(self.count_var.get())
            interval = float(self.interval_var.get())
        except ValueError:
            messagebox.showerror("입력 오류", "좌표/횟수/간격은 숫자여야 합니다.")
            return None
        if count < 1:
            messagebox.showerror("입력 오류", "클릭 횟수는 1 이상이어야 합니다.")
            return None
        if interval < 0:
            messagebox.showerror("입력 오류", "간격은 0 이상이어야 합니다.")
            return None

        mode = self.schedule_mode.get()
        if mode == "relative":
            try:
                hours = int(self.hours_var.get())
                minutes = int(self.minutes_var.get())
            except ValueError:
                messagebox.showerror("입력 오류", "시간/분은 숫자여야 합니다.")
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
                messagebox.showerror("입력 오류", "절대 시각은 숫자여야 합니다.")
                return None
            if not (0 <= ah <= 23 and 0 <= am <= 59):
                messagebox.showerror("입력 오류", "시는 0~23, 분은 0~59 범위여야 합니다.")
                return None
            now = dt.datetime.now()
            target = now.replace(hour=ah, minute=am, second=0, microsecond=0)
            if target <= now:
                # Already past today → schedule for tomorrow.
                target += dt.timedelta(days=1)
            total = int((target - now).total_seconds())
            schedule_label = f"{target.strftime('%Y-%m-%d %H:%M')} (약 {self._fmt(total)} 후)"

        return {
            "x": x, "y": y, "count": count, "interval": interval,
            "total": total, "schedule_label": schedule_label,
            "click_type": self.click_type.get(),
        }

    # =========================================================
    # Actions
    # =========================================================

    def capture_position(self) -> None:
        """3초 카운트다운 후 현재 마우스 위치를 좌표 필드에 채운다."""
        if self.running:
            messagebox.showinfo("진행 중", "예약 클릭 진행 중에는 캡처할 수 없습니다.")
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
        """예약 시작 버튼 핸들러."""
        if self.running:
            return
        params = self._validate_inputs()
        if params is None:
            return

        confirm_msg = (
            f"좌표:        ({params['x']}, {params['y']})\n"
            f"시작:        {params['schedule_label']}\n"
            f"클릭 종류:   {self._click_type_label(params['click_type'])}\n"
            f"클릭:        {params['count']}회 (간격 {params['interval']}초)\n"
            f"절전 방지:   {'ON' if self.prevent_sleep_var.get() else 'OFF'}\n"
            f"사운드 알림: {'ON' if self.sound_var.get() else 'OFF'}\n\n"
            f"이대로 실행하시겠습니까?"
        )
        if not messagebox.askyesno("확인", confirm_msg):
            return

        # Lock UI and dispatch worker.
        self.running = True
        self.cancel_event.clear()
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self._set_progress(0)
        self._log("")
        self._log(
            f"[시작] {params['schedule_label']} → "
            f"({params['x']}, {params['y']}) "
            f"{self._click_type_label(params['click_type'])} {params['count']}회"
        )

        if self.prevent_sleep_var.get():
            self._set_sleep_block(True)

        self.worker_thread = threading.Thread(
            target=self._run_schedule, args=(params,), daemon=True,
        )
        self.worker_thread.start()

    def cancel(self) -> None:
        """중단 버튼 핸들러."""
        if self.running:
            self.cancel_event.set()
            self._log("[중단 요청] 사용자가 중단을 요청했습니다.")

    # =========================================================
    # Worker (background thread)
    # =========================================================

    def _run_schedule(self, p: dict) -> None:
        """카운트다운 → 마우스 이동 → 클릭 실행 (워커 스레드)."""
        try:
            ok = self._countdown(p["total"])
            if not ok:
                self._ui(self._log, "[중단] 카운트다운 중 취소됨")
                self._ui(self._set_status, "중단됨")
                self._ui(self._set_progress, 0)
                return

            if self.sound_var.get():
                beep(1000, 200)

            self._ui(self._set_status, "마우스 이동 중...")
            self._ui(self._log, f"[이동] ({p['x']}, {p['y']}) 로 마우스 이동")
            pyautogui.moveTo(p["x"], p["y"], duration=1)

            self._do_clicks(p)
            if self.cancel_event.is_set():
                # _do_clicks already updated UI on cancel.
                return

            if self.sound_var.get():
                beep(1500, 300)

            self._ui(self._set_progress, 100)
            self._ui(self._set_status, "완료")
            self._ui(self._log, f"[완료] {p['count']}회 {self._click_type_label(p['click_type'])} 수행")
        except pyautogui.FailSafeException:
            self._ui(self._log, "[중단] fail-safe 트리거 (마우스가 화면 모서리에 도달)")
            self._ui(self._set_status, "fail-safe 중단")
        except Exception as e:
            self._ui(self._log, f"[오류] {type(e).__name__}: {e}")
            self._ui(self._set_status, "오류 발생")
        finally:
            self.running = False
            # Sleep-block release must run on main thread.
            if self._sleep_block_active:
                self._ui(self._set_sleep_block, False)
            self._ui(self.start_btn.config, state="normal")
            self._ui(self.cancel_btn.config, state="disabled")

    def _do_clicks(self, p: dict) -> None:
        """클릭 종류에 맞춰 count 회 클릭."""
        click_type = p["click_type"]
        count = p["count"]
        interval = p["interval"]
        x, y = p["x"], p["y"]
        for i in range(1, count + 1):
            if self.cancel_event.is_set():
                self._ui(self._log, f"[중단] {i - 1}/{count} 회 후 중단")
                self._ui(self._set_status, "중단됨")
                return
            if click_type == "right":
                pyautogui.rightClick(x, y)
            elif click_type == "double":
                pyautogui.doubleClick(x, y)
            else:
                pyautogui.click(x, y)
            self._ui(self._log, f"  {self._click_type_label(click_type)} {i}/{count}")
            if i < count:
                time.sleep(interval)

    def _countdown(self, total: int) -> bool:
        """대기 시간 동안 진행 표시. 반환: True 정상, False 취소."""
        if total <= 0:
            return True
        deadline = time.monotonic() + total
        last_minute_bucket = -1
        last_progress_int = -1

        # Phase 1: per-minute updates while >10s remain.
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

        # Phase 2: final 10-second countdown (1-second tick).
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
                # Cancel-aware sleep (0.1s 단위 체크).
                end = time.monotonic() + delay
                while time.monotonic() < end:
                    if self.cancel_event.is_set():
                        return False
                    time.sleep(min(0.1, end - time.monotonic()))
        return True

    # =========================================================
    # Profile (JSON) save / load
    # =========================================================

    def _collect_profile(self) -> dict:
        return {
            "x": self.x_var.get(),
            "y": self.y_var.get(),
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
        }

    def _apply_profile(self, p: dict) -> None:
        self.x_var.set(str(p.get("x", "500")))
        self.y_var.set(str(p.get("y", "500")))
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
        self._on_mode_change()

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
        """시작 시 프로파일이 있으면 조용히 적용."""
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
    """GUI 진입점."""
    root = tk.Tk()
    AutoClickerApp(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
