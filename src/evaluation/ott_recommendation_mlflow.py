# Databricks notebook source
"""Unity Catalog의 OTT 데이터로 추천 전략을 비교하고 MLflow에 기록한다."""

# COMMAND ----------

from __future__ import annotations

import json
import re
from hashlib import sha256
from inspect import signature
from datetime import datetime, timezone

import mlflow

from recommendation_evaluator import (
    STRATEGY_WEIGHTS,
    OfflineRecommendationEngine,
    build_temporal_holdout,
    evaluate_strategy,
)


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
if not hasattr(mlflow, "start_span"):
    raise RuntimeError(f"현재 MLflow {mlflow.__version__}에는 Tracing API가 없습니다.")

# COMMAND ----------

# set_experiment는 Run과 Trace를 같은 Experiment로 보낸다.
mlflow.set_experiment(experiment_id=experiment_id)
run_timestamp = datetime.now(timezone.utc).isoformat()
parent_run_id = ""
trace_id = ""
child_run_ids: dict[str, str] = {}
table_names = ["movies", "users", "viewing_history", "user_reviews", "critic_reviews"]
summaries: dict[str, dict[str, float]] = {}
detail_frames = {}


def start_traced_span(name: str, span_type: str, run_id: str | None = None):
    """설치된 MLflow가 지원할 때 Trace를 부모 Run과 명시적으로 연결한다."""

    arguments = {"name": name, "span_type": span_type}
    if run_id and "run_id" in signature(mlflow.start_span).parameters:
        arguments["run_id"] = run_id
    return mlflow.start_span(**arguments)


