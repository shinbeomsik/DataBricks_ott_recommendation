import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import express, { type NextFunction, type Request, type Response } from "express";

import {
  RecommendationEngine,
  STRATEGY_DESCRIPTIONS,
  STRATEGY_WEIGHTS,
} from "./recommendationEngine.js";

const serverDirectory = dirname(fileURLToPath(import.meta.url));
const appDirectory = resolve(serverDirectory, "..");
const dataDirectory = resolve(appDirectory, "data");
const clientDirectory = resolve(appDirectory, "dist");

// 앱 시작 시 CSV를 한 번만 읽고 통계·추천 행렬을 메모리에 준비한다.
// 이후 API 요청은 준비된 엔진을 재사용하므로 파일을 반복해서 읽지 않는다.
const engine = RecommendationEngine.fromCsvDir(dataDirectory);
const app = express();

app.disable("x-powered-by");
app.use(express.json({ limit: "100kb" }));

function queryText(request: Request, name: string, fallback = ""): string {
  const value = request.query[name];
  return typeof value === "string" ? value : fallback;
}

function queryNumber(request: Request, name: string, fallback: number): number {
  const parsed = Number(queryText(request, name, String(fallback)));
  return Number.isFinite(parsed) ? parsed : fallback;
}

function queryBoolean(request: Request, name: string): boolean {
  return ["true", "1", "yes"].includes(queryText(request, name).toLowerCase());
}

app.get("/api/health", (_request, response) => {
  response.json({ status: "ok", runtime: "node", ui: "react" });
});

app.get("/api/bootstrap", (_request, response) => {
  response.json({
    summary: engine.dataSummary(),
    users: engine.users.map((user) => ({
      value: user.user_id,
      label: `${user.display_name} · ${user.user_id}`,
    })),
    genres: engine.genres,
    strategies: Object.keys(STRATEGY_WEIGHTS),
    strategyDescriptions: STRATEGY_DESCRIPTIONS,
  });
});

app.get("/api/recommendations", (request, response) => {
  const userId = queryText(request, "userId", engine.users[0]?.user_id);
  const strategy = queryText(request, "strategy", "균형 맞춤");
  const recommendations = engine.recommend({
    userId,
    strategy,
    genre: queryText(request, "genre", "전체"),
    contentRating: queryText(request, "contentRating", "전체"),
    limit: queryNumber(request, "limit", 10),
    includeWatched: queryBoolean(request, "includeWatched"),
  });
  response.json({
    profile: engine.userSummary(userId),
    recommendations,
    strategyDescription:
      STRATEGY_DESCRIPTIONS[strategy as keyof typeof STRATEGY_DESCRIPTIONS] ??
      STRATEGY_DESCRIPTIONS["균형 맞춤"],
  });
});

app.get("/api/movies/search", (request, response) => {
  response.json({
    movies: engine.searchMovies(
      queryText(request, "query"),
      queryText(request, "genre", "전체"),
      queryNumber(request, "limit", 30),
    ),
  });
});

app.get("/api/movies/:movieId", (request, response) => {
  const userId = queryText(request, "userId") || undefined;
  response.json(engine.movieDetail(request.params.movieId, userId));
});

// API가 아닌 경로에는 Vite가 만든 React 정적 파일을 제공한다.
app.use(express.static(clientDirectory, { index: false, maxAge: "1h" }));
app.use((request, response, next) => {
  if (request.method === "GET" && request.accepts("html") && existsSync(resolve(clientDirectory, "index.html"))) {
    response.sendFile(resolve(clientDirectory, "index.html"));
    return;
  }
  next();
});

app.use((error: unknown, _request: Request, response: Response, _next: NextFunction) => {
  const message = error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
  console.error(message);
  response.status(400).json({ error: message });
});

const port = Number(process.env.DATABRICKS_APP_PORT ?? process.env.PORT ?? 8000);
app.listen(port, "0.0.0.0", () => {
  console.log(`ScenePick React app listening on port ${port}`);
});
