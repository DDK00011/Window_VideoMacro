"""AutoClicker - 콘솔 기반 예약 클릭 프로그램.

메뉴:
  1) 현재 마우스 좌표 확인 (3초 카운트다운 후 출력)
  2) 예약 클릭 실행 (대기 시간 후 N회 클릭)
  3) 종료

안전 장치:
  - PyAutoGUI FAILSAFE 활성화 (마우스를 화면 모서리로 이동 시 즉시 중단)
  - Ctrl+C 로 안전 종료
  - 입력 검증 (음수/문자 재입력)
"""

import sys
import time

try:
    import pyautogui
except ImportError:
    # pyautogui가 없으면 설치 안내 후 종료한다.
    print("[오류] pyautogui가 설치되어 있지 않습니다.")
    print("       다음 명령으로 설치하세요: pip install -r requirements.txt")
    sys.exit(1)


# Enable fail-safe explicitly (default is True, but state it for clarity).
pyautogui.FAILSAFE = True


def print_intro() -> None:
    """프로그램 시작 시 안전 안내를 출력한다."""
    print("=" * 48)
    print("   AutoClicker (예약 클릭 프로그램)")
    print("=" * 48)
    print("[안전 안내]")
    print(" - 마우스를 화면 모서리(좌상단 등)로 옮기면 즉시 중단됩니다 (fail-safe).")
    print(" - Ctrl+C 로 언제든 종료할 수 있습니다.")
    print(" - 긴 대기 시간 동안 Windows 절전/화면 잠금이 동작하면")
    print("   클릭이 실패할 수 있습니다. 절전 설정을 미리 확인하세요.")
    print("-" * 48)


def show_menu() -> str:
    """메뉴를 출력하고 사용자가 입력한 선택값을 반환한다."""
    print()
    print("1) 현재 마우스 좌표 확인")
    print("2) 예약 클릭 실행")
    print("3) 종료")
    return input("선택 > ").strip()


def show_current_position() -> None:
    """3초 카운트다운 후 현재 마우스 좌표를 출력한다."""
    print("3초 후 현재 마우스 위치를 출력합니다. 클릭하고 싶은 위치로 마우스를 옮기세요.")
    for i in range(3, 0, -1):
        print(f"  {i}...")
        time.sleep(1)
    # pyautogui.position() returns a Point(x, y) tuple-like object.
    x, y = pyautogui.position()
    print(f"[좌표] x={x}, y={y}")


def prompt_int(label: str, *, min_value: int = 0, default: int | None = None) -> int:
    """정수 입력을 검증하며 받는다.

    - 숫자가 아니거나 min_value 미만이면 다시 입력받는다.
    - default 가 주어지면 빈 입력 시 default 를 반환한다.
    """
    suffix = f" (기본 {default}, Enter 시 적용)" if default is not None else ""
    while True:
        raw = input(f"{label}{suffix}: ").strip()
        if raw == "" and default is not None:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("  → 숫자가 아닙니다. 다시 입력하세요.")
            continue
        if value < min_value:
            print(f"  → {min_value} 이상의 값을 입력하세요.")
            continue
        return value


def prompt_float(label: str, *, min_value: float = 0.0, default: float | None = None) -> float:
    """실수 입력을 검증하며 받는다."""
    suffix = f" (기본 {default}, Enter 시 적용)" if default is not None else ""
    while True:
        raw = input(f"{label}{suffix}: ").strip()
        if raw == "" and default is not None:
            return default
        try:
            value = float(raw)
        except ValueError:
            print("  → 숫자가 아닙니다. 다시 입력하세요.")
            continue
        if value < min_value:
            print(f"  → {min_value} 이상의 값을 입력하세요.")
            continue
        return value


def confirm(label: str) -> bool:
    """y/n 확인을 받는다."""
    while True:
        raw = input(f"{label} (y/n): ").strip().lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  → y 또는 n 으로 입력하세요.")


