# AutoClicker 개발 계획서 (Dev_Plan)

> 본 문서는 사용자 프롬프트와 추가 요구사항(약 2시간 뒤 6번 마우스 클릭)을 기반으로 작성된 구체화된 개발 계획서이다.
> 대상 OS: Windows / 언어: Python 3.10+ / 핵심 라이브러리: PyAutoGUI

---

## 1. 프로젝트 개요

### 1.1 목적
사용자가 지정한 화면 좌표를, 지정한 시간(시/분)이 지난 뒤 자동으로 클릭해 주는 콘솔 기반 예약 클릭 프로그램을 만든다.

### 1.2 핵심 사용 시나리오
- **주 시나리오**: "약 2시간 뒤에 지정 좌표에서 6번의 마우스 클릭을 자동 수행"
- **부 시나리오**: 임의의 시간(예: 30분, 1시간 30분, 5시간) 후 1회 또는 N회 클릭

### 1.3 비목표 (Non-Goals)
- 키보드 입력 자동화 (이번 범위 아님)
- GUI(Tkinter, PyQt 등) — 콘솔 입출력만 사용
- 매크로 녹화/재생
- 다중 모니터 정밀 제어 (PyAutoGUI 기본 동작에 위임)
- 백그라운드 데몬화 (포그라운드 콘솔 실행 전제)

---

## 2. 요구사항 정리

### 2.1 기능 요구사항 (Functional)
| ID | 항목 | 상세 |
|----|------|------|
| F-1 | 좌표 확인 메뉴 | 3초 카운트다운 후 현재 마우스 위치 (x, y) 출력 |
| F-2 | 예약 클릭 메뉴 | x, y, 대기 시간(시), 대기 시간(분) 입력 |
| F-3 | 반복 클릭 | 동일 좌표를 N번(기본 6번) 반복 클릭, 클릭 간 간격(초) 입력 가능 |
| F-4 | 분 단위 진행 표시 | 실행 중 1분마다 콘솔에 남은 시간 출력 |
| F-5 | 최종 카운트다운 | 클릭 10초 전부터 1초 단위 카운트다운 출력 |
| F-6 | 마우스 이동 후 클릭 | `pyautogui.moveTo(x, y, duration=1)` → `pyautogui.click(x, y)` |
| F-7 | 종료 메뉴 | 안전 종료 |

### 2.2 안전/예외 요구사항 (Safety)
| ID | 항목 | 상세 |
|----|------|------|
| S-1 | FAILSAFE 활성화 | `pyautogui.FAILSAFE = True` (기본값이지만 명시) |
| S-2 | Fail-safe 안내 | 마우스를 화면 모서리(좌상단 등)로 옮기면 중단된다는 안내를 시작 시 출력 |
| S-3 | FailSafeException 처리 | 발생 시 "사용자가 fail-safe로 중단했습니다" 출력 후 메뉴로 복귀 |
| S-4 | Ctrl+C 처리 | `KeyboardInterrupt` 캐치 → 안전 종료 메시지 출력 |
| S-5 | 절전 모드 안내 | 시작 시 "긴 대기 시간 동안 절전/잠금이 동작하면 클릭이 실패할 수 있다"는 안내 출력 |
| S-6 | 입력 검증 | 숫자가 아니거나 음수일 경우 재입력 요구 |

### 2.3 비기능 요구사항 (Non-Functional)
- **단순성**: 초보자도 README만 보고 실행할 수 있어야 함
- **가독성**: 모든 핵심 함수에 한국어 docstring + 영어 라인 코멘트
- **이식성**: Windows 우선이지만 macOS/Linux에서도 큰 수정 없이 동작
- **의존성 최소화**: 외부 의존성은 `pyautogui` 단 하나

---

## 3. 파일 구성

```
AutoClicker/
├── Docs/
│   └── Dev_Plan.md          # 본 문서
├── main.py                   # 메인 실행 파일
├── requirements.txt          # 의존성 목록
└── README.md                 # 설치/실행 가이드
```

