import unittest
from pathlib import Path

from recommendation_engine import STRATEGY_WEIGHTS, RecommendationEngine

DATA_DIR = Path(__file__).resolve().parent / "data"


class RecommendationEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = RecommendationEngine.from_csv_dir(DATA_DIR)

    def test_data_summary_matches_source_files(self):
        summary = self.engine.data_summary()
        self.assertEqual(summary["movie_count"], 200)
        self.assertEqual(summary["user_count"], 300)
        self.assertEqual(summary["viewing_count"], 4000)
        self.assertEqual(summary["user_review_count"], 1000)
        self.assertEqual(summary["critic_review_count"], 500)

    def test_recommendations_exclude_watched_movies_by_default(self):
        watched = self.engine.watched_movie_ids("USR0001")
        recommendations = self.engine.recommend("USR0001", limit=15)
        self.assertEqual(len(recommendations), 15)
        self.assertTrue(set(recommendations["movie_id"]).isdisjoint(watched))
        self.assertTrue(recommendations["recommendation_score"].is_monotonic_decreasing)

    def test_recommendation_filters_are_applied(self):
        recommendations = self.engine.recommend(
            "USR0002",
            genre="Thriller",
            max_runtime=120,
            content_rating="15+",
            limit=20,
        )
        self.assertFalse(recommendations.empty)
        self.assertEqual(set(recommendations["primary_genre"]), {"Thriller"})
        self.assertLessEqual(recommendations["runtime_minutes"].max(), 120)
        self.assertEqual(set(recommendations["content_rating"]), {"15+"})

    def test_strategy_changes_ranking(self):
        taste = self.engine.recommend("USR0003", strategy="취향 집중", limit=10)
        critics = self.engine.recommend("USR0003", strategy="평론가 추천", limit=10)
        self.assertNotEqual(taste["movie_id"].tolist(), critics["movie_id"].tolist())

    def test_strategy_weights_match_product_rules(self):
        self.assertEqual(STRATEGY_WEIGHTS["균형 맞춤"], (0.34, 0.33, 0.33))
        self.assertEqual(STRATEGY_WEIGHTS["취향 집중"], (0.80, 0.10, 0.10))
        self.assertEqual(STRATEGY_WEIGHTS["비슷한 시청자"], (0.10, 0.80, 0.10))
        self.assertEqual(STRATEGY_WEIGHTS["평론가 추천"], (0.10, 0.10, 0.80))
        for weights in STRATEGY_WEIGHTS.values():
            self.assertAlmostEqual(sum(weights), 1.0)

    def test_recommendations_include_human_readable_reason(self):
        recommendations = self.engine.recommend("USR0004", limit=5)
        self.assertTrue(recommendations["recommendation_reason"].str.len().gt(0).all())

    def test_catalog_search_uses_korean_keyword_text(self):
        results = self.engine.search_movies("세탁표")
        self.assertFalse(results.empty)
        self.assertIn("MOV0001", set(results["movie_id"]))

    def test_user_and_movie_detail(self):
        summary = self.engine.user_summary("USR0001")
        detail = self.engine.movie_detail("MOV0001", "USR0001")
        expected_user_reviews = int(
            self.engine.data.user_reviews["movie_id"].eq("MOV0001").sum()
        )
        expected_critic_reviews = int(
            self.engine.data.critic_reviews["movie_id"].eq("MOV0001").sum()
        )

        self.assertEqual(summary["user_id"], "USR0001")
        self.assertEqual(detail["movie"]["movie_id"], "MOV0001")
        self.assertIn("stats", detail)
        self.assertEqual(len(detail["user_reviews"]), expected_user_reviews)
        self.assertEqual(len(detail["critic_reviews"]), expected_critic_reviews)
        self.assertIn("display_name", detail["user_reviews"][0])
        self.assertIn("review_text", detail["user_reviews"][0])


if __name__ == "__main__":
    unittest.main()
