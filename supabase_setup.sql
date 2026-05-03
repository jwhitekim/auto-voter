-- 암호화된 인증 정보 (etsid, userid, password)
CREATE TABLE IF NOT EXISTS bot_storage (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 봇 실행 상태 (last_article_id, last_article_title, browser_state)
CREATE TABLE IF NOT EXISTS bot_state (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