### 3.1 각 파일 책임
- **main.py**: 메뉴 루프, 입력 처리, 카운트다운, 클릭 실행 등 모든 로직
- **requirements.txt**: `pyautogui` 한 줄
- **README.md**: 설치 (`pip install -r requirements.txt`), 실행 (`python main.py`), 사용법, FAQ

---

## 4. 메뉴 및 사용자 흐름

### 4.1 시작 화면
```
==========================================
   AutoClicker (예약 클릭 프로그램)
==========================================
[안전 안내]
- 마우스를 화면 모서리로 옮기면 즉시 중단됩니다 (fail-safe).
- Ctrl+C 로 언제든 종료할 수 있습니다.
- 긴 대기 시간 동안 Windows 절전/화면 잠금이 동작하면
  클릭이 동작하지 않을 수 있습니다. 절전 설정을 확인하세요.
------------------------------------------
1) 현재 마우스 좌표 확인
2) 예약 클릭 실행
3) 종료
선택 >
```

### 4.2 메뉴 1: 좌표 확인 흐름
1. "3초 후 현재 마우스 위치를 출력합니다" 안내
2. 3 → 2 → 1 카운트다운
3. `pyautogui.position()` 호출 후 `(x, y)` 출력
4. 메뉴 복귀

### 4.3 메뉴 2: 예약 클릭 실행 흐름
1. x 좌표 입력 (정수, 0 이상)
2. y 좌표 입력 (정수, 0 이상)
3. 대기 시간(시) 입력 (정수, 0 이상)
4. 대기 시간(분) 입력 (정수, 0~59 권장)
5. **클릭 횟수 입력** (정수, 1 이상, 기본 6)
6. **클릭 간 간격(초) 입력** (실수, 0 이상, 기본 0.2)
7. 입력 요약 출력 + 사용자 확인 (`y/n`)
8. 카운트다운 시작:
   - 총 대기 시간이 60초 초과면 "1분 단위 진행 표시" 모드
   - 마지막 10초 진입 시 1초 단위 카운트다운으로 전환
9. 클릭 실행:
   - `moveTo(x, y, duration=1)`
   - `click(x, y)` × N회 (사이에 `time.sleep(interval)`)
10. 결과 출력 ("6회 클릭 완료") 후 메뉴 복귀

### 4.4 메뉴 3: 종료
- 정상 종료 메시지 출력 후 `sys.exit(0)`

---

## 5. 6회 클릭 설계 결정

### 5.1 옵션 비교
| 옵션 | 설명 | 장점 | 단점 | 채택 |
|------|------|------|------|------|
| A. 동일 좌표 N회 | 한 좌표를 N번 클릭, 간격 지정 | 가장 단순, 입력 적음 | 좌표마다 다른 클릭 불가 | ✅ **채택** |
| B. 좌표 리스트 | 6개 좌표를 각각 입력해 순차 클릭 | 유연함 | 입력 번거로움, 초보자 부담 ↑ | ❌ |
| C. 좌표 파일 로드 | JSON/CSV에서 좌표 읽기 | 재사용성 | 범위 초과 (이번 단계에서는 과함) | ❌ |

→ **결정**: 옵션 A 채택. 단, 함수 시그니처를 `clicks: list[tuple[int,int]]` 같은 형태로 두지 않고 `(x, y, count, interval)` 단순 형태로 시작한다. 추후 옵션 B로 확장 시에도 호출부만 변경하면 된다.

### 5.2 기본값
- 클릭 횟수: **6** (사용자 시나리오 반영)
- 클릭 간격: **0.2초** (너무 빠르면 OS가 더블클릭으로 인식할 가능성 있음)

---

## 6. 카운트다운 로직 설계

### 6.1 단계 구분
```
T-remaining (전체)
├── T > 60초:  "남은 시간: HH시간 MM분" 1분마다 출력
├── 60초 ≥ T > 10초: 1분 표시 → 60초 미만이면 다음 단계로 자연 진입
└── T ≤ 10초:  "10, 9, 8, ..., 1, 0 클릭!" 1초마다 출력
```

