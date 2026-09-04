import unittest

from app.core.clients.gemini import GeminiFeatureEvaluator, ALL_FEATURES


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        # 여러 번 호출될 수 있으므로 리스트로 응답을 순서대로 반환한다.
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def _full_features(**overrides):
    features = {name: 0.5 for name in ALL_FEATURES}
    features["confidence"] = 0.8
    features.update(overrides)
    return features


def _response_with(features: dict) -> FakeResponse:
    import json
    return FakeResponse({
        "candidates": [{"content": {"parts": [{"text": json.dumps(features)}]}}]
    })


class GeminiFeatureEvaluatorTests(unittest.TestCase):
    def test_parses_structured_feature_scores(self):
        features = _full_features(usefulness=0.82, promotion=0.02)
        session = FakeSession([_response_with(features)])
        evaluator = GeminiFeatureEvaluator("secret", session=session)

        result = evaluator.evaluate({"id": "1", "title": "제목", "content": "본문"})

        self.assertEqual(result["usefulness"], 0.82)
        self.assertEqual(result["promotion"], 0.02)
        self.assertEqual(result["confidence"], 0.8)
        self.assertEqual(session.calls[0][1]["headers"]["x-goog-api-key"], "secret")

    def test_clamps_out_of_range_values(self):
        features = _full_features(usefulness=1.5, toxicity=-0.3)
        session = FakeSession([_response_with(features)])
        evaluator = GeminiFeatureEvaluator("secret", session=session)

        result = evaluator.evaluate({"id": "1", "title": "제목", "content": "본문"})

        self.assertEqual(result["usefulness"], 1.0)
        self.assertEqual(result["toxicity"], 0.0)

    def test_retries_once_then_succeeds(self):
        good = _response_with(_full_features())
        session = FakeSession([FakeResponse({"candidates": []}), good])
        evaluator = GeminiFeatureEvaluator("secret", session=session, max_retries=1)

        result = evaluator.evaluate({"id": "1", "title": "제목", "content": "본문"})

        self.assertIsNotNone(result)
        self.assertEqual(len(session.calls), 2)

    def test_returns_none_after_exhausting_retries(self):
        session = FakeSession([FakeResponse({"candidates": []}), FakeResponse({"candidates": []})])
        evaluator = GeminiFeatureEvaluator("secret", session=session, max_retries=1)

        result = evaluator.evaluate({"id": "1", "title": "제목", "content": "본문"})

        self.assertIsNone(result)
        self.assertEqual(len(session.calls), 2)

    def test_missing_required_key_is_treated_as_failure(self):
        incomplete = _full_features()
        del incomplete["promotion"]
        session = FakeSession([_response_with(incomplete)])
        evaluator = GeminiFeatureEvaluator("secret", session=session, max_retries=0)

        result = evaluator.evaluate({"id": "1", "title": "제목", "content": "본문"})

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
