"""ScenePick의 인메모리 하이브리드 영화 추천 엔진이다.

이 모듈은 제공된 6개 CSV를 검증·정규화한 뒤 다음 세 신호를 결합한다.

1. 콘텐츠 유사도: 사용자가 본 작품의 장르·언어·국가·키워드와 후보의 유사도
2. 협업 점수: 시청 행동이 비슷한 다른 사용자가 후보 작품에 보인 만족도
3. 품질 점수: 관객/평론가 평가, 완주율, 시청량을 평활화한 작품 자체의 품질

데모 데이터 규모가 작기 때문에 별도 모델 서버나 벡터 DB 없이 NumPy 배열과
Pandas DataFrame을 앱 프로세스 메모리에 유지한다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# 전략별 튜플은 순서대로 (콘텐츠, 협업, 품질) 가중치다. 각 튜플의 합은 1이며,
# 화면의 전략 라디오 버튼도 이 딕셔너리의 키를 그대로 선택지로 사용한다.
STRATEGY_WEIGHTS = {
    "균형 맞춤": (0.34, 0.33, 0.33),
    "취향 집중": (0.80, 0.10, 0.10),
    "비슷한 시청자": (0.10, 0.80, 0.10),
    "평론가 추천": (0.10, 0.10, 0.80),
}


# 앱이 정상 계산에 필요로 하는 CSV별 최소 컬럼 계약이다. CSV에 이보다 많은 컬럼이
# 있어도 허용하지만, 아래 필수 컬럼 중 하나라도 없으면 시작 단계에서 명확히 실패한다.
REQUIRED_COLUMNS = {
    "movies": {
        "movie_id",
        "title",
        "primary_genre",
        "genre_detail",
        "production_country",
        "original_language",
        "runtime_minutes",
        "content_rating",
        "director_name",
        "studio_name",
        "platform_release_date",
        "is_platform_original",
        "setting",
        "protagonist",
        "keywords",
        "logline",
    },
    "users": {
        "user_id",
        "display_name",
        "preferred_genre",
        "subscription_plan",
        "preferred_device",
        "watch_time_preference",
        "account_status",
    },
    "viewing_history": {
        "viewing_id",
        "user_id",
        "movie_id",
        "completion_pct",
        "playback_status",
        "rewatch_number",
    },
    "user_reviews": {
        "user_id",
        "movie_id",
        "rating",
        "review_title",
        "review_text",
        "reviewed_at",
    },
    "critic_reviews": {
        "critic_id",
        "movie_id",
        "score_100",
        "review_title",
        "review_text",
        "reviewed_at",
        "recommended",
    },
    "critics": {"critic_id", "pen_name", "publication_name", "is_top_critic"},
}


class RecommendationDataError(ValueError):
    """필수 CSV 또는 필수 컬럼이 없어 추천 데이터 계약을 만족하지 못할 때 발생한다."""


@dataclass(frozen=True)
class RecommendationData:
    """검증과 타입 정규화를 마친 6개 원본 데이터셋의 불변 컨테이너다.

    ``frozen=True``는 DataFrame 객체 자체의 수정을 완전히 막지는 않지만, 로딩 후
    각 속성을 다른 DataFrame으로 실수로 재할당하는 문제를 방지한다.
    """

    movies: pd.DataFrame
    users: pd.DataFrame
    viewing_history: pd.DataFrame
    user_reviews: pd.DataFrame
    critic_reviews: pd.DataFrame
    critics: pd.DataFrame


def _as_bool(series: pd.Series) -> pd.Series:
    """CSV의 다양한 불리언 표기(true/1/yes/y)를 대소문자 무관 Boolean으로 바꾼다."""

    return series.astype(str).str.strip().str.casefold().isin({"true", "1", "yes", "y"})


def _safe_minmax(values: pd.Series | np.ndarray) -> np.ndarray:
    """숫자 배열을 0~1 범위로 정규화하면서 빈 배열·NaN·상수 배열을 안전 처리한다.

    모든 값이 같으면 특정 작품만 유리해지지 않도록 중립값 0.5를 반환하고,
    유한하지 않은 값은 최저점인 0으로 처리한다.
    """

    array = np.asarray(values, dtype=float)
    if array.size == 0:
        return array
    finite = np.isfinite(array)
    if not finite.any():
        return np.zeros_like(array)
    low = float(np.nanmin(array[finite]))
    high = float(np.nanmax(array[finite]))
    if high - low < 1e-12:
        return np.full_like(array, 0.5)
    result = (array - low) / (high - low)
    result[~finite] = 0.0
    return np.clip(result, 0.0, 1.0)


def load_recommendation_data(data_dir: str | Path) -> RecommendationData:
    """지정한 폴더의 6개 CSV를 읽고 스키마와 계산용 타입을 검증한다.

    파일 존재 여부와 필수 컬럼을 먼저 확인해 추천 계산 중간의 모호한 KeyError를
    방지한다. 날짜·숫자·불리언 컬럼은 CSV 문자열 표현에서 명시적 타입으로 바꾼다.
    """

    data_path = Path(data_dir)
    frames: dict[str, pd.DataFrame] = {}

    # REQUIRED_COLUMNS의 키는 파일명(확장자 제외)과 RecommendationData 속성명에 맞춘다.
    for name, required in REQUIRED_COLUMNS.items():
        csv_path = data_path / f"{name}.csv"
        if not csv_path.exists():
            raise RecommendationDataError(
                f"필수 데이터 파일이 없습니다: {csv_path.name}"
            )
        # 원본 파일은 변경하지 않고 DataFrame으로 읽은 뒤 메모리에서만 정규화한다.
        frame = pd.read_csv(csv_path)
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise RecommendationDataError(
                f"{csv_path.name}에 필수 컬럼이 없습니다: {', '.join(missing)}"
            )
        frames[name] = frame

    # 숫자 변환 실패는 NaN으로 두어 이후 통계/필터가 비정상 문자열 때문에 중단되지 않게 한다.
    movies = frames["movies"].copy()
    movies["runtime_minutes"] = pd.to_numeric(
        movies["runtime_minutes"], errors="coerce"
    )
    movies["is_platform_original"] = _as_bool(movies["is_platform_original"])
    movies["platform_release_date"] = pd.to_datetime(
        movies["platform_release_date"], errors="coerce"
    )

    viewing_history = frames["viewing_history"].copy()
    viewing_history["completion_pct"] = pd.to_numeric(
        viewing_history["completion_pct"], errors="coerce"
    ).fillna(0.0)
    viewing_history["rewatch_number"] = pd.to_numeric(
        viewing_history["rewatch_number"], errors="coerce"
    ).fillna(0.0)

    user_reviews = frames["user_reviews"].copy()
    user_reviews["rating"] = pd.to_numeric(user_reviews["rating"], errors="coerce")

    critic_reviews = frames["critic_reviews"].copy()
    critic_reviews["score_100"] = pd.to_numeric(
        critic_reviews["score_100"], errors="coerce"
    )
    critic_reviews["recommended"] = _as_bool(critic_reviews["recommended"])

    critics = frames["critics"].copy()
    critics["is_top_critic"] = _as_bool(critics["is_top_critic"])

    # 타입 변환이 끝난 프레임만 하나의 데이터 객체로 묶어 엔진에 전달한다.
    return RecommendationData(
        movies=movies,
        users=frames["users"].copy(),
        viewing_history=viewing_history,
        user_reviews=user_reviews,
        critic_reviews=critic_reviews,
        critics=critics,
    )


class RecommendationEngine:
    """배포된 데모 CSV 규모에 맞춘 인메모리 하이브리드 추천기다."""

    def __init__(self, data: RecommendationData):
        """데이터를 보관하고 추천 요청에 반복 사용될 통계와 행렬을 미리 계산한다."""

        self.data = data

        # ID별 한 행만 유지하고 순서를 고정한다. 이 순서는 이후 모든 NumPy 행렬의
        # 행/열 인덱스와 연결되므로 movie_ids/user_ids와 함께 일관되게 사용해야 한다.
        self.movies = data.movies.drop_duplicates("movie_id").reset_index(drop=True)
        self.users = data.users.drop_duplicates("user_id").reset_index(drop=True)
        self.movie_ids = self.movies["movie_id"].astype(str).tolist()
        self.user_ids = self.users["user_id"].astype(str).tolist()
        self.movie_index = {
            movie_id: index for index, movie_id in enumerate(self.movie_ids)
        }
        self.user_index = {
            user_id: index for index, user_id in enumerate(self.user_ids)
        }

        # 앱 시작 시 비용이 큰 집계와 행렬 생성을 한 번 수행해 사용자 요청 응답을 빠르게 한다.
        self.movie_stats = self._build_movie_stats()
        self.feature_names, self.feature_matrix = self._build_feature_matrix()
        self.interaction_matrix = self._build_interaction_matrix()

    @classmethod
    def from_csv_dir(cls, data_dir: str | Path) -> RecommendationEngine:
        """CSV 폴더를 검증·로딩하고 즉시 사용할 수 있는 엔진을 생성한다."""

        return cls(load_recommendation_data(data_dir))

    @property
    def genres(self) -> list[str]:
        """영화 데이터에 실제 존재하는 장르를 중복 없이 정렬해 반환한다."""

        return sorted(
            self.movies["primary_genre"].dropna().astype(str).unique().tolist()
        )

    def _build_movie_stats(self) -> pd.DataFrame:
        """작품별 시청·관객·평론가 통계를 집계하고 품질 점수를 계산한다."""

        history = self.data.viewing_history

        # 한 작품에 대한 총 시청 수, 평균 완주율, 완주/재시청 횟수를 행동 품질로 사용한다.
        viewing = history.groupby("movie_id", as_index=False).agg(
            view_count=("viewing_id", "count"),
            avg_completion_pct=("completion_pct", "mean"),
            completed_view_count=(
                "playback_status",
                lambda values: int(
                    values.astype(str).str.casefold().eq("completed").sum()
                ),
            ),
            rewatch_count=("rewatch_number", lambda values: int((values > 0).sum())),
        )

        # 관객과 평론가 평가는 평균뿐 아니라 표본 수를 함께 보존해 베이지안 평활화에 쓴다.
        audience = self.data.user_reviews.groupby("movie_id", as_index=False).agg(
            user_rating=("rating", "mean"), user_review_count=("rating", "count")
        )
        critics = self.data.critic_reviews.groupby("movie_id", as_index=False).agg(
            critic_score=("score_100", "mean"),
            critic_review_count=("score_100", "count"),
            critic_recommend_rate=("recommended", "mean"),
        )

        # 리뷰나 시청 이력이 전혀 없는 작품도 후보에서 사라지지 않도록 left join한다.
        stats = self.movies[["movie_id"]].merge(viewing, on="movie_id", how="left")
        stats = stats.merge(audience, on="movie_id", how="left")
        stats = stats.merge(critics, on="movie_id", how="left")

        numeric_columns = [
            "view_count",
            "avg_completion_pct",
            "completed_view_count",
            "rewatch_count",
            "user_review_count",
            "critic_review_count",
            "critic_recommend_rate",
        ]
        stats[numeric_columns] = stats[numeric_columns].fillna(0.0)

        # 리뷰가 적은 작품의 극단적인 평균이 과대평가되지 않도록 전체 평균을 사전값으로
        # 섞는다. 관객은 가상 리뷰 5개, 평론가는 가상 리뷰 3개의 강도로 평활화한다.
        global_user_rating = float(self.data.user_reviews["rating"].mean())
        global_critic_score = float(self.data.critic_reviews["score_100"].mean())
        stats["bayesian_user_score"] = (
            stats["user_review_count"] * stats["user_rating"].fillna(global_user_rating)
            + 5.0 * global_user_rating
        ) / (stats["user_review_count"] + 5.0)
        stats["bayesian_critic_score"] = (
            stats["critic_review_count"]
            * stats["critic_score"].fillna(global_critic_score)
            + 3.0 * global_critic_score
        ) / (stats["critic_review_count"] + 3.0)
        # 시청 수는 긴 꼬리 분포를 완화하기 위해 log1p 후 0~1로 정규화한다.
        stats["popularity_score"] = _safe_minmax(np.log1p(stats["view_count"]))

        # 서로 다른 단위(5점, 100점, 백분율)를 모두 0~1 범위로 맞춘 뒤 결합한다.
        audience_score = stats["bayesian_user_score"] / 5.0
        critic_score = stats["bayesian_critic_score"] / 100.0
        completion_score = (stats["avg_completion_pct"] / 100.0).clip(0, 1)
        stats["quality_score"] = (
            0.35 * audience_score
            + 0.25 * critic_score
            + 0.25 * completion_score
            + 0.15 * stats["popularity_score"]
        )
        # 평론가 추천 전략은 평론가 점수 비중을 65%로 높인 별도 품질 축을 사용한다.
        stats["critic_quality_score"] = (
            0.65 * critic_score
            + 0.15 * audience_score
            + 0.10 * completion_score
            + 0.10 * stats["popularity_score"]
        )
        return stats.set_index("movie_id", drop=False)

    @staticmethod
    def _movie_tokens(row: pd.Series) -> set[str]:
        """영화 한 편을 장르·언어·국가·키워드 토큰 집합으로 변환한다."""

        tokens = {
            f"genre:{str(row['primary_genre']).strip().casefold()}",
            f"language:{str(row['original_language']).strip().casefold()}",
            f"country:{str(row['production_country']).strip().casefold()}",
        }
        for keyword in str(row.get("keywords", "")).split("|"):
            normalized = keyword.strip().casefold()
            if normalized:
                tokens.add(f"keyword:{normalized}")
        return tokens

    def _build_feature_matrix(self) -> tuple[list[str], np.ndarray]:
        """작품 토큰을 IDF 가중치와 L2 정규화를 적용한 콘텐츠 특성 행렬로 만든다.

        행은 영화, 열은 특성 토큰이다. 흔한 특성은 낮게, 드문 특성은 높게 반영하며
        각 영화 벡터의 길이를 1로 맞춰 내적을 코사인 유사도처럼 사용할 수 있게 한다.
        """

        token_sets = [self._movie_tokens(row) for _, row in self.movies.iterrows()]
        feature_names = sorted(set().union(*token_sets))
        feature_index = {name: index for index, name in enumerate(feature_names)}
        matrix = np.zeros((len(self.movies), len(feature_names)), dtype=float)
        for row_index, tokens in enumerate(token_sets):
            for token in tokens:
                matrix[row_index, feature_index[token]] = 1.0

        # IDF는 많은 작품에 공통으로 등장하는 토큰의 구분력을 낮춘다.
        document_frequency = np.maximum(matrix.sum(axis=0), 1.0)
        inverse_document_frequency = (
            np.log((1.0 + len(self.movies)) / document_frequency) + 1.0
        )
        matrix *= inverse_document_frequency
        # 0 벡터에서 나눗셈이 일어나지 않도록 where 조건과 0 출력 버퍼를 사용한다.
        row_norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = np.divide(
            matrix, row_norms, out=np.zeros_like(matrix), where=row_norms > 0
        )
        return feature_names, matrix

    def _build_interaction_matrix(self) -> np.ndarray:
        """시청 행동과 관객 평점을 사용자×영화 만족도 행렬로 결합한다.

        시청 이력은 완주율을 가장 크게 보고 완주 상태와 재시청을 보조 신호로 쓴다.
        같은 사용자·영화 조합이 여러 번 있으면 가장 강한 행동을 대표값으로 사용한다.
        """

        history = self.data.viewing_history.copy()
        completion = (history["completion_pct"] / 100.0).clip(0.0, 1.0)
        completed = (
            history["playback_status"]
            .astype(str)
            .str.casefold()
            .eq("completed")
            .astype(float)
        )
        rewatch = history["rewatch_number"].clip(0, 2) / 2.0
        # 0.15의 기본값은 재생을 시작한 행위 자체를 약한 관심 신호로 인정한다.
        history["interaction_strength"] = (
            0.15 + 0.65 * completion + 0.15 * completed + 0.05 * rewatch
        ).clip(0.0, 1.0)
        history_scores = history.groupby(["user_id", "movie_id"], as_index=False)[
            "interaction_strength"
        ].max()

        # 5점 평점을 0~1로 변환하고, 시청 이력과 리뷰가 모두 있으면 65:35로 결합한다.
        reviews = self.data.user_reviews[["user_id", "movie_id", "rating"]].copy()
        reviews["review_strength"] = (reviews["rating"] / 5.0).clip(0.0, 1.0)
        combined = history_scores.merge(
            reviews, on=["user_id", "movie_id"], how="outer"
        )
        has_history = combined["interaction_strength"].notna()
        has_review = combined["review_strength"].notna()
        combined["strength"] = combined["interaction_strength"].fillna(0.0)
        both = has_history & has_review
        combined.loc[both, "strength"] = (
            0.65 * combined.loc[both, "interaction_strength"]
            + 0.35 * combined.loc[both, "review_strength"]
        )
        combined.loc[~has_history & has_review, "strength"] = combined.loc[
            ~has_history & has_review, "review_strength"
        ]

        # 문자열 ID를 미리 만든 정수 인덱스로 변환해 조밀한 NumPy 행렬에 기록한다.
        matrix = np.zeros((len(self.user_ids), len(self.movie_ids)), dtype=float)
        for row in combined.itertuples(index=False):
            user_index = self.user_index.get(str(row.user_id))
            movie_index = self.movie_index.get(str(row.movie_id))
            if user_index is not None and movie_index is not None:
                matrix[user_index, movie_index] = float(row.strength)
        return matrix

    def _content_scores(self, user_id: str) -> np.ndarray:
        """사용자의 과거 만족도와 선호 장르로 콘텐츠 기반 후보 점수를 계산한다."""

        user_row = self.users.loc[self.users["user_id"].eq(user_id)].iloc[0]
        user_vector = self.interaction_matrix[self.user_index[user_id]]

        # 사용자의 영화별 만족도를 가중치로 삼아 본 작품의 특성 벡터를 합산한다.
        profile = user_vector @ self.feature_matrix

        # 가입 프로필에 명시된 선호 장르는 시청 이력이 적은 사용자도 추천을 받을 수
        # 있도록 사용자 콘텐츠 벡터에 추가 가중치 2.0을 준다.
        preferred_token = f"genre:{str(user_row['preferred_genre']).strip().casefold()}"
        if preferred_token in self.feature_names:
            profile[self.feature_names.index(preferred_token)] += 2.0

        profile_norm = np.linalg.norm(profile)
        if profile_norm <= 1e-12:
            return np.zeros(len(self.movie_ids), dtype=float)
        # 영화 벡터와 정규화된 사용자 벡터의 내적으로 유사도를 구하고 0~1로 맞춘다.
        raw_scores = self.feature_matrix @ (profile / profile_norm)
        return _safe_minmax(raw_scores)

    def _collaborative_scores(self, user_id: str) -> np.ndarray:
        """행동 벡터가 비슷한 사용자들의 만족도를 이용해 협업 점수를 계산한다."""

        target_index = self.user_index[user_id]
        target = self.interaction_matrix[target_index]
        target_norm = np.linalg.norm(target)
        if target_norm <= 1e-12:
            return np.zeros(len(self.movie_ids), dtype=float)

        # 대상 사용자와 모든 사용자의 코사인 유사도를 한 번의 행렬 연산으로 구한다.
        norms = np.linalg.norm(self.interaction_matrix, axis=1)
        similarities = np.divide(
            self.interaction_matrix @ target,
            norms * target_norm,
            out=np.zeros(len(self.user_ids), dtype=float),
            where=norms > 0,
        )
        # 자기 자신은 이웃에서 제외하고, 0.08 미만의 약한 유사도는 잡음으로 제거한다.
        similarities[target_index] = 0.0
        similarities[similarities < 0.08] = 0.0
        if similarities.sum() <= 1e-12:
            return np.zeros(len(self.movie_ids), dtype=float)

        # 각 이웃의 영화 만족도를 사용자 유사도로 가중 평균한다.
        raw_scores = similarities @ self.interaction_matrix / similarities.sum()
        return _safe_minmax(raw_scores)

    def watched_movie_ids(self, user_id: str) -> set[str]:
        """시청 이력 또는 리뷰가 있는 작품 ID를 합쳐 이미 경험한 작품으로 간주한다."""

        history_ids = set(
            self.data.viewing_history.loc[
                self.data.viewing_history["user_id"].eq(user_id), "movie_id"
            ].astype(str)
        )
        review_ids = set(
            self.data.user_reviews.loc[
                self.data.user_reviews["user_id"].eq(user_id), "movie_id"
            ].astype(str)
        )
        return history_ids.union(review_ids)

    def _top_profile_genres(self, user_id: str, limit: int = 3) -> list[str]:
        """완주율을 가중치로 사용해 사용자의 상위 장르를 최대 ``limit``개 찾는다."""

        user_history = self.data.viewing_history.loc[
            self.data.viewing_history["user_id"].eq(user_id),
            ["movie_id", "completion_pct"],
        ].merge(self.movies[["movie_id", "primary_genre"]], on="movie_id", how="left")
        # 시청 기록이 없는 신규 사용자는 가입 프로필의 선호 장르를 콜드 스타트 값으로 쓴다.
        if user_history.empty:
            preferred = self.users.loc[
                self.users["user_id"].eq(user_id), "preferred_genre"
            ].iloc[0]
            return [str(preferred)]
        # 단순 시청 횟수 대신 완주율을 합산해 오래 본 장르가 위로 오도록 한다.
        weights = user_history.assign(
            weight=user_history["completion_pct"].clip(0, 100) / 100.0
        )
        ranked = (
            weights.groupby("primary_genre")["weight"]
            .sum()
            .sort_values(ascending=False)
        )
        return ranked.head(limit).index.astype(str).tolist()

    def _recommendation_reason(
        self,
        user_id: str,
        movie_row: pd.Series,
        content_score: float,
        collaborative_score: float,
        quality_score: float,
    ) -> str:
        """상위 점수 신호를 사람이 읽을 수 있는 짧은 추천 근거로 변환한다.

        최대 두 개만 노출해 표가 지나치게 길어지는 것을 막는다. 어떤 강한 신호도
        임계값을 넘지 못하면 세 요소가 고르게 우수하다는 기본 설명을 사용한다.
        """

        reasons: list[str] = []
        top_genres = self._top_profile_genres(user_id)
        if str(movie_row["primary_genre"]) in top_genres:
            reasons.append(f"선호 패턴의 {movie_row['primary_genre']}")
        if collaborative_score >= 0.55:
            reasons.append("비슷한 시청자가 높게 평가")
        if quality_score >= 0.72:
            critic_score = self.movie_stats.loc[
                movie_row["movie_id"], "bayesian_critic_score"
            ]
            reasons.append(f"평론가 {critic_score:.0f}점대")
        if bool(movie_row["is_platform_original"]):
            reasons.append("플랫폼 오리지널")
        if content_score >= 0.70 and not reasons:
            reasons.append("시청 취향 키워드와 높은 일치")
        if not reasons:
            reasons.append("취향·반응·품질 지표가 고르게 우수")
        return " · ".join(reasons[:2])

    def recommend(
        self,
        user_id: str,
        strategy: str = "균형 맞춤",
        genre: str = "전체",
        max_runtime: int | None = None,
        content_rating: str = "전체",
        limit: int = 10,
        include_watched: bool = False,
    ) -> pd.DataFrame:
        """사용자와 필터 조건에 맞는 개인화 추천 결과를 점수순으로 반환한다.

        최종 점수는 선택 전략의 가중치에 따라 콘텐츠·협업·품질 점수를 결합한
        0~100 값이다. 이미 본 작품, 장르, 등급, 상영 시간 필터는 점수 계산 후
        적용하며 결과 수는 안전을 위해 1~50개 범위로 제한한다. ``max_runtime``은
        명시적으로 전달된 경우에만 적용되므로 앱의 기본 추천에는 상영 시간 제한이 없다.
        """

        # 사용자 ID는 행렬 인덱스와 연결되므로 존재하지 않으면 즉시 명확한 오류를 낸다.
        if user_id not in self.user_index:
            raise ValueError(f"알 수 없는 사용자입니다: {user_id}")
        if strategy not in STRATEGY_WEIGHTS:
            strategy = "균형 맞춤"

        # 모든 영화에 대해 세 독립 점수 축을 같은 순서의 NumPy 배열로 만든다.
        content_scores = self._content_scores(user_id)
        collaborative_scores = self._collaborative_scores(user_id)
        # 평론가 전략만 평론가 비중이 강화된 품질 점수를 사용한다.
        quality_column = (
            "critic_quality_score" if strategy == "평론가 추천" else "quality_score"
        )
        quality_scores = self.movie_stats.loc[self.movie_ids, quality_column].to_numpy(
            dtype=float
        )
        content_weight, collaborative_weight, quality_weight = STRATEGY_WEIGHTS[
            strategy
        ]
        # STRATEGY_WEIGHTS의 세 가중치 합이 1이므로 최종 점수도 0~1 범위를 유지한다.
        final_scores = (
            content_weight * content_scores
            + collaborative_weight * collaborative_scores
            + quality_weight * quality_scores
        )

        # 화면 표시와 추천 이유 생성에 필요한 구성 점수와 작품 통계를 한 표에 합친다.
        results = self.movies.copy()
        results["content_score"] = content_scores
        results["collaborative_score"] = collaborative_scores
        results["quality_component"] = quality_scores
        results["recommendation_score"] = final_scores * 100.0
        results = results.merge(
            self.movie_stats.reset_index(drop=True),
            on="movie_id",
            how="left",
            suffixes=("", "_stats"),
        )

        # 개인화 점수를 보존한 상태에서 사용자가 선택한 후보 조건을 순차적으로 적용한다.
        if not include_watched:
            results = results.loc[
                ~results["movie_id"].isin(self.watched_movie_ids(user_id))
            ]
        if genre != "전체":
            results = results.loc[results["primary_genre"].eq(genre)]
        if content_rating != "전체":
            results = results.loc[results["content_rating"].eq(content_rating)]
        if max_runtime is not None:
            results = results.loc[
                results["runtime_minutes"].le(max(1, int(max_runtime)))
            ]

        if results.empty:
            return results

        # 동점이면 품질과 최신 공개일을 보조 정렬 기준으로 사용해 결과를 안정화한다.
        results = results.sort_values(
            ["recommendation_score", "quality_component", "platform_release_date"],
            ascending=[False, False, False],
        ).head(max(1, min(int(limit), 50)))
        results = results.copy()
        # 최종 후보에만 설명을 생성해 불필요한 전체 영화 행 단위 연산을 줄인다.
        results["recommendation_reason"] = results.apply(
            lambda row: self._recommendation_reason(
                user_id,
                row,
                float(row["content_score"]),
                float(row["collaborative_score"]),
                float(row["quality_component"]),
            ),
            axis=1,
        )
        results.insert(0, "rank", range(1, len(results) + 1))
        return results.reset_index(drop=True)

    def user_summary(self, user_id: str) -> dict[str, object]:
        """프로필 카드에 표시할 사용자 메타데이터와 시청/평점 요약을 반환한다."""

        if user_id not in self.user_index:
            raise ValueError(f"알 수 없는 사용자입니다: {user_id}")
        user = self.users.loc[self.users["user_id"].eq(user_id)].iloc[0]
        history = self.data.viewing_history.loc[
            self.data.viewing_history["user_id"].eq(user_id)
        ]
        reviews = self.data.user_reviews.loc[
            self.data.user_reviews["user_id"].eq(user_id)
        ]
        # 기록이 없는 사용자는 평균 완주율 0, 평균 평점 None으로 명시한다.
        return {
            "user_id": user_id,
            "display_name": str(user["display_name"]),
            "preferred_genre": str(user["preferred_genre"]),
            "top_genres": self._top_profile_genres(user_id),
            "subscription_plan": str(user["subscription_plan"]),
            "preferred_device": str(user["preferred_device"]),
            "watch_time_preference": str(user["watch_time_preference"]),
            "watched_count": int(history["movie_id"].nunique()),
            "completed_count": int(
                history["playback_status"]
                .astype(str)
                .str.casefold()
                .eq("completed")
                .sum()
            ),
            "average_completion": float(history["completion_pct"].mean())
            if not history.empty
            else 0.0,
            "average_rating": float(reviews["rating"].mean())
            if not reviews.empty
            else None,
        }

    def movie_detail(
        self, movie_id: str, user_id: str | None = None
    ) -> dict[str, object]:
        """작품 메타정보, 집계 통계, 전체 관객·평론가 리뷰와 사용자 경험을 반환한다."""

        if movie_id not in self.movie_index:
            raise ValueError(f"알 수 없는 작품입니다: {movie_id}")
        movie = self.movies.loc[self.movies["movie_id"].eq(movie_id)].iloc[0]
        stats = self.movie_stats.loc[movie_id]
        # 평론가 기본 정보를 리뷰에 붙인 뒤 Top Critic, 고득점, 최신 작성일 순으로 정렬한다.
        critic_reviews = self.data.critic_reviews.loc[
            self.data.critic_reviews["movie_id"].eq(movie_id)
        ].merge(
            self.data.critics[
                ["critic_id", "pen_name", "publication_name", "is_top_critic"]
            ],
            on="critic_id",
            how="left",
        )
        critic_reviews = critic_reviews.sort_values(
            ["is_top_critic", "score_100", "reviewed_at"],
            ascending=[False, False, False],
        )

        # 관객 리뷰에는 작성자의 표시 이름을 붙이고 최신 리뷰부터 보여준다.
        audience_reviews = self.data.user_reviews.loc[
            self.data.user_reviews["movie_id"].eq(movie_id)
        ].merge(
            self.users[["user_id", "display_name"]],
            on="user_id",
            how="left",
        )
        audience_reviews = audience_reviews.sort_values(
            ["reviewed_at", "rating"], ascending=[False, False]
        )

        # user_id가 전달된 경우에만 해당 사용자의 이전 완주율과 평점을 함께 조회한다.
        user_history = pd.DataFrame()
        user_review = pd.DataFrame()
        if user_id:
            user_history = self.data.viewing_history.loc[
                self.data.viewing_history["user_id"].eq(user_id)
                & self.data.viewing_history["movie_id"].eq(movie_id)
            ]
            user_review = self.data.user_reviews.loc[
                self.data.user_reviews["user_id"].eq(user_id)
                & self.data.user_reviews["movie_id"].eq(movie_id)
            ]

        return {
            "movie": movie.to_dict(),
            "stats": stats.to_dict(),
            "user_reviews": audience_reviews.to_dict("records"),
            "critic_reviews": critic_reviews.to_dict("records"),
            "watched_by_user": not user_history.empty,
            "user_completion": (
                float(user_history["completion_pct"].max())
                if not user_history.empty
                else None
            ),
            "user_rating": float(user_review["rating"].iloc[0])
            if not user_review.empty
            else None,
        }

    def search_movies(
        self, query: str = "", genre: str = "전체", limit: int = 30
    ) -> pd.DataFrame:
        """여러 텍스트 컬럼을 통합 검색하고 장르로 필터링한 작품 목록을 반환한다.

        정규식 해석을 끄고 대소문자를 접어 사용자가 입력한 문자를 그대로 부분
        검색한다. 검색 결과 수는 과도한 화면 렌더링을 막기 위해 최대 100개다.
        """

        results = self.movies.copy()

        # 연속 공백과 대소문자 차이를 제거해 검색어 비교를 안정화한다.
        normalized_query = " ".join(str(query or "").casefold().split())
        if normalized_query:
            searchable_columns: Iterable[str] = (
                "title",
                "keywords",
                "logline",
                "director_name",
                "setting",
                "protagonist",
            )
            # 제목·키워드·로그라인·감독·배경·주인공을 한 문자열로 합쳐 한 번에 검색한다.
            search_text = (
                results[list(searchable_columns)]
                .fillna("")
                .agg(" ".join, axis=1)
                .str.casefold()
            )
            results = results.loc[
                search_text.str.contains(normalized_query, regex=False)
            ]
        if genre != "전체":
            results = results.loc[results["primary_genre"].eq(genre)]

        # 검색 결과는 개인화가 아닌 전체 품질 점수와 공개일 순으로 정렬한다.
        results = results.merge(
            self.movie_stats.reset_index(drop=True),
            on="movie_id",
            how="left",
            suffixes=("", "_stats"),
        )
        return (
            results.sort_values(
                ["quality_score", "platform_release_date"], ascending=[False, False]
            )
            .head(max(1, min(int(limit), 100)))
            .reset_index(drop=True)
        )

    def data_summary(self) -> dict[str, int]:
        """앱 상단 통계 배지에 표시할 데이터셋별 행 수를 반환한다."""

        return {
            "movie_count": len(self.movies),
            "user_count": len(self.users),
            "viewing_count": len(self.data.viewing_history),
            "user_review_count": len(self.data.user_reviews),
            "critic_count": len(self.data.critics),
            "critic_review_count": len(self.data.critic_reviews),
        }