### 6.2 의사코드
```python
def countdown(total_seconds: int) -> None:
    deadline = time.monotonic() + total_seconds
    last_minute_print = -1  # avoid duplicate prints
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 10:
            break
        # print every 60s boundary
        elapsed_min = int((total_seconds - remaining) // 60)
        if elapsed_min != last_minute_print:
            print_remaining(remaining)
            last_minute_print = elapsed_min
        time.sleep(1)

    final_countdown(remaining)  # last 10s, 1-second tick
```

### 6.3 시간 측정 기준
- `time.time()` 대신 **`time.monotonic()`** 사용 (시스템 시각 변경 영향 회피)
- 누적 sleep이 아닌 deadline 기준 차감 → drift 최소화

---

## 7. 모듈/함수 설계 (main.py)

```
main()                          # 메뉴 루프 + 전역 예외 처리
├── print_intro()              # 안전 안내 출력
├── show_menu()                # 메뉴 출력 + 선택 입력
│
├── show_current_position()    # 메뉴 1
│
├── run_scheduled_click()      # 메뉴 2
│   ├── prompt_int(label, min) # 입력 검증 헬퍼
│   ├── prompt_float(...)
│   ├── confirm(label)         # y/n 확인
│   ├── countdown(total_sec)
│   │   ├── format_remaining(sec) → "X시간 Y분 Z초"
│   │   └── final_countdown(sec)
│   └── perform_clicks(x, y, count, interval)
│
└── exit_program()             # 메뉴 3
```

### 7.1 입력 검증 헬퍼
```python
def prompt_int(label: str, *, min_value: int = 0) -> int:
    """Prompt until a non-negative integer is entered."""
    while True:
        raw = input(f"{label}: ").strip()
        try:
            v = int(raw)
            if v < min_value:
                print(f"  → {min_value} 이상의 값을 입력하세요.")
                continue
            return v
        except ValueError:
            print("  → 숫자가 아닙니다. 다시 입력하세요.")
```

---

## 8. 예외 처리 매트릭스

| 발생 위치 | 예외 | 처리 |
|-----------|------|------|
| 입력 단계 | `ValueError` | 재입력 루프 |
| 클릭 실행 중 | `pyautogui.FailSafeException` | 메시지 출력 후 메뉴 복귀 |
| 어디서든 | `KeyboardInterrupt` | "프로그램을 종료합니다" 출력 후 정상 종료 |
| 어디서든 | `Exception` (광범위) | 메시지 + traceback 출력 후 메뉴 복귀 (메뉴 단계에서만) |

---

## 9. 구현 단계 (Step-by-Step)

### Step 1. 골격 (30분)
- [ ] `requirements.txt`: `pyautogui>=0.9.54`
- [ ] `main.py`: shebang, import, `if __name__ == "__main__": main()`
- [ ] 메뉴 루프 + 종료

### Step 2. 좌표 확인 (15분)
- [ ] `show_current_position()` 구현
- [ ] 3초 카운트다운

### Step 3. 입력 검증 (20분)
- [ ] `prompt_int`, `prompt_float`, `confirm` 헬퍼
- [ ] x, y, 시, 분, 횟수, 간격 입력 흐름

### Step 4. 카운트다운 (40분)
- [ ] `countdown(total_seconds)` 1분 단위
- [ ] `final_countdown(seconds)` 10초 단위
- [ ] `format_remaining` 포맷팅

### Step 5. 클릭 실행 (15분)
- [ ] `perform_clicks(x, y, count, interval)`
- [ ] `moveTo(x, y, duration=1)` → `click()` × N

### Step 6. 안전 처리 (20분)
- [ ] `pyautogui.FAILSAFE = True`
- [ ] `FailSafeException` / `KeyboardInterrupt` try-except
- [ ] 안전 안내 메시지 (`print_intro`)

### Step 7. 문서화 (30분)
- [ ] `README.md` 작성 (설치/실행/사용법/FAQ)
- [ ] main.py 주석 보강

### Step 8. 테스트 (30분)
- [ ] 좌표 확인 동작 확인
- [ ] 1분 짧은 대기 → 카운트다운 → 클릭 흐름 검증
- [ ] fail-safe 트리거 (마우스 좌상단 이동) 검증
- [ ] Ctrl+C 종료 검증
- [ ] 잘못된 입력 (문자, 음수) 재입력 검증

