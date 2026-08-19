import { readFileSync } from "node:fs";
import { join } from "node:path";

import { parse } from "csv-parse/sync";

export const STRATEGY_WEIGHTS = {
  "균형 맞춤": { content: 0.34, collaborative: 0.33, quality: 0.33 },
  "취향 집중": { content: 0.8, collaborative: 0.1, quality: 0.1 },
  "비슷한 시청자": { content: 0.1, collaborative: 0.8, quality: 0.1 },
  "평론가 추천": { content: 0.1, collaborative: 0.1, quality: 0.8 },
} as const;

export const STRATEGY_DESCRIPTIONS: Record<Strategy, string> = {
  "균형 맞춤": "콘텐츠 취향 34%, 유사 시청자 33%, 작품 품질 33%를 고르게 반영합니다.",
  "취향 집중": "콘텐츠 취향 80%, 유사 시청자 10%, 작품 품질 10%를 반영합니다.",
  "비슷한 시청자": "유사 시청자 80%, 콘텐츠 취향 10%, 작품 품질 10%를 반영합니다.",
  "평론가 추천": "평론가 중심 품질 80%, 콘텐츠 취향 10%, 유사 시청자 10%를 반영합니다.",
};

export type Strategy = keyof typeof STRATEGY_WEIGHTS;

type CsvRow = Record<string, string>;

export interface Movie {
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
  production_budget_krw: number;
  theatrical_admissions: number;
  platform_release_date: string;
  is_platform_original: boolean;
  setting: string;
  protagonist: string;
  core_conflict: string;
  keywords: string;
  logline: string;
}

export interface User {
  user_id: string;
  display_name: string;
  preferred_genre: string;
  subscription_plan: string;
  preferred_device: string;
  watch_time_preference: string;
  account_status: string;
}

interface ViewingHistory {
  viewing_id: string;
  user_id: string;
  movie_id: string;
  completion_pct: number;
  playback_status: string;
  rewatch_number: number;
}

export interface UserReview {
  review_id: string;
  user_id: string;
  movie_id: string;
  rating: number;
  review_title: string;
  review_text: string;
  reviewed_at: string;
  display_name?: string;
}

interface Critic {
  critic_id: string;
  pen_name: string;
  publication_name: string;
  is_top_critic: boolean;
}

export interface CriticReview {
  critic_review_id: string;
  critic_id: string;
  movie_id: string;
  score_100: number;
  letter_grade: string;
  review_title: string;
  review_text: string;
  reviewed_at: string;
  verdict: string;
  recommended: boolean;
  pen_name?: string;
  publication_name?: string;
  is_top_critic?: boolean;
}

export interface MovieStats {
  movie_id: string;
  view_count: number;
  avg_completion_pct: number;
  completed_view_count: number;
  rewatch_count: number;
  user_rating: number | null;
  user_review_count: number;
  critic_score: number | null;
  critic_review_count: number;
  critic_recommend_rate: number;
  bayesian_user_score: number;
  bayesian_critic_score: number;
  popularity_score: number;
  quality_score: number;
  critic_quality_score: number;
}

export interface RecommendationResult extends Movie, MovieStats {
  rank: number;
  content_score: number;
  collaborative_score: number;
  quality_component: number;
  recommendation_score: number;
  recommendation_reason: string;
}

