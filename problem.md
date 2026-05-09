# 현재 알려진 문제

## 🔴 긴급 (즉시 조치 필요)

### 1. ENCRYPTION_KEY 손실 시 자격증명 복호화 불가

**파일**: `app/storage.py` 27~35줄

`ENCRYPTION_KEY` 환경변수가 없을 때 코드가 자동으로 키를 생성해 `.env` 파일에 씁니다.  
Railway는 파일시스템이 ephemeral(재배포·재시작 시 초기화)이므로, 이 키는 재시작 후 사라집니다.  
키가 바뀌면 Supabase에 저장된 `userid`, `password`, `etsid`를 복호화할 수 없어 봇이 동작하지 않습니다.

**재현 조건**: Railway에서 재배포 또는 컨테이너 재시작 발생 시

**해결 방법**:
1. 현재 실행 중인 봇의 로그에서 생성된 `ENCRYPTION_KEY` 값 확인
2. Railway 대시보드 → Variables → `ENCRYPTION_KEY` 영구 등록
3. 등록 후 `/login` 으로 자격증명 재저장

---

### 2. Railway 빌드 시 Playwright Chromium 미설치

**파일**: `Procfile`, `docs/install_chromium.txt`

`requirements.txt`에 `playwright` 패키지가 있어도 브라우저 바이너리는 별도로 설치해야 합니다.  
현재 `Procfile`은 `worker: python main.py`만 있고, 빌드 단계에서 Chromium을 설치하는 커맨드가 없습니다.  
`/login` 명령어 실행 시 `playwright._impl._errors.Error: Executable doesn't exist` 오류 발생.

**해결 방법**:  
Railway → Settings → Build Command에 추가:
```
pip install -r requirements.txt && playwright install chromium --with-deps
```

---

## 🟡 권장 수정

### 3. 브라우저 상태(쿠키)가 평문으로 Supabase 저장

**파일**: `app/auth.py` 22~33줄

`save_browser_state()`는 브라우저 전체 상태(쿠키 포함)를 JSON 그대로 `bot_state` 테이블에 저장합니다.  
`bot_storage` 테이블의 자격증명은 Fernet 암호화가 적용되지만, `bot_state`의 브라우저 상태는 평문입니다.  
Supabase 접근 권한이 노출되면 세션 쿠키 하이재킹이 가능합니다.

**해결 방법**: `save_browser_state` / `load_browser_state`에도 `SecureStorage`의 Fernet 암호화 적용

---

### 4. 의존성 버전 미고정

**파일**: `requirements.txt`

`python-telegram-bot`과 `supabase`는 하한만 지정되어 있고, 나머지는 버전 지정이 없습니다.  
의존성 업데이트로 인한 호환성 오류가 배포 중에 발생할 수 있습니다.

```
requests          # 버전 없음
playwright        # 버전 없음
playwright-stealth # 버전 없음
cryptography      # 버전 없음
pyyaml            # 버전 없음
python-dotenv     # 버전 없음
```

**해결 방법**: 현재 동작하는 환경에서 `pip freeze > requirements.txt` 실행 후 커밋

---

## 🟢 코드 품질

### 5. 프로덕션 코드에 DEBUG print 문 잔류

**파일**: `app/bot.py` 168~185줄

`cmd_vote` 함수 내에 `print(f"[DEBUG] ...")` 문이 여러 개 남아 있습니다.  
로그에 etsid 쿠키 값이 출력되어 Railway 로그에서 세션값이 노출될 수 있습니다.

```python
print(f"[DEBUG] Main 초기화 성공, etsid: {bot.session.headers.get('Cookie')}")
```

**해결 방법**: `print` → `logging.debug`로 교체하거나 제거

---

### 6. `_last_run_time`, `_last_bot` 모듈 전역 변수

**파일**: `app/bot.py` 30~31줄, 233줄

봇 재시작 시 `_last_run_time`이 초기화되어 `/status`에서 "없음"으로 표시됩니다.  
중요한 상태라면 Supabase `bot_state`에 저장하는 것이 일관성 있는 구조입니다.
