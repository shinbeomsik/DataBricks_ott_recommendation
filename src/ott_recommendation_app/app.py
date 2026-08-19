"""ScenePick OTT 추천 서비스의 Gradio 화면과 사용자 이벤트를 구성한다.

Databricks Apps 런타임은 ``app.yaml``의 명령에 따라 이 파일을 실행한다.
모듈을 불러오는 시점에 배포 소스의 ``data`` 폴더에서 CSV를 읽어 추천 엔진을
한 번 초기화하고, 이후 사용자의 클릭·검색 이벤트에서는 이미 준비된 엔진을
재사용한다. 따라서 요청마다 CSV를 다시 읽지 않는다.
"""

from __future__ import annotations

import html
import os
from pathlib import Path

import gradio as gr
import pandas as pd
from recommendation_engine import STRATEGY_WEIGHTS, RecommendationEngine

# 실행 파일의 절대 위치를 기준으로 데이터 경로를 계산한다. 이렇게 하면 로컬과
# Databricks Apps에서 현재 작업 디렉터리가 달라도 같은 CSV를 찾을 수 있다.
APP_DIR = Path(__file__).resolve().parent

# 현재 앱 런타임은 앱 소스에 함께 배포된 CSV를 메모리로 읽는다. Unity Catalog의
# Delta 테이블은 별도로 적재되어 있으며, 앱을 UC 직접 조회 방식으로 전환하기
# 전까지 이 로컬 복사본이 추천 계산의 입력 데이터다.
ENGINE = RecommendationEngine.from_csv_dir(APP_DIR / "data")


# 데이터에 저장된 영문 장르 코드는 추천 엔진의 필터 값으로 유지하고,
# 화면에는 사용자가 이해하기 쉬운 한글명을 함께 표시한다.
GENRE_LABELS = {
    "Action": "액션",
    "Animation": "애니메이션",
    "Comedy": "코미디",
    "Documentary": "다큐멘터리",
    "Drama": "드라마",
    "Fantasy": "판타지",
    "Horror": "공포",
    "Romance": "로맨스",
    "Science Fiction": "SF",
    "Thriller": "스릴러",
}

# 사용자 프로필의 코드값을 화면에 표시할 한글 라벨로 변환하는 사전이다.
DEVICE_LABELS = {
    "smart_tv": "스마트 TV",
    "mobile": "모바일",
    "tablet": "태블릿",
    "web": "웹",
    "game_console": "게임 콘솔",
}

TIME_LABELS = {
    "weekday_night": "평일 저녁",
    "late_night": "심야",
    "weekend_afternoon": "주말 오후",
    "weekend_night": "주말 저녁",
    "commute": "출퇴근",
}

# 추천 전략 이름은 RecommendationEngine의 가중치 키와 반드시 같아야 한다.
# 설명 문구는 사용자가 선택한 전략이 무엇을 우선하는지 프로필 아래에 보여준다.
STRATEGY_DESCRIPTIONS = {
    "균형 맞춤": "콘텐츠 취향 34%, 유사 시청자 33%, 작품 품질 33%를 고르게 반영합니다.",
    "취향 집중": "콘텐츠 취향 80%, 유사 시청자 10%, 작품 품질 10%를 반영합니다.",
    "비슷한 시청자": "유사 시청자 80%, 콘텐츠 취향 10%, 작품 품질 10%를 반영합니다.",
    "평론가 추천": "평론가 중심 품질 80%, 콘텐츠 취향 10%, 유사 시청자 10%를 반영합니다.",
}