export interface UserSummary {
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

export interface MovieDetail {
  movie: Movie;
  stats: MovieStats;
  user_reviews: UserReview[];
  critic_reviews: CriticReview[];
  watched_by_user: boolean;
  user_completion: number | null;
  user_rating: number | null;
}

interface RecommendationData {
  movies: Movie[];
  users: User[];
  viewingHistory: ViewingHistory[];
  userReviews: UserReview[];
  criticReviews: CriticReview[];
  critics: Critic[];
}

interface Aggregate {
  count: number;
  sum: number;
}

const REQUIRED_COLUMNS: Record<string, string[]> = {
  movies: [
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
  ],
  users: [
    "user_id",
    "display_name",
    "preferred_genre",
    "subscription_plan",
    "preferred_device",
    "watch_time_preference",
    "account_status",
  ],
  viewing_history: [
    "viewing_id",
    "user_id",
    "movie_id",
    "completion_pct",
    "playback_status",
    "rewatch_number",
  ],
  user_reviews: [
    "review_id",
    "user_id",
    "movie_id",
    "rating",
    "review_title",
    "review_text",
    "reviewed_at",
  ],
  critic_reviews: [
    "critic_review_id",
    "critic_id",
    "movie_id",
    "score_100",
    "review_title",
    "review_text",
    "reviewed_at",
    "recommended",
  ],
  critics: ["critic_id", "pen_name", "publication_name", "is_top_critic"],
};

function numberValue(value: string | undefined, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function booleanValue(value: string | undefined): boolean {
  return ["true", "1", "yes", "y"].includes((value ?? "").trim().toLowerCase());
}

function clamp(value: number, low = 0, high = 1): number {
  return Math.min(high, Math.max(low, value));
}

function average(values: number[], fallback = 0): number {
  const finite = values.filter(Number.isFinite);
  if (finite.length === 0) return fallback;
  return finite.reduce((sum, value) => sum + value, 0) / finite.length;
}

function norm(values: number[]): number {
  return Math.sqrt(values.reduce((sum, value) => sum + value * value, 0));
}

function dot(left: number[], right: number[]): number {
  let result = 0;
  for (let index = 0; index < left.length; index += 1) {
    result += left[index] * right[index];
  }
  return result;
}

function safeMinMax(values: number[]): number[] {
  if (values.length === 0) return [];
  const finite = values.filter(Number.isFinite);
  if (finite.length === 0) return values.map(() => 0);
  const low = Math.min(...finite);
  const high = Math.max(...finite);
  if (high - low < 1e-12) return values.map(() => 0.5);
  return values.map((value) => (Number.isFinite(value) ? clamp((value - low) / (high - low)) : 0));
}

function uniqueBy<T>(items: T[], key: (item: T) => string): T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const value = key(item);
    if (seen.has(value)) return false;
    seen.add(value);
    return true;
  });
}

function readCsv(dataDir: string, name: string): CsvRow[] {
  const filePath = join(dataDir, `${name}.csv`);
  const records = parse(readFileSync(filePath, "utf8"), {
    bom: true,
    columns: true,
    skip_empty_lines: true,
    trim: false,
  }) as CsvRow[];
  const headers = records.length > 0 ? Object.keys(records[0]) : [];
  const missing = REQUIRED_COLUMNS[name].filter((column) => !headers.includes(column));
  if (missing.length > 0) {
    throw new Error(`${name}.csv에 필수 컬럼이 없습니다: ${missing.join(", ")}`);
  }
  return records;
}

function loadRecommendationData(dataDir: string): RecommendationData {
  // CSV의 문자열 값을 추천 계산에 맞는 숫자와 불리언으로 한 번만 정규화한다.
  const movies = readCsv(dataDir, "movies").map((row) => ({
    movie_id: row.movie_id,
    title: row.title,
    release_date: row.release_date,
    primary_genre: row.primary_genre,
    genre_detail: row.genre_detail,
    production_country: row.production_country,
    original_language: row.original_language,
    runtime_minutes: numberValue(row.runtime_minutes),
    content_rating: row.content_rating,
    director_name: row.director_name,
    studio_name: row.studio_name,
    production_budget_krw: numberValue(row.production_budget_krw),
    theatrical_admissions: numberValue(row.theatrical_admissions),
    platform_release_date: row.platform_release_date,
    is_platform_original: booleanValue(row.is_platform_original),
    setting: row.setting,
    protagonist: row.protagonist,
    core_conflict: row.core_conflict,
    keywords: row.keywords,
    logline: row.logline,
  }));
  const users = readCsv(dataDir, "users").map((row) => ({
    user_id: row.user_id,
    display_name: row.display_name,
    preferred_genre: row.preferred_genre,
    subscription_plan: row.subscription_plan,
    preferred_device: row.preferred_device,
    watch_time_preference: row.watch_time_preference,
    account_status: row.account_status,
  }));
  const viewingHistory = readCsv(dataDir, "viewing_history").map((row) => ({
    viewing_id: row.viewing_id,
    user_id: row.user_id,
    movie_id: row.movie_id,
    completion_pct: numberValue(row.completion_pct),
    playback_status: row.playback_status,
    rewatch_number: numberValue(row.rewatch_number),
  }));
  const userReviews = readCsv(dataDir, "user_reviews").map((row) => ({
    review_id: row.review_id,
    user_id: row.user_id,
    movie_id: row.movie_id,
    rating: numberValue(row.rating, Number.NaN),
    review_title: row.review_title,
    review_text: row.review_text,
    reviewed_at: row.reviewed_at,
  }));
  const criticReviews = readCsv(dataDir, "critic_reviews").map((row) => ({
    critic_review_id: row.critic_review_id,
    critic_id: row.critic_id,
    movie_id: row.movie_id,
    score_100: numberValue(row.score_100, Number.NaN),
    letter_grade: row.letter_grade,
    review_title: row.review_title,
    review_text: row.review_text,
    reviewed_at: row.reviewed_at,
    verdict: row.verdict,
    recommended: booleanValue(row.recommended),
  }));
  const critics = readCsv(dataDir, "critics").map((row) => ({
    critic_id: row.critic_id,
    pen_name: row.pen_name,
    publication_name: row.publication_name,
    is_top_critic: booleanValue(row.is_top_critic),
  }));
  return { movies, users, viewingHistory, userReviews, criticReviews, critics };
}

