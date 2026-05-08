"""AutoClicker — 다중 좌표 예약 클릭 (1회용 스크립트).

시나리오:
  - 1시간 45분 뒤
  - 지정된 9개 좌표를 좌클릭, 10초 간격
  - Windows 자동 절전 방지 + 사운드 알림 + fail-safe + Ctrl+C 종료
  - DPI awareness 적용 (다중 모니터 / 배율 다를 때 좌표 정확성)
  - autoclick_log.txt 로 모든 단계 자동 기록 (사후 진단)

화면 꺼짐 동작:
  - 모니터 꺼짐 (디스플레이 절전): OK (ES_DISPLAY_REQUIRED 로 차단)
  - 시스템 절전 (Sleep):           OK (ES_SYSTEM_REQUIRED 로 차단)
  - Windows 잠금 화면:             X — secure desktop, 일반 권한 입력 불가
    → 자동 잠금 비활성화 또는 --keep-alive 옵션 사용 권장

실행:
  py schedule_multi_click.py                      # 정식 (1h 45m 대기)
  py schedule_multi_click.py --dry-run            # 실제 클릭 X (안전 검증)
  py schedule_multi_click.py --quick              # 대기 5초로 단축
  py schedule_multi_click.py --dry-run --quick    # 스모크 테스트
  py schedule_multi_click.py --keep-alive         # 5분마다 마우스 jiggle (자동 잠금 방지)

좌표/시간 변경: 아래 CONFIG 섹션만 수정.
"""

import argparse
import datetime as dt
import os
import sys
import threading
import time

# Force UTF-8 console output on Windows.
# cmd default cp949 (Korean) cannot encode em-dash, smart quotes, etc.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _set_dpi_awareness() -> None:
    """Windows DPI awareness 활성화.

    다중 모니터 + 모니터별 배율(100/125/150%)이 다를 때 pyautogui 좌표를
    가상 화면 진짜 픽셀과 일치시킨다. 적용하지 않으면 OS 가 좌표를
    시스템 배율로 자동 스케일링해 어긋남이 발생한다.

    우선순위: Per-Monitor V2 (Win10 1703+) → Per-Monitor (8.1+) → System (Vista+)
    """
    if not sys.platform.startswith("win"):
        return
    import ctypes
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
    print("[ERROR] pyautogui not installed. Run: py -m pip install -r requirements.txt")
    sys.exit(1)

# Optional Windows audio.
try:
    import winsound  # type: ignore
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

pyautogui.FAILSAFE = True
IS_WINDOWS = sys.platform.startswith("win")


# ============== CONFIG ==============
WAIT_HOURS = 1
WAIT_MINUTES = 45

CLICK_INTERVAL_SEC = 10  # 클릭 간 간격 (초)
HOVER_STABILIZATION_SEC = 0.3  # moveTo 후 click 직전 hover 대기 (앱 hover 인식)

# (x, y) 좌표 리스트 — 순차 좌클릭
COORDS = [
    (45, 132),     # 1번
    (920, 138),    # 2번
    (1874, 130),   # 3번
    (1325, 958),   # 4번
    (656, 949),    # 5번
    (39, 954),     # 6번
    (591, 956),    # 7번
    (1204, 947),   # 8번
    (1831, 949),   # 9번
]
# ====================================


# Windows execution-state flags (kernel32.SetThreadExecutionState).
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

# Log file alongside the script (cwd-independent).
LOG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "autoclick_log.txt",
)


def emit(msg: str) -> None:
    """콘솔 + 로그 파일에 메시지 기록."""
    print(msg)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
    except Exception:
        pass


def init_log_session(args: argparse.Namespace) -> None:
    """로그 파일에 새 실행 세션 헤더를 기록."""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 56 + "\n")
            f.write(f"=== Run started: {dt.datetime.now().isoformat()}\n")
            flags = []
            if args.dry_run:
                flags.append("dry-run")
            if args.quick:
                flags.append("quick")
            if args.keep_alive:
                flags.append("keep-alive")
            if flags:
                f.write(f"=== Modes: {', '.join(flags)}\n")
            try:
                f.write(f"=== pyautogui size={pyautogui.size()}, position={pyautogui.position()}\n")
            except Exception:
                pass
            f.write("=" * 56 + "\n")
    except Exception:
        pass