# Gradio 기본 테마 위에 적용하는 앱 전용 스타일이다. 색상 토큰을 :root에 모아
# 카드, 표, 상세 화면이 같은 디자인 체계를 공유하게 하고 모바일 레이아웃도 보정한다.
APP_CSS = """
:root {
  --canvas: #090a12;
  --panel: rgba(22, 23, 36, .92);
  --panel-strong: #171827;
  --line: rgba(255, 255, 255, .10);
  --muted: #9ea4b7;
  --text: #f7f7fb;
  --violet: #8b5cf6;
  --coral: #fb7185;
  --mint: #2dd4bf;
}
body, .gradio-container { background: var(--canvas) !important; }
.gradio-container {
  max-width: 1500px !important;
  margin: 0 auto !important;
  padding: 24px 24px 64px !important;
  color: var(--text) !important;
}
.hero {
  position: relative;
  overflow: hidden;
  padding: 42px 44px;
  border: 1px solid var(--line);
  border-radius: 30px;
  background:
    radial-gradient(circle at 86% 18%, rgba(251, 113, 133, .30), transparent 28%),
    radial-gradient(circle at 72% 70%, rgba(139, 92, 246, .34), transparent 34%),
    linear-gradient(125deg, #17122d 0%, #171827 48%, #10111c 100%);
  box-shadow: 0 26px 80px rgba(0, 0, 0, .38);
}
.hero::after {
  content: "";
  position: absolute;
  width: 220px;
  height: 320px;
  right: 54px;
  top: -48px;
  border-radius: 120px;
  border: 1px solid rgba(255,255,255,.12);
  transform: rotate(28deg);
}
.hero__eyebrow { color: #c4b5fd; font-size: 12px; font-weight: 800; letter-spacing: .18em; }
.hero h1 { max-width: 760px; margin: 10px 0 12px; color: white; font-size: clamp(34px, 5vw, 58px); line-height: 1.02; letter-spacing: -.055em; }
.hero h1 span { color: #fda4af; }
.hero p { max-width: 720px; margin: 0; color: #c9ccda; font-size: 16px; line-height: 1.75; }
.hero__stats { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 25px; }
.hero__stat { padding: 8px 12px; border: 1px solid rgba(255,255,255,.13); border-radius: 999px; background: rgba(255,255,255,.055); color: #ececf5; font-size: 12px; font-weight: 700; }
.section-card {
  padding: 22px !important;
  border: 1px solid var(--line) !important;
  border-radius: 22px !important;
  background: var(--panel) !important;
  box-shadow: 0 14px 38px rgba(0, 0, 0, .20) !important;
}
.section-heading { margin-bottom: 14px; }
.section-heading strong { display: block; color: var(--text); font-size: 17px; }
.section-heading span { display: block; margin-top: 4px; color: var(--muted); font-size: 12px; line-height: 1.55; }
.recommend-button button {
  min-height: 52px !important;
  border: 0 !important;
  border-radius: 15px !important;
  background: linear-gradient(135deg, var(--violet), #6d28d9 62%, #be185d) !important;
  box-shadow: 0 12px 30px rgba(109, 40, 217, .30) !important;
  color: white !important;
  font-weight: 850 !important;
}
.profile-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 11px; margin: 20px 0 12px; }
.profile-card { padding: 16px; border: 1px solid var(--line); border-radius: 17px; background: rgba(255,255,255,.045); }
.profile-card__label { color: var(--muted); font-size: 11px; font-weight: 750; }
.profile-card__value { margin-top: 5px; color: white; font-size: 20px; font-weight: 850; letter-spacing: -.025em; }
.profile-note, .empty-state, .error-state { margin: 14px 0; padding: 16px 18px; border-radius: 16px; line-height: 1.65; }
/*
 * Gradio/Databricks의 테마 규칙이 HTML 컴포넌트 내부 글자색을 덮어써도
 * 프로필 설명 전체가 어두워지지 않도록 부모와 하위 태그의 색을 명시한다.
 */
.profile-note {
  border: 1px solid rgba(94,234,212,.48);
  background: rgba(13,148,136,.15);
  color: #f0fdfa !important;
  font-size: 14px;
  opacity: 1 !important;
}
.profile-note * { color: inherit !important; opacity: 1 !important; }
.profile-note strong { color: #ffffff !important; font-weight: 850; }
.profile-note span { color: #ccfbf1 !important; }
.empty-state { border: 1px dashed rgba(255,255,255,.18); background: rgba(255,255,255,.035); color: var(--muted); text-align: center; }
.error-state { border: 1px solid rgba(251,113,133,.32); background: rgba(251,113,133,.09); color: #fecdd3; }
#recommendation-table, #catalog-table {
  /* 바깥 컨테이너가 라벨까지 자르지 않게 하고 제목 위쪽에 안전 여백을 둔다. */
  overflow: visible !important;
  padding-top: 10px !important;
  border: 1px solid var(--line) !important;
  border-radius: 20px !important;
  background: var(--panel-strong) !important;
}
#recommendation-table > .label > p,
#catalog-table > .label > p {
  margin: 0 !important;
  padding: 2px 14px 12px !important;
  color: #f7f7fb !important;
  font-size: 14px !important;
  font-weight: 800 !important;
  line-height: 1.5 !important;
  opacity: 1 !important;
}
#recommendation-table .table-wrap,
#catalog-table .table-wrap {
  /* 제목은 고정하고 실제 데이터 표에서만 가로·세로 스크롤이 일어나게 한다. */
  overflow: auto !important;
  border-top: 1px solid var(--line) !important;
  border-radius: 0 0 19px 19px !important;
}
#recommendation-table .table-wrap table { min-width: 1080px !important; }
#recommendation-table .table-wrap th {
  background: #10111c !important;
  color: #f7f7fb !important;
}
#recommendation-table .table-wrap td {
  background: #171827 !important;
  color: #e5e7eb !important;
}
#recommendation-table .table-wrap tbody tr:nth-child(even) td { background: #111320 !important; }
#recommendation-table .table-wrap th button,
#recommendation-table .table-wrap th span,
#recommendation-table .table-wrap td button,
#recommendation-table .table-wrap td span { color: inherit !important; }
.recommendation-workspace { align-items: flex-start !important; flex-wrap: nowrap !important; gap: 18px !important; margin-top: 18px; }
.recommendation-list-pane, .recommendation-detail-pane { min-width: 0 !important; }
.recommendation-detail-pane {
  gap: 0 !important;
  overflow: hidden !important;
  padding: 10px 0 0 !important;
  border: 1px solid var(--line) !important;
  border-radius: 20px !important;
  background: var(--panel-strong) !important;
}
.detail-pane-heading { margin: 0; padding: 2px 14px 12px; color: #f7f7fb; font-size: 14px; font-weight: 800; line-height: 1.5; }
#movie-detail-panel {
  height: 500px !important;
  overflow-x: hidden !important;
  overflow-y: auto !important;
  padding: 0 !important;
  border: 0 !important;
  border-top: 1px solid var(--line) !important;
  background: transparent !important;
  scrollbar-color: rgba(139,92,246,.72) rgba(255,255,255,.04);
}
#movie-detail-panel .empty-state { margin: 16px; }
.movie-detail { margin: 0; padding: 22px; border: 0; border-radius: 0; background: linear-gradient(145deg, rgba(139,92,246,.09), rgba(255,255,255,.025)); }
.movie-detail__top { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.movie-detail__eyebrow { color: #c4b5fd; font-size: 11px; font-weight: 800; letter-spacing: .12em; }
.movie-detail h2 { margin: 5px 0 8px; color: white; font-size: 29px; letter-spacing: -.035em; }
.movie-detail__meta { color: var(--muted); font-size: 13px; }
.movie-detail__badge { padding: 7px 10px; border-radius: 999px; background: rgba(251,113,133,.14); color: #fda4af; font-size: 11px; font-weight: 850; white-space: nowrap; }
.movie-detail__logline { margin: 20px 0; color: #e5e7eb; font-size: 15px; line-height: 1.75; }
.detail-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.detail-kpi { padding: 13px 14px; border-radius: 14px; background: rgba(255,255,255,.045); }
.detail-kpi span { display: block; color: var(--muted); font-size: 10px; }
.detail-kpi strong { display: block; margin-top: 4px; color: white; font-size: 17px; }
.review-sections { display: grid; gap: 18px; margin-top: 22px; }
.review-section { padding: 17px; border: 1px solid var(--line); border-radius: 17px; background: rgba(0,0,0,.14); }
.review-section__heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.review-section__heading strong { color: #fff !important; font-size: 15px; }
.review-count { padding: 4px 9px; border-radius: 999px; background: rgba(255,255,255,.07); color: #d9dbe5 !important; font-size: 11px; font-weight: 800; }
.review-list { display: grid; gap: 10px; }
.review-card { padding: 14px 16px; border-left: 3px solid var(--mint); border-radius: 0 13px 13px 0; background: rgba(255,255,255,.04); }
.review-card--critic { border-left-color: var(--violet); }
.review-card__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.review-card__title { color: #fff !important; font-size: 13px; font-weight: 850; }
.review-card__meta { color: #a7f3d0 !important; font-size: 11px; white-space: nowrap; }
.review-card--critic .review-card__meta { color: #c4b5fd !important; }
.review-card__text { margin: 8px 0 0 !important; color: #d9dbe5 !important; font-size: 12px; line-height: 1.65; }
.review-empty { color: var(--muted) !important; font-size: 12px; line-height: 1.6; }
.recommendation-detail-pane .detail-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.recommendation-detail-pane .review-card__header { flex-direction: column; gap: 5px; }
.recommendation-detail-pane .review-card__meta { white-space: normal; }
.method-grid { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 14px; }
.method-card { padding: 20px; border: 1px solid var(--line); border-radius: 18px; background: rgba(255,255,255,.035); }
.method-card strong { color: white; }
.method-card p { margin-bottom: 0; color: var(--muted); font-size: 13px; line-height: 1.65; }
.privacy-note { margin-top: 18px; color: var(--muted); font-size: 12px; line-height: 1.6; }
footer { display: none !important; }
@media (max-width: 900px) {
  .gradio-container { padding: 12px 12px 40px !important; }
  .hero { padding: 30px 24px; border-radius: 22px; }
  .hero::after { display: none; }
  .profile-grid, .detail-kpis { grid-template-columns: repeat(2, minmax(0,1fr)); }
  .recommendation-workspace { flex-direction: column !important; }
  .recommendation-list-pane, .recommendation-detail-pane { width: 100% !important; max-width: 100% !important; }
  #movie-detail-panel { height: auto !important; max-height: 720px !important; }
  .review-card__header { flex-direction: column; gap: 5px; }
  .review-card__meta { white-space: normal; }
  .method-grid { grid-template-columns: 1fr; }
}
"""