export class RecommendationEngine {
  readonly movies: Movie[];
  readonly users: User[];
  readonly genres: string[];

  private readonly data: RecommendationData;
  private readonly movieIndex = new Map<string, number>();
  private readonly userIndex = new Map<string, number>();
  private readonly movieMap = new Map<string, Movie>();
  private readonly userMap = new Map<string, User>();
  private readonly movieStats = new Map<string, MovieStats>();
  private readonly featureNames: string[];
  private readonly featureIndex = new Map<string, number>();
  private readonly featureMatrix: number[][];
  private readonly interactionMatrix: number[][];

  constructor(data: RecommendationData) {
    this.data = data;
    this.movies = uniqueBy(data.movies, (movie) => movie.movie_id);
    this.users = uniqueBy(data.users, (user) => user.user_id);
    this.genres = [...new Set(this.movies.map((movie) => movie.primary_genre))].sort();

    this.movies.forEach((movie, index) => {
      this.movieIndex.set(movie.movie_id, index);
      this.movieMap.set(movie.movie_id, movie);
    });
    this.users.forEach((user, index) => {
      this.userIndex.set(user.user_id, index);
      this.userMap.set(user.user_id, user);
    });

    this.buildMovieStats();
    const features = this.buildFeatureMatrix();
    this.featureNames = features.names;
    this.featureMatrix = features.matrix;
    this.featureNames.forEach((name, index) => this.featureIndex.set(name, index));
    this.interactionMatrix = this.buildInteractionMatrix();
  }

  static fromCsvDir(dataDir: string): RecommendationEngine {
    return new RecommendationEngine(loadRecommendationData(dataDir));
  }

