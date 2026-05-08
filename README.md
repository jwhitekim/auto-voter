# 에브리타임 자동 공감 봇

텔레그램으로 제어하는 에브리타임 게시판 자동 공감 봇입니다.  
Railway에서 24시간 동작하며, 마지막으로 처리한 게시글을 Supabase에 기록해 중단 후 재개가 가능합니다.

## 기능

| 명령어 | 설명 |
|--------|------|
| `/login` | 아이디/비밀번호로 자동 로그인 (Playwright) |
| `/setsession` | etsid 쿠키 수동 입력 |
| `/vote` | 공감 봇 실행 (진행 상황 실시간 업데이트) |
| `/status` | 로그인 상태 및 마지막 실행 정보 확인 |
| `/logout` | 저장된 인증 정보 삭제 |

- 세션 만료 시 저장된 자격증명으로 **자동 재로그인**
- 체크포인트 기반 **이어하기**: 마지막으로 공감한 게시글 이후부터 탐색
- 삭제된 게시글로 인한 체크포인트 소실 시 **타임스탬프 기반 중단**
- 자격증명은 **Fernet 암호화** 후 Supabase에 저장

## 기술 스택

- Python 3.10+
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v20+
- [Playwright](https://playwright.dev/python/) + playwright-stealth (로그인 자동화)
- [Supabase](https://supabase.com/) (암호화된 자격증명 및 상태 저장)
- [Railway](https://railway.app/) (배포)

## 프로젝트 구조

```
├── main.py                 # 진입점
├── app/
│   ├── bot.py              # 텔레그램 핸들러
│   ├── voter.py            # 에브리타임 API + 투표 로직
│   ├── auth.py             # Playwright 기반 로그인
│   └── storage.py          # Fernet 암호화 Supabase 스토리지
├── config/
│   └── config.yaml         # 게시판 ID, 타이밍 등 설정
├── supabase_setup.sql      # DB 테이블 생성 SQL
├── Procfile                # Railway worker 설정
└── docs/
    └── install_chromium.txt
```

## 설치 및 배포

### 1. Supabase 설정

[Supabase](https://supabase.com/)에서 프로젝트 생성 후 `supabase_setup.sql`을 SQL Editor에서 실행합니다.

```sql
-- bot_storage: 암호화된 자격증명 (etsid, userid, password)
-- bot_state:   봇 실행 상태 (체크포인트, 브라우저 상태)
```

### 2. 환경변수

`.env` 파일 또는 Railway 환경변수에 다음을 설정합니다.

```env
TELEGRAM_TOKEN=       # BotFather에서 발급
TELEGRAM_CHAT_ID=     # 허용할 채팅 ID (숫자)
SUPABASE_URL=         # Supabase 프로젝트 URL
SUPABASE_KEY=         # Supabase anon key
ENCRYPTION_KEY=       # Fernet 키 (미설정 시 자동 생성 — 아래 주의사항 참고)
```

> **주의**: `ENCRYPTION_KEY`는 Railway 대시보드에 영구 환경변수로 등록해야 합니다.  
> 설정하지 않으면 배포·재시작 시 새 키가 생성되어 기존 저장 데이터를 복호화할 수 없습니다.  
> 초기 실행 로그에서 생성된 키를 확인해 Railway에 등록하세요.

### 3. 의존성 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Railway 배포

1. 이 저장소를 Railway에 연결
2. 위 환경변수를 Railway Variables에 등록
3. **Build Command**에 Playwright 설치 추가:
   ```
   pip install -r requirements.txt && playwright install chromium --with-deps
   ```
4. `Procfile`에 의해 `worker: python main.py`로 실행됨

## 설정 (`config/config.yaml`)

```yaml
bot:
  board_id: "389115"  # 대상 게시판 ID (URL에서 확인)
  max_pages: 5        # 탐색할 최대 페이지 수

timing:
  sleep_min: 1.0      # 공감 간 최소 대기 시간 (초)
  sleep_max: 3.0      # 공감 간 최대 대기 시간 (초)
  page_delay: 0.5     # 페이지 간 대기 시간 (초)
```

게시판 ID는 에브리타임 게시판 URL에서 확인할 수 있습니다.  
예: `https://everytime.kr/389115` → `board_id: "389115"`

## 로컬 실행

```bash
cp .env.example .env  # 환경변수 설정
python main.py
```

## 주의사항

- 이 봇은 에브리타임의 이용약관에 위배될 수 있습니다. 사용에 따른 책임은 본인에게 있습니다.
- `/login` 명령어 사용 시 입력한 비밀번호 메시지는 자동 삭제됩니다.
- 특정 Chat ID만 명령어를 사용할 수 있도록 인가 처리되어 있습니다.
