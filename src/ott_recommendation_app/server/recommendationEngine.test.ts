import assert from "node:assert/strict";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { RecommendationEngine, STRATEGY_WEIGHTS } from "./recommendationEngine.js";

const serverDirectory = dirname(fileURLToPath(import.meta.url));
const engine = RecommendationEngine.fromCsvDir(resolve(serverDirectory, "..", "data"));

test("CSV 데이터 규모를 그대로 읽는다", () => {
  assert.deepEqual(engine.dataSummary(), {
    movie_count: 200,
    user_count: 300,
    viewing_count: 4000,
    user_review_count: 1000,
    critic_count: 40,
    critic_review_count: 500,
  });
});

test("기본 추천에서 이미 본 작품을 제외하고 점수순으로 정렬한다", () => {
  const watched = engine.watchedMovieIds("USR0001");
  const recommendations = engine.recommend({ userId: "USR0001", limit: 15 });
  assert.equal(recommendations.length, 15);
  assert.equal(recommendations.some((movie) => watched.has(movie.movie_id)), false);
  for (let index = 1; index < recommendations.length; index += 1) {
    assert.ok(recommendations[index - 1].recommendation_score >= recommendations[index].recommendation_score);
  }
});

test("장르와 관람 등급 필터를 적용한다", () => {
  const recommendations = engine.recommend({
    userId: "USR0002",
    genre: "Thriller",
    contentRating: "15+",
    limit: 20,
  });
  assert.ok(recommendations.length > 0);
  assert.ok(recommendations.every((movie) => movie.primary_genre === "Thriller"));
  assert.ok(recommendations.every((movie) => movie.content_rating === "15+"));
});

test("전략별 80:10:10 가중치와 균형 가중치의 합은 1이다", () => {
  assert.deepEqual(STRATEGY_WEIGHTS["취향 집중"], { content: 0.8, collaborative: 0.1, quality: 0.1 });
  assert.deepEqual(STRATEGY_WEIGHTS["비슷한 시청자"], { content: 0.1, collaborative: 0.8, quality: 0.1 });
  assert.deepEqual(STRATEGY_WEIGHTS["평론가 추천"], { content: 0.1, collaborative: 0.1, quality: 0.8 });
  for (const weights of Object.values(STRATEGY_WEIGHTS)) {
    assert.ok(Math.abs(weights.content + weights.collaborative + weights.quality - 1) < 1e-12);
  }
});

test("취향 집중과 평론가 추천은 다른 순위를 만든다", () => {
  const taste = engine.recommend({ userId: "USR0003", strategy: "취향 집중", limit: 10 });
  const critics = engine.recommend({ userId: "USR0003", strategy: "평론가 추천", limit: 10 });
  assert.notDeepEqual(
    taste.map((movie) => movie.movie_id),
    critics.map((movie) => movie.movie_id),
  );
});

test("한국어 키워드 검색과 작품 상세 리뷰를 제공한다", () => {
  const search = engine.searchMovies("세탁표");
  assert.ok(search.some((movie) => movie.movie_id === "MOV0001"));
  const detail = engine.movieDetail("MOV0001", "USR0001");
  assert.equal(detail.movie.movie_id, "MOV0001");
  assert.ok(detail.user_reviews.length > 0);
  assert.ok(detail.critic_reviews.length > 0);
  assert.ok(detail.user_reviews.every((review) => Boolean(review.display_name)));
});
