"""AutoClicker — 다중 좌표 예약 클릭 (1회용 스크립트).

시나리오:
  - 1시간 45분 뒤
  - 지정된 9개 좌표를 좌클릭, 10초 간격
  - Windows 자동 절전 방지 + 사운드 알림 + fail-safe + Ctrl+C 종료

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

    # Phase 1: per-minute updates while >10s remain.
    while True:
        if stop_event is not None and stop_event.is_set():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 10:
            break
        bucket = int(remaining // 60)
        if bucket != last_minute_bucket:
            print(f"[남은 시간] {fmt(remaining)}")
            last_minute_bucket = bucket
        time.sleep(min(1.0, max(0.0, remaining - 10)))

    # Phase 2: final 10-second 1-second tick.
    print("[클릭 직전] 마지막 10초 카운트다운")
    seconds_left = int(round(max(0.0, deadline - time.monotonic())))
    for s in range(seconds_left, 0, -1):
        if stop_event is not None and stop_event.is_set():
            return False
        if time.monotonic() >= deadline:
            break
        print(f"  클릭까지 {s}초...")
        target = deadline - (s - 1)
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)
    return True


def perform_clicks(dry_run: bool = False, interval: float = CLICK_INTERVAL_SEC) -> None:
    """COORDS 리스트를 순차 좌클릭. dry_run 시 print 만."""
    n = len(COORDS)
    for i, (x, y) in enumerate(COORDS, 1):
        if dry_run:
            print(f"[DRY-RUN {i}/{n}] would click ({x}, {y})  (no actual click)")
        else:
            print(f"[{i}/{n}] 좌표 ({x}, {y}) 이동 → 좌클릭")
            pyautogui.moveTo(x, y, duration=0.5)
            pyautogui.click(x, y)
        if i < n:
            if not dry_run:
                print(f"  → 다음 클릭까지 {interval}초 대기")
            time.sleep(interval)
    print(f"[완료] {n}개 좌표 {'시뮬' if dry_run else '클릭'} 처리됨")


def keep_alive_worker(stop_event: threading.Event, period_sec: int = 300) -> None:
    """주기적으로 마우스 1픽셀 이동 → idle 타이머 리셋 (Windows 자동 잠금 방지).

    Fail-safe 코너 근처에서는 skip.
    """
    while not stop_event.wait(period_sec):
        try:
            x, y = pyautogui.position()
            # Skip if near top-left corner (fail-safe boundary).
            if x < 10 or y < 10:
                continue
            pyautogui.moveTo(x - 1, y, duration=0.05)
            pyautogui.moveTo(x, y, duration=0.05)
        except pyautogui.FailSafeException:
            # Don't crash keep-alive on fail-safe; just skip this round.
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

    if args.quick:
        total = 5
        interval = 0.5
    else:
        total = WAIT_HOURS * 3600 + WAIT_MINUTES * 60
        interval = CLICK_INTERVAL_SEC

    # Header.
    print("=" * 56)
    print("  AutoClicker — 다중 좌표 예약 클릭")
    flags = []
    if args.dry_run:
        flags.append("DRY-RUN")
    if args.quick:
        flags.append("QUICK")
    if args.keep_alive:
        flags.append("KEEP-ALIVE")
    if flags:
        print(f"  ** MODE: {' + '.join(flags)} **")
    print("=" * 56)
    print(f"  대기 시간:  {fmt(total)}  ({total}초)")
    print(f"  좌표:       {len(COORDS)}개  ({interval}초 간격, 좌클릭)")
    for i, (x, y) in enumerate(COORDS, 1):
        print(f"    {i}번: ({x:>5}, {y:>4})")
    print()
    print("  [안전] 마우스를 화면 모서리(좌상단) 이동 시 즉시 중단 (fail-safe)")
    print("  [안전] Ctrl+C 로 언제든 종료")
    if IS_WINDOWS and not args.dry_run:
        print("  [옵션] Windows 자동 절전/디스플레이 꺼짐 방지 활성화")
    if args.keep_alive:
        print("  [옵션] Keep-alive: 5분마다 마우스 1픽셀 이동 (자동 잠금 방지)")
    print("=" * 56)
    print()

    stop_event = threading.Event()

    # Start keep-alive thread (only when needed and not dry-run).
    if args.keep_alive and not args.dry_run:
        threading.Thread(
            target=keep_alive_worker, args=(stop_event,), daemon=True
        ).start()

    if not args.dry_run:
        prevent_sleep(True)
    try:
        if not countdown(total, stop_event):
            print("[중단] 카운트다운 중 취소")
            return
        if not args.dry_run:
            beep(1000, 200)  # click-imminent alert

        # Stop keep-alive before clicks (avoid race with target clicks).
        stop_event.set()

        perform_clicks(dry_run=args.dry_run, interval=interval)

        if not args.dry_run:
            beep(1500, 300)  # done alert
    except pyautogui.FailSafeException:
        print("\n[중단] fail-safe 트리거 (마우스가 화면 모서리에 도달)")
    except KeyboardInterrupt:
        print("\n[중단] 사용자가 Ctrl+C 로 종료")
    except Exception as e:
        print(f"\n[오류] {type(e).__name__}: {e}")
    finally:
        stop_event.set()
        if not args.dry_run:
            prevent_sleep(False)


if __name__ == "__main__":
    main()