**예상 총 소요 시간: 약 3시간**

---

## 10. 테스트 시나리오 체크리스트

| # | 시나리오 | 기대 결과 |
|---|----------|-----------|
| T-1 | 메뉴 1 선택 | 3초 후 좌표 출력 |
| T-2 | 메뉴 2: x=500, y=500, 0시 1분, 6회, 0.2초 | 1분 후 6회 클릭 수행 |
| T-3 | 메뉴 2 진행 중 마우스 좌상단 이동 | "fail-safe로 중단" 메시지 + 메뉴 복귀 |
| T-4 | 메뉴 2 진행 중 Ctrl+C | "프로그램을 종료합니다" 출력 + 종료 |
| T-5 | x 좌표에 "abc" 입력 | "숫자가 아닙니다" 출력 + 재입력 |
| T-6 | 시(hour)에 -1 입력 | "0 이상의 값을 입력하세요" 출력 + 재입력 |
| T-7 | 메뉴 2: 2시간 0분, 6회 (실제 시나리오) | 1분 단위 진행 표시 → 마지막 10초 카운트 → 6회 클릭 |
| T-8 | 메뉴 3 선택 | 정상 종료 |

---

## 11. README.md 구조 (예고)

```
# AutoClicker

## 무엇을 하는 프로그램인가요?
## 요구사항 (Python 3.10+)
## 설치
  1. Python 설치
  2. pip install -r requirements.txt
## 실행
  python main.py
## 사용법
  - 좌표 확인하기
  - 예약 클릭 실행하기 (스크린샷/예시)
## 주의사항
  - 절전 모드
  - fail-safe
  - 관리자 권한이 필요한 창은 클릭 안 됨
## FAQ
## 라이선스 (선택)
```

---

## 12. 위험 요소 및 대응

| 위험 | 영향 | 대응 |
|------|------|------|
| 절전/잠금으로 인한 클릭 실패 | 시나리오 실패 | 시작 시 안내, README에 절전 해제 방법 |
| DPI 스케일링으로 좌표 어긋남 | 의도치 않은 위치 클릭 | 좌표 확인 메뉴로 사전 검증, README 안내 |
| 관리자 권한 창 클릭 불가 | 클릭이 무반응 | README FAQ에 명시 (관리자 권한으로 Python 실행) |
| 사용자가 시간 잘못 입력 | 너무 빠른/느린 실행 | 입력 후 요약 + y/n 확인 단계 |
| 60초 미만 입력 시 1분 카운트 미출력 | UX 혼란 | 60초 미만이면 바로 final_countdown 진입 |

---

## 13. 향후 확장 (이번 범위 아님, 메모)

- 좌표 리스트 기반 다중 좌표 클릭 (옵션 B)
- JSON 설정 파일 로드 (옵션 C)
- 더블클릭/우클릭 지원
- 키보드 입력 시퀀스
- 일정 반복 (cron-like)
- GUI (Tkinter) 버전

---

## 14. 의존성

```
# requirements.txt
pyautogui>=0.9.54
```

- Windows에서 `pyautogui`는 추가 시스템 의존성 없이 동작 (macOS는 Quartz, Linux는 Xlib 등 별도 필요)

---

## 15. 결정 사항 요약

1. **반복 클릭 방식**: 동일 좌표 N회 (기본 6회) + 간격(초) 입력
2. **시간 측정**: `time.monotonic()` 기반 deadline 차감
3. **카운트다운 단계**: > 60초 1분 단위 → ≤ 10초 1초 단위
4. **입력 흐름**: x, y, 시, 분, 횟수, 간격 → 요약 → y/n 확인
5. **에러 정책**: 입력 단계는 재시도, 실행 단계는 메뉴 복귀, Ctrl+C는 즉시 종료
6. **단일 파일**: 별도 모듈 분리 없이 main.py 한 파일로 작성 (초보자 친화)

---

## 16. Phase 2 — GUI / Production-ready 확장