  private buildMovieStats(): void {
    const viewAggregates = new Map<string, { count: number; completion: number; completed: number; rewatched: number }>();
    for (const row of this.data.viewingHistory) {
      const aggregate = viewAggregates.get(row.movie_id) ?? { count: 0, completion: 0, completed: 0, rewatched: 0 };
      aggregate.count += 1;
      aggregate.completion += row.completion_pct;
      aggregate.completed += row.playback_status.toLowerCase() === "completed" ? 1 : 0;
      aggregate.rewatched += row.rewatch_number > 0 ? 1 : 0;
      viewAggregates.set(row.movie_id, aggregate);
    }

    const audienceAggregates = new Map<string, Aggregate>();
    for (const review of this.data.userReviews) {
      if (!Number.isFinite(review.rating)) continue;
      const aggregate = audienceAggregates.get(review.movie_id) ?? { count: 0, sum: 0 };
      aggregate.count += 1;
      aggregate.sum += review.rating;
      audienceAggregates.set(review.movie_id, aggregate);
    }

    const criticAggregates = new Map<string, Aggregate & { recommended: number }>();
    for (const review of this.data.criticReviews) {
      if (!Number.isFinite(review.score_100)) continue;
      const aggregate = criticAggregates.get(review.movie_id) ?? { count: 0, sum: 0, recommended: 0 };
      aggregate.count += 1;
      aggregate.sum += review.score_100;
      aggregate.recommended += review.recommended ? 1 : 0;
      criticAggregates.set(review.movie_id, aggregate);
    }

    const globalUserRating = average(this.data.userReviews.map((review) => review.rating));
    const globalCriticScore = average(this.data.criticReviews.map((review) => review.score_100));
    const popularity = safeMinMax(
      this.movies.map((movie) => Math.log1p(viewAggregates.get(movie.movie_id)?.count ?? 0)),
    );

    this.movies.forEach((movie, index) => {
      const viewing = viewAggregates.get(movie.movie_id);
      const audience = audienceAggregates.get(movie.movie_id);
      const critic = criticAggregates.get(movie.movie_id);
      const userRating = audience ? audience.sum / audience.count : null;
      const criticScore = critic ? critic.sum / critic.count : null;
      const userReviewCount = audience?.count ?? 0;
      const criticReviewCount = critic?.count ?? 0;
      const bayesianUserScore =
        (userReviewCount * (userRating ?? globalUserRating) + 5 * globalUserRating) /
        (userReviewCount + 5);
      const bayesianCriticScore =
        (criticReviewCount * (criticScore ?? globalCriticScore) + 3 * globalCriticScore) /
        (criticReviewCount + 3);
      const averageCompletion = viewing && viewing.count > 0 ? viewing.completion / viewing.count : 0;
      const audienceScore = bayesianUserScore / 5;
      const normalizedCriticScore = bayesianCriticScore / 100;
      const completionScore = clamp(averageCompletion / 100);
      const popularityScore = popularity[index];

      this.movieStats.set(movie.movie_id, {
        movie_id: movie.movie_id,
        view_count: viewing?.count ?? 0,
        avg_completion_pct: averageCompletion,
        completed_view_count: viewing?.completed ?? 0,
        rewatch_count: viewing?.rewatched ?? 0,
        user_rating: userRating,
        user_review_count: userReviewCount,
        critic_score: criticScore,
        critic_review_count: criticReviewCount,
        critic_recommend_rate: critic && critic.count > 0 ? critic.recommended / critic.count : 0,
        bayesian_user_score: bayesianUserScore,
        bayesian_critic_score: bayesianCriticScore,
        popularity_score: popularityScore,
        quality_score:
          0.35 * audienceScore +
          0.25 * normalizedCriticScore +
          0.25 * completionScore +
          0.15 * popularityScore,
        critic_quality_score:
          0.65 * normalizedCriticScore +
          0.15 * audienceScore +
          0.1 * completionScore +
          0.1 * popularityScore,
      });
    });
  }

  private movieTokens(movie: Movie): Set<string> {
    const tokens = new Set<string>([
      `genre:${movie.primary_genre.trim().toLowerCase()}`,
      `language:${movie.original_language.trim().toLowerCase()}`,
      `country:${movie.production_country.trim().toLowerCase()}`,
    ]);
    for (const keyword of movie.keywords.split("|")) {
      const normalized = keyword.trim().toLowerCase();
      if (normalized) tokens.add(`keyword:${normalized}`);
    }
    return tokens;
  }

  private buildFeatureMatrix(): { names: string[]; matrix: number[][] } {
    const tokenSets = this.movies.map((movie) => this.movieTokens(movie));
    const names = [...new Set(tokenSets.flatMap((tokens) => [...tokens]))].sort();
    const index = new Map(names.map((name, position) => [name, position]));
    const matrix = tokenSets.map((tokens) => {
      const row = Array<number>(names.length).fill(0);
      for (const token of tokens) row[index.get(token)!] = 1;
      return row;
    });
    const documentFrequency = names.map((_, column) =>
      Math.max(1, matrix.reduce((sum, row) => sum + row[column], 0)),
    );
    const inverseDocumentFrequency = documentFrequency.map(
      (frequency) => Math.log((1 + this.movies.length) / frequency) + 1,
    );
    for (const row of matrix) {
      for (let column = 0; column < row.length; column += 1) {
        row[column] *= inverseDocumentFrequency[column];
      }
      const rowNorm = norm(row);
      if (rowNorm > 0) {
        for (let column = 0; column < row.length; column += 1) row[column] /= rowNorm;
      }
    }
    return { names, matrix };
  }

