-- 암호화된 봇 저장소
-- 인증 정보: etsid, userid, password
-- 실행 상태: last_article_id, last_run_time, browser_state
-- 설정/통계: board_id, board_name, skip_keywords, run_history
CREATE TABLE IF NOT EXISTS bot_storage (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
