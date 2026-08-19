# ScenePick OTT 맞춤 추천

제공된 영화·사용자·시청 이력·관객 리뷰·평론가 리뷰 CSV를 결합해
개인화 영화를 추천하는 Gradio 기반 Databricks App입니다.

## 주요 기능

- 300명의 시청·평점 이력을 기반으로 개인화 추천
- 콘텐츠 유사도, 유사 시청자, 관객·평론가 품질 지표를 결합한 하이브리드 랭킹
- `균형 맞춤`, `취향 집중`, `비슷한 시청자`, `평론가 추천` 전략
- 이미 본 작품 제외, 장르·상영 시간·관람 등급 필터
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

Python 3.11 이상을 사용합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\src\ott_recommendation_app\requirements.txt
Set-Location .\src\ott_recommendation_app
$env:GRADIO_ANALYTICS_ENABLED = "False"
..\..\.venv\Scripts\python.exe .\app.py
```

브라우저에서 `http://127.0.0.1:8000` 으로 접속합니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover `
  -s .\src\ott_recommendation_app `
  -p "test_*.py" -v
```

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

항목별 확장 패턴은 [OTT 리소스 네이밍 표준](docs/ott_resource_naming.md)을 따릅니다.

## 파일 구조

```text
resources/ott_recommendation_app.app.yml  Databricks App 리소스
src/ott_recommendation_app/app.py         Gradio UI
src/ott_recommendation_app/recommendation_engine.py
src/ott_recommendation_app/data/          로컬·앱 데모용 CSV 복사본
src/ott_recommendation_app/app.yaml       Databricks App 실행 명령
src/ott_recommendation_app/requirements.txt
src/ott_recommendation_app/test_recommendation_engine.py
src/sql/ingest_ott_data.sql               Unity Catalog 적재 SQL
docs/ott_resource_naming.md
```
