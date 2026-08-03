import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router";
import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { api } from "../lib/api";
import { formatDate, formatDuration } from "../lib/format";
import type {
  BenchmarkSummary,
  DocumentItem,
  GroundTruth,
  MetricAggregate,
} from "../types";

const qualityMetrics = [
  {
    key: "overall_quality",
    short: "Overall",
    label: "종합 품질",
    description: "측정 가능한 품질 차원만 동일 가중치로 평균",
  },
  {
    key: "text_accuracy",
    short: "Text",
    label: "본문 정확도",
    description: "Unicode 정규화 문자 편집 거리를 양쪽 길이로 정규화한 정확도",
  },
  {
    key: "layout_f1_iou50",
    short: "Layout",
    label: "레이아웃 F1",
    description: "동일 유형 블록을 IoU 0.5 기준으로 매칭한 F1",
  },
  {
    key: "table_teds",
    short: "Table",
    label: "표 TEDS",
    description: "Canonical 표 구조와 셀 내용을 반영한 TEDS-style 유사도",
  },
  {
    key: "reading_order_accuracy",
    short: "Order",
    label: "읽기 순서",
    description: "매칭 블록 순서의 역전쌍 비율 기반 정확도",
  },
  {
    key: "formula_accuracy",
    short: "Formula",
    label: "수식 정확도",
    description: "정규화 LaTeX 편집 거리 기반 정확도",
  },
  {
    key: "pii_f1",
    short: "PII",
    label: "PII F1",
    description: "유형·시작·끝 위치가 일치하는 민감정보 Span F1",
  },
] as const;

function percentage(value: number | null | undefined) {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
}

function confidence(metric: MetricAggregate | undefined) {
  if (!metric || metric.ci95_low === null || metric.ci95_high === null) return "표본 추가 필요";
  return `95% CI ${percentage(metric.ci95_low)}–${percentage(metric.ci95_high)}`;
}