  private buildInteractionMatrix(): number[][] {
    const matrix = Array.from({ length: this.users.length }, () => Array<number>(this.movies.length).fill(0));
    const historyStrength = new Map<string, number>();
    for (const row of this.data.viewingHistory) {
      const completion = clamp(row.completion_pct / 100);
      const completed = row.playback_status.toLowerCase() === "completed" ? 1 : 0;
      const rewatch = clamp(row.rewatch_number, 0, 2) / 2;
      const strength = clamp(0.15 + 0.65 * completion + 0.15 * completed + 0.05 * rewatch);
      const key = `${row.user_id}\u0000${row.movie_id}`;
      historyStrength.set(key, Math.max(historyStrength.get(key) ?? 0, strength));
    }

    const reviewAggregates = new Map<string, Aggregate>();
    for (const review of this.data.userReviews) {
      if (!Number.isFinite(review.rating)) continue;
      const key = `${review.user_id}\u0000${review.movie_id}`;
      const aggregate = reviewAggregates.get(key) ?? { count: 0, sum: 0 };
      aggregate.count += 1;
      aggregate.sum += clamp(review.rating / 5);
      reviewAggregates.set(key, aggregate);
    }

    const keys = new Set([...historyStrength.keys(), ...reviewAggregates.keys()]);
    for (const key of keys) {
      const [userId, movieId] = key.split("\u0000");
      const userPosition = this.userIndex.get(userId);
      const moviePosition = this.movieIndex.get(movieId);
      if (userPosition === undefined || moviePosition === undefined) continue;
      const history = historyStrength.get(key);
      const reviewAggregate = reviewAggregates.get(key);
      const review = reviewAggregate ? reviewAggregate.sum / reviewAggregate.count : undefined;
      const strength =
        history !== undefined && review !== undefined
          ? 0.65 * history + 0.35 * review
          : (history ?? review ?? 0);
      matrix[userPosition][moviePosition] = strength;
    }
    return matrix;
  }

  private contentScores(userId: string): number[] {
    const userPosition = this.userIndex.get(userId)!;
    const user = this.userMap.get(userId)!;
    const profile = Array<number>(this.featureNames.length).fill(0);
    const interactions = this.interactionMatrix[userPosition];
    for (let movie = 0; movie < interactions.length; movie += 1) {
      const strength = interactions[movie];
      if (strength <= 0) continue;
      for (let feature = 0; feature < profile.length; feature += 1) {
        profile[feature] += strength * this.featureMatrix[movie][feature];
      }
    }
    const preferredFeature = this.featureIndex.get(`genre:${user.preferred_genre.trim().toLowerCase()}`);
    if (preferredFeature !== undefined) profile[preferredFeature] += 2;
    const profileNorm = norm(profile);
    if (profileNorm <= 1e-12) return this.movies.map(() => 0);
    const normalized = profile.map((value) => value / profileNorm);
    return safeMinMax(this.featureMatrix.map((features) => dot(features, normalized)));
  }

  private collaborativeScores(userId: string): number[] {
    const targetPosition = this.userIndex.get(userId)!;
    const target = this.interactionMatrix[targetPosition];
    const targetNorm = norm(target);
    if (targetNorm <= 1e-12) return this.movies.map(() => 0);
    const similarities = this.interactionMatrix.map((row, index) => {
      if (index === targetPosition) return 0;
      const rowNorm = norm(row);
      if (rowNorm <= 1e-12) return 0;
      const similarity = dot(row, target) / (rowNorm * targetNorm);
      return similarity >= 0.08 ? similarity : 0;
    });
    const similaritySum = similarities.reduce((sum, value) => sum + value, 0);
    if (similaritySum <= 1e-12) return this.movies.map(() => 0);
    const scores = this.movies.map((_, moviePosition) => {
      let weighted = 0;
      for (let userPosition = 0; userPosition < this.users.length; userPosition += 1) {
        weighted += similarities[userPosition] * this.interactionMatrix[userPosition][moviePosition];
      }
      return weighted / similaritySum;
    });
    return safeMinMax(scores);
  }

