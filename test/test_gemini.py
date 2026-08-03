import unittest

from app.core.clients.gemini import GeminiInterestDecider


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class GeminiInterestDeciderTests(unittest.TestCase):
    def test_uses_structured_decision(self):
        response = FakeResponse({
            "candidates": [{"content": {"parts": [{"text": '{"should_vote": true, "reason": "관심사 일치"}'}]}}]
        })
        session = FakeSession(response)
        decider = GeminiInterestDecider("secret", "개발과 음악을 좋아함", session=session)

        self.assertTrue(decider.should_vote({"id": "1", "title": "개발", "content": "파이썬 이야기"}))
        self.assertNotIn("secret", str(session.calls[0][1]["json"]))
        self.assertEqual(session.calls[0][1]["headers"]["x-goog-api-key"], "secret")

    def test_invalid_response_fails_closed(self):
        session = FakeSession(FakeResponse({"candidates": []}))
        decider = GeminiInterestDecider("secret", "관심사", session=session)

        self.assertIsNone(decider.should_vote({"id": "1", "title": "제목", "content": "본문"}))


if __name__ == "__main__":
    unittest.main()
