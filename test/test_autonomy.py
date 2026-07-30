import logging
import unittest
import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

from postgrest.exceptions import APIError

from app.config import KSTFormatter
from app.core import autonomy
from app.core.article_trends import infer_activity_windows, parse_article_datetime
from app.core.database import SecureDatabase


class FakeJobQueue:
    def __init__(self):
        self.jobs = {}
        self.run_once_calls = []

    def get_jobs_by_name(self, name):
        return tuple(self.jobs.get(name, ()))

    def run_once(self, callback, *, when, name, data):
        job = object()
        self.jobs.setdefault(name, []).append(job)
        self.run_once_calls.append({
            "callback": callback,
            "when": when,
            "name": name,
            "data": data,
        })
        return job


class FakeApplication:
    def __init__(self):
        self.job_queue = FakeJobQueue()


class FakeQuery:
    def __init__(self, error=None):
        self.error = error
        self.payload = None

    def insert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        if self.error:
            raise self.error
        return object()


class FakeSupabase:
    def __init__(self, query):
        self.query = query

    def table(self, name):
        if name != "bot_storage":
            raise AssertionError(name)
        return self.query


class AutonomySchedulingTests(unittest.TestCase):
    def test_afternoon_window_ends_on_same_day(self):
        with patch("app.core.autonomy.random.randint", return_value=3 * 60 * 60):
            result = autonomy._random_dt_in_window(
                date(2099, 7, 28),
                ((17, 0), (20, 0)),
            )

        self.assertEqual(result.isoformat(), "2099-07-28T20:00:00+09:00")

    def test_actual_midnight_crossing_window_ends_next_day(self):
        with patch("app.core.autonomy.random.randint", return_value=3 * 60 * 60):
            result = autonomy._random_dt_in_window(
                date(2099, 7, 28),
                ((21, 0), (0, 0)),
            )

        self.assertEqual(result.isoformat(), "2099-07-29T00:00:00+09:00")

    def test_same_daily_jobs_are_not_scheduled_twice(self):
        application = FakeApplication()
        base_date = date(2099, 7, 28)

        autonomy._schedule_triggers_for(application, base_date)
        autonomy._schedule_triggers_for(application, base_date)

        self.assertEqual(len(application.job_queue.run_once_calls), 2)
        self.assertEqual(
            {call["name"] for call in application.job_queue.run_once_calls},
            {
                "autonomy_trigger_2099-07-28_A",
                "autonomy_trigger_2099-07-28_B",
            },
        )
        for call in application.job_queue.run_once_calls:
            self.assertEqual(call["data"]["base_date"], "2099-07-28")


class ArticleTrendTests(unittest.TestCase):
    def test_naive_article_time_is_interpreted_as_kst(self):
        parsed = parse_article_datetime("2026-07-30 08:15:00")

        self.assertEqual(parsed.isoformat(), "2026-07-30T08:15:00+09:00")

    def test_busy_periods_move_both_windows(self):
        now = datetime(2026, 7, 30, 23, 0, tzinfo=autonomy.KST)
        articles = []
        article_id = 0
        for days_ago in range(5):
            for hour in (8, 9, 10, 19, 20, 21):
                for minute in (5, 35):
                    article_id += 1
                    created_at = now - timedelta(days=days_ago)
                    created_at = created_at.replace(hour=hour, minute=minute)
                    articles.append({
                        "id": str(article_id),
                        "created_at": created_at.isoformat(),
                        "posvote": 0,
                    })

        windows, summary = infer_activity_windows(
            articles,
            now=now,
            fallback_windows=[((6, 0), (9, 0)), ((17, 0), (20, 0))],
            search_ranges=(((5, 0), (12, 0)), ((15, 0), (23, 0))),
            lookback_days=7,
            minimum_samples=20,
            minimum_slot_samples=3,
        )

        self.assertEqual(windows, [((8, 0), (11, 0)), ((19, 0), (22, 0))])
        self.assertEqual(summary["sample_count"], 60)
        self.assertFalse(summary["used_fallback"])

    def test_insufficient_samples_keep_default_windows(self):
        now = datetime(2026, 7, 30, 23, 0, tzinfo=autonomy.KST)
        articles = [{
            "created_at": now.replace(hour=10).isoformat(),
            "posvote": 10,
        }]
        fallback = [((6, 0), (9, 0)), ((17, 0), (20, 0))]

        windows, summary = infer_activity_windows(
            articles,
            now=now,
            fallback_windows=fallback,
            search_ranges=(((5, 0), (12, 0)), ((15, 0), (23, 0))),
            lookback_days=7,
            minimum_samples=20,
            minimum_slot_samples=3,
        )

        self.assertEqual(windows, fallback)
        self.assertTrue(summary["used_fallback"])
        self.assertEqual(summary["selected_windows"], fallback)


class KSTFormatterTests(unittest.TestCase):
    def test_log_timestamp_contains_kst_offset(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "message", (), None)
        record.created = 0

        value = KSTFormatter().formatTime(record)

        self.assertEqual(value, "1970-01-01 09:00:00.000+09:00")


class ClaimOnceTests(unittest.TestCase):
    def _database(self, query):
        database = SecureDatabase.__new__(SecureDatabase)
        database.supabase = FakeSupabase(query)
        database._encrypt = lambda value: f"encrypted:{value}"
        database._now = lambda: "2026-07-28T00:00:00+00:00"
        return database

    def test_claim_succeeds_only_for_new_key(self):
        query = FakeQuery()
        database = self._database(query)

        result = database.claim_once("autonomy_slot:2026-07-28:B", "claimed")

        self.assertTrue(result)
        self.assertEqual(
            query.payload,
            {
                "key": "autonomy_slot:2026-07-28:B",
                "value": "encrypted:claimed",
                "updated_at": "2026-07-28T00:00:00+00:00",
            },
        )

    def test_duplicate_claim_is_rejected(self):
        error = APIError({"code": "23505", "message": "duplicate key"})
        database = self._database(FakeQuery(error))

        result = database.claim_once("autonomy_slot:2026-07-28:B", "claimed")

        self.assertFalse(result)

    def test_storage_error_fails_closed(self):
        database = self._database(FakeQuery(RuntimeError("offline")))

        result = database.claim_once("autonomy_slot:2026-07-28:B", "claimed")

        self.assertIsNone(result)


class DuplicateExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_claimed_slot_does_not_initialize_vote_runner(self):
        when = autonomy.datetime(2099, 7, 28, 18, 0, tzinfo=autonomy.KST)
        context = type(
            "Context",
            (),
            {
                "job": type(
                    "Job",
                    (),
                    {
                        "data": {
                            "slot": "B",
                            "when": when,
                            "base_date": "2099-07-28",
                        }
                    },
                )()
            },
        )()

        loop = asyncio.get_running_loop()
        with (
            patch.object(loop, "run_in_executor", AsyncMock(return_value=False)),
            patch("app.core.autonomy.VoteRunner") as runner,
        ):
            await autonomy._run_autonomous_vote(context)

        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
