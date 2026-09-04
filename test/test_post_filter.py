import unittest

from app.core.services.post_filter import hard_filter


class HardFilterTests(unittest.TestCase):
    def test_passes_normal_post(self):
        article = {"title": "오늘 학식 어때요", "content": "3층 식당 괜찮던데"}
        self.assertIsNone(hard_filter(article))

    def test_rejects_empty_post(self):
        article = {"title": "", "content": ""}
        self.assertEqual(hard_filter(article), "empty_content")

    def test_rejects_blacklist_keyword_in_title(self):
        article = {"title": "과외 구합니다", "content": "본문"}
        reason = hard_filter(article, skip_keywords=["과외"])
        self.assertEqual(reason, "blacklist_keyword:과외")

    def test_blacklist_match_is_case_insensitive(self):
        article = {"title": "PROMO event", "content": "본문"}
        reason = hard_filter(article, skip_keywords=["promo"])
        self.assertIsNotNone(reason)

    def test_no_keywords_configured_does_not_filter(self):
        article = {"title": "아무 제목", "content": "본문"}
        self.assertIsNone(hard_filter(article, skip_keywords=[]))


if __name__ == "__main__":
    unittest.main()
