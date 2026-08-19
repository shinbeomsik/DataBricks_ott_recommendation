# OTT 추천 서비스 리소스 네이밍 표준

이 문서는 `DBX-STD-NAMING-001` 1.0.0을 `media` 도메인의 OTT 추천
서비스에 적용한 프로젝트 단위 구현 표준입니다. 상위 표준과 충돌하면
상위 표준과 Databricks 플랫폼 제약이 우선합니다.

## 1. 토큰과 표기법

| 역할 | 표준 토큰 |
|---|---|
| Domain | `media` |
| Product | `ott` |
| Purpose | `recommendation` |
| UC schema subject | `ott_recommendation` |

- Workspace/UI 리소스는 소문자 `kebab-case`를 사용한다.
- Unity Catalog, Bundle 논리 키, Task key, Parameter key는 소문자
  `snake_case`를 사용한다.
- UI 리소스는 `{domain}-{product}-{purpose}-{resource-type}` 순서를
  기본으로 한다.
- 환경은 Workspace, Catalog, Bundle target에서 한 번만 표현하고 하위
  리소스에 `dev`, `staging`, `prod`를 반복하지 않는다.

## 2. 현재 생성 리소스

| 대상 | 이름 | 근거 |
|---|---|---|
| Bundle | `media-ott-recommendation` | Repository/Bundle `{domain}-{product-purpose}` |
| Bundle App key | `ott_recommendation_app` | 의미 있는 `snake_case` |
| Databricks App | `media-ott-recommendation-app` | `{domain}-{product}-{purpose}-app` |
| App source | `src/ott_recommendation_app` | Python 패키지 친화적 `snake_case` |
| App resource file | `ott_recommendation_app.app.yml` | `<name>.<resource_type>.yml` |

Development mode가 사용자별 접두사를 적용하므로 App 이름에 `dev`를
수동으로 추가하지 않는다.

## 3. Unity Catalog 리소스

개발 환경의 원본 CSV는
`analytics_dev.ott_recommendation.source_datasets` Volume에 보관하고,
다음 managed Delta table에 적재한다.

```text
analytics_dev.ott_recommendation.movies
analytics_dev.ott_recommendation.users
analytics_dev.ott_recommendation.critics
analytics_dev.ott_recommendation.critic_reviews
analytics_dev.ott_recommendation.user_reviews
analytics_dev.ott_recommendation.viewing_history
```

Staging과 Production은 Catalog만 각각 `analytics_staging`, `analytics_prod`로
변경한다. Schema와 Table 이름에 환경 토큰을 추가하지 않는다.

| 리소스 | 표준 이름 |
|---|---|
| Catalog | `analytics_{env}` |
| Schema | `ott_recommendation` |
| Source volume | `source_datasets` |
| Feature table | `user_movie_features` |
| Recommendation table | `personalized_movie_recommendations` |
| Evaluation view | `recommendation_quality_metrics` |

## 4. 후속 Workload 패턴

| 리소스 | 이름 |
|---|---|
| Ingestion Job | `media-ott-recommendation-ingest-source-job` |
| Feature Job | `media-ott-recommendation-build-features-job` |
| Evaluation Job | `media-ott-recommendation-evaluate-quality-job` |
| Feature Pipeline | `media-ott-recommendation-feature-processing-pipeline` |
| Operations Dashboard | `media-ott-recommendation-operations-dashboard` |
| SQL Warehouse | `media-recommendation-warehouse` |

권장 Task key는 `load_source_datasets`, `build_user_movie_features`,
`generate_recommendations`, `evaluate_recommendation_quality`, `publish_metrics`이다.

## 5. 태그

Production workload에는 다음 키를 사용한다. 조직 정보가 확정되기
전에 placeholder를 실제 배포 값으로 사용하지 않는다.

```yaml
environment: ${bundle.target}
domain: media
product: ott_recommendation
owner_group: <account-group-name>
cost_center: <approved-cost-center>
managed_by: bundle
criticality: <low|medium|high>
data_classification: <approved-classification>
```

개인 이름, 이메일, 전화번호, 사번 및 민감정보는 리소스 이름과 태그에
넣지 않는다.

## 6. 금지 예시

```text
media-ott-dev-recommendation-app       # 하위 리소스의 환경 중복
media-ott-recommendation-final-app     # final 금지 토큰
media-ott-recommendation-v2-app        # 장기 리소스의 버전 토큰
media_ott_recommendation_app           # UI 리소스에 snake_case 사용
analytics_prod.ott_recommendation_prod.movies_prod
```

버전은 Git tag와 Bundle 배포 기록으로, 소유자와 비용 정보는 태그로
관리한다.