def _genre_label(genre: str) -> str:
    """엔진의 영문 장르 코드를 ``한글 (영문)`` 형태의 화면 라벨로 바꾼다."""

    return f"{GENRE_LABELS.get(genre, genre)} ({genre})"


def _genre_value(label: str) -> str:
    """화면에서 선택한 장르 라벨을 엔진이 사용하는 영문 코드로 되돌린다.

    알 수 없는 라벨은 필터 오류를 내는 대신 전체 장르로 안전하게 처리한다.
    """

    if label == "전체 장르":
        return "전체"
    for genre in ENGINE.genres:
        if label == _genre_label(genre):
            return genre
    return "전체"


def _escape(value: object) -> str:
    """CSV 문자열을 HTML에 넣기 전에 특수문자를 이스케이프해 마크업 삽입을 막는다."""

    return html.escape("" if value is None else str(value))


def _coerce_dataframe(value: object) -> pd.DataFrame:
    """Gradio 버전에 따라 달라질 수 있는 표 이벤트 값을 DataFrame으로 통일한다."""

    if isinstance(value, pd.DataFrame):
        return value
    if isinstance(value, dict) and "headers" in value and "data" in value:
        return pd.DataFrame(value["data"], columns=value["headers"])
    return pd.DataFrame(value)


def _format_optional(value: object, suffix: str = "") -> str:
    """점수처럼 비어 있을 수 있는 숫자를 소수점 한 자리의 표시 문자열로 만든다."""

    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.1f}{suffix}"


