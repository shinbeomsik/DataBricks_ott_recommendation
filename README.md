# ScenePick OTT 맞춤 추천

제공된 영화·사용자·시청 이력·관객 리뷰·평론가 리뷰 CSV를 결합해
개인화 영화를 추천하는 React·TypeScript 기반 Databricks App입니다.

React 화면은 Vite로 빌드하고, Node.js/Express API가 CSV 로딩과 추천 계산,
작품 검색, 상세 리뷰 조회 및 React 정적 파일 제공을 담당합니다. 앱 실행 과정에
Python 런타임은 사용하지 않습니다. 추천 품질 검증은 앱과 분리된 Databricks
서버리스 Python Job이 Unity Catalog 데이터를 읽어 MLflow에 기록합니다.

## 주요 기능

- 300명의 시청·평점 이력을 기반으로 개인화 추천
- 콘텐츠 유사도, 유사 시청자, 관객·평론가 품질 지표를 결합한 하이브리드 랭킹
- `균형 맞춤`, `취향 집중`, `비슷한 시청자`, `평론가 추천` 전략
- 이미 본 작품 제외, 장르·관람 등급 필터
- 작품별 추천 이유와 관객·평론가·완주율 상세 지표
- 제목, 키워드, 로그라인, 감독, 배경의 한국어 검색

## 데이터

원본 CSV는 Unity Catalog의
`analytics_dev.ott_recommendation.source_datasets` Volume에 보관하고,
같은 Catalog와 Schema에 아래 6개 managed Delta table로 적재합니다.
재현 가능한 적재 SQL은 `src/sql/ingest_ott_data.sql`에 있습니다.

현재 앱은 로컬 실행과 독립적인 데모 배포를 위해
`src/ott_recommendation_app/data/`의 CSV 복사본도 사용합니다. Unity Catalog
테이블을 앱의 런타임 데이터 소스로 사용하려면 App service principal에
Catalog/Schema 조회 권한, Table `SELECT`, SQL Warehouse 사용 권한이 필요합니다.

| 파일 | 행 | 역할 |
|---|---:|---|
| `movies.csv` | 200 | 작품 메타데이터와 콘텐츠 특성 |
| `users.csv` | 300 | 샘플 시청자 프로필 |
| `viewing_history.csv` | 4,000 | 시청, 완주율, 재시청 행동 |
| `user_reviews.csv` | 1,000 | 관객 평점과 텍스트 리뷰 |
| `critics.csv` | 40 | 평론가 프로필 |
| `critic_reviews.csv` | 500 | 평론가 점수와 리뷰 |

## 로컬 실행

Node.js 22.16 이상과 pnpm을 사용합니다.

```powershell
Set-Location .\src\ott_recommendation_app
corepack enable
pnpm install --frozen-lockfile
pnpm build
pnpm start
```

브라우저에서 `http://127.0.0.1:8000` 으로 접속합니다.

## 테스트

```powershell
Set-Location .\src\ott_recommendation_app
pnpm check
pnpm test
```

## MLflow 추천 전략 실험

`ott_recommendation_evaluation_job`은 Unity Catalog의 영화, 사용자, 시청 이력,
관객 리뷰, 평론가 리뷰 테이블을 읽고 다음 네 전략을 동일한 조건에서 비교합니다.

- `균형 맞춤`: 콘텐츠 34%, 유사 시청자 33%, 품질 33%
- `취향 집중`: 콘텐츠 80%, 유사 시청자 10%, 품질 10%
- `비슷한 시청자`: 콘텐츠 10%, 유사 시청자 80%, 품질 10%
- `평론가 추천`: 콘텐츠 10%, 유사 시청자 10%, 평론가 중심 품질 80%

사용자별로 가장 최근의 긍정 반응 작품 한 편을 테스트 정답으로 숨기고, 해당
사용자·작품 쌍을 시청 이력과 리뷰 학습 데이터에서 모두 제거합니다. 과거 데이터만
사용해 Top 10을 추천한 뒤 `Precision@10`, `Recall@10`, `Hit Rate@10`,
`NDCG@10`, `MRR@10`, 카탈로그 커버리지, 평균·P50·P95 지연시간을 측정합니다.

