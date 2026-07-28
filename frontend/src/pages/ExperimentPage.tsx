// Run 상태·재실행·산출물을 Polling하는 실험 상세 화면이다.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { StatusBadge } from "../components/StatusBadge";
import { api, downloadArtifact } from "../lib/api";
import { formatDate, formatDuration } from "../lib/format";
import type { ExperimentDetail, Run } from "../types";

const isTerminal = (status?: string) =>
  ["COMPLETED", "PARTIALLY_COMPLETED", "FAILED"].includes(status ?? "");

export function ExperimentPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const experiment = useQuery({
    queryKey: ["experiment", id],
    queryFn: () => api<ExperimentDetail>(`/experiments/${id}`),
    refetchInterval: (query) => (isTerminal(query.state.data?.status) ? false : 2_000),
  });
  const retry = useMutation({
    mutationFn: (runId: string) => api<Run>(`/runs/${runId}/retry`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["experiment", id] }),
  });
  const data = experiment.data;
  if (!data) return <div className="loading-panel">실행 상태를 불러오는 중…</div>;
  const completed = data.runs.filter((run) => run.parse_status === "SUCCEEDED").length;

  return (
    <>
      <header className="page-header detail-header">
        <div>
          <Link to="/" className="back-link">
            ← Experiments
          </Link>
          <span className="eyebrow">EXPERIMENT DETAIL</span>
          <h1>{data.name}</h1>
          <p>
            {data.document_filename} · {formatDate(data.created_at)}
          </p>
        </div>
        <div className="header-actions">
          <StatusBadge status={data.status} />
          <Link
            className={`button primary ${completed < 2 ? "disabled" : ""}`}
            to={completed >= 2 ? `/experiments/${id}/compare` : "#"}
          >
            결과 비교
          </Link>
        </div>
      </header>
      <section className="progress-panel">
        <div>
          <span>
            {completed} / {data.runs.length} runs complete
          </span>
          <strong>{Math.round((completed / data.runs.length) * 100)}%</strong>
        </div>
        <div className="progress-track">
          <i style={{ width: `${(completed / data.runs.length) * 100}%` }} />
        </div>
        {!isTerminal(data.status) && <small>2초 간격으로 실행 상태를 갱신합니다.</small>}
      </section>
      <section className="run-grid">
        {data.runs.map((run) => (
          <article className="run-card" key={run.id}>
            <div className="run-card-head">
              <div>
                <span className="eyebrow">{run.parser_snapshot.model_name}</span>
                <h2>{run.parser_snapshot.name}</h2>
              </div>
              <StatusBadge status={run.parse_status} />
            </div>
            <dl className="run-metrics">
              <div>
                <dt>처리 시간</dt>
                <dd>{formatDuration(run.latency_ms)}</dd>
              </div>
              <div>
                <dt>비식별화</dt>
                <dd>
                  {run.deidentification_status === "NOT_REQUESTED" ? (
                    "미실행"
                  ) : (
                    <StatusBadge status={run.deidentification_status} />
                  )}
                </dd>
              </div>
              <div>
                <dt>Version</dt>
                <dd>{run.parser_snapshot.model_version ?? "—"}</dd>
              </div>
            </dl>
            {run.error_message && (
              <div className="run-error">
                <strong>{run.error_code}</strong>
                {run.error_message}
              </div>
            )}
            {run.deidentification && (
              <div className="deid-summary">
                <span>
                  <strong>{run.deidentification.provider}</strong>
                  {run.deidentification.input_type}
                </span>
                <span>
                  검출 {run.deidentification.detected_entity_count ?? "—"} · 마스킹{" "}
                  {run.deidentification.masked_entity_count ?? "—"} ·{" "}
                  {formatDuration(run.deidentification.latency_ms)}
                </span>
                {run.deidentification.error_message && (
                  <small>{run.deidentification.error_message}</small>
                )}
              </div>
            )}
            {run.parse_status === "SUCCEEDED" && (
              <div className="artifact-row">
                {["text", "markdown", "canonical", "raw"].map((artifact) => (
                  <button
                    type="button"
                    className="artifact-button"
                    key={artifact}
                    onClick={() => downloadArtifact(run.id, artifact)}
                  >
                    ↓ {artifact}
                  </button>
                ))}
                {run.deidentification_status === "SUCCEEDED" && (
                  <button
                    type="button"
                    className="artifact-button"
                    onClick={() => downloadArtifact(run.id, "deidentified")}
                  >
                    ↓ deidentified
                  </button>
                )}
              </div>
            )}
            {(["FAILED", "INTERRUPTED"].includes(run.parse_status) ||
              (run.parse_status === "SUCCEEDED" &&
                ["FAILED", "INTERRUPTED"].includes(run.deidentification_status))) && (
              <button className="button ghost wide" onClick={() => retry.mutate(run.id)}>
                ↻ 재실행
              </button>
            )}
          </article>
        ))}
      </section>
    </>
  );
}