  watchedMovieIds(userId: string): Set<string> {
    const watched = new Set<string>();
    this.data.viewingHistory.filter((row) => row.user_id === userId).forEach((row) => watched.add(row.movie_id));
    this.data.userReviews.filter((row) => row.user_id === userId).forEach((row) => watched.add(row.movie_id));
    return watched;
  }

  private topProfileGenres(userId: string, limit = 3): string[] {
    const weights = new Map<string, number>();
    for (const row of this.data.viewingHistory) {
      if (row.user_id !== userId) continue;
      const movie = this.movieMap.get(row.movie_id);
      if (!movie) continue;
      weights.set(movie.primary_genre, (weights.get(movie.primary_genre) ?? 0) + clamp(row.completion_pct / 100));
    }
    if (weights.size === 0) return [this.userMap.get(userId)!.preferred_genre];
    return [...weights.entries()]
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
      .slice(0, limit)
      .map(([genre]) => genre);
  }

  private recommendationReason(
    userId: string,
    movie: Movie,
    contentScore: number,
    collaborativeScore: number,
    qualityScore: number,
  ): string {
    const reasons: string[] = [];
    if (this.topProfileGenres(userId).includes(movie.primary_genre)) reasons.push(`선호 패턴의 ${movie.primary_genre}`);
    if (collaborativeScore >= 0.55) reasons.push("비슷한 시청자가 높게 평가");
    if (qualityScore >= 0.72) reasons.push(`평론가 ${this.movieStats.get(movie.movie_id)!.bayesian_critic_score.toFixed(0)}점대`);
    if (movie.is_platform_original) reasons.push("플랫폼 오리지널");
    if (contentScore >= 0.7 && reasons.length === 0) reasons.push("시청 취향 키워드와 높은 일치");
    if (reasons.length === 0) reasons.push("취향·반응·품질 지표가 고르게 우수");
    return reasons.slice(0, 2).join(" · ");
  }

  recommend(options: {
    userId: string;
    strategy?: string;
    genre?: string;
    contentRating?: string;
    limit?: number;
    includeWatched?: boolean;
  }): RecommendationResult[] {
    const { userId } = options;
    if (!this.userIndex.has(userId)) throw new Error(`알 수 없는 사용자입니다: ${userId}`);
    const strategy: Strategy = options.strategy && options.strategy in STRATEGY_WEIGHTS
      ? (options.strategy as Strategy)
      : "균형 맞춤";
    const weights = STRATEGY_WEIGHTS[strategy];
    const contentScores = this.contentScores(userId);
    const collaborativeScores = this.collaborativeScores(userId);
    const watched = this.watchedMovieIds(userId);

    const results = this.movies
      .map((movie, index) => {
        const stats = this.movieStats.get(movie.movie_id)!;
        const qualityComponent = strategy === "평론가 추천" ? stats.critic_quality_score : stats.quality_score;
        return {
          ...movie,
          ...stats,
          rank: 0,
          content_score: contentScores[index],
          collaborative_score: collaborativeScores[index],
          quality_component: qualityComponent,
          recommendation_score:
            100 *
            (weights.content * contentScores[index] +
              weights.collaborative * collaborativeScores[index] +
              weights.quality * qualityComponent),
          recommendation_reason: this.recommendationReason(
            userId,
            movie,
            contentScores[index],
            collaborativeScores[index],
            qualityComponent,
          ),
        } satisfies RecommendationResult;
      })
      .filter((movie) => options.includeWatched || !watched.has(movie.movie_id))
      .filter((movie) => !options.genre || options.genre === "전체" || movie.primary_genre === options.genre)
      .filter(
        (movie) =>
          !options.contentRating ||
          options.contentRating === "전체" ||
          movie.content_rating === options.contentRating,
      )
      .sort(
        (left, right) =>
          right.recommendation_score - left.recommendation_score ||
          right.quality_component - left.quality_component ||
          right.platform_release_date.localeCompare(left.platform_release_date),
      )
      .slice(0, clamp(Math.trunc(options.limit ?? 10), 1, 50));
    return results.map((result, index) => ({ ...result, rank: index + 1 }));
  }