def prevent_sleep(enable: bool) -> None:
    """Windows 절전/디스플레이 꺼짐 차단."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        if enable:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )
        else:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    except Exception:
        pass


def beep(freq: int = 1000, ms: int = 200) -> None:
    """가능하면 winsound 비프음."""
    if HAS_WINSOUND and IS_WINDOWS:
        try:
            winsound.Beep(freq, ms)
        except Exception:
            pass


def fmt(seconds: float) -> str:
    """남은 초 → 'X시간 Y분 Z초'."""
    s = max(0, int(round(seconds)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}시간 {m}분 {sec}초"


def countdown(total_seconds: int, stop_event: threading.Event | None = None) -> bool:
    """1분 단위 → 마지막 10초 1초 단위 카운트다운.

    stop_event set 시 즉시 중단.
    반환: True 정상 완료, False 중단됨.
    """
    if total_seconds <= 0:
        return True
    deadline = time.monotonic() + total_seconds
    last_minute_bucket = -1

    while True:
        if stop_event is not None and stop_event.is_set():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 10:
            break
        bucket = int(remaining // 60)
        if bucket != last_minute_bucket:
            emit(f"[남은 시간] {fmt(remaining)}")
            last_minute_bucket = bucket
        time.sleep(min(1.0, max(0.0, remaining - 10)))

    emit("[클릭 직전] 마지막 10초 카운트다운")
    seconds_left = int(round(max(0.0, deadline - time.monotonic())))
    for s in range(seconds_left, 0, -1):
        if stop_event is not None and stop_event.is_set():
            return False
        if time.monotonic() >= deadline:
            break
        emit(f"  클릭까지 {s}초...")
        target = deadline - (s - 1)
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)
    return True


def perform_clicks(dry_run: bool = False, interval: float = CLICK_INTERVAL_SEC) -> None:
    """COORDS 리스트를 순차 좌클릭.

    각 단계의 마우스 위치를 자세히 로그/기록:
      - target:     의도한 좌표
      - before:     이동 전 마우스 위치
      - after_move: moveTo 결과 (어긋남 감지)
      - delta:      target 과 after_move 차이 (DPI/스케일링 즉시 진단)
      - after_click: 클릭 후 위치

    moveTo 후 HOVER_STABILIZATION_SEC 대기 → click (일부 앱은 hover 후 click 필요).
    """
    n = len(COORDS)
    for i, (x, y) in enumerate(COORDS, 1):
        before = pyautogui.position()
        if dry_run:
            emit(f"[DRY-RUN {i}/{n}] target=({x},{y}) before=({before.x},{before.y})  (no actual click)")
        else:
            emit(f"[{i}/{n}] target=({x},{y}) before=({before.x},{before.y})")
            pyautogui.moveTo(x, y, duration=0.5)
            after_move = pyautogui.position()
            dx = after_move.x - x
            dy = after_move.y - y
            if dx == 0 and dy == 0:
                emit(f"   moved -> ({after_move.x},{after_move.y})  [OK 정확]")
            else:
                emit(f"   moved -> ({after_move.x},{after_move.y})  delta=({dx:+},{dy:+})  [WARN 어긋남]")
            time.sleep(HOVER_STABILIZATION_SEC)
            pyautogui.click(x, y)
            after_click = pyautogui.position()
            emit(f"   clicked, after=({after_click.x},{after_click.y})")
        if i < n:
            if not dry_run:
                emit(f"   -> 다음 클릭까지 {interval}초 대기")
            time.sleep(interval)
    emit(f"[완료] {n}개 좌표 {'시뮬' if dry_run else '클릭'} 처리됨")


def keep_alive_worker(stop_event: threading.Event, period_sec: int = 300) -> None:
    """주기적으로 마우스 1픽셀 이동 → idle 타이머 리셋 (Windows 자동 잠금 방지)."""
    while not stop_event.wait(period_sec):
        try:
            x, y = pyautogui.position()
            if x < 10 or y < 10:
                continue  # avoid fail-safe boundary
            pyautogui.moveTo(x - 1, y, duration=0.05)
            pyautogui.moveTo(x, y, duration=0.05)
        except pyautogui.FailSafeException:
            pass
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="다중 좌표 예약 클릭 (1회용)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  python schedule_multi_click.py                      # 정식 (1h 45m 대기)\n"
            "  python schedule_multi_click.py --dry-run            # 실제 클릭 X\n"
            "  python schedule_multi_click.py --quick              # 대기 5초로 단축\n"
            "  python schedule_multi_click.py --dry-run --quick    # 스모크 테스트\n"
            "  python schedule_multi_click.py --keep-alive         # 자동 잠금 방지\n"
        ),
    )
    p.add_argument("--dry-run", action="store_true",
                   help="실제 클릭 대신 print 만 (안전 검증)")
    p.add_argument("--quick", action="store_true",
                   help="대기 시간을 5초로 단축")
    p.add_argument("--keep-alive", action="store_true",
                   help="5분마다 마우스 1픽셀 이동 → Windows 자동 잠금 방지")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    init_log_session(args)

    if args.quick:
        total = 5
        interval = 0.5
    else:
        total = WAIT_HOURS * 3600 + WAIT_MINUTES * 60
        interval = CLICK_INTERVAL_SEC

    # Header.
    emit("=" * 56)
    emit("  AutoClicker - 다중 좌표 예약 클릭")
    flags = []
    if args.dry_run:
        flags.append("DRY-RUN")
    if args.quick:
        flags.append("QUICK")
    if args.keep_alive:
        flags.append("KEEP-ALIVE")
    if flags:
        emit(f"  ** MODE: {' + '.join(flags)} **")
    emit("=" * 56)
    emit(f"  대기 시간:  {fmt(total)}  ({total}초)")
    emit(f"  좌표:       {len(COORDS)}개  ({interval}초 간격, 좌클릭, hover 안정화 {HOVER_STABILIZATION_SEC}초)")
    for i, (x, y) in enumerate(COORDS, 1):
        emit(f"    {i}번: ({x:>5}, {y:>4})")
    emit("")
    try:
        emit(f"  [Env] pyautogui size={pyautogui.size()}, position={pyautogui.position()}")
    except Exception:
        pass
    emit(f"  [Log] {LOG_FILE}")
    emit(f"  [안전] 마우스 -> 화면 모서리(좌상단) 이동 시 즉시 중단 (fail-safe)")
    emit(f"  [안전] Ctrl+C 로 언제든 종료")
    if IS_WINDOWS and not args.dry_run:
        emit(f"  [옵션] Windows 자동 절전/디스플레이 꺼짐 방지 활성화")
    if args.keep_alive:
        emit(f"  [옵션] Keep-alive: 5분마다 마우스 1픽셀 이동 (자동 잠금 방지)")
    emit("=" * 56)
    emit("")

    stop_event = threading.Event()

    if args.keep_alive and not args.dry_run:
        threading.Thread(
            target=keep_alive_worker, args=(stop_event,), daemon=True
        ).start()

    if not args.dry_run:
        prevent_sleep(True)
    try:
        if not countdown(total, stop_event):
            emit("[중단] 카운트다운 중 취소")
            return
        if not args.dry_run:
            beep(1000, 200)

        stop_event.set()  # stop keep-alive before clicks (avoid race)

        perform_clicks(dry_run=args.dry_run, interval=interval)

        if not args.dry_run:
            beep(1500, 300)
    except pyautogui.FailSafeException:
        emit("\n[중단] fail-safe 트리거 (마우스가 화면 모서리에 도달)")
    except KeyboardInterrupt:
        emit("\n[중단] 사용자가 Ctrl+C 로 종료")
    except Exception as e:
        emit(f"\n[오류] {type(e).__name__}: {e}")
    finally:
        stop_event.set()
        if not args.dry_run:
            prevent_sleep(False)


if __name__ == "__main__":
    main()