def _format_review_date(value: object) -> str:
    """ISO 형식의 리뷰 작성 시각을 화면용 ``YYYY.MM.DD`` 날짜로 바꾼다."""

    reviewed_at = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(reviewed_at):
        return "날짜 미상"
    return reviewed_at.strftime("%Y.%m.%d")


def recommend_for_user(
    user_id: str,
    strategy: str,
    genre_label: str,
    content_rating: str,
    result_count: float,
    include_watched: bool,
):
    """추천 탭의 입력값을 엔진에 전달하고 프로필 HTML과 결과 표를 반환한다.

    Gradio 버튼 클릭과 최초 화면 로드가 함께 사용하는 콜백이다. UI 컴포넌트가
    숫자를 실수로 전달할 수 있으므로 결과 수를 정수로 정규화한다.
    엔진의 입력 검증 오류는 서버 예외로 노출하지 않고 사용자용 오류 카드로 바꾼다.
    """

    try:
        # 화면 라벨을 데이터의 영문 장르 코드로 되돌린 후 하이브리드 추천을 계산한다.
        genre = _genre_value(genre_label)
        recommendations = ENGINE.recommend(
            user_id=user_id,
            strategy=strategy,
            genre=genre,
            content_rating=content_rating,
            limit=int(result_count or 10),
            include_watched=bool(include_watched),
        )
        # 같은 사용자의 요약 통계를 함께 조회해 추천 결과의 배경을 설명한다.
        profile = ENGINE.user_summary(user_id)
    except (KeyError, TypeError, ValueError) as error:
        return (
            f'<div class="error-state"><strong>추천을 계산하지 못했습니다.</strong><br>{_escape(error)}</div>',
            pd.DataFrame(),
        )

    if recommendations.empty:
        return (
            '<div class="empty-state">조건에 맞는 안 본 작품이 없습니다. 장르나 관람 등급 조건을 넓혀보세요.</div>',
            pd.DataFrame({"메시지": ["조건에 맞는 추천 결과가 없습니다"]}),
        )

    # 사용자 프로필 영역은 추천 결과와 별도로 HTML 카드 형태로 렌더링한다.
    top_genres = ", ".join(
        GENRE_LABELS.get(item, item) for item in profile["top_genres"]
    )
    rating_text = _format_optional(profile["average_rating"], " / 5")
    profile_html = f"""
    <div class="profile-grid">
      <div class="profile-card"><div class="profile-card__label">시청한 작품</div><div class="profile-card__value">{profile["watched_count"]}편</div></div>
      <div class="profile-card"><div class="profile-card__label">평균 완주율</div><div class="profile-card__value">{profile["average_completion"]:.1f}%</div></div>
      <div class="profile-card"><div class="profile-card__label">남긴 평점</div><div class="profile-card__value">{rating_text}</div></div>
      <div class="profile-card"><div class="profile-card__label">추천 결과</div><div class="profile-card__value">{len(recommendations)}편</div></div>
    </div>
    <div class="profile-note">
      <strong>{_escape(profile["display_name"])}</strong>님의 주요 취향은 <strong>{_escape(top_genres)}</strong>이고,
      주로 <strong>{_escape(DEVICE_LABELS.get(profile["preferred_device"], profile["preferred_device"]))}</strong>로
      <strong>{_escape(TIME_LABELS.get(profile["watch_time_preference"], profile["watch_time_preference"]))}</strong>에 시청합니다.<br>
      <span>{_escape(STRATEGY_DESCRIPTIONS[strategy])}</span>
    </div>
    """

    # 엔진 내부 진단 컬럼 중 사용자에게 필요한 항목만 선택하고 한글 헤더로 바꾼다.
    table = recommendations[
        [
            "rank",
            "movie_id",
            "title",
            "primary_genre",
            "runtime_minutes",
            "content_rating",
            "recommendation_score",
            "user_rating",
            "critic_score",
            "avg_completion_pct",
            "recommendation_reason",
        ]
    ].copy()
    table["primary_genre"] = table["primary_genre"].map(
        lambda value: GENRE_LABELS.get(value, value)
    )
    table["recommendation_score"] = table["recommendation_score"].round(1)
    table["user_rating"] = pd.to_numeric(table["user_rating"], errors="coerce").round(1)
    table["critic_score"] = pd.to_numeric(table["critic_score"], errors="coerce").round(
        0
    )
    table["avg_completion_pct"] = pd.to_numeric(
        table["avg_completion_pct"], errors="coerce"
    ).round(1)
    table.columns = [
        "순위",
        "작품 ID",
        "작품명",
        "장르",
        "상영(분)",
        "관람등급",
        "추천점수",
        "관객평점",
        "평론가점수",
        "완주율(%)",
        "추천 이유",
    ]
    return profile_html, table


