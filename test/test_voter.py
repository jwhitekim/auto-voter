import unittest

from app.core.vote_runner import run_vote


class FakeStorage:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.saves = []

    def load(self, key):
        return self.values.get(key)

    def save(self, key, value):
        self.saves.append((key, value))
        self.values[key] = value


class FakeClient:
    def __init__(self, pages, storage, vote_result="voted"):
        self.storage = storage
        self.pages = pages
        self.vote_result = vote_result
        self.voted_ids = []

    def check_session(self, board_id):
        return True

    def get_article_ids(self, board_id, limit_num=20, start_num=0):
        return self.pages.get(start_num, [])

    def find_article(self, board_id, before_article_id, max_pages=50, page_delay=0.5):
        count = 0
        offset = 0
        for _ in range(max_pages):
            articles = self.get_article_ids(board_id, start_num=offset)
            if not articles:
                break
            for idx, item in enumerate(articles):
                if item["id"] == before_article_id:
                    return count, idx
                count += 1
            offset += 20
        return count, -1

    def push_vote(self, article_id):
        if self.storage.load("last_article_id") == "newest":
            raise AssertionError("checkpoint must not be updated before votes finish")
        self.voted_ids.append(article_id)
        return self.vote_result


class FakeInterestDecider:
    def __init__(self, liked_ids):
        self.liked_ids = set(liked_ids)
        self.seen_ids = []

    def should_vote(self, article):
        self.seen_ids.append(article["id"])
        return article["id"] in self.liked_ids


def article(article_id, posvote=0):
    return {
        "id": article_id,
        "title": f"title {article_id}",
        "created_at": "2026-06-21 12:00:00",
        "posvote": posvote,
    }


class VoterTests(unittest.TestCase):
    def _run(self, client, storage):
        cfg = {
            "bot": {"board_id": "board", "max_pages": 5},
            "timing": {"sleep_min": 0, "sleep_max": 0, "page_delay": 0},
        }
        return run_vote(
            client=client,
            storage=storage,
            cfg=cfg,
            target_board="board",
        )

    def test_votes_only_articles_before_found_checkpoint_then_updates_checkpoint(self):
        storage = FakeStorage({"last_article_id": "old"})
        client = FakeClient({
            0: [article("newest"), article("newer"), article("old"), article("older")]
        }, storage)

        result = self._run(client, storage)

        self.assertEqual(client.voted_ids, ["newest", "newer"])
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
        client = FakeClient(pages, storage)

        result = self._run(client, storage)

        self.assertFalse(result["checkpoint_found"])
        self.assertFalse(result["scan_limit_reached"])
        self.assertEqual(result["scanned"], 100)
        self.assertEqual(result["candidates"], 100)
        self.assertEqual(result["processed"], 100)

    def test_does_not_advance_checkpoint_when_any_vote_fails(self):
        storage = FakeStorage({"last_article_id": "old"})
        client = FakeClient({
            0: [article("newest"), article("old")]
        }, storage, vote_result="failed")

        result = self._run(client, storage)

        self.assertEqual(result["failed"], 1)
        self.assertEqual(storage.load("last_article_id"), "old")

    def test_dry_run_does_not_call_push_vote(self):
        storage = FakeStorage({"last_article_id": "old"})
        client = FakeClient({
            0: [article("newest"), article("old")]
        }, storage)
        cfg = {
            "bot": {"board_id": "board", "max_pages": 5},
            "timing": {"sleep_min": 0, "sleep_max": 0, "page_delay": 0},
        }

        result = run_vote(
            client=client,
            storage=storage,
            cfg=cfg,
            target_board="board",
            dry_run=True,
        )

        self.assertEqual(client.voted_ids, [])
        self.assertEqual(result["processed"], 1)

    def test_votes_only_articles_selected_by_interest_decider(self):
        storage = FakeStorage({"last_article_id": "old"})
        client = FakeClient({
            0: [article("liked"), article("not-liked"), article("old")]
        }, storage)
        decider = FakeInterestDecider({"liked"})
        cfg = {
            "bot": {"board_id": "board", "max_pages": 5},
            "timing": {"sleep_min": 0, "sleep_max": 0, "page_delay": 0},
        }

        result = run_vote(
            client=client,
            storage=storage,
            cfg=cfg,
            target_board="board",
            interest_decider=decider,
        )

        self.assertEqual(decider.seen_ids, ["liked", "not-liked"])
        self.assertEqual(client.voted_ids, ["liked"])
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