def trace_samples(detail_frame, limit: int = 3) -> list[dict[str, object]]:
    """사용자 이름과 리뷰 원문 없이 평가 예시만 Trace 출력으로 만든다."""

    samples = []
    for row in detail_frame.head(limit).itertuples():
        samples.append(
            {
                "user_hash": sha256(str(row.user_id).encode("utf-8")).hexdigest()[:12],
                "ground_truth_movie_id": str(row.ground_truth_movie_id),
                "ground_truth_rank": int(row.ground_truth_rank),
                "recommended_movie_ids": str(row.recommended_movie_ids).split("|")[:top_k],
            }
        )
    return samples

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
            "tracing_enabled": True,
            "trace_schema_version": "1.0",
        }
    )

    # 평가 전체가 Trace 하나이며 아래 단계는 자동으로 부모·자식 Span 관계를 가진다.
    with start_traced_span("ott-recommendation-evaluation", "CHAIN", parent_run_id) as root_span:
        trace_id = getattr(root_span, "trace_id", getattr(root_span, "request_id", ""))
        root_span.set_inputs(
            {
                "source_tables": [f"{catalog}.{schema}.{name}" for name in table_names],
                "top_k": top_k,
                "holdout_count": holdout_count,
                "strategies": list(STRATEGY_WEIGHTS),
            }
        )
        root_span.set_attribute("project", "media-ott-recommendation")
        root_span.set_attribute("bundle_target", bundle_target)
        root_span.set_attribute("mlflow_version", mlflow.__version__)
        root_span.set_attribute("trace_schema_version", "1.0")
        root_span.set_attribute("contains_review_text", False)
        root_span.set_attribute("sample_user_identity", "sha256-prefix")
        if trace_id:
            mlflow.set_tag("mlflow_trace_id", trace_id)

        # 평가에 필요한 5개 테이블만 읽고 행 수만 Trace에 남긴다.
        with start_traced_span("load-unity-catalog-tables", "RETRIEVER") as load_span:
            load_span.set_inputs(
                {"tables": [f"{catalog}.{schema}.{name}" for name in table_names]}
            )
            frames = {
                table_name: spark.table(f"{catalog}.{schema}.{table_name}").toPandas()
                for table_name in table_names
            }
            source_rows = {table_name: int(len(frame)) for table_name, frame in frames.items()}
            load_span.set_outputs({"row_counts": source_rows, "table_count": len(table_names)})

        # 최신 긍정 작품을 정답으로 숨기고 해당 사용자·작품 쌍을 학습 데이터에서 제거한다.
        with start_traced_span("build-temporal-holdout", "CHAIN") as split_span:
            split_span.set_inputs(
                {
                    "holdout_count": holdout_count,
                    "minimum_train_positive_items": 2,
                    "completion_threshold": 80,
                    "rating_threshold": 4.0,
                }
            )
            split = build_temporal_holdout(frames, holdout_count=holdout_count)
            split_stats = split.stats
            split_span.set_outputs(split_stats)

        # TF-IDF 콘텐츠 특성, 사용자·작품 상호작용, 품질 점수를 한 번 준비해 재사용한다.
        with start_traced_span("build-recommendation-features", "CHAIN") as feature_span:
            feature_span.set_inputs(
                {
                    "movie_rows": int(len(split.frames["movies"])),
                    "user_rows": int(len(split.frames["users"])),
                    "train_viewing_rows": split_stats["train_viewing_rows"],
                    "train_user_review_rows": split_stats["train_user_review_rows"],
                }
            )
            engine = OfflineRecommendationEngine(split.frames)
            feature_span.set_outputs(
                {
                    "movies": len(engine.movie_ids),
                    "users": len(engine.user_ids),
                    "content_features": len(engine.feature_names),
                    "interaction_matrix_shape": list(engine.interaction_matrix.shape),
                }
            )

        # 전략별 Span에는 가중치, 집계 지표, 비식별 샘플 세 건만 저장한다.
        for strategy, weights in STRATEGY_WEIGHTS.items():
            with start_traced_span(f"evaluate-{strategy}", "CHAIN") as strategy_span:
                strategy_span.set_inputs(
                    {
                        "strategy": strategy,
                        "weights": weights,
                        "evaluated_users": len(split.holdouts),
                        "top_k": top_k,
                    }
                )
                metrics, detail_frame = evaluate_strategy(
                    engine,
                    split.holdouts,
                    strategy,
                    top_k=top_k,
                )
                summaries[strategy] = metrics
                detail_frames[strategy] = detail_frame
                strategy_span.set_outputs(
                    {"metrics": metrics, "sample_evaluations": trace_samples(detail_frame)}
                )

            # 기존 MLflow 전략별 Run과 Artifact 기록도 그대로 유지한다.
            with start_traced_span(f"log-{strategy}-mlflow-run", "CHAIN") as log_span:
                log_span.set_inputs({"strategy": strategy, "metric_count": len(metrics)})
                with mlflow.start_run(run_name=strategy, nested=True) as child_run:
                    child_run_ids[strategy] = child_run.info.run_id
                    if trace_id:
                        mlflow.set_tag("mlflow_trace_id", trace_id)
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
                    mlflow.log_text(
                        detail_frames[strategy].to_csv(index=False),
                        "per_user_metrics.csv",
                    )
                    mlflow.log_dict(metrics, "metric_summary.json")
                log_span.set_outputs(
                    {
                        "child_run_id": child_run_ids[strategy],
                        "artifacts": ["per_user_metrics.csv", "metric_summary.json"],
                    }
                )

        # 기본 우승 기준은 NDCG@K이며, 동률이면 Recall@K를 사용한다.
        with start_traced_span("select-best-strategy", "CHAIN") as selection_span:
            selection_span.set_inputs({"selection_metric": "ndcg_at_k", "metrics": summaries})
            best_strategy = max(
                summaries,
                key=lambda name: (summaries[name]["ndcg_at_k"], summaries[name]["recall_at_k"]),
            )
            best_metrics = summaries[best_strategy]
            selection_span.set_outputs(
                {
                    "best_strategy": best_strategy,
                    "best_ndcg_at_k": best_metrics["ndcg_at_k"],
                    "best_recall_at_k": best_metrics["recall_at_k"],
                }
            )

        with start_traced_span("log-evaluation-summary", "CHAIN") as summary_span:
            summary_span.set_inputs(
                {"best_strategy": best_strategy, "strategy_count": len(summaries)}
            )
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
                    "created_at_utc": run_timestamp,
                    "source_rows": source_rows,
                    "split_stats": split_stats,
                    "strategy_weights": STRATEGY_WEIGHTS,
                    "tracing": {
                        "enabled": True,
                        "trace_id": trace_id,
                        "contains_review_text": False,
                    },
                },
                "evaluation_config.json",
            )
            mlflow.log_dict(
                {
                    "best_strategy": best_strategy,
                    "selection_metric": "ndcg_at_k",
                    "strategies": summaries,
                    "child_run_ids": child_run_ids,
                    "trace_id": trace_id,
                },
                "strategy_comparison.json",
            )
            summary_span.set_outputs(
                {
                    "parent_run_id": parent_run_id,
                    "artifacts": ["evaluation_config.json", "strategy_comparison.json"],
                }
            )
        root_span.set_outputs(
            {
                "best_strategy": best_strategy,
                "best_metrics": best_metrics,
                "evaluated_users": split_stats["eligible_users"],
                "strategy_metrics": summaries,
            }
        )

# Notebook 종료 전에 비동기 Trace 전송을 비우고 실제 저장 여부를 확인한다.
mlflow.flush_trace_async_logging()
persisted_trace = mlflow.get_trace(trace_id) if trace_id else None
if persisted_trace is None:
    raise RuntimeError(f"MLflow Trace 저장을 확인하지 못했습니다: {trace_id or 'empty trace id'}")

result = {
    "status": "SUCCESS",
    "experiment_id": experiment_id,
    "parent_run_id": parent_run_id,
    "trace_id": trace_id,
    "trace_persisted": True,
    "mlflow_version": mlflow.__version__,
    "best_strategy": best_strategy,
    "top_k": top_k,
    "evaluated_users": split_stats["eligible_users"],
    "metrics": summaries,
    "child_run_ids": child_run_ids,
}
print(json.dumps(result, ensure_ascii=False, indent=2))
dbutils.notebook.exit(json.dumps(result, ensure_ascii=False))
