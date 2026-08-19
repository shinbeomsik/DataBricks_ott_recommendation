import { type FormEvent, useEffect, useMemo, useState } from "react";

interface BootstrapData {
  summary: Record<string, number>;
  users: Array<{ value: string; label: string }>;
  genres: string[];
  strategies: string[];
  strategyDescriptions: Record<string, string>;
}

interface UserSummary {
  user_id: string;
  display_name: string;
  preferred_genre: string;
  top_genres: string[];
  subscription_plan: string;
  preferred_device: string;
  watch_time_preference: string;
  watched_count: number;
  completed_count: number;
  average_completion: number;
  average_rating: number | null;
}

interface Movie {
  movie_id: string;
  title: string;
  release_date: string;
  primary_genre: string;
  genre_detail: string;
  production_country: string;
  original_language: string;
  runtime_minutes: number;
  content_rating: string;
  director_name: string;
  studio_name: string;
  platform_release_date: string;
  is_platform_original: boolean;
  setting: string;
  protagonist: string;
  keywords: string;
  logline: string;
}

interface MovieStats {
  view_count: number;
  avg_completion_pct: number;
  user_rating: number | null;
  user_review_count: number;
  critic_score: number | null;
  critic_review_count: number;
  critic_recommend_rate: number;
  bayesian_user_score: number;
  bayesian_critic_score: number;
  quality_score: number;
}

interface Recommendation extends Movie, MovieStats {
  rank: number;
  recommendation_score: number;
  recommendation_reason: string;
  content_score: number;
  collaborative_score: number;
  quality_component: number;
}

interface UserReview {
  review_id: string;
  display_name?: string;
  rating: number;
  review_title: string;
  review_text: string;
  reviewed_at: string;
}

interface CriticReview {
  critic_review_id: string;
  pen_name?: string;
  publication_name?: string;
  is_top_critic?: boolean;
  score_100: number;
  letter_grade: string;
  review_title: string;
  review_text: string;
  reviewed_at: string;
  recommended: boolean;
}

interface MovieDetailData {
  movie: Movie;
  stats: MovieStats;
  user_reviews: UserReview[];
  critic_reviews: CriticReview[];
  watched_by_user: boolean;
  user_completion: number | null;
  user_rating: number | null;
}

interface RecommendationResponse {
  profile: UserSummary;
  recommendations: Recommendation[];
  strategyDescription: string;
}

interface CatalogMovie extends Movie, MovieStats {}

const GENRE_LABELS: Record<string, string> = {
  Action: "액션",
  Animation: "애니메이션",
  Comedy: "코미디",
  Documentary: "다큐멘터리",
  Drama: "드라마",
  Fantasy: "판타지",
  Horror: "공포",
  Romance: "로맨스",
  "Science Fiction": "SF",
  Thriller: "스릴러",
};

const DEVICE_LABELS: Record<string, string> = {
  smart_tv: "스마트 TV",
  mobile: "모바일",
  tablet: "태블릿",
  web: "웹",
  game_console: "게임 콘솔",
};

const TIME_LABELS: Record<string, string> = {
  weekday_night: "평일 저녁",
  late_night: "심야",
  weekend_afternoon: "주말 오후",
  weekend_night: "주말 저녁",
  commute: "출퇴근",
};

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  const body = (await response.json()) as T & { error?: string };
  if (!response.ok) throw new Error(body.error ?? "요청을 처리하지 못했습니다.");
  return body;
}

function genreLabel(genre: string): string {
  return `${GENRE_LABELS[genre] ?? genre} (${genre})`;
}