  userSummary(userId: string): UserSummary {
    const user = this.userMap.get(userId);
    if (!user) throw new Error(`알 수 없는 사용자입니다: ${userId}`);
    const history = this.data.viewingHistory.filter((row) => row.user_id === userId);
    const reviews = this.data.userReviews.filter((row) => row.user_id === userId);
    return {
      user_id: userId,
      display_name: user.display_name,
      preferred_genre: user.preferred_genre,
      top_genres: this.topProfileGenres(userId),
      subscription_plan: user.subscription_plan,
      preferred_device: user.preferred_device,
      watch_time_preference: user.watch_time_preference,
      watched_count: new Set(history.map((row) => row.movie_id)).size,
      completed_count: history.filter((row) => row.playback_status.toLowerCase() === "completed").length,
      average_completion: average(history.map((row) => row.completion_pct)),
      average_rating: reviews.length > 0 ? average(reviews.map((review) => review.rating)) : null,
    };
  }

  movieDetail(movieId: string, userId?: string): MovieDetail {
    const movie = this.movieMap.get(movieId);
    if (!movie) throw new Error(`알 수 없는 작품입니다: ${movieId}`);
    const criticMap = new Map(this.data.critics.map((critic) => [critic.critic_id, critic]));
    const criticReviews = this.data.criticReviews
      .filter((review) => review.movie_id === movieId)
      .map((review) => {
        const critic = criticMap.get(review.critic_id);
        return {
          ...review,
          pen_name: critic?.pen_name ?? "평론가",
          publication_name: critic?.publication_name ?? "",
          is_top_critic: critic?.is_top_critic ?? false,
        };
      })
      .sort(
        (left, right) =>
          Number(right.is_top_critic) - Number(left.is_top_critic) ||
          right.score_100 - left.score_100 ||
          right.reviewed_at.localeCompare(left.reviewed_at),
      );
    const userReviews = this.data.userReviews
      .filter((review) => review.movie_id === movieId)
      .map((review) => ({ ...review, display_name: this.userMap.get(review.user_id)?.display_name ?? "시청자" }))
      .sort((left, right) => right.reviewed_at.localeCompare(left.reviewed_at) || right.rating - left.rating);
    const userHistory = userId
      ? this.data.viewingHistory.filter((row) => row.user_id === userId && row.movie_id === movieId)
      : [];
    const userReview = userId
      ? this.data.userReviews.find((review) => review.user_id === userId && review.movie_id === movieId)
      : undefined;
    return {
      movie,
      stats: this.movieStats.get(movieId)!,
      user_reviews: userReviews,
      critic_reviews: criticReviews,
      watched_by_user: userHistory.length > 0,
      user_completion: userHistory.length > 0 ? Math.max(...userHistory.map((row) => row.completion_pct)) : null,
      user_rating: userReview?.rating ?? null,
    };
  }

  searchMovies(query = "", genre = "전체", limit = 30): Array<Movie & MovieStats> {
    const normalized = query.trim().replace(/\s+/g, " ").toLowerCase();
    return this.movies
      .filter((movie) => {
        const text = [movie.title, movie.keywords, movie.logline, movie.director_name, movie.setting, movie.protagonist]
          .join(" ")
          .toLowerCase();
        return !normalized || text.includes(normalized);
      })
      .filter((movie) => genre === "전체" || movie.primary_genre === genre)
      .map((movie) => ({ ...movie, ...this.movieStats.get(movie.movie_id)! }))
      .sort(
        (left, right) =>
          right.quality_score - left.quality_score ||
          right.platform_release_date.localeCompare(left.platform_release_date),
      )
      .slice(0, clamp(Math.trunc(limit), 1, 100));
  }

  dataSummary(): Record<string, number> {
    return {
      movie_count: this.movies.length,
      user_count: this.users.length,
      viewing_count: this.data.viewingHistory.length,
      user_review_count: this.data.userReviews.length,
      critic_count: this.data.critics.length,
      critic_review_count: this.data.criticReviews.length,
    };
  }
}
