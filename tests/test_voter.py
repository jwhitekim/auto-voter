import unittest

from app.voter import Main


class FakeStorage:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.saves = []

    def load(self, key):
        return self.values.get(key)

    def save(self, key, value):
        self.saves.append((key, value))
        self.values[key] = value


class FakeMain(Main):
    def __init__(self, pages, storage, vote_result="voted"):
        self.cfg = {
            "bot": {"board_id": "board", "max_pages": 5},
            "timing": {"sleep_min": 0, "sleep_max": 0, "page_delay": 0},
        }
        self.storage = storage
        self.target_board = "board"
        self.id_title_map = {}
        self.pages = pages
        self.vote_result = vote_result
        self.voted_ids = []

    def check_session(self, board_id):
        return True

    def get_article_ids(self, board_id, limit_num=20, start_num=0):
        return self.pages.get(start_num, [])

    def push_vote(self, article_id):
        if self.storage.load("last_article_id") == "newest":
            raise AssertionError("checkpoint must not be updated before votes finish")
        self.voted_ids.append(article_id)
        return self.vote_result


def article(article_id, posvote=0):
    return {
        "id": article_id,
        "title": f"title {article_id}",
        "created_at": "2026-06-21 12:00:00",
        "posvote": posvote,
    }


class VoterTests(unittest.TestCase):
    def test_votes_only_articles_before_found_checkpoint_then_updates_checkpoint(self):
        storage = FakeStorage({"last_article_id": "old"})
        bot = FakeMain({
            0: [article("newest"), article("newer"), article("old"), article("older")]
        }, storage)

        result = bot.start()

        self.assertEqual(bot.voted_ids, ["newest", "newer"])
        self.assertTrue(result["checkpoint_found"])
        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["candidates"], 2)
        self.assertEqual(result["scanned"], 4)
        self.assertEqual(storage.load("last_article_id"), "newest")

    def test_reports_scan_limit_when_checkpoint_is_not_found(self):
        storage = FakeStorage({"last_article_id": "missing"})
        pages = {
            i * 20: [article(f"post-{i}-{j}") for j in range(20)]
            for i in range(5)
        }
        bot = FakeMain(pages, storage)

        result = bot.start()

        self.assertFalse(result["checkpoint_found"])
        self.assertTrue(result["scan_limit_reached"])
        self.assertEqual(result["scanned"], 100)
        self.assertEqual(result["candidates"], 100)
        self.assertEqual(result["processed"], 100)

    def test_does_not_advance_checkpoint_when_any_vote_fails(self):
        storage = FakeStorage({"last_article_id": "old"})
        bot = FakeMain({
            0: [article("newest"), article("old")]
        }, storage, vote_result="failed")

        result = bot.start()

        self.assertEqual(result["failed"], 1)
        self.assertEqual(storage.load("last_article_id"), "old")


if __name__ == "__main__":
    unittest.main()
