// Parser 병렬 비교·Diff·표·평가·내보내기 화면이다.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { JsonViewer } from "../components/JsonViewer";
import { MarkdownViewer } from "../components/MarkdownViewer";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import {
  api,
  downloadArtifact,
  downloadComparisonCsv,
  downloadDocument,
} from "../lib/api";
import { formatBytes, formatDuration } from "../lib/format";
import type {
  CanonicalTable,
  Comparison,
  ComparisonRun,
  ManualEvaluation,
  TextDiff,
} from "../types";

type ViewMode =
  | "rendered"
  | "text"
  | "markdown"
  | "canonical"
  | "tables"
  | "deidentified"
  | "diff";
type EvaluationPayload = Omit<ManualEvaluation, "id" | "run_id" | "evaluator_id">;

const modes: Array<{ value: ViewMode; label: string }> = [
  { value: "rendered", label: "Rendered" },
  { value: "text", label: "Text" },
  { value: "markdown", label: "Markdown source" },
  { value: "canonical", label: "Raw JSON" },
  { value: "tables", label: "Tables" },
  { value: "deidentified", label: "Deidentified" },
  { value: "diff", label: "Diff" },
];

const emptyEvaluation: EvaluationPayload = {
  text_score: null,
  table_score: null,
  reading_order_score: null,
  deidentification_score: null,
  is_preferred: false,
  notes: null,
};