function formatOptional(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined || Number.isNaN(value) ? "-" : value.toFixed(digits);
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "날짜 미상";
  return new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

function MovieDetail({ detail, loading }: { detail: MovieDetailData | null; loading: boolean }) {
  if (loading) return <div className="empty-state">작품 상세와 리뷰를 불러오는 중입니다.</div>;
  if (!detail) return <div className="empty-state">왼쪽 추천 목록에서 작품을 선택해 상세 정보와 리뷰를 확인하세요.</div>;
  const { movie, stats } = detail;
  return (
    <article className="movie-detail">
      <header className="movie-detail__top">
        <div>
          <span className="eyebrow">{movie.movie_id} · {genreLabel(movie.primary_genre)}</span>
          <h2>{movie.title}</h2>
          <p className="movie-meta">
            {movie.production_country} · {movie.runtime_minutes}분 · {movie.content_rating} · 감독 {movie.director_name}
          </p>
        </div>
        {movie.is_platform_original && <span className="original-badge">ORIGINAL</span>}
      </header>

      <p className="movie-logline">{movie.logline}</p>
      <div className="keyword-row">
        {movie.keywords.split("|").filter(Boolean).map((keyword) => <span key={keyword}>#{keyword}</span>)}
      </div>

      <div className="detail-kpis">
        <div><span>관객 평점</span><strong>{formatOptional(stats.user_rating)} / 5</strong></div>
        <div><span>평론가 점수</span><strong>{formatOptional(stats.critic_score)} / 100</strong></div>
        <div><span>평균 완주율</span><strong>{formatOptional(stats.avg_completion_pct)}%</strong></div>
        <div><span>누적 시청</span><strong>{stats.view_count.toLocaleString("ko-KR")}회</strong></div>
      </div>

      {detail.watched_by_user && (
        <div className="my-history">
          이 작품을 본 기록이 있습니다. 완주율 {formatOptional(detail.user_completion)}%
          {detail.user_rating !== null ? ` · 내 평점 ${detail.user_rating.toFixed(1)}점` : ""}
        </div>
      )}

      <div className="review-sections">
        <section className="review-section">
          <div className="review-heading"><strong>관객 리뷰</strong><span>{detail.user_reviews.length}개</span></div>
          <div className="review-list">
            {detail.user_reviews.length === 0 && <p className="review-empty">등록된 관객 리뷰가 없습니다.</p>}
            {detail.user_reviews.map((review) => (
              <article className="review-card" key={review.review_id}>
                <div className="review-card__header">
                  <strong>{review.review_title}</strong>
                  <span>★ {review.rating.toFixed(1)} · {review.display_name} · {formatDate(review.reviewed_at)}</span>
                </div>
                <p>{review.review_text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="review-section">
          <div className="review-heading"><strong>평론가 리뷰</strong><span>{detail.critic_reviews.length}개</span></div>
          <div className="review-list">
            {detail.critic_reviews.length === 0 && <p className="review-empty">등록된 평론가 리뷰가 없습니다.</p>}
            {detail.critic_reviews.map((review) => (
              <article className="review-card review-card--critic" key={review.critic_review_id}>
                <div className="review-card__header">
                  <strong>{review.review_title}</strong>
                  <span>
                    {review.score_100.toFixed(0)}점 · {review.pen_name} / {review.publication_name}
                    {review.is_top_critic ? " · TOP CRITIC" : ""} · {formatDate(review.reviewed_at)}
                  </span>
                </div>
                <p>{review.review_text}</p>
              </article>
            ))}
          </div>
        </section>
      </div>
    </article>
  );
}

export default function App() {
  const [bootstrap, setBootstrap] = useState<BootstrapData | null>(null);
  const [activeTab, setActiveTab] = useState<"recommend" | "catalog">("recommend");
  const [userId, setUserId] = useState("");
  const [strategy, setStrategy] = useState("균형 맞춤");
  const [genre, setGenre] = useState("전체");
  const [contentRating, setContentRating] = useState("전체");
  const [resultCount, setResultCount] = useState(10);
  const [includeWatched, setIncludeWatched] = useState(false);
  const [profile, setProfile] = useState<UserSummary | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [selectedMovieId, setSelectedMovieId] = useState<string | null>(null);
  const [detail, setDetail] = useState<MovieDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [catalogQuery, setCatalogQuery] = useState("");
  const [catalogGenre, setCatalogGenre] = useState("전체");
  const [catalogMovies, setCatalogMovies] = useState<CatalogMovie[]>([]);

  const currentStrategyDescription = useMemo(
    () => bootstrap?.strategyDescriptions[strategy] ?? "",
    [bootstrap, strategy],
  );

  async function loadMovieDetail(movieId: string, currentUserId = userId) {
    setSelectedMovieId(movieId);
    setDetailLoading(true);
    try {
      const query = new URLSearchParams({ userId: currentUserId });
      setDetail(await getJson<MovieDetailData>(`/api/movies/${encodeURIComponent(movieId)}?${query}`));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "상세 정보를 불러오지 못했습니다.");
    } finally {
      setDetailLoading(false);
    }
  }

  async function fetchRecommendations(currentUserId: string, currentStrategy = strategy) {
    const query = new URLSearchParams({
      userId: currentUserId,
      strategy: currentStrategy,
      genre,
      contentRating,
      limit: String(resultCount),
      includeWatched: String(includeWatched),
    });
    const result = await getJson<RecommendationResponse>(`/api/recommendations?${query}`);
    setProfile(result.profile);
    setRecommendations(result.recommendations);
    setDetail(null);
    setSelectedMovieId(null);
    if (result.recommendations[0]) await loadMovieDetail(result.recommendations[0].movie_id, currentUserId);
  }

  useEffect(() => {
    let cancelled = false;
    async function initialize() {
      try {
        const [initialData, catalog] = await Promise.all([
          getJson<BootstrapData>("/api/bootstrap"),
          getJson<{ movies: CatalogMovie[] }>("/api/movies/search?limit=30"),
        ]);
        if (cancelled) return;
        setBootstrap(initialData);
        setCatalogMovies(catalog.movies);
        const initialUser = initialData.users[0]?.value ?? "";
        setUserId(initialUser);
        if (initialUser) await fetchRecommendations(initialUser, "균형 맞춤");
      } catch (requestError) {
        if (!cancelled) setError(requestError instanceof Error ? requestError.message : "앱을 시작하지 못했습니다.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void initialize();
    return () => { cancelled = true; };
    // 최초 로드에서만 기본 데이터를 가져온다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submitRecommendation(event: FormEvent) {
    event.preventDefault();
    if (!userId) return;
    setLoading(true);
    setError("");
    try {
      await fetchRecommendations(userId);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "추천을 계산하지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  async function submitCatalogSearch(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams({ query: catalogQuery, genre: catalogGenre, limit: "60" });
      const result = await getJson<{ movies: CatalogMovie[] }>(`/api/movies/search?${query}`);
      setCatalogMovies(result.movies);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "작품을 검색하지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <section className="hero">
        <span className="hero__eyebrow">SCENEPICK · REACT OTT RECOMMENDATION</span>
        <h1>오늘의 취향에 맞는<br /><em>다음 장면을 찾아요.</em></h1>
        <p>시청 기록, 완주율, 관객 평점, 평론가 반응을 하나로 결합한 설명 가능한 맞춤 영화 추천 서비스입니다.</p>
        <div className="hero__stats">
          <span>작품 {(bootstrap?.summary.movie_count ?? 0).toLocaleString("ko-KR")}편</span>
          <span>시청 이력 {(bootstrap?.summary.viewing_count ?? 0).toLocaleString("ko-KR")}건</span>
          <span>관객 리뷰 {(bootstrap?.summary.user_review_count ?? 0).toLocaleString("ko-KR")}건</span>
          <span>평론가 {(bootstrap?.summary.critic_count ?? 0).toLocaleString("ko-KR")}명</span>
        </div>
      </section>

      <nav className="tabs" aria-label="주요 기능">
        <button className={activeTab === "recommend" ? "active" : ""} onClick={() => setActiveTab("recommend")}>내 취향 추천</button>
        <button className={activeTab === "catalog" ? "active" : ""} onClick={() => setActiveTab("catalog")}>작품 탐색</button>
      </nav>

      {error && <div className="error-state" role="alert">{error}</div>}

      {activeTab === "recommend" && (
        <section className="tab-panel">
          <form onSubmit={submitRecommendation}>
            <div className="control-grid">
              <section className="control-card">
                <div className="section-heading"><strong>시청 프로필</strong><span>실제 시청·평점 이력을 가진 샘플 사용자를 선택하세요.</span></div>
                <label className="field-label" htmlFor="user-select">사용자</label>
                <select id="user-select" value={userId} onChange={(event) => setUserId(event.target.value)}>
                  {(bootstrap?.users ?? []).map((user) => <option key={user.value} value={user.value}>{user.label}</option>)}
                </select>
                <fieldset className="strategy-fieldset">
                  <legend>추천 전략</legend>
                  <div className="strategy-options">
                    {(bootstrap?.strategies ?? []).map((item) => (
                      <label className={strategy === item ? "selected" : ""} key={item}>
                        <input type="radio" name="strategy" value={item} checked={strategy === item} onChange={() => setStrategy(item)} />
                        <span>{item}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              </section>

              <section className="control-card">
                <div className="section-heading"><strong>이번 추천 조건</strong><span>장르와 관람 등급, 추천 작품 수를 조절하세요.</span></div>
                <div className="field-row">
                  <label><span className="field-label">장르</span>
                    <select value={genre} onChange={(event) => setGenre(event.target.value)}>
                      <option value="전체">전체 장르</option>
                      {(bootstrap?.genres ?? []).map((item) => <option key={item} value={item}>{genreLabel(item)}</option>)}
                    </select>
                  </label>
                  <label><span className="field-label">관람등급</span>
                    <select value={contentRating} onChange={(event) => setContentRating(event.target.value)}>
                      {["전체", "ALL", "12+", "15+", "18+"].map((item) => <option key={item}>{item}</option>)}
                    </select>
                  </label>
                </div>
                <label className="range-field"><span>추천 작품 수 <strong>{resultCount}편</strong></span>
                  <input type="range" min="5" max="20" step="1" value={resultCount} onChange={(event) => setResultCount(Number(event.target.value))} />
                </label>
                <label className="checkbox-field">
                  <input type="checkbox" checked={includeWatched} onChange={(event) => setIncludeWatched(event.target.checked)} />
                  <span>이미 본 작품 포함</span>
                </label>
              </section>
            </div>

            <div className="method-summary">
              <strong>추천 방식</strong>
              <span>시청 이력·콘텐츠 취향·비슷한 시청자의 반응·관객과 평론가 평가를 결합합니다. {currentStrategyDescription}</span>
            </div>
            <button className="primary-button" type="submit" disabled={loading}>{loading ? "계산 중…" : "취향 추천"}</button>
          </form>

          {profile && (
            <section className="profile-section">
              <div className="profile-grid">
                <div><span>시청 작품</span><strong>{profile.watched_count}편</strong></div>
                <div><span>완주 횟수</span><strong>{profile.completed_count}회</strong></div>
                <div><span>평균 완주율</span><strong>{profile.average_completion.toFixed(1)}%</strong></div>
                <div><span>추천 결과</span><strong>{recommendations.length}편</strong></div>
              </div>
              <p className="profile-note">
                <strong>{profile.display_name}</strong>님의 주요 취향은 <strong>{profile.top_genres.map(genreLabel).join(", ")}</strong>이고,
                주로 <strong>{DEVICE_LABELS[profile.preferred_device] ?? profile.preferred_device}</strong>로
                <strong> {TIME_LABELS[profile.watch_time_preference] ?? profile.watch_time_preference}</strong>에 시청합니다.
              </p>
            </section>
          )}

          <div className="recommendation-workspace">
            <section className="recommendation-pane">
              <div className="pane-heading"><strong>맞춤 추천</strong><span>작품을 선택하면 오른쪽에서 상세와 리뷰를 확인할 수 있습니다.</span></div>
              <div className="recommendation-list">
                {!loading && recommendations.length === 0 && <div className="empty-state">조건에 맞는 추천 작품이 없습니다.</div>}
                {recommendations.map((movie) => (
                  <button
                    type="button"
                    className={`recommendation-card ${selectedMovieId === movie.movie_id ? "selected" : ""}`}
                    key={movie.movie_id}
                    onClick={() => void loadMovieDetail(movie.movie_id)}
                  >
                    <span className="rank">{String(movie.rank).padStart(2, "0")}</span>
                    <span className="recommendation-card__body">
                      <strong>{movie.title}</strong>
                      <small>{genreLabel(movie.primary_genre)} · {movie.runtime_minutes}분 · {movie.content_rating}</small>
                      <em>{movie.recommendation_reason}</em>
                    </span>
                    <span className="score">{movie.recommendation_score.toFixed(1)}<small>점</small></span>
                  </button>
                ))}
              </div>
            </section>

            <section className="detail-pane">
              <div className="pane-heading"><strong>선택 작품 상세</strong><span>관객 및 평론가 리뷰 전체</span></div>
              <div className="detail-scroll"><MovieDetail detail={detail} loading={detailLoading} /></div>
            </section>
          </div>
        </section>
      )}

      {activeTab === "catalog" && (
        <section className="tab-panel">
          <form className="catalog-search" onSubmit={submitCatalogSearch}>
            <label><span className="field-label">작품 검색</span>
              <input value={catalogQuery} onChange={(event) => setCatalogQuery(event.target.value)} placeholder="제목, 키워드, 로그라인, 감독, 배경으로 검색" />
            </label>
            <label><span className="field-label">장르</span>
              <select value={catalogGenre} onChange={(event) => setCatalogGenre(event.target.value)}>
                <option value="전체">전체 장르</option>
                {(bootstrap?.genres ?? []).map((item) => <option key={item} value={item}>{genreLabel(item)}</option>)}
              </select>
            </label>
            <button className="secondary-button" type="submit" disabled={loading}>검색</button>
          </form>
          <div className="catalog-heading"><strong>작품 카탈로그</strong><span>{catalogMovies.length}편</span></div>
          <div className="catalog-grid">
            {catalogMovies.map((movie) => (
              <article className="catalog-card" key={movie.movie_id}>
                <span className="eyebrow">{movie.movie_id} · {genreLabel(movie.primary_genre)}</span>
                <h3>{movie.title}</h3>
                <p>{movie.logline}</p>
                <div><span>{movie.runtime_minutes}분 · {movie.content_rating}</span><strong>★ {formatOptional(movie.user_rating)}</strong></div>
              </article>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