콘솔 버전(main.py) 완성 후 사용자 요청에 따라 GUI 모드와 production-ready 기능을 추가했다. GUI는 별도 파일 `gui.py` 로 분리되어 콘솔 버전과 독립적으로 운영된다. Windows 환경을 1순위 타겟으로 한다.

### 16.1 추가된 기능
| # | 기능 | 구현 |
|---|------|------|
| 1 | Tkinter GUI | `gui.py` (표준 라이브러리만, 추가 의존성 없음) |
| 2 | 마우스 위치 라이브 미리보기 | `root.after(200, ...)` 재귀 갱신 |
| 3 | 시작 시점 (상대/절대) 토글 | 라디오 버튼, `datetime.now()` 비교 — 지난 시각이면 다음 날로 자동 |
| 4 | 클릭 종류 (좌/우/더블) | `pyautogui.click / rightClick / doubleClick` |
| 5 | 자동 절전 방지 (Windows) | `kernel32.SetThreadExecutionState` (ctypes) |
| 6 | 사운드 알림 | `winsound.Beep`, fallback ASCII bell |
| 7 | 진행 Progress Bar | `ttk.Progressbar`, `time.monotonic()` 기반 % 갱신 |
| 8 | 프로파일 저장/로드 | `autoclicker_profile.json`, 시작 시 자동 적용 |
| 9 | 키보드 단축키 | `Ctrl+Enter` 시작 / `Esc` 중단 / `F8` 캡처 |
| 10 | 백그라운드 워커 | `threading.Thread` + `threading.Event` 취소 신호 |
| 11 | 안전한 창 닫기 | `WM_DELETE_WINDOW` 핸들러, 진행 중 확인창 + 절전 차단 해제 |
| 12 | Windows .bat 런처 | `run_gui.bat`, `run_console.bat` (UTF-8, 더블클릭 실행) |
| 13 | EXE 빌드 가이드 | PyInstaller 명령을 README 에 명시 |

### 16.2 스레드 모델
- **메인 스레드**: Tkinter UI 갱신, 사용자 입력, `SetThreadExecutionState` 호출
- **워커 스레드**: 카운트다운 + 마우스 이동 + 클릭 실행
- 모든 UI 갱신은 워커 → `root.after(0, ...)` 로 메인 스레드에 위임 (Tkinter 스레드 안전성 확보)
- 취소 신호는 `threading.Event` 로 비동기 통신, 카운트다운 sleep 도 0.1초 단위로 cancel-aware

### 16.3 Windows 의존 부분과 Fallback
| 기능 | Windows | 비-Windows |
|------|---------|------------|
| 자동 절전 방지 | `SetThreadExecutionState` | 비활성화 (체크박스 disabled) |
| 사운드 알림 | `winsound.Beep` | ASCII bell (`\a`) |
| .bat 런처 | 더블클릭 실행 | 미지원 (셸에서 직접 `python gui.py`) |
| 진입 체크 | `IS_WINDOWS = sys.platform.startswith("win")` | 동일, 분기 처리 |

### 16.4 의존성 정책
- 새 기능에 추가 패키지 0개 (`winsound`, `ctypes`, `tkinter`, `json`, `threading`, `datetime` 모두 표준 라이브러리)
- `requirements.txt` 변경 없음 — `pyautogui` 한 줄 그대로

### 16.5 변경되지 않은 부분
- `main.py` (콘솔) — Phase 1 그대로 유지
- `Docs/Dev_Plan.md` 1~15장 — 본 16장만 append

### 16.6 향후 확장 후보 (이번 범위 아님)
- 다중 좌표 순차 클릭 (좌표 리스트 / Treeview UI)
- 트레이 아이콘 (`pystray` 의존성 추가)
- 글로벌 핫키 (`keyboard` 의존성 추가, 관리자 권한 필요)
- 작업 큐잉 (예약 여러 개 동시 등록)
- 다크 모드 / 테마 (customtkinter)
- 다국어 (i18n)

### 16.7 검증 상태
- ✅ `gui.py` syntax 검증 통과 (ast.parse)
- ⚠️ 실 환경 동작 테스트는 사용자 측 권장 (Tkinter 렌더링, pyautogui 클릭, 절전 차단, 사운드)
