import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { api } from "../lib/api";
import { formatDate, formatDuration } from "../lib/format";
import type { Experiment, ExperimentDetail, Run } from "../types";

type Filter = "ALL" | "ACTIVE" | "SUCCEEDED" | "FAILED" | "INTERRUPTED";

function stageLabel(run: Run) {
  if (run.parse_status === "PENDING") return "실행 슬롯 대기";
  if (run.parse_status === "RUNNING") return "문서 파싱";
  if (run.parse_status === "SUCCEEDED" && run.deidentification_status === "RUNNING") {
    return "비식별화";
  }
  if (run.parse_status === "SUCCEEDED" && run.deidentification_status === "PENDING") {
    return "비식별화 대기";
  }
  if (run.parse_status === "SUCCEEDED") return "산출물 생성 완료";
  if (run.parse_status === "FAILED") return "파서 실행 실패";
  return "작업 중단";
}

function displayStatus(run: Run) {
  if (run.parse_status === "SUCCEEDED" && ["PENDING", "RUNNING"].includes(run.deidentification_status)) {
    return run.deidentification_status;
  }
  if (run.parse_status === "SUCCEEDED" && run.deidentification_status === "FAILED") {
    return "PARTIALLY_COMPLETED";
  }
  return run.parse_status;
}