def show_movie_detail(table_value: object, user_id: str, evt: gr.SelectData):
    """추천 표에서 선택한 작품의 통계·관객·평론가 리뷰를 상세 카드로 렌더링한다.

    Gradio 선택 이벤트의 행 번호로 작품 ID를 찾는다. 잘못된 행이나 초기 빈 표가
    전달되면 상세 조회를 시도하지 않고 사용 방법을 안내하는 빈 상태를 반환한다.
    """

    try:
        table = _coerce_dataframe(table_value)
        index = evt.index[0] if isinstance(evt.index, (tuple, list)) else evt.index
        movie_id = str(table.iloc[int(index)]["작품 ID"])
        detail = ENGINE.movie_detail(movie_id, user_id)
    except (IndexError, KeyError, TypeError, ValueError):
        return '<div class="empty-state">추천 표에서 작품 행을 클릭해 상세 정보를 확인하세요.</div>'

    movie = detail["movie"]
    stats = detail["stats"]
    original_badge = "오리지널" if movie["is_platform_original"] else "라이선스"
    prior_note = ""
    if detail["watched_by_user"]:
        prior_note = (
            f" · 내 이전 완주율 {_format_optional(detail['user_completion'], '%')}"
            f" · 내 평점 {_format_optional(detail['user_rating'], ' / 5')}"
        )

    # 연결된 관객 리뷰를 작성자, 평점, 작성일과 함께 모두 렌더링한다.
    audience_items = []
    for review in detail["user_reviews"]:
        audience_items.append(
            '<article class="review-card">'
            '<div class="review-card__header">'
            f'<strong class="review-card__title">{_escape(review.get("review_title"))}</strong>'
            f'<span class="review-card__meta">{_escape(review.get("display_name") or review.get("user_id"))} · '
            f'{_format_optional(review.get("rating"), " / 5")} · '
            f'{_format_review_date(review.get("reviewed_at"))}</span>'
            "</div>"
            f'<p class="review-card__text">{_escape(review.get("review_text"))}</p>'
            "</article>"
        )
    audience_html = (
        "".join(audience_items)
        or '<div class="review-empty">아직 등록된 관객 리뷰가 없습니다.</div>'
    )

    # 연결된 평론가 리뷰도 평론가 정보, 점수, 추천 여부, 작성일과 함께 모두 렌더링한다.
    critic_items = []
    for review in detail["critic_reviews"]:
        recommendation_label = "추천" if bool(review.get("recommended")) else "비추천"
        critic_items.append(
            '<article class="review-card review-card--critic">'
            '<div class="review-card__header">'
            f'<strong class="review-card__title">{_escape(review.get("review_title"))}</strong>'
            f'<span class="review-card__meta">{_escape(review.get("pen_name"))} · '
            f'{_escape(review.get("publication_name"))} · '
            f'{_format_optional(review.get("score_100"), "점")} · '
            f'{recommendation_label} · {_format_review_date(review.get("reviewed_at"))}</span>'
            "</div>"
            f'<p class="review-card__text">{_escape(review.get("review_text"))}</p>'
            "</article>"
        )
    critic_html = (
        "".join(critic_items)
        or '<div class="review-empty">아직 등록된 평론가 리뷰가 없습니다.</div>'
    )

    return f"""
    <article class="movie-detail">
      <div class="movie-detail__top">
        <div>
          <div class="movie-detail__eyebrow">{_escape(movie["movie_id"])} · {_escape(GENRE_LABELS.get(movie["primary_genre"], movie["primary_genre"]))}</div>
          <h2>{_escape(movie["title"])}</h2>
          <div class="movie-detail__meta">
            {_escape(movie["director_name"])} 감독 · {_escape(movie["studio_name"])} · {int(movie["runtime_minutes"])}분 · {_escape(movie["content_rating"])}{prior_note}
          </div>
        </div>
        <div class="movie-detail__badge">{original_badge}</div>
      </div>
      <p class="movie-detail__logline">{_escape(movie["logline"])}</p>
      <div class="detail-kpis">
        <div class="detail-kpi"><span>관객 평점</span><strong>{_format_optional(stats.get("user_rating"), " / 5")}</strong></div>
        <div class="detail-kpi"><span>평론가 점수</span><strong>{_format_optional(stats.get("critic_score"), "점")}</strong></div>
        <div class="detail-kpi"><span>평균 완주율</span><strong>{_format_optional(stats.get("avg_completion_pct"), "%")}</strong></div>
        <div class="detail-kpi"><span>누적 시청</span><strong>{int(stats.get("view_count", 0))}회</strong></div>
      </div>
      <div class="review-sections">
        <section class="review-section">
          <div class="review-section__heading"><strong>관객 리뷰</strong><span class="review-count">{len(detail["user_reviews"])}개</span></div>
          <div class="review-list">{audience_html}</div>
        </section>
        <section class="review-section">
          <div class="review-section__heading"><strong>평론가 리뷰</strong><span class="review-count">{len(detail["critic_reviews"])}개</span></div>
          <div class="review-list">{critic_html}</div>
        </section>
      </div>
    </article>
    """