def format_remaining(seconds: float) -> str:
    """남은 초를 'X시간 Y분 Z초' 문자열로 포맷팅한다."""
    s = max(0, int(round(seconds)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}시간 {m}분 {sec}초"


def countdown(total_seconds: int) -> None:
    """대기 시간 동안 진행 상황을 콘솔에 출력한다.

    - 남은 시간 > 10초: 1분 단위로 남은 시간 출력.
    - 남은 시간 ≤ 10초: 1초 단위 카운트다운.

    `time.monotonic()` 기반 deadline 차감으로 누적 drift 를 최소화한다.
    """
    if total_seconds <= 0:
        return

    deadline = time.monotonic() + total_seconds
    last_minute_bucket = -1  # avoid duplicate per-minute prints

    # Phase 1: per-minute updates while more than 10 seconds remain.
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 10:
            break
        bucket = int(remaining // 60)
        if bucket != last_minute_bucket:
            print(f"[남은 시간] {format_remaining(remaining)}")
            last_minute_bucket = bucket
        # Sleep up to 1s, but never past the 10-second boundary.
        time.sleep(min(1.0, max(0.0, remaining - 10)))

    # Phase 2: final 10-second countdown, 1-second tick aligned to deadline.
    print("[클릭 직전] 마지막 10초 카운트다운을 시작합니다.")
    seconds_left = int(round(max(0.0, deadline - time.monotonic())))
    for s in range(seconds_left, 0, -1):
        if time.monotonic() >= deadline:
            break
        print(f"  클릭까지 {s}초...")
        # Sleep until the next per-second boundary anchored to deadline.
        target = deadline - (s - 1)
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)


def perform_clicks(x: int, y: int, count: int, interval: float) -> None:
    """좌표로 마우스를 이동한 뒤 count 번 클릭한다.

    - 이동: pyautogui.moveTo(x, y, duration=1)
    - 클릭: pyautogui.click(x, y) × count, 사이에 interval 초 대기.
    """
    print(f"[이동] ({x}, {y}) 로 마우스를 이동합니다...")
    pyautogui.moveTo(x, y, duration=1)
    for i in range(1, count + 1):
        pyautogui.click(x, y)
        print(f"  클릭 {i}/{count}")
        if i < count:
            time.sleep(interval)
    print(f"[완료] {count}회 클릭을 수행했습니다.")


def run_scheduled_click() -> None:
    """예약 클릭 메뉴 흐름을 실행한다."""
    print("\n--- 예약 클릭 설정 ---")
    print("(대기 시간/횟수/간격은 Enter 시 기본값이 적용됩니다.)")

    # Collect all parameters with validation.
    x = prompt_int("x 좌표")
    y = prompt_int("y 좌표")
    hours = prompt_int("대기 시간 (시간)", default=2)
    minutes = prompt_int("대기 시간 (분)", default=0)
    count = prompt_int("클릭 횟수", min_value=1, default=6)
    interval = prompt_float("클릭 간 간격(초)", min_value=0.0, default=0.2)

    total_seconds = hours * 3600 + minutes * 60

    # Show summary and ask for final confirmation.
    print()
    print("--- 입력 요약 ---")
    print(f"  좌표:       ({x}, {y})")
    print(f"  대기 시간:  {hours}시간 {minutes}분  (총 {total_seconds}초)")
    print(f"  클릭 횟수:  {count}회")
    print(f"  클릭 간격:  {interval}초")
    if not confirm("이대로 실행하시겠습니까?"):
        print("취소되었습니다. 메뉴로 돌아갑니다.")
        return

    if total_seconds == 0:
        print("[경고] 대기 시간이 0초입니다. 즉시 클릭을 수행합니다.")
    else:
        print(f"\n[시작] 약 {format_remaining(total_seconds)} 후에 클릭합니다.")

    countdown(total_seconds)
    perform_clicks(x, y, count, interval)


def main() -> None:
    """메인 메뉴 루프."""
    print_intro()
    while True:
        try:
            choice = show_menu()
            if choice == "1":
                show_current_position()
            elif choice == "2":
                run_scheduled_click()
            elif choice == "3":
                print("프로그램을 종료합니다.")
                break
            else:
                print("  → 1, 2, 3 중에서 선택하세요.")
        except pyautogui.FailSafeException:
            # Triggered when the user moves the mouse to a screen corner.
            print("\n[중단] 사용자가 fail-safe로 중단했습니다. (마우스를 화면 모서리로 이동)")
        except KeyboardInterrupt:
            # Ctrl+C from anywhere — exit cleanly.
            print("\n[종료] 사용자가 Ctrl+C 로 종료했습니다.")
            break
        except Exception as e:
            # Catch-all so the menu stays alive for unrelated bugs.
            print(f"\n[오류] {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