export function TasksPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("ALL");
  const experiments = useQuery({
    queryKey: ["experiments"],
    queryFn: () => api<Experiment[]>("/experiments"),
    refetchInterval: 4_000,
  });
  const detailQueries = useQueries({
    queries: (experiments.data ?? []).map((experiment) => ({
      queryKey: ["experiment", experiment.id],
      queryFn: () => api<ExperimentDetail>(`/experiments/${experiment.id}`),
      refetchInterval: ["PENDING", "RUNNING"].includes(experiment.status)
        ? 2_000
        : (false as const),
    })),
  });
  const cancel = useMutation({
    mutationFn: (runId: string) => api<Run>(`/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["experiment"] });
      queryClient.invalidateQueries({ queryKey: ["experiments"] });
    },
  });
  const retry = useMutation({
    mutationFn: (runId: string) => api<Run>(`/runs/${runId}/retry`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["experiment"] });
      queryClient.invalidateQueries({ queryKey: ["experiments"] });
    },
  });

  const tasks = useMemo(
    () =>
      detailQueries.flatMap((query) =>
        query.data
          ? query.data.runs.map((run) => ({
              run,
              experimentId: query.data.id,
              experimentName: query.data.name,
              document: query.data.document_filename,
              createdAt: query.data.created_at,
              runCount: query.data.runs.length,
            }))
          : [],
      ),
    [detailQueries],
  );
  const filtered = tasks.filter((task) => {
    const status = displayStatus(task.run);
    const query = search.trim().toLowerCase();
    const matchesSearch =
      !query ||
      task.experimentName.toLowerCase().includes(query) ||
      task.document.toLowerCase().includes(query) ||
      task.run.parser_snapshot.name.toLowerCase().includes(query) ||
      task.run.id.toLowerCase().includes(query);
    const matchesFilter =
      filter === "ALL" ||
      (filter === "ACTIVE" && ["PENDING", "RUNNING"].includes(status)) ||
      (filter === "FAILED" && ["FAILED", "PARTIALLY_COMPLETED"].includes(status)) ||
      status === filter;
    return matchesSearch && matchesFilter;
  });
  const activeCount = tasks.filter((task) =>
    ["PENDING", "RUNNING"].includes(displayStatus(task.run)),
  ).length;
  const failedCount = tasks.filter((task) =>
    ["FAILED", "PARTIALLY_COMPLETED"].includes(displayStatus(task.run)),
  ).length;
  const isLoading = experiments.isLoading || detailQueries.some((query) => query.isLoading);

  return (
    <>
      <PageHeader
        eyebrow="TASK ORCHESTRATION"
        title="Tasks"
        description="Parser 실행, 비식별화 단계와 결과 산출물을 하나의 작업 흐름에서 추적합니다."
        actions={
          <div className="header-actions">
            <Link className="button ghost" to="/experiments/new?mode=compare">
              <Icon name="compare" size={15} /> 비교 실행
            </Link>
            <Link className="button primary" to="/experiments/new?mode=single">
              <Icon name="plus" size={15} /> 단건 처리
            </Link>
          </div>
        }
      />

      <section className="task-summary" aria-label="작업 요약">
        <div>
          <span className="metric-kicker">All runs</span>
          <strong>{tasks.length}</strong>
          <small>전체 실행</small>
        </div>
        <div>
          <span className="metric-kicker active">In progress</span>
          <strong>{activeCount}</strong>
          <small>대기 또는 실행 중</small>
        </div>
        <div>
          <span className="metric-kicker success">Completed</span>
          <strong>{tasks.filter((task) => displayStatus(task.run) === "SUCCEEDED").length}</strong>
          <small>산출물 생성 완료</small>
        </div>
        <div>
          <span className="metric-kicker error">Needs attention</span>
          <strong>{failedCount}</strong>
          <small>실패 또는 일부 완료</small>
        </div>
      </section>

      <section className="workspace-panel">
        <div className="filter-bar">
          <label className="search-input">
            <Icon name="search" size={15} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Task, 문서, Parser 검색"
              aria-label="작업 검색"
            />
          </label>
          <div className="filter-tabs" aria-label="작업 상태 필터">
            {(["ALL", "ACTIVE", "SUCCEEDED", "FAILED", "INTERRUPTED"] as Filter[]).map((value) => (
              <button
                type="button"
                key={value}
                className={filter === value ? "active" : ""}
                onClick={() => setFilter(value)}
              >
                {value === "ALL"
                  ? "전체"
                  : value === "ACTIVE"
                    ? "실행 중"
                    : value === "SUCCEEDED"
                      ? "완료"
                      : value === "FAILED"
                        ? "주의 필요"
                        : "중단"}
              </button>
            ))}
          </div>
        </div>

        {cancel.isError && <div className="error-banner">작업을 취소하지 못했습니다: {cancel.error.message}</div>}
        {retry.isError && <div className="error-banner">작업을 재실행하지 못했습니다: {retry.error.message}</div>}

        {isLoading ? (
          <div className="task-table-skeleton" aria-label="작업을 불러오는 중">
            {Array.from({ length: 5 }, (_, index) => <span key={index} />)}
          </div>
        ) : filtered.length ? (
          <div className="task-table" role="table" aria-label="Parser 작업">
            <div className="task-table-head" role="row">
              <span>Task</span>
              <span>Document</span>
              <span>Parser</span>
              <span>Status</span>
              <span>Stage</span>
              <span>Started</span>
              <span>Duration</span>
              <span aria-label="Actions" />
            </div>
            {filtered.map((task) => {
              const status = displayStatus(task.run);
              const active = ["PENDING", "RUNNING"].includes(status);
              const retryable =
                ["FAILED", "INTERRUPTED"].includes(task.run.parse_status) ||
                (task.run.parse_status === "SUCCEEDED" &&
                  ["FAILED", "INTERRUPTED"].includes(task.run.deidentification_status));
              return (
                <div className={`task-row ${active ? "is-active" : ""}`} role="row" key={task.run.id}>
                  <div className="task-identity">
                    <Link to={`/experiments/${task.experimentId}`}>{task.experimentName}</Link>
                    <code title={task.run.id}>{task.run.id.slice(0, 8)}</code>
                  </div>
                  <span className="truncate" title={task.document}>{task.document}</span>
                  <div className="parser-cell">
                    <span className="parser-glyph">{task.run.parser_snapshot.name.slice(0, 1)}</span>
                    <span>
                      <strong>{task.run.parser_snapshot.name}</strong>
                      <small>{task.run.parser_snapshot.model_version ?? "default"}</small>
                    </span>
                  </div>
                  <StatusBadge status={status} />
                  <div className="task-stage">
                    <span>{stageLabel(task.run)}</span>
                    {active && (
                      <div className={`task-progress ${status === "RUNNING" ? "indeterminate" : ""}`}>
                        <i />
                      </div>
                    )}
                  </div>
                  <span>{task.run.started_at ? formatDate(task.run.started_at) : "대기 중"}</span>
                  <span className="mono">{formatDuration(task.run.latency_ms)}</span>
                  <div className="row-actions">
                    {active && (
                      <button
                        type="button"
                        className="icon-button danger"
                        aria-label={`${task.experimentName} 작업 취소`}
                        title="작업 취소"
                        onClick={() => {
                          if (window.confirm(`${task.experimentName}의 ${task.run.parser_snapshot.name} 작업을 취소할까요?`)) {
                            cancel.mutate(task.run.id);
                          }
                        }}
                        disabled={cancel.isPending}
                      >
                        <Icon name="stop" size={14} />
                      </button>
                    )}
                    {retryable && (
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`${task.experimentName} 작업 재실행`}
                        title="재실행"
                        onClick={() => retry.mutate(task.run.id)}
                        disabled={retry.isPending}
                      >
                        <Icon name="refresh" size={14} />
                      </button>
                    )}
                    <Link
                      className="icon-button"
                      to={`/experiments/${task.experimentId}`}
                      aria-label={`${task.experimentName} 상세 보기`}
                      title="상세 보기"
                    >
                      <Icon name="arrowRight" size={14} />
                    </Link>
                  </div>
                  {task.run.error_message && (
                    <details className="task-error-detail">
                      <summary>오류 요약 보기</summary>
                      <strong>{task.run.error_code}</strong>
                      <p>{task.run.error_message}</p>
                    </details>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState
            compact
            icon="tasks"
            title={tasks.length ? "조건에 맞는 작업이 없습니다" : "아직 실행된 작업이 없습니다"}
            description={tasks.length ? "검색어나 상태 필터를 변경해 보세요." : "문서와 Parser를 선택해 첫 작업을 실행하세요."}
            action={
              tasks.length ? (
                <button type="button" className="button ghost" onClick={() => { setSearch(""); setFilter("ALL"); }}>
                  필터 초기화
                </button>
              ) : (
                <Link className="button primary" to="/experiments/new?mode=single">작업 만들기</Link>
              )
            }
          />
        )}
      </section>
    </>
  );
}