export function ComparePage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<ViewMode>("rendered");
  const [wrap, setWrap] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);
  const [normalizeWhitespace, setNormalizeWhitespace] = useState(true);
  const [baseRunId, setBaseRunId] = useState("");
  const [targetRunId, setTargetRunId] = useState("");
  const comparison = useQuery({
    queryKey: ["comparison", id],
    queryFn: () => api<Comparison>(`/experiments/${id}/comparison`),
    // Parsing과 선택적 비식별화가 모두 종료된 후에만 Polling을 중지한다.
    refetchInterval: (query) =>
      query.state.data?.runs.some(
        (run) =>
          ["PENDING", "RUNNING"].includes(run.parse_status) ||
          ["PENDING", "RUNNING"].includes(run.deidentification_status),
      )
        ? 2_000
        : false,
  });
  const runs = useMemo(
    () => comparison.data?.runs.filter((run) => run.parse_status === "SUCCEEDED") ?? [],
    [comparison.data],
  );
  // Polling으로 기존 선택이 사라지거나 순서가 바뀌면 유효한 Run으로 대체한다.
  const resolvedBaseRunId =
    runs.some((run) => run.run_id === baseRunId) ? baseRunId : (runs[0]?.run_id ?? "");
  const resolvedTargetRunId =
    runs.some((run) => run.run_id === targetRunId && run.run_id !== resolvedBaseRunId)
      ? targetRunId
      : (runs.find((run) => run.run_id !== resolvedBaseRunId)?.run_id ?? "");
  const diff = useQuery({
    queryKey: [
      "text-diff",
      id,
      resolvedBaseRunId,
      resolvedTargetRunId,
      normalizeWhitespace,
    ],
    queryFn: () =>
      api<TextDiff>(
        `/experiments/${id}/text-diff?base_run_id=${resolvedBaseRunId}` +
          `&target_run_id=${resolvedTargetRunId}` +
          `&normalize_whitespace=${normalizeWhitespace}`,
      ),
    // 서로 다른 성공 Run 두 개가 준비되기 전에는 의미 없는 요청을 보내지 않는다.
    enabled:
      mode === "diff" &&
      Boolean(resolvedBaseRunId) &&
      Boolean(resolvedTargetRunId) &&
      resolvedBaseRunId !== resolvedTargetRunId,
  });
  const saveEvaluation = useMutation({
    mutationFn: ({
      runId,
      data,
    }: {
      runId: string;
      data: EvaluationPayload;
    }) =>
      api<ManualEvaluation>(`/runs/${runId}/evaluation`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["comparison", id] }),
  });
  const exportCsv = useMutation({
    mutationFn: () => downloadComparisonCsv(id),
  });

  useEffect(() => {
    if (!fullscreen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [fullscreen]);

  if (comparison.isError) {
    return (
      <div className="error-state" role="alert">
        <Icon name="circleAlert" size={24} />
        <h2>비교 결과를 불러오지 못했습니다</h2>
        <p>{comparison.error.message}</p>
        <button className="button ghost" type="button" onClick={() => comparison.refetch()}>
          <Icon name="refresh" size={14} /> 다시 시도
        </button>
      </div>
    );
  }
  if (!comparison.data) {
    return (
      <div className="comparison-skeleton" aria-label="비교 결과를 준비하는 중">
        <span /><span /><span />
      </div>
    );
  }

  return (
    <div className={`compare-page ${fullscreen ? "is-fullscreen" : ""}`}>
      <PageHeader
        eyebrow="COMPARISON WORKSPACE"
        title={comparison.data.document.filename}
        description={`${runs.length}개 Parser 결과 · 유사도는 정확도가 아닌 상대 일치도입니다.`}
        actions={
          <>
            <button
              type="button"
              className="button ghost"
              disabled={exportCsv.isPending}
              onClick={() => exportCsv.mutate()}
            >
              <Icon name="download" size={14} />
              {exportCsv.isPending ? "내보내는 중…" : "CSV 내보내기"}
            </button>
            <button
              type="button"
              className="button ghost"
              onClick={() => setFullscreen((current) => !current)}
              aria-pressed={fullscreen}
            >
              <Icon name={fullscreen ? "x" : "maximize"} size={14} />
              {fullscreen ? "집중 모드 닫기" : "집중 모드"}
            </button>
          </>
        }
      >
        {!fullscreen && (
          <Link to={`/experiments/${id}`} className="back-link">
            <Icon name="arrowLeft" size={14} /> Task detail
          </Link>
        )}
      </PageHeader>
      <div className="comparison-toolbar">
        <nav className="mode-switch comparison-modes" aria-label="비교 결과 유형">
          {modes.map((item) => (
            <button
              type="button"
              key={item.value}
              className={mode === item.value ? "active" : ""}
              onClick={() => setMode(item.value)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="comparison-options">
          {mode !== "diff" && mode !== "tables" && mode !== "rendered" && (
            <label className="switch-label compact-switch">
              <input type="checkbox" checked={wrap} onChange={() => setWrap(!wrap)} />
              <span />
              Wrap
            </label>
          )}
          <span><Icon name="activity" size={13} /> synchronized result context</span>
        </div>
      </div>
      {exportCsv.isError && (
        <div className="error-banner">CSV 파일을 내려받지 못했습니다.</div>
      )}
      <div className="compare-canvas">
        <aside className="source-panel">
          <header>
            <div>
              <span className="eyebrow">SOURCE DOCUMENT</span>
              <h2>Original</h2>
            </div>
            <span className="source-type">{comparison.data.document.filename.split(".").pop()?.toUpperCase()}</span>
          </header>
          <div className="source-preview">
            <div className="document-sheet">
              <span>01</span>
              <Icon name="document" size={34} />
              <strong>{comparison.data.document.filename}</strong>
              <p>원본 페이지 미리보기는 현재 API가 제공하지 않습니다.</p>
            </div>
          </div>
          <div className="source-footer">
            <button
              type="button"
              className="button ghost wide"
              onClick={() =>
                downloadDocument(
                  comparison.data.document.id,
                  comparison.data.document.filename,
                )
              }
            >
              <Icon name="download" size={14} /> 원본 다운로드
            </button>
            <p><Icon name="info" size={13} /> 결과는 동일한 원본 문서를 기준으로 정렬됩니다.</p>
          </div>
        </aside>

        <main className="results-canvas">
          {runs.length === 0 ? (
            <EmptyState
              compact
              icon="compare"
              title="비교 가능한 결과가 없습니다"
              description="성공한 Parser Run이 2개 이상 준비되면 결과를 비교할 수 있습니다."
              action={<Link className="button ghost" to={`/experiments/${id}`}>Task 상태 보기</Link>}
            />
          ) : mode === "diff" ? (
            <DiffView
              runs={runs}
              baseRunId={resolvedBaseRunId}
              targetRunId={resolvedTargetRunId}
              normalizeWhitespace={normalizeWhitespace}
              result={diff.data}
              loading={diff.isFetching}
              onBaseChange={setBaseRunId}
              onTargetChange={setTargetRunId}
              onNormalizeChange={setNormalizeWhitespace}
            />
          ) : (
            <section className={`comparison-grid cols-${Math.min(runs.length, 4)}`}>
              {runs.map((run) => (
                <article
                  className={`comparison-column ${run.evaluation?.is_preferred ? "preferred" : ""}`}
                  key={run.run_id}
                >
                  <div className="comparison-column-head">
                    {run.evaluation?.is_preferred && (
                      <span className="preferred-ribbon"><Icon name="sparkle" size={12} /> Preferred result</span>
                    )}
                    <div className="column-identity">
                      <span className="parser-glyph">{run.parser_name.slice(0, 1)}</span>
                      <div>
                        <span className="eyebrow">{run.parser_version || "DEFAULT PROFILE"}</span>
                        <h2>{run.parser_name}</h2>
                      </div>
                    </div>
                    <StatusBadge status={run.parse_status} compact />
                    <div className="metric-strip">
                      <span>
                        <strong>{formatDuration(run.metrics.latency_ms)}</strong>
                        Latency
                      </span>
                      <span><strong>{run.metrics.text_length.toLocaleString()}</strong>Characters</span>
                      <span><strong>{run.metrics.table_count}</strong>Tables</span>
                      <span><strong>{formatBytes(run.metrics.result_size_bytes)}</strong>Result size</span>
                      {mode === "deidentified" && (
                        <span><strong>{run.deidentification?.masked_entity_count ?? "—"}</strong>Masked</span>
                      )}
                    </div>
                  </div>
                  <RunContent run={run} mode={mode} wrap={wrap} />
                  <div className="comparison-downloads">
                    <button
                      disabled={mode === "deidentified" && !run.deidentified}
                      onClick={() =>
                        downloadArtifact(
                          run.run_id,
                          mode === "rendered" || mode === "markdown"
                            ? "markdown"
                            : mode === "tables"
                              ? "canonical"
                              : mode,
                        )
                      }
                    >
                      <Icon name="download" size={13} />
                      {mode === "rendered" ? "markdown" : mode === "tables" ? "canonical" : mode}
                    </button>
                  </div>
                  <EvaluationEditor
                    key={`${run.run_id}-${run.evaluation?.id ?? "new"}-${run.evaluation?.is_preferred}`}
                    run={run}
                    saving={saveEvaluation.isPending}
                    onSave={(data) => saveEvaluation.mutate({ runId: run.run_id, data })}
                  />
                </article>
              ))}
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

function RunContent({
  run,
  mode,
  wrap,
}: {
  run: ComparisonRun;
  mode: Exclude<ViewMode, "diff">;
  wrap: boolean;
}) {
  if (mode === "tables") return <TablesView tables={run.tables} />;
  if (mode === "rendered") return <MarkdownViewer value={run.markdown} />;
  if (mode === "canonical") return <JsonViewer value={run.canonical} />;
  const content =
    mode === "deidentified" ? run.deidentified : run[mode];
  return <pre className={wrap ? "wrap" : ""}>{content || "결과가 비어 있습니다."}</pre>;
}

function TablesView({ tables }: { tables: CanonicalTable[] }) {
  if (tables.length === 0) {
    return <div className="empty-result">추출된 표가 없습니다.</div>;
  }
  return (
    <div className="tables-view">
      {tables.map((table, index) => {
        // Canonical Cell의 행·열 병합 정보를 유지하도록 행 단위로 묶는다.
        const rows = new Map<number, typeof table.cells>();
        for (const cell of [...table.cells].sort((a, b) => a.column - b.column)) {
          rows.set(cell.row, [...(rows.get(cell.row) ?? []), cell]);
        }
        return (
          <section className="table-result" key={table.id ?? `${table.page_number}-${index}`}>
            <header>
              <strong>Table {index + 1}</strong>
              <span>Page {table.page_number ?? "—"}</span>
            </header>
            {table.cells.length ? (
              <div className="table-scroll">
                <table>
                  <tbody>
                    {[...rows.entries()]
                      .sort(([left], [right]) => left - right)
                      .map(([row, cells]) => (
                        <tr key={row}>
                          {cells.map((cell) => (
                            <td
                              key={`${cell.row}-${cell.column}`}
                              rowSpan={cell.row_span}
                              colSpan={cell.column_span}
                            >
                              {cell.text}
                            </td>
                          ))}
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <pre>{table.text || "표 텍스트가 비어 있습니다."}</pre>
            )}
          </section>
        );
      })}
    </div>
  );
}

function DiffView({
  runs,
  baseRunId,
  targetRunId,
  normalizeWhitespace,
  result,
  loading,
  onBaseChange,
  onTargetChange,
  onNormalizeChange,
}: {
  runs: ComparisonRun[];
  baseRunId: string;
  targetRunId: string;
  normalizeWhitespace: boolean;
  result: TextDiff | undefined;
  loading: boolean;
  onBaseChange: (value: string) => void;
  onTargetChange: (value: string) => void;
  onNormalizeChange: (value: boolean) => void;
}) {
  return (
    <section className="diff-panel">
      <div className="diff-controls">
        <label>
          기준 Run
          <select value={baseRunId} onChange={(event) => onBaseChange(event.target.value)}>
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {run.parser_name}
              </option>
            ))}
          </select>
        </label>
        <span className="diff-arrow">→</span>
        <label>
          비교 Run
          <select value={targetRunId} onChange={(event) => onTargetChange(event.target.value)}>
            {runs
              .filter((run) => run.run_id !== baseRunId)
              .map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {run.parser_name}
                </option>
              ))}
          </select>
        </label>
        <label className="toggle-label">
          <input
            type="checkbox"
            checked={normalizeWhitespace}
            onChange={(event) => onNormalizeChange(event.target.checked)}
          />
          공백·줄바꿈 정규화
        </label>
      </div>
      {loading && <div className="loading-panel">텍스트 차이를 계산하는 중…</div>}
      {!loading && result && (
        <>
          <div className="diff-stats">
            <span>
              <strong>{(result.similarity_ratio * 100).toFixed(1)}%</strong>
              텍스트 유사도
            </span>
            <span className="added">
              <strong>+{result.added_count.toLocaleString()}</strong>
              추가 문자
            </span>
            <span className="removed">
              <strong>−{result.removed_count.toLocaleString()}</strong>
              제거 문자
            </span>
          </div>
          <div className="diff-content">
            {result.diff.map((part, index) => (
              <span className={`diff-${part.type}`} key={`${index}-${part.type}`}>
                {part.text}
              </span>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function EvaluationEditor({
  run,
  saving,
  onSave,
}: {
  run: ComparisonRun;
  saving: boolean;
  onSave: (data: EvaluationPayload) => void;
}) {
  const [form, setForm] = useState<EvaluationPayload>({
    ...emptyEvaluation,
    ...run.evaluation,
  });
  useEffect(() => {
    // Query 무효화 후 저장된 평가가 돌아오면 로컬 Form 상태를 갱신한다.
    setForm({ ...emptyEvaluation, ...run.evaluation });
  }, [run.evaluation]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSave(form);
  };
  const scoreField = (
    key: keyof Pick<
      EvaluationPayload,
      "text_score" | "table_score" | "reading_order_score" | "deidentification_score"
    >,
    label: string,
  ) => (
    <label>
      {label}
      <select
        value={form[key] ?? ""}
        onChange={(event) =>
          setForm((current) => ({
            ...current,
            [key]: event.target.value ? Number(event.target.value) : null,
          }))
        }
      >
        <option value="">미평가</option>
        {[1, 2, 3, 4, 5].map((score) => (
          <option key={score} value={score}>
            {score}점
          </option>
        ))}
      </select>
    </label>
  );
  return (
    <details className="evaluation-panel" open={run.evaluation?.is_preferred}>
      <summary>
        <span>Manual Evaluation</span>
        <strong>{run.evaluation ? "평가 수정" : "평가하기"}</strong>
      </summary>
      <form onSubmit={submit}>
        <div className="evaluation-scores">
          {scoreField("text_score", "본문")}
          {scoreField("table_score", "표 구조")}
          {scoreField("reading_order_score", "읽기 순서")}
          {scoreField("deidentification_score", "비식별화")}
        </div>
        <label className="preferred-check">
          <input
            type="checkbox"
            checked={form.is_preferred}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                is_preferred: event.target.checked,
              }))
            }
          />
          이 실험의 선호 Parser로 지정
        </label>
        <label>
          평가 메모
          <textarea
            maxLength={4000}
            value={form.notes ?? ""}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                notes: event.target.value || null,
              }))
            }
            placeholder="표 병합, 읽기 순서, 비식별화 결과 등을 기록하세요."
          />
        </label>
        <button className="button primary wide" disabled={saving}>
          {saving ? "저장 중…" : "평가 저장"}
        </button>
      </form>
    </details>
  );
}
