import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { api, downloadArtifact, downloadVendorArtifact } from "../lib/api";
import { formatBytes, formatDate, formatDuration } from "../lib/format";
import type { ExperimentDetail, Run } from "../types";

const isTerminal = (status?: string) =>
  ["COMPLETED", "PARTIALLY_COMPLETED", "FAILED"].includes(status ?? "");

function runStatus(run: Run) {
  if (
    run.parse_status === "SUCCEEDED" &&
    ["PENDING", "RUNNING"].includes(run.deidentification_status)
  ) {
    return run.deidentification_status;
  }
  if (run.parse_status === "SUCCEEDED" && run.deidentification_status === "FAILED") {
    return "PARTIALLY_COMPLETED";
  }
  return run.parse_status;
}

export function ExperimentPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const [singleDetailsOpen, setSingleDetailsOpen] = useState(true);
  const experiment = useQuery({
    queryKey: ["experiment", id],
    queryFn: () => api<ExperimentDetail>(`/experiments/${id}`),
    refetchInterval: (query) => (isTerminal(query.state.data?.status) ? false : 2_000),
  });
  const retry = useMutation({
    mutationFn: (runId: string) => api<Run>(`/runs/${runId}/retry`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["experiment", id] }),
  });
  const cancel = useMutation({
    mutationFn: (runId: string) => api<Run>(`/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["experiment", id] }),
  });
  const data = experiment.data;
  if (experiment.isError) {
    return (
      <div className="error-state" role="alert">
        <Icon name="circleAlert" size={24} />
        <h2>실험 정보를 불러오지 못했습니다</h2>
        <p>{experiment.error.message}</p>
        <button className="button ghost" type="button" onClick={() => experiment.refetch()}>
          <Icon name="refresh" size={14} /> 다시 시도
        </button>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="detail-skeleton" aria-label="실행 상태를 불러오는 중">
        <span /><span /><span /><span />
      </div>
    );
  }
  const successful = data.runs.filter((run) => run.parse_status === "SUCCEEDED").length;
  const settled = data.runs.filter((run) =>
    ["SUCCEEDED", "FAILED", "INTERRUPTED"].includes(run.parse_status),
  ).length;
  const progress = data.runs.length ? (settled / data.runs.length) * 100 : 0;
  const active = data.runs.filter((run) =>
    ["PENDING", "RUNNING"].includes(runStatus(run)),
  ).length;

  return (
    <>
      <PageHeader
        eyebrow="TASK DETAIL"
        title={data.name}
        description={`${data.document_filename} · ${formatDate(data.created_at)}`}
        actions={
          <>
            <StatusBadge status={data.status} />
            {data.runs.length >= 2 && (
              <Link
                className={`button primary ${successful < 2 ? "disabled" : ""}`}
                to={successful >= 2 ? `/experiments/${id}/compare` : "#"}
                aria-disabled={successful < 2}
              >
                <Icon name="compare" size={15} /> 결과 비교
              </Link>
            )}
          </>
        }
      >
        <Link to="/tasks" className="back-link">
          <Icon name="arrowLeft" size={14} /> Tasks
        </Link>
      </PageHeader>

      {(retry.isError || cancel.isError) && (
        <div className="error-banner" role="alert">
          작업 요청을 처리하지 못했습니다: {(retry.error ?? cancel.error)?.message}
        </div>
      )}

      <section className="experiment-progress">
        <div className="progress-overview">
          <div>
            <span className="eyebrow">EXECUTION PROGRESS</span>
            <strong>{settled} <small>/ {data.runs.length} runs settled</small></strong>
          </div>
          <div className="progress-status-copy">
            {active ? (
              <><span className="live-indicator" /> {active}개 작업 처리 중</>
            ) : (
              <><Icon name="check" size={14} /> 모든 작업 상태 확정</>
            )}
          </div>
        </div>
        <div className="progress-track large" aria-label={`실행 진행률 ${Math.round(progress)}%`}>
          <i style={{ width: `${progress}%` }} />
        </div>
        <div className="progress-legend">
          <span><i className="success" /> 성공 {successful}</span>
          <span><i className="active" /> 활성 {active}</span>
          <span><i className="error" /> 실패 {data.runs.filter((run) => run.parse_status === "FAILED").length}</span>
          {!isTerminal(data.status) && <small>2초마다 자동으로 동기화됩니다.</small>}
        </div>
      </section>

      <section className="run-list">
        <div className="section-title">
          <div>
            <span className="eyebrow">PARSER RUNS</span>
            <h2>실행 타임라인</h2>
          </div>
          <span className="result-count">{data.runs.length} runs</span>
        </div>
        {data.runs.map((run, index) => {
          const status = runStatus(run);
          const isActive = ["PENDING", "RUNNING"].includes(status);
          const retryable =
            ["FAILED", "INTERRUPTED"].includes(run.parse_status) ||
            (run.parse_status === "SUCCEEDED" &&
              ["FAILED", "INTERRUPTED"].includes(run.deidentification_status));
          return (
            <article className={`run-row ${isActive ? "is-active" : ""}`} key={run.id}>
              <div className="run-sequence">{String(index + 1).padStart(2, "0")}</div>
              <div className="run-main">
                <header className="run-row-head">
                  <div className="parser-cell large">
                    <span className="parser-glyph">{run.parser_snapshot.name.slice(0, 1)}</span>
                    <span>
                      <small>{run.parser_snapshot.model_name || "PARSER ENGINE"}</small>
                      <strong>{run.parser_snapshot.name}</strong>
                    </span>
                  </div>
                  <StatusBadge status={status} />
                </header>
                <div className="run-timeline">
                  <div className="done">
                    <span><Icon name="check" size={12} /></span>
                    <div><strong>Queued</strong><small>실행 등록</small></div>
                  </div>
                  <i />
                  <div className={run.parse_status === "RUNNING" ? "current" : run.parse_status === "SUCCEEDED" ? "done" : run.parse_status === "PENDING" ? "" : "failed"}>
                    <span><Icon name={run.parse_status === "SUCCEEDED" ? "check" : run.parse_status === "FAILED" ? "x" : "parser"} size={12} /></span>
                    <div><strong>Parse</strong><small>{run.parse_status}</small></div>
                  </div>
                  <i />
                  <div className={run.deidentification_status === "RUNNING" ? "current" : run.deidentification_status === "SUCCEEDED" || run.deidentification_status === "NOT_REQUESTED" ? "done" : run.deidentification_status === "FAILED" ? "failed" : ""}>
                    <span><Icon name={run.deidentification_status === "FAILED" ? "x" : "layers"} size={12} /></span>
                    <div><strong>De-identify</strong><small>{run.deidentification_status}</small></div>
                  </div>
                  <i />
                  <div className={run.parse_status === "SUCCEEDED" ? "done" : ""}>
                    <span><Icon name="file" size={12} /></span>
                    <div><strong>Artifacts</strong><small>{run.parse_status === "SUCCEEDED" ? "READY" : "WAITING"}</small></div>
                  </div>
                </div>
              </div>
              <dl className="run-summary">
                <div><dt>Started</dt><dd>{run.started_at ? formatDate(run.started_at) : "—"}</dd></div>
                <div><dt>Duration</dt><dd className="mono">{formatDuration(run.latency_ms)}</dd></div>
                <div><dt>Version</dt><dd className="mono">{run.parser_snapshot.model_version ?? "—"}</dd></div>
              </dl>
              <div className="run-actions">
                {isActive && (
                  <button
                    className="button ghost danger"
                    type="button"
                    onClick={() => {
                      if (window.confirm(`${run.parser_snapshot.name} 작업을 취소할까요?`)) {
                        cancel.mutate(run.id);
                      }
                    }}
                    disabled={cancel.isPending}
                  >
                    <Icon name="stop" size={14} /> 취소
                  </button>
                )}
                {retryable && (
                  <button
                    className="button ghost"
                    type="button"
                    onClick={() => retry.mutate(run.id)}
                    disabled={retry.isPending}
                  >
                    <Icon name="refresh" size={14} /> 재실행
                  </button>
                )}
              </div>

              {(run.error_message || run.deidentification || run.parse_status === "SUCCEEDED") && (
                <details
                  className="run-detail"
                  open={data.runs.length === 1 ? singleDetailsOpen : undefined}
                  onToggle={
                    data.runs.length === 1
                      ? (event) => setSingleDetailsOpen(event.currentTarget.open)
                      : undefined
                  }
                >
                  <summary>
                    <span>Run details & artifacts</span>
                    <Icon name="chevronDown" size={14} />
                  </summary>
                  <div className="run-detail-content">
                    {run.error_message && (
                      <div className="run-error">
                        <span><Icon name="circleAlert" size={15} /></span>
                        <div><strong>{run.error_code}</strong><p>{run.error_message}</p></div>
                      </div>
                    )}
                    {run.deidentification && (
                      <div className="deid-summary">
                        <div>
                          <span className="eyebrow">DE-IDENTIFICATION</span>
                          <strong>{run.deidentification.provider}</strong>
                        </div>
                        <span>Input <strong>{run.deidentification.input_type}</strong></span>
                        <span>Detected <strong>{run.deidentification.detected_entity_count ?? "—"}</strong></span>
                        <span>Masked <strong>{run.deidentification.masked_entity_count ?? "—"}</strong></span>
                        <span>Latency <strong>{formatDuration(run.deidentification.latency_ms)}</strong></span>
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
                            <Icon name="download" size={13} /> {artifact}
                          </button>
                        ))}
                        {run.deidentification_status === "SUCCEEDED" && (
                          <>
                            <button type="button" className="artifact-button" onClick={() => downloadArtifact(run.id, "deidentified")}>
                              <Icon name="download" size={13} /> deidentified
                            </button>
                            {run.deidentification?.masked_file_available && (
                              <button type="button" className="artifact-button" onClick={() => downloadArtifact(run.id, "masked")}>
                                <Icon name="download" size={13} /> masked file
                              </button>
                            )}
                          </>
                        )}
                        {(run.artifacts ?? []).map((artifact) => (
                          <button
                            type="button"
                            className="artifact-button vendor"
                            key={artifact.name}
                            title={`${artifact.source} · ${formatBytes(artifact.size_bytes)}`}
                            onClick={() => downloadVendorArtifact(run.id, artifact.name)}
                          >
                            <Icon name="download" size={13} />
                            {artifact.name}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </details>
              )}
            </article>
          );
        })}
      </section>
    </>
  );
}