def search_catalog(query: str, genre_label: str):
    """검색어와 장르 조건에 맞는 작품을 찾아 화면용 카탈로그 표로 변환한다."""

    results = ENGINE.search_movies(
        query=query, genre=_genre_value(genre_label), limit=50
    )
    if results.empty:
        return pd.DataFrame({"메시지": ["검색 결과가 없습니다"]})
    # 검색 결과도 추천 표와 마찬가지로 필요한 컬럼만 노출하고 표시 형식을 정리한다.
    table = results[
        [
            "movie_id",
            "title",
            "primary_genre",
            "genre_detail",
            "director_name",
            "runtime_minutes",
            "content_rating",
            "user_rating",
            "critic_score",
            "keywords",
        ]
    ].copy()
    table["primary_genre"] = table["primary_genre"].map(
        lambda value: GENRE_LABELS.get(value, value)
    )
    table["user_rating"] = pd.to_numeric(table["user_rating"], errors="coerce").round(1)
    table["critic_score"] = pd.to_numeric(table["critic_score"], errors="coerce").round(
        0
    )
    table.columns = [
        "작품 ID",
        "작품명",
        "장르",
        "세부 장르",
        "감독",
        "상영(분)",
        "관람등급",
        "관객평점",
        "평론가점수",
        "키워드",
    ]
    return table


