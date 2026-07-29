import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link } from "react-router";
import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { api } from "../lib/api";
import { formatDuration } from "../lib/format";
import type { Comparison, Experiment } from "../types";

const metricDefinitions = {
  text_score: "본문의 누락, 오인식과 전반적인 텍스트 품질에 대한 수동 평가",
  table_score: "셀 병합, 행·열 구조와 표 내용 보존에 대한 수동 평가",
  reading_order_score: "문서의 자연스러운 읽기 순서 재현에 대한 수동 평가",
  deidentification_score: "민감 정보 탐지와 마스킹 결과에 대한 수동 평가",
};

type ScoreKey = keyof typeof metricDefinitions;

function average(values: Array<number | null | undefined>) {
  const valid = values.filter((value): value is number => typeof value === "number");
  return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null;
}

export function EvaluationPage() {
  const experiments = useQuery({
    queryKey: ["experiments"],
    queryFn: () => api<Experiment[]>("/experiments"),
  });
  const eligible = (experiments.data ?? [])
    .filter((experiment) => ["COMPLETED", "PARTIALLY_COMPLETED"].includes(experiment.status))
    .slice(0, 12);
  const comparisons = useQueries({
    queries: eligible.map((experiment) => ({
      queryKey: ["comparison", experiment.id],
      queryFn: () => api<Comparison>(`/experiments/${experiment.id}/comparison`),
    })),
  });
  const runs = useMemo(
    () =>
      comparisons.flatMap((query, index) =>
        (query.data?.runs ?? []).map((run) => ({
          ...run,
          experimentId: eligible[index]?.id ?? "",
          experimentName: eligible[index]?.name ?? "",
          document: query.data?.document.filename ?? "",
        })),
      ),
    [comparisons, eligible],
  );
  const evaluated = runs.filter((run) => run.evaluation);
  const scoreKeys: ScoreKey[] = [
    "text_score",
    "table_score",
    "reading_order_score",
    "deidentification_score",
  ];
  const scores = scoreKeys.map((key) => ({
    key,
    value: average(evaluated.map((run) => run.evaluation?.[key])),
  }));
  const byParser = Object.values(
    evaluated.reduce<Record<string, { name: string; runs: typeof evaluated }>>((acc, run) => {
      acc[run.parser_name] ??= { name: run.parser_name, runs: [] };
      acc[run.parser_name].runs.push(run);
      return acc;
    }, {}),
  ).map((group) => ({
    ...group,
    score: average(
      group.runs.flatMap((run) =>
        scoreKeys.map((key) => run.evaluation?.[key]),
      ),
    ),
    latency: average(group.runs.map((run) => run.metrics.latency_ms)),
  })).sort((left, right) => (right.score ?? -1) - (left.score ?? -1));
  const loading = experiments.isLoading || comparisons.some((query) => query.isLoading);

  return (
    <>
      <PageHeader
        eyebrow="QUALITY BENCHMARK"
        title="Evaluation"
        description="실제 비교 실행에 저장된 수동 평가를 정확도와 처리 성능으로 분리해 해석합니다."
        actions={
          <Link className="button primary" to="/experiments/new">
            <Icon name="flask" size={15} /> 평가할 비교 실행
          </Link>
        }
      />

      {loading ? (
        <div className="evaluation-loading">
          <span />
          <span />
          <span />
        </div>
      ) : evaluated.length ? (
        <>
          <section className="evaluation-overview">
            <article className="evaluation-lead">
              <span className="eyebrow">EVALUATED SAMPLE SET</span>
              <div className="evaluation-lead-metric">
                <strong>{evaluated.length}</strong>
                <span>evaluated runs</span>
              </div>
              <p>
                {new Set(evaluated.map((run) => run.document)).size}개 문서 ·{" "}
                {new Set(evaluated.map((run) => run.parser_name)).size}개 Parser
              </p>
              <div className="evaluation-meta">
                <span><Icon name="check" size={13} /> 실제 저장 평가만 집계</span>
                <span><Icon name="activity" size={13} /> 5점 척도</span>
              </div>
            </article>
            <article className="score-card">
              <header>
                <div>
                  <span className="eyebrow">QUALITY DIMENSIONS</span>
                  <h2>평균 평가 점수</h2>
                </div>
                <span className="score-scale">0 — 5</span>
              </header>
              <div className="score-list">
                {scores.map((metric) => {
                  const label = {
                    text_score: "Text quality",
                    table_score: "Table structure",
                    reading_order_score: "Reading order",
                    deidentification_score: "PII masking",
                  }[metric.key];
                  return (
                    <div className="score-row" key={metric.key}>
                      <span title={metricDefinitions[metric.key]}>
                        {label} <Icon name="info" size={12} />
                      </span>
                      <div className="score-track">
                        <i style={{ width: `${((metric.value ?? 0) / 5) * 100}%` }} />
                      </div>
                      <strong>{metric.value?.toFixed(1) ?? "—"}</strong>
                    </div>
                  );
                })}
              </div>
            </article>
          </section>

          <section className="evaluation-grid">
            <article className="benchmark-panel">
              <header className="panel-header">
                <div>
                  <span className="eyebrow">PARSER BENCHMARK</span>
                  <h2>품질 비교</h2>
                </div>
                <span>수동 평가 평균</span>
              </header>
              <div className="parser-benchmark">
                {byParser.map((parser, index) => (
                  <div className="benchmark-row" key={parser.name}>
                    <span className="benchmark-rank">{String(index + 1).padStart(2, "0")}</span>
                    <div>
                      <strong>{parser.name}</strong>
                      <small>{parser.runs.length} evaluated runs</small>
                    </div>
                    <div className="benchmark-track">
                      <i style={{ width: `${((parser.score ?? 0) / 5) * 100}%` }} />
                    </div>
                    <strong>{parser.score?.toFixed(2) ?? "—"}</strong>
                    {index === 0 && <span className="best-label">BEST</span>}
                  </div>
                ))}
              </div>
            </article>
            <article className="latency-panel">
              <header className="panel-header">
                <div>
                  <span className="eyebrow">PERFORMANCE</span>
                  <h2>평균 처리 시간</h2>
                </div>
                <span>낮을수록 빠름</span>
              </header>
              <div className="latency-list">
                {byParser
                  .filter((parser) => parser.latency !== null)
                  .sort((left, right) => (left.latency ?? 0) - (right.latency ?? 0))
                  .map((parser) => (
                    <div key={parser.name}>
                      <span>{parser.name}</span>
                      <strong>{formatDuration(parser.latency)}</strong>
                    </div>
                  ))}
              </div>
              <p className="panel-note">
                정확도 점수와 latency는 서로 다른 척도이므로 같은 축에 혼합하지 않습니다.
              </p>
            </article>
          </section>

          <section className="workspace-panel evaluation-runs">
            <div className="panel-header">
              <div>
                <span className="eyebrow">RECENT REVIEWS</span>
                <h2>평가 실행</h2>
              </div>
              <span>{evaluated.length} results</span>
            </div>
            <div className="evaluation-table">
              <div className="evaluation-table-head">
                <span>Experiment</span>
                <span>Parser</span>
                <span>Text</span>
                <span>Table</span>
                <span>Order</span>
                <span>PII</span>
                <span>Latency</span>
                <span />
              </div>
              {evaluated.map((run) => (
                <div className="evaluation-table-row" key={run.run_id}>
                  <div>
                    <strong>{run.experimentName}</strong>
                    <span title={run.document}>{run.document}</span>
                  </div>
                  <span className="mono">{run.parser_name}</span>
                  <Score value={run.evaluation?.text_score} />
                  <Score value={run.evaluation?.table_score} />
                  <Score value={run.evaluation?.reading_order_score} />
                  <Score value={run.evaluation?.deidentification_score} />
                  <span>{formatDuration(run.metrics.latency_ms)}</span>
                  <Link
                    className="icon-button"
                    to={`/experiments/${run.experimentId}/compare`}
                    aria-label={`${run.experimentName} 비교 열기`}
                  >
                    <Icon name="arrowRight" size={14} />
                  </Link>
                </div>
              ))}
            </div>
          </section>
        </>
      ) : (
        <EmptyState
          icon="evaluation"
          title="저장된 평가가 없습니다"
          description="완료된 비교에서 Parser 결과를 검토하고 본문, 표, 읽기 순서, 비식별화 점수를 저장하면 여기에 집계됩니다."
          action={
            eligible[0] ? (
              <Link className="button primary" to={`/experiments/${eligible[0].id}/compare`}>
                최근 비교 평가하기
              </Link>
            ) : (
              <Link className="button primary" to="/experiments/new">비교 실행 만들기</Link>
            )
          }
        />
      )}
    </>
  );
}

function Score({ value }: { value: number | null | undefined }) {
  return <span className={`evaluation-score ${value === 5 ? "best" : ""}`}>{value ?? "—"}</span>;
}