평가 실행마다 MLflow Trace도 한 건 생성합니다. Trace에는 다음 Span이 부모·자식
구조로 기록됩니다.

```text
ott-recommendation-evaluation
├─ load-unity-catalog-tables
├─ build-temporal-holdout
├─ build-recommendation-features
├─ evaluate-균형 맞춤
├─ evaluate-취향 집중
├─ evaluate-비슷한 시청자
├─ evaluate-평론가 추천
├─ log-{전략}-mlflow-run (전략마다 한 번)
├─ select-best-strategy
└─ log-evaluation-summary
```

테이블명과 행 수, 분할 통계, 전략 가중치, 집계 지표, 사용자 평가 샘플 세 건을
Trace 입력·출력으로 남깁니다. 사용자 샘플은 SHA-256 접두사로 비식별화하며 사용자
이름과 리뷰 원문은 기록하지 않습니다.

아래 스크립트는 인증 확인 → 사전 점검 → strict 검증 → Bundle 배포 → 평가 Job
실행을 한 번에 수행합니다.

```powershell
.\scripts\run-mlflow-evaluation.ps1 -Profile "DEFAULT" -Target "dev"
```

Databricks 왼쪽 메뉴의 **Experiments**에서
`[dev 사용자] media-ott-recommendation-quality-experiment`를 열면 전체 비교용 부모 Run과
전략별 자식 Run 네 개가 표시됩니다. 기본 우승 전략은 `NDCG@10`이 가장 높은
전략이며, 동률이면 `Recall@10`으로 결정합니다. 각 자식 Run의 Artifacts에는
사용자별 정답 순위가 담긴 `per_user_metrics.csv`도 저장됩니다. 같은 Experiment의
**Traces** 탭에서는 단계별 입력·출력, 실행시간, 오류 여부를 확인할 수 있습니다.

## Databricks 검증과 배포

기본 프로필은 `DEFAULT`, 기본 타겟은 `dev`입니다. 다른 프로필을
사용할 때는 명시적으로 바꾸세요.

```powershell
.\scripts\databricks.ps1 auth profiles
.\scripts\check.ps1 -Profile "DEFAULT"
.\scripts\databricks.ps1 bundle validate --strict --target dev --profile DEFAULT
```

배포와 앱 시작을 한 번에 수행하려면 다음 스크립트를 사용합니다.

```powershell
.\scripts\deploy-ott-app.ps1 -Profile "DEFAULT" -Target "dev"
```

스크립트는 `auth profiles` → `check.ps1` → `bundle validate --strict` →
`bundle deploy` → `bundle run ott_recommendation_app` 순서를 지킵니다.

## 리소스 네이밍

- Bundle: `media-ott-recommendation`
- Bundle App key: `ott_recommendation_app`
- Databricks App: `media-ott-recommendation-app`
- App source: `src/ott_recommendation_app`
- MLflow Experiment key: `ott_recommendation_evaluation`
- 평가 Job key: `ott_recommendation_evaluation_job`

항목별 확장 패턴은 [OTT 리소스 네이밍 표준](docs/ott_resource_naming.md)을 따릅니다.

## 파일 구조

```text
resources/ott_recommendation_app.app.yml  Databricks App 리소스
resources/ott_recommendation_evaluation.mlflow.yml  MLflow Experiment와 평가 Job
src/ott_recommendation_app/client/        React 화면과 반응형 스타일
src/ott_recommendation_app/server/        Express API와 TypeScript 추천 엔진
src/ott_recommendation_app/data/          로컬·앱 데모용 CSV 복사본
src/ott_recommendation_app/package.json   빌드·실행·테스트 명령과 Node 의존성
src/ott_recommendation_app/pnpm-lock.yaml 재현 가능한 의존성 잠금 파일
src/ott_recommendation_app/app.yaml       Node.js 실행 명령
src/evaluation/recommendation_evaluator.py 시간 분할·추천·평가지표 계산
src/evaluation/ott_recommendation_mlflow.py MLflow 기록용 Databricks Notebook
src/sql/ingest_ott_data.sql               Unity Catalog 적재 SQL
scripts/run-mlflow-evaluation.ps1          평가 리소스 배포·실행 스크립트
docs/ott_resource_naming.md
```