# 앱 화면을 만들기 전에 선택지와 헤더 통계를 한 번 계산한다. 데이터가 정적이므로
# 매 이벤트마다 다시 만들 필요가 없고, 앱 프로세스가 재시작될 때만 갱신된다.
summary = ENGINE.data_summary()
user_choices = [
    (f"{row.display_name} · {row.user_id}", row.user_id)
    for row in ENGINE.users.sort_values(["display_name", "user_id"]).itertuples(
        index=False
    )
]
genre_choices = ["전체 장르"] + [_genre_label(genre) for genre in ENGINE.genres]
default_user_id = "USR0001" if "USR0001" in ENGINE.user_ids else ENGINE.user_ids[0]


# Blocks는 전체 UI의 컨테이너다. analytics_enabled=False는 app.yaml의 환경 변수와
# 함께 Gradio 분석 수집을 명시적으로 비활성화한다.
with gr.Blocks(
    title="ScenePick · OTT 맞춤 추천",
    theme=gr.themes.Soft(),
    css=APP_CSS,
    analytics_enabled=False,
) as demo:
    # 데이터 규모를 첫 화면에서 바로 확인할 수 있는 상단 소개 영역이다.
    gr.HTML(
        f"""
        <section class="hero">
          <div class="hero__eyebrow">SCENEPICK · OTT RECOMMENDATION</div>
          <h1>오늘의 취향에 맞는<br><span>다음 장면을 찾아요.</span></h1>
          <p>시청 기록, 완주율, 관객 평점, 평론가 반응을 하나로 결합한 설명 가능한 맞춤 영화 추천 서비스입니다.</p>
          <div class="hero__stats">
            <span class="hero__stat">작품 {summary["movie_count"]:,}편</span>
            <span class="hero__stat">시청 이력 {summary["viewing_count"]:,}건</span>
            <span class="hero__stat">관객 리뷰 {summary["user_review_count"]:,}건</span>
            <span class="hero__stat">평론가 {summary["critic_count"]:,}명</span>
          </div>
        </section>
        """
    )

    # 기능을 개인화 추천, 전체 작품 탐색, 추천 방식 설명의 세 탭으로 분리한다.
    with gr.Tabs():
        with gr.Tab("내 취향 추천"):
            # 왼쪽은 사용자/전략, 오른쪽은 후보 필터를 입력받는다.
            with gr.Row():
                with gr.Column(scale=5, elem_classes=["section-card"]):
                    gr.HTML(
                        '<div class="section-heading"><strong>시청 프로필</strong><span>샘플 사용자를 선택하면 실제 시청·평점 이력을 기반으로 계산합니다.</span></div>'
                    )
                    user_id = gr.Dropdown(
                        choices=user_choices,
                        value=default_user_id,
                        label="사용자",
                        filterable=True,
                    )
                    strategy = gr.Radio(
                        choices=list(STRATEGY_WEIGHTS),
                        value="균형 맞춤",
                        label="추천 전략",
                    )
                with gr.Column(scale=5, elem_classes=["section-card"]):
                    gr.HTML(
                        '<div class="section-heading"><strong>이번 추천 조건</strong><span>장르와 관람 등급, 추천 작품 수를 조절하세요.</span></div>'
                    )
                    with gr.Row():
                        genre_filter = gr.Dropdown(
                            choices=genre_choices,
                            value="전체 장르",
                            label="장르",
                        )
                        content_rating = gr.Dropdown(
                            choices=["전체", "ALL", "12+", "15+", "18+"],
                            value="전체",
                            label="관람등급",
                        )
                    with gr.Row():
                        result_count = gr.Slider(
                            5, 20, value=10, step=1, label="추천 작품 수"
                        )
                        include_watched = gr.Checkbox(
                            value=False, label="이미 본 작품 포함"
                        )

            recommend_button = gr.Button(
                "취향 추천", variant="primary", elem_classes=["recommend-button"]
            )
            profile_summary = gr.HTML()
            # 넓은 화면에서는 추천 목록과 선택 작품 상세를 좌우로 배치한다.
            # 상세 패널은 리뷰가 많아도 목록 높이를 밀어내지 않도록 내부에서 스크롤된다.
            with gr.Row(elem_classes=["recommendation-workspace"]):
                with gr.Column(
                    scale=7, min_width=320, elem_classes=["recommendation-list-pane"]
                ):
                    recommendation_table = gr.Dataframe(
                        label="맞춤 추천 · 행을 클릭하면 작품 상세가 열립니다",
                        interactive=False,
                        wrap=True,
                        elem_id="recommendation-table",
                    )
                with gr.Column(
                    scale=5, min_width=320, elem_classes=["recommendation-detail-pane"]
                ):
                    gr.HTML(
                        '<div class="detail-pane-heading">선택 작품 상세 · 관객 및 평론가 리뷰</div>'
                    )
                    movie_detail = gr.HTML(
                        '<div class="empty-state">왼쪽 추천 목록에서 작품을 선택해 상세 정보와 리뷰를 확인하세요.</div>',
                        elem_id="movie-detail-panel",
                    )

            # callback 함수의 매개변수 순서와 동일하게 컴포넌트를 묶어 재사용한다.
            recommendation_inputs = [
                user_id,
                strategy,
                genre_filter,
                content_rating,
                result_count,
                include_watched,
            ]
            # 버튼 클릭 시 프로필 요약과 추천 표를 동시에 갱신한다.
            recommend_button.click(
                fn=recommend_for_user,
                inputs=recommendation_inputs,
                outputs=[profile_summary, recommendation_table],
            )
            # 추천 표의 행을 선택하면 작품 상세 카드만 갱신한다.
            recommendation_table.select(
                fn=show_movie_detail,
                inputs=[recommendation_table, user_id],
                outputs=movie_detail,
            )
            # 첫 접속에서도 빈 화면이 보이지 않도록 기본 사용자 추천을 자동 계산한다.
            demo.load(
                fn=recommend_for_user,
                inputs=recommendation_inputs,
                outputs=[profile_summary, recommendation_table],
            )

        with gr.Tab("작품 탐색"):
            # 추천 사용자와 무관하게 전체 카탈로그를 텍스트/장르 조건으로 검색한다.
            with gr.Row():
                catalog_query = gr.Textbox(
                    label="작품 검색",
                    placeholder="제목, 키워드, 로그라인, 감독, 배경으로 검색",
                    scale=3,
                )
                catalog_genre = gr.Dropdown(
                    choices=genre_choices,
                    value="전체 장르",
                    label="장르",
                    scale=1,
                )
                catalog_button = gr.Button("검색", variant="primary", scale=1)
            catalog_table = gr.Dataframe(
                value=search_catalog("", "전체 장르"),
                label="작품 카탈로그",
                interactive=False,
                wrap=True,
                elem_id="catalog-table",
            )
            # 검색 버튼과 Enter 제출이 같은 검색 callback을 사용한다.
            catalog_button.click(
                fn=search_catalog,
                inputs=[catalog_query, catalog_genre],
                outputs=catalog_table,
            )
            catalog_query.submit(
                fn=search_catalog,
                inputs=[catalog_query, catalog_genre],
                outputs=catalog_table,
            )

        with gr.Tab("추천 방식"):
            # 추천 모델의 세 구성 요소와 개인정보 처리 원칙을 정적인 설명으로 제공한다.
            gr.HTML(
                """
                <div class="method-grid">
                  <div class="method-card"><strong>1. 콘텐츠 유사도</strong><p>시청한 작품의 장르·키워드·언어를 사용자 취향 프로필로 만들고 후보 작품과의 유사도를 계산합니다.</p></div>
                  <div class="method-card"><strong>2. 유사 시청자 반응</strong><p>시청 완주율·재시청·평점을 결합한 행동 행렬로 비슷한 시청자가 만족한 안 본 작품을 찾습니다.</p></div>
                  <div class="method-card"><strong>3. 품질·인기 보정</strong><p>관객 평점, 평론가 점수, 완주율, 시청수를 평활화해 리뷰가 적은 작품이 과대 평가되는 문제를 줄입니다.</p></div>
                </div>
                <div class="privacy-note">
                  이 데모는 제공된 CSV만 사용하며 외부 API를 호출하지 않습니다. 보호된 특성을 추천 점수에 사용하지 않고, 사용자에게는 추천 근거를 함께 표시합니다.
                </div>
                """
            )


if __name__ == "__main__":
    # Databricks Apps는 외부에서 컨테이너에 접속하므로 모든 인터페이스(0.0.0.0)에
    # 바인딩해야 한다. 플랫폼이 주입한 포트를 우선하고 로컬에서는 8000을 사용한다.
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("DATABRICKS_APP_PORT", "8000")),
        show_error=True,
    )