export function EvaluationPage() {
  const queryClient = useQueryClient();
  const [documentId, setDocumentId] = useState("");
  const [groundTruthFile, setGroundTruthFile] = useState<File | null>(null);
  const [datasetName, setDatasetName] = useState("internal-golden");
  const [datasetVersion, setDatasetVersion] = useState("1.0");
  const summary = useQuery({
    queryKey: ["benchmark-summary"],
    queryFn: () => api<BenchmarkSummary>("/benchmarks/summary"),
  });
  const groundTruths = useQuery({
    queryKey: ["ground-truths"],
    queryFn: () => api<GroundTruth[]>("/benchmarks/ground-truths"),
  });
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<DocumentItem[]>("/documents"),
  });
  const recompute = useMutation({
    mutationFn: () =>
      api<{ evaluated_runs: number; skipped_runs: number }>("/benchmarks/recompute", {
        method: "POST",
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["benchmark-summary"] }),
  });
  const upload = useMutation({
    mutationFn: async () => {
      if (!documentId || !groundTruthFile) throw new Error("문서와 Ground Truth 파일을 선택하세요.");
      const body = new FormData();
      body.set("file", groundTruthFile);
      body.set("dataset_name", datasetName);
      body.set("dataset_version", datasetVersion);
      body.set("schema_version", "1.0");
      return api<GroundTruth>(`/benchmarks/documents/${documentId}/ground-truth`, {
        method: "PUT",
        body,
      });
    },
    onSuccess: () => {
      setGroundTruthFile(null);
      queryClient.invalidateQueries({ queryKey: ["ground-truths"] });
      queryClient.invalidateQueries({ queryKey: ["benchmark-summary"] });
    },
  });
  const data = summary.data;

  const submitGroundTruth = (event: FormEvent) => {
    event.preventDefault();
    upload.mutate();
  };

  return (
    <>
      <PageHeader
        eyebrow="GROUND-TRUTH BENCHMARK"
        title="Evaluation"
        description="정답 문서와 Parser 결과를 같은 Canonical 구조로 비교해 재현 가능한 품질 지표와 95% 신뢰구간을 계산합니다."
        actions={
          <>
            <button
              className="button ghost"
              type="button"
              disabled={recompute.isPending}
              onClick={() => recompute.mutate()}
            >
              <Icon name="refresh" size={14} />
              {recompute.isPending ? "계산 중…" : "전체 재계산"}
            </button>
            <Link className="button primary" to="/experiments/new">
              <Icon name="flask" size={15} /> Benchmark 실행
            </Link>
          </>
        }
      />

      {summary.isLoading ? (
        <div className="evaluation-loading"><span /><span /><span /></div>
      ) : summary.isError ? (
        <div className="error-state" role="alert">
          <Icon name="circleAlert" size={24} />
          <h2>정량 평가 결과를 불러오지 못했습니다</h2>
          <p>{summary.error.message}</p>
        </div>
      ) : (
        <>
          <section className="evaluation-overview quantitative-overview">
            <article className="evaluation-lead">
              <span className="eyebrow">VERSIONED SAMPLE SET</span>
              <div className="evaluation-lead-metric">
                <strong>{data?.evaluated_run_count ?? 0}</strong>
                <span>evaluated runs</span>
              </div>
              <p>
                Ground Truth {data?.ground_truth_document_count ?? 0}개 · Parser{" "}
                {data?.parsers.length ?? 0}개
              </p>
              <div className="evaluation-meta">
                <span><Icon name="check" size={13} /> evaluator v{data?.evaluator_version}</span>
                <span><Icon name="activity" size={13} /> 95% confidence interval</span>
              </div>
              <div className="dataset-tags">
                {(data?.dataset_versions ?? []).map((version) => (
                  <span key={version}>{version}</span>
                ))}
              </div>
            </article>
            <article className="score-card metric-catalog">
              <header>
                <div>
                  <span className="eyebrow">FORMAL METRICS</span>
                  <h2>품질 차원</h2>
                </div>
                <span className="score-scale">0 — 100%</span>
              </header>
              <div className="metric-definition-grid">
                {qualityMetrics.slice(1).map((metric) => (
                  <div key={metric.key}>
                    <strong>{metric.label}</strong>
                    <span>{metric.description}</span>
                  </div>
                ))}
              </div>
            </article>
          </section>

          <section className="workspace-panel ground-truth-panel">
            <div className="panel-header">
              <div>
                <span className="eyebrow">REFERENCE DATA</span>
                <h2>Ground Truth 등록</h2>
              </div>
              <span>Canonical JSON · 최대 25 MB</span>
            </div>
            <form onSubmit={submitGroundTruth}>
              <label>
                대상 문서
                <select
                  required
                  value={documentId}
                  onChange={(event) => setDocumentId(event.target.value)}
                >
                  <option value="">문서를 선택하세요</option>
                  {(documents.data ?? []).map((document) => (
                    <option value={document.id} key={document.id}>
                      {document.original_filename}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Dataset
                <input
                  required
                  value={datasetName}
                  onChange={(event) => setDatasetName(event.target.value)}
                />
              </label>
              <label>
                Version
                <input
                  required
                  value={datasetVersion}
                  onChange={(event) => setDatasetVersion(event.target.value)}
                />
              </label>
              <label className="ground-truth-file">
                정답 JSON
                <input
                  required
                  type="file"
                  accept="application/json,.json"
                  onChange={(event) => setGroundTruthFile(event.target.files?.[0] ?? null)}
                />
              </label>
              <button className="button primary" type="submit" disabled={upload.isPending}>
                <Icon name="upload" size={14} />
                {upload.isPending ? "검증·평가 중…" : "등록 후 자동 평가"}
              </button>
            </form>
            {(upload.isError || recompute.isError) && (
              <p className="form-error">
                {(upload.error ?? recompute.error)?.message}
              </p>
            )}
            <div className="ground-truth-list">
              {(groundTruths.data ?? []).map((truth) => (
                <div key={truth.id}>
                  <strong>{truth.document_filename}</strong>
                  <span>{truth.dataset_name}@{truth.dataset_version}</span>
                  <small>schema {truth.schema_version} · {formatDate(truth.updated_at)}</small>
                </div>
              ))}
            </div>
          </section>

          {data?.parsers.length ? (
            <>
              <section className="workspace-panel benchmark-matrix-panel">
                <div className="panel-header">
                  <div>
                    <span className="eyebrow">PARSER × METRIC</span>
                    <h2>정량 품질 비교</h2>
                  </div>
                  <span>버전·설정별 별도 집계</span>
                </div>
                <div className="benchmark-matrix">
                  <div className="benchmark-matrix-head">
                    <span>Parser</span>
                    {qualityMetrics.map((metric) => <span key={metric.key}>{metric.short}</span>)}
                    <span>p95</span>
                  </div>
                  {data.parsers.map((parser, index) => (
                    <div className="benchmark-matrix-row" key={parser.parser_key}>
                      <div>
                        <span className="benchmark-rank">{String(index + 1).padStart(2, "0")}</span>
                        <div>
                          <strong>{parser.parser_name}</strong>
                          <small>
                            {parser.parser_version ?? "default"} · cfg {parser.config_hash} · n=
                            {parser.run_count}
                          </small>
                        </div>
                      </div>
                      {qualityMetrics.map((metric) => {
                        const value = parser.metrics[metric.key];
                        return (
                          <span
                            className={metric.key === "overall_quality" ? "primary-metric" : ""}
                            key={metric.key}
                            title={`${metric.description} · ${confidence(value)}`}
                          >
                            <strong>{percentage(value?.value)}</strong>
                            <small>{value?.sample_count ? `n=${value.sample_count}` : "N/A"}</small>
                          </span>
                        );
                      })}
                      <span>
                        <strong>{formatDuration(parser.latency_p95_ms)}</strong>
                        <small>
                          {parser.pages_per_minute
                            ? `${parser.pages_per_minute.toFixed(1)} pages/min`
                            : "—"}
                        </small>
                      </span>
                    </div>
                  ))}
                </div>
              </section>

              <section className="workspace-panel evaluation-runs quantitative-runs">
                <div className="panel-header">
                  <div>
                    <span className="eyebrow">DOCUMENT-LEVEL RESULTS</span>
                    <h2>최근 자동 평가</h2>
                  </div>
                  <span>{data.recent_results.length} results</span>
                </div>
                <div className="evaluation-table">
                  <div className="evaluation-table-head">
                    <span>Experiment</span>
                    <span>Parser</span>
                    <span>Overall</span>
                    <span>Text</span>
                    <span>Layout</span>
                    <span>Table</span>
                    <span>Order</span>
                    <span />
                  </div>
                  {data.recent_results.map((result) => (
                    <div className="evaluation-table-row" key={result.run_id}>
                      <div>
                        <strong>{result.experiment_name}</strong>
                        <span title={result.document_filename}>{result.document_filename}</span>
                      </div>
                      <span className="mono">
                        {result.parser_name}
                        <small>{result.parser_version ?? "default"}</small>
                      </span>
                      <Metric value={result.metrics.overall_quality} />
                      <Metric value={result.metrics.text_accuracy} />
                      <Metric value={result.metrics.layout_f1_iou50} />
                      <Metric value={result.metrics.table_teds} />
                      <Metric value={result.metrics.reading_order_accuracy} />
                      <Link
                        className="icon-button"
                        to={`/experiments/${result.experiment_id}/compare`}
                        aria-label={`${result.experiment_name} 비교 열기`}
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
              title="정량 평가 결과가 없습니다"
              description="위에서 문서별 Canonical Ground Truth를 등록하면 이미 완료된 Run을 즉시 재평가하고 이후 실행도 자동 평가합니다."
              action={<Link className="button primary" to="/experiments/new">Benchmark 실행 만들기</Link>}
            />
          )}
        </>
      )}
    </>
  );
}

function Metric({ value }: { value: number | null | undefined }) {
  return (
    <span className={`evaluation-score ${typeof value === "number" && value >= 0.95 ? "best" : ""}`}>
      {percentage(value)}
    </span>
  );
}
