"""ScenePick 추천 전략의 오프라인 평가 로직.

운영 앱은 React와 Node.js로 실행되지만, Databricks의 MLflow 실험 Job에서는
이 모듈로 동일한 추천 공식을 재현한다. 최신 긍정 반응 작품을 사용자별로 한 편씩
숨긴 뒤 과거 데이터만으로 추천하고, 숨긴 작품의 순위를 추천 품질로 측정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd


STRATEGY_WEIGHTS: dict[str, dict[str, float]] = {
    "균형 맞춤": {"content": 0.34, "collaborative": 0.33, "quality": 0.33},
    "취향 집중": {"content": 0.80, "collaborative": 0.10, "quality": 0.10},
    "비슷한 시청자": {"content": 0.10, "collaborative": 0.80, "quality": 0.10},
    "평론가 추천": {"content": 0.10, "collaborative": 0.10, "quality": 0.80},
}


@dataclass(frozen=True)
class HoldoutSplit:
    """시간 분할 결과와 분할 통계를 함께 전달한다."""

    frames: dict[str, pd.DataFrame]
    holdouts: dict[str, str]
    stats: dict[str, int]


def _text(value: Any) -> str:
    """Unity Catalog에서 읽은 null을 빈 문자열로 안전하게 바꾼다."""

    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _number(value: Any, fallback: float = 0.0) -> float:
    """문자열과 null이 섞인 숫자 컬럼을 유한한 실수로 정규화한다."""

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if np.isfinite(parsed) else fallback


def _boolean(value: Any) -> bool:
    """CSV와 Delta에서 올 수 있는 여러 불리언 표현을 하나로 통일한다."""

    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return _text(value).lower() in {"true", "1", "yes", "y"}


def _safe_minmax(values: np.ndarray) -> np.ndarray:
    """모든 값이 같거나 비정상이어도 0~1 점수를 안정적으로 반환한다."""

    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    if values.size == 0:
        return values
    if finite.size == 0:
        return np.zeros_like(values)
    low = float(finite.min())
    high = float(finite.max())
    if high - low < 1e-12:
        return np.full_like(values, 0.5)
    normalized = (values - low) / (high - low)
    return np.clip(np.nan_to_num(normalized), 0.0, 1.0)


def _required_columns(frame: pd.DataFrame, table: str, columns: set[str]) -> None:
    """평가 도중 모호한 오류가 나지 않도록 입력 스키마를 먼저 검사한다."""

    missing = sorted(columns.difference(frame.columns))
    if missing:
        raise ValueError(f"{table} 테이블에 필수 컬럼이 없습니다: {', '.join(missing)}")


def build_temporal_holdout(
    frames: dict[str, pd.DataFrame],
    *,
    holdout_count: int = 1,
    min_train_positive_items: int = 2,
) -> HoldoutSplit:
    """사용자별 최신 긍정 반응을 테스트 정답으로 숨긴다.

    시청 완료 또는 완주율 80% 이상, 평점 4점 이상을 긍정 반응으로 정의한다.
    한 사용자·작품에 이벤트가 여러 개면 가장 최근 시각만 사용한다. 평가 정답으로
    선택한 사용자·작품 쌍은 시청 이력과 관객 리뷰 양쪽 학습 데이터에서 모두 제거해
    정답 정보가 추천 계산에 섞이는 것을 막는다.
    """

    if holdout_count != 1:
        raise ValueError("현재 평가지표는 사용자별 holdout_count=1만 지원합니다.")

    viewing = frames["viewing_history"].copy()
    reviews = frames["user_reviews"].copy()
    users = frames["users"].copy()
    movies = frames["movies"].copy()

    _required_columns(
        viewing,
        "viewing_history",
        {"user_id", "movie_id", "completion_pct", "playback_status", "started_at"},
    )
    _required_columns(reviews, "user_reviews", {"user_id", "movie_id", "rating", "reviewed_at"})
    _required_columns(users, "users", {"user_id"})
    _required_columns(movies, "movies", {"movie_id"})

    valid_users = set(users["user_id"].astype(str))
    valid_movies = set(movies["movie_id"].astype(str))

    viewing_completion = pd.to_numeric(viewing["completion_pct"], errors="coerce").fillna(0.0)
    viewing_completed = viewing["playback_status"].astype(str).str.lower().eq("completed")
    positive_viewing = viewing.loc[viewing_completion.ge(80.0) | viewing_completed, ["user_id", "movie_id", "started_at"]]
    positive_viewing = positive_viewing.rename(columns={"started_at": "event_at"})

    review_rating = pd.to_numeric(reviews["rating"], errors="coerce").fillna(0.0)
    positive_reviews = reviews.loc[review_rating.ge(4.0), ["user_id", "movie_id", "reviewed_at"]]
    positive_reviews = positive_reviews.rename(columns={"reviewed_at": "event_at"})

    positives = pd.concat([positive_viewing, positive_reviews], ignore_index=True)
    positives["user_id"] = positives["user_id"].astype(str)
    positives["movie_id"] = positives["movie_id"].astype(str)
    positives = positives.loc[
        positives["user_id"].isin(valid_users) & positives["movie_id"].isin(valid_movies)
    ].copy()
    positives["event_at"] = pd.to_datetime(positives["event_at"], utc=True, errors="coerce")
    positives = positives.dropna(subset=["event_at"])
    positives = (
        positives.groupby(["user_id", "movie_id"], as_index=False)["event_at"]
        .max()
        .sort_values(["user_id", "event_at", "movie_id"])
    )

    counts = positives.groupby("user_id")["movie_id"].nunique()
    eligible_users = set(counts[counts >= min_train_positive_items + holdout_count].index)
    latest = (
        positives.loc[positives["user_id"].isin(eligible_users)]
        .sort_values(["user_id", "event_at", "movie_id"])
        .groupby("user_id", as_index=False)
        .tail(1)
    )
    holdouts = dict(zip(latest["user_id"], latest["movie_id"], strict=True))
    if not holdouts:
        raise ValueError("시간 분할 조건을 만족하는 사용자가 없어 MLflow 평가를 실행할 수 없습니다.")

    holdout_pairs = set(holdouts.items())

    def remove_holdouts(frame: pd.DataFrame) -> pd.DataFrame:
        pairs = zip(frame["user_id"].astype(str), frame["movie_id"].astype(str))
        keep = [pair not in holdout_pairs for pair in pairs]
        return frame.loc[keep].reset_index(drop=True)

    train_frames = {name: frame.copy() for name, frame in frames.items()}
    train_frames["viewing_history"] = remove_holdouts(viewing)
    train_frames["user_reviews"] = remove_holdouts(reviews)
    stats = {
        "eligible_users": len(holdouts),
        "positive_user_movie_pairs": int(len(positives)),
        "holdout_pairs": len(holdouts),
        "train_viewing_rows": int(len(train_frames["viewing_history"])),
        "train_user_review_rows": int(len(train_frames["user_reviews"])),
    }
    return HoldoutSplit(frames=train_frames, holdouts=holdouts, stats=stats)


class OfflineRecommendationEngine:
    """React 앱의 추천 공식을 NumPy로 재현하는 평가 전용 엔진."""

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames
        self.movies = frames["movies"].drop_duplicates("movie_id").reset_index(drop=True).copy()
        self.users = frames["users"].drop_duplicates("user_id").reset_index(drop=True).copy()
        self.viewing = frames["viewing_history"].copy()
        self.user_reviews = frames["user_reviews"].copy()
        self.critic_reviews = frames["critic_reviews"].copy()

        _required_columns(
            self.movies,
            "movies",
            {
                "movie_id",
                "primary_genre",
                "production_country",
                "original_language",
                "keywords",
                "platform_release_date",
            },
        )
        _required_columns(self.users, "users", {"user_id", "preferred_genre"})
        _required_columns(
            self.viewing,
            "viewing_history",
            {"user_id", "movie_id", "completion_pct", "playback_status", "rewatch_number"},
        )
        _required_columns(self.user_reviews, "user_reviews", {"user_id", "movie_id", "rating"})
        _required_columns(
            self.critic_reviews,
            "critic_reviews",
            {"movie_id", "score_100", "recommended"},
        )

        self.movie_ids = self.movies["movie_id"].astype(str).tolist()
        self.user_ids = self.users["user_id"].astype(str).tolist()
        self.movie_index = {movie_id: index for index, movie_id in enumerate(self.movie_ids)}
        self.user_index = {user_id: index for index, user_id in enumerate(self.user_ids)}
        self.preferred_genre = {
            str(row.user_id): _text(row.preferred_genre).lower() for row in self.users.itertuples()
        }

        self.feature_names, self.feature_matrix = self._build_feature_matrix()
        self.feature_index = {name: index for index, name in enumerate(self.feature_names)}
        self.interaction_matrix = self._build_interaction_matrix()
        self.interaction_norms = np.linalg.norm(self.interaction_matrix, axis=1)
        self.quality_score, self.critic_quality_score = self._build_quality_scores()
        self.watched = self._build_watched_sets()

        release_dates = pd.to_datetime(self.movies["platform_release_date"], errors="coerce")
        self.release_order = release_dates.fillna(pd.Timestamp("1900-01-01")).map(pd.Timestamp.toordinal).to_numpy()

    def _movie_tokens(self, row: Any) -> set[str]:
        tokens = {
            f"genre:{_text(row.primary_genre).lower()}",
            f"language:{_text(row.original_language).lower()}",
            f"country:{_text(row.production_country).lower()}",
        }
        for keyword in _text(row.keywords).split("|"):
            normalized = keyword.strip().lower()
            if normalized:
                tokens.add(f"keyword:{normalized}")
        return tokens

    def _build_feature_matrix(self) -> tuple[list[str], np.ndarray]:
        token_sets = [self._movie_tokens(row) for row in self.movies.itertuples()]
        names = sorted(set().union(*token_sets))
        index = {name: position for position, name in enumerate(names)}
        matrix = np.zeros((len(self.movies), len(names)), dtype=float)
        for row_number, tokens in enumerate(token_sets):
            for token in tokens:
                matrix[row_number, index[token]] = 1.0
        document_frequency = np.maximum(1.0, np.count_nonzero(matrix, axis=0))
        inverse_document_frequency = np.log((1.0 + len(self.movies)) / document_frequency) + 1.0
        matrix *= inverse_document_frequency
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)
        return names, matrix

    def _build_interaction_matrix(self) -> np.ndarray:
        matrix = np.zeros((len(self.users), len(self.movies)), dtype=float)
        history_strength: dict[tuple[str, str], float] = {}
        for row in self.viewing.itertuples():
            user_id, movie_id = str(row.user_id), str(row.movie_id)
            if user_id not in self.user_index or movie_id not in self.movie_index:
                continue
            completion = float(np.clip(_number(row.completion_pct) / 100.0, 0.0, 1.0))
            completed = 1.0 if _text(row.playback_status).lower() == "completed" else 0.0
            rewatch = float(np.clip(_number(row.rewatch_number), 0.0, 2.0) / 2.0)
            strength = float(np.clip(0.15 + 0.65 * completion + 0.15 * completed + 0.05 * rewatch, 0.0, 1.0))
            key = (user_id, movie_id)
            history_strength[key] = max(history_strength.get(key, 0.0), strength)

        review_values: dict[tuple[str, str], list[float]] = {}
        for row in self.user_reviews.itertuples():
            user_id, movie_id = str(row.user_id), str(row.movie_id)
            rating = _number(row.rating, np.nan)
            if user_id not in self.user_index or movie_id not in self.movie_index or not np.isfinite(rating):
                continue
            review_values.setdefault((user_id, movie_id), []).append(float(np.clip(rating / 5.0, 0.0, 1.0)))

        for user_id, movie_id in set(history_strength).union(review_values):
            history = history_strength.get((user_id, movie_id))
            ratings = review_values.get((user_id, movie_id))
            review = float(np.mean(ratings)) if ratings else None
            if history is not None and review is not None:
                strength = 0.65 * history + 0.35 * review
            else:
                strength = history if history is not None else (review or 0.0)
            matrix[self.user_index[user_id], self.movie_index[movie_id]] = strength
        return matrix

    def _build_quality_scores(self) -> tuple[np.ndarray, np.ndarray]:
        view_stats: dict[str, dict[str, float]] = {}
        for row in self.viewing.itertuples():
            movie_id = str(row.movie_id)
            if movie_id not in self.movie_index:
                continue
            stats = view_stats.setdefault(movie_id, {"count": 0.0, "completion": 0.0})
            stats["count"] += 1.0
            stats["completion"] += _number(row.completion_pct)

        audience: dict[str, list[float]] = {}
        for row in self.user_reviews.itertuples():
            movie_id = str(row.movie_id)
            rating = _number(row.rating, np.nan)
            if movie_id in self.movie_index and np.isfinite(rating):
                audience.setdefault(movie_id, []).append(rating)

        critic: dict[str, list[float]] = {}
        for row in self.critic_reviews.itertuples():
            movie_id = str(row.movie_id)
            score = _number(row.score_100, np.nan)
            if movie_id in self.movie_index and np.isfinite(score):
                critic.setdefault(movie_id, []).append(score)

        all_user_ratings = [rating for ratings in audience.values() for rating in ratings]
        all_critic_scores = [score for scores in critic.values() for score in scores]
        global_user = float(np.mean(all_user_ratings)) if all_user_ratings else 3.0
        global_critic = float(np.mean(all_critic_scores)) if all_critic_scores else 60.0
        popularity = _safe_minmax(
            np.array([np.log1p(view_stats.get(movie_id, {}).get("count", 0.0)) for movie_id in self.movie_ids])
        )

        quality = np.zeros(len(self.movies), dtype=float)
        critic_quality = np.zeros(len(self.movies), dtype=float)
        for index, movie_id in enumerate(self.movie_ids):
            user_ratings = audience.get(movie_id, [])
            critic_scores = critic.get(movie_id, [])
            user_count = len(user_ratings)
            critic_count = len(critic_scores)
            user_mean = float(np.mean(user_ratings)) if user_ratings else global_user
            critic_mean = float(np.mean(critic_scores)) if critic_scores else global_critic
            bayesian_user = (user_count * user_mean + 5.0 * global_user) / (user_count + 5.0)
            bayesian_critic = (critic_count * critic_mean + 3.0 * global_critic) / (critic_count + 3.0)
            view = view_stats.get(movie_id, {"count": 0.0, "completion": 0.0})
            avg_completion = view["completion"] / view["count"] if view["count"] else 0.0
            audience_score = bayesian_user / 5.0
            normalized_critic = bayesian_critic / 100.0
            completion_score = float(np.clip(avg_completion / 100.0, 0.0, 1.0))
            quality[index] = (
                0.35 * audience_score
                + 0.25 * normalized_critic
                + 0.25 * completion_score
                + 0.15 * popularity[index]
            )
            critic_quality[index] = (
                0.65 * normalized_critic
                + 0.15 * audience_score
                + 0.10 * completion_score
                + 0.10 * popularity[index]
            )
        return quality, critic_quality

    def _build_watched_sets(self) -> dict[str, set[str]]:
        watched = {user_id: set() for user_id in self.user_ids}
        for frame in (self.viewing, self.user_reviews):
            for row in frame[["user_id", "movie_id"]].itertuples(index=False):
                user_id, movie_id = str(row.user_id), str(row.movie_id)
                if user_id in watched and movie_id in self.movie_index:
                    watched[user_id].add(movie_id)
        return watched

    def _content_scores(self, user_id: str) -> np.ndarray:
        user_position = self.user_index[user_id]
        interactions = self.interaction_matrix[user_position]
        profile = interactions @ self.feature_matrix
        preferred = self.feature_index.get(f"genre:{self.preferred_genre.get(user_id, '')}")
        if preferred is not None:
            profile[preferred] += 2.0
        profile_norm = np.linalg.norm(profile)
        if profile_norm <= 1e-12:
            return np.zeros(len(self.movies), dtype=float)
        return _safe_minmax(self.feature_matrix @ (profile / profile_norm))

    def _collaborative_scores(self, user_id: str) -> np.ndarray:
        user_position = self.user_index[user_id]
        target = self.interaction_matrix[user_position]
        target_norm = self.interaction_norms[user_position]
        if target_norm <= 1e-12:
            return np.zeros(len(self.movies), dtype=float)
        denominator = self.interaction_norms * target_norm
        similarities = np.divide(
            self.interaction_matrix @ target,
            denominator,
            out=np.zeros(len(self.users), dtype=float),
            where=denominator > 0,
        )
        similarities[user_position] = 0.0
        similarities[similarities < 0.08] = 0.0
        similarity_sum = similarities.sum()
        if similarity_sum <= 1e-12:
            return np.zeros(len(self.movies), dtype=float)
        return _safe_minmax((similarities @ self.interaction_matrix) / similarity_sum)

    def recommend(self, user_id: str, strategy: str, top_k: int) -> list[str]:
        """한 사용자에게 학습 이력에 없는 작품을 점수순으로 추천한다."""

        weights = STRATEGY_WEIGHTS[strategy]
        content = self._content_scores(user_id)
        collaborative = self._collaborative_scores(user_id)
        quality = self.critic_quality_score if strategy == "평론가 추천" else self.quality_score
        score = (
            weights["content"] * content
            + weights["collaborative"] * collaborative
            + weights["quality"] * quality
        )
        candidates = [
            index for index, movie_id in enumerate(self.movie_ids) if movie_id not in self.watched[user_id]
        ]
        ranked = sorted(
            candidates,
            key=lambda index: (score[index], quality[index], self.release_order[index], self.movie_ids[index]),
            reverse=True,
        )
        return [self.movie_ids[index] for index in ranked[:top_k]]


def evaluate_strategies(
    frames: dict[str, pd.DataFrame],
    *,
    top_k: int = 10,
    holdout_count: int = 1,
) -> tuple[dict[str, dict[str, float]], dict[str, pd.DataFrame], dict[str, int]]:
    """네 추천 전략을 같은 시간 분할과 지표로 공정하게 비교한다."""

    if not 1 <= top_k <= 50:
        raise ValueError("top_k는 1에서 50 사이여야 합니다.")
    split = build_temporal_holdout(frames, holdout_count=holdout_count)
    engine = OfflineRecommendationEngine(split.frames)
    evaluation_users = sorted(user_id for user_id in split.holdouts if user_id in engine.user_index)
    if not evaluation_users:
        raise ValueError("추천 엔진의 사용자와 시간 분할 사용자가 일치하지 않습니다.")

    summaries: dict[str, dict[str, float]] = {}
    details: dict[str, pd.DataFrame] = {}
    for strategy in STRATEGY_WEIGHTS:
        rows: list[dict[str, Any]] = []
        recommended_catalog: set[str] = set()
        for user_id in evaluation_users:
            started = perf_counter()
            recommendations = engine.recommend(user_id, strategy, top_k)
            latency_ms = (perf_counter() - started) * 1000.0
            recommended_catalog.update(recommendations)
            ground_truth = split.holdouts[user_id]
            rank = recommendations.index(ground_truth) + 1 if ground_truth in recommendations else 0
            hit = 1.0 if rank else 0.0
            rows.append(
                {
                    "strategy": strategy,
                    "user_id": user_id,
                    "ground_truth_movie_id": ground_truth,
                    "ground_truth_rank": rank,
                    "hit_at_k": hit,
                    "precision_at_k": hit / top_k,
                    "recall_at_k": hit,
                    "ndcg_at_k": 1.0 / np.log2(rank + 1.0) if rank else 0.0,
                    "reciprocal_rank": 1.0 / rank if rank else 0.0,
                    "latency_ms": latency_ms,
                    "recommended_movie_ids": "|".join(recommendations),
                }
            )
        detail = pd.DataFrame(rows)
        latency = detail["latency_ms"].to_numpy(dtype=float)
        summaries[strategy] = {
            "precision_at_k": float(detail["precision_at_k"].mean()),
            "recall_at_k": float(detail["recall_at_k"].mean()),
            "hit_rate_at_k": float(detail["hit_at_k"].mean()),
            "ndcg_at_k": float(detail["ndcg_at_k"].mean()),
            "mrr_at_k": float(detail["reciprocal_rank"].mean()),
            "catalog_coverage": len(recommended_catalog) / max(1, len(engine.movie_ids)),
            "latency_mean_ms": float(latency.mean()),
            "latency_p50_ms": float(np.percentile(latency, 50)),
            "latency_p95_ms": float(np.percentile(latency, 95)),
            "evaluated_users": float(len(detail)),
            "top_k": float(top_k),
        }
        details[strategy] = detail
    return summaries, details, split.stats
