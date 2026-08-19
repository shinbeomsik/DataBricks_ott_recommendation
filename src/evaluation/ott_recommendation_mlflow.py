# Databricks notebook source
"""Unity Catalog의 OTT 데이터로 추천 전략을 비교하고 MLflow에 기록한다."""

# COMMAND ----------

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import mlflow

from recommendation_evaluator import STRATEGY_WEIGHTS, evaluate_strategies


# Job의 base_parameters 값을 위젯으로 받아 dev/prod 카탈로그와 실험을 재사용한다.
dbutils.widgets.text("catalog", "analytics_dev", "Unity Catalog catalog")
dbutils.widgets.text("schema", "ott_recommendation", "Unity Catalog schema")
dbutils.widgets.text("experiment_id", "", "MLflow experiment ID")
dbutils.widgets.text("top_k", "10", "추천 결과 개수")
dbutils.widgets.text("holdout_count", "1", "사용자별 테스트 작품 수")
dbutils.widgets.text("bundle_target", "dev", "Bundle target")

catalog = dbutils.widgets.get("catalog").strip()
schema = dbutils.widgets.get("schema").strip()
experiment_id = dbutils.widgets.get("experiment_id").strip()
top_k = int(dbutils.widgets.get("top_k"))
holdout_count = int(dbutils.widgets.get("holdout_count"))
bundle_target = dbutils.widgets.get("bundle_target").strip()

identifier_pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
if not identifier_pattern.fullmatch(catalog) or not identifier_pattern.fullmatch(schema):
    raise ValueError("catalog와 schema에는 영문자, 숫자, 밑줄만 사용할 수 있습니다.")
if not experiment_id:
    raise ValueError("Bundle에서 생성한 MLflow experiment_id가 필요합니다.")

# COMMAND ----------

# 평가에 필요한 5개 테이블만 읽는다. critics 테이블은 랭킹 점수에 직접 사용하지 않는다.
table_names = ["movies", "users", "viewing_history", "user_reviews", "critic_reviews"]
frames = {
    table_name: spark.table(f"{catalog}.{schema}.{table_name}").toPandas()
    for table_name in table_names
}
source_rows = {table_name: int(len(frame)) for table_name, frame in frames.items()}

# 사용자별 최신 긍정 작품을 숨긴 시간 분할로 네 전략을 같은 조건에서 비교한다.
summaries, detail_frames, split_stats = evaluate_strategies(
    frames,
    top_k=top_k,
    holdout_count=holdout_count,
)

# COMMAND ----------

mlflow.set_experiment(experiment_id=experiment_id)
run_timestamp = datetime.now(timezone.utc).isoformat()
parent_run_id = ""
child_run_ids: dict[str, str] = {}

with mlflow.start_run(run_name=f"strategy-benchmark-top-{top_k}") as parent_run:
    parent_run_id = parent_run.info.run_id
    mlflow.set_tags(
        {
            "project": "media-ott-recommendation",
            "evaluation_type": "temporal-holdout",
            "bundle_target": bundle_target,
            "runtime_role": "offline-evaluation",
        }
    )
    mlflow.log_params(
        {
            "catalog": catalog,
            "schema": schema,
            "top_k": top_k,
            "holdout_count": holdout_count,
            "positive_view_completion_threshold": 80,
            "positive_review_rating_threshold": 4.0,
            "minimum_train_positive_items": 2,
            "strategy_count": len(STRATEGY_WEIGHTS),
        }
    )
    mlflow.log_dict(
        {
            "created_at_utc": run_timestamp,
            "source_rows": source_rows,
            "split_stats": split_stats,
            "strategy_weights": STRATEGY_WEIGHTS,
        },
        "evaluation_config.json",
    )

    for strategy, metrics in summaries.items():
        with mlflow.start_run(run_name=strategy, nested=True) as child_run:
            child_run_ids[strategy] = child_run.info.run_id
            weights = STRATEGY_WEIGHTS[strategy]
            mlflow.set_tags({"strategy": strategy, "parent_run_id": parent_run_id})
            mlflow.log_params(
                {
                    "content_weight": weights["content"],
                    "collaborative_weight": weights["collaborative"],
                    "quality_weight": weights["quality"],
                    "quality_variant": "critic" if strategy == "평론가 추천" else "hybrid",
                }
            )
            mlflow.log_metrics(metrics)
            mlflow.log_text(detail_frames[strategy].to_csv(index=False), "per_user_metrics.csv")
            mlflow.log_dict(metrics, "metric_summary.json")

    # 기본 우승 기준은 순위 품질을 반영하는 NDCG@K이며, 동률이면 Recall@K를 사용한다.
    best_strategy = max(
        summaries,
        key=lambda name: (summaries[name]["ndcg_at_k"], summaries[name]["recall_at_k"]),
    )
    best_metrics = summaries[best_strategy]
    mlflow.set_tag("best_strategy", best_strategy)
    mlflow.log_metrics(
        {
            "best_ndcg_at_k": best_metrics["ndcg_at_k"],
            "best_recall_at_k": best_metrics["recall_at_k"],
            "best_hit_rate_at_k": best_metrics["hit_rate_at_k"],
        }
    )
    mlflow.log_dict(
        {
            "best_strategy": best_strategy,
            "selection_metric": "ndcg_at_k",
            "strategies": summaries,
            "child_run_ids": child_run_ids,
        },
        "strategy_comparison.json",
    )

result = {
    "status": "SUCCESS",
    "experiment_id": experiment_id,
    "parent_run_id": parent_run_id,
    "best_strategy": best_strategy,
    "top_k": top_k,
    "evaluated_users": split_stats["eligible_users"],
    "metrics": summaries,
    "child_run_ids": child_run_ids,
}
print(json.dumps(result, ensure_ascii=False, indent=2))
dbutils.notebook.exit(json.dumps(result, ensure_ascii=False))
