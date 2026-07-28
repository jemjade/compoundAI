// Parser 병렬 비교·Diff·표·평가·내보내기 화면이다.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { StatusBadge } from "../components/StatusBadge";
import { api, downloadArtifact, downloadComparisonCsv } from "../lib/api";
import { formatBytes, formatDuration } from "../lib/format";
import type {
  CanonicalTable,
  Comparison,
  ComparisonRun,
  ManualEvaluation,
  TextDiff,
} from "../types";

type ViewMode = "text" | "markdown" | "canonical" | "tables" | "deidentified" | "diff";
type EvaluationPayload = Omit<ManualEvaluation, "id" | "run_id" | "evaluator_id">;

const modes: Array<{ value: ViewMode; label: string }> = [
  { value: "text", label: "Text" },
  { value: "markdown", label: "Markdown" },
  { value: "canonical", label: "JSON" },
  { value: "tables", label: "Tables" },
  { value: "deidentified", label: "Deidentified" },
  { value: "diff", label: "Text Diff" },
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
  const [mode, setMode] = useState<ViewMode>("text");
  const [wrap, setWrap] = useState(true);
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

  if (!comparison.data) return <div className="loading-panel">비교 결과를 준비하는 중…</div>;

  return (
    <div className="compare-page">
      <header className="page-header compare-header">
        <div>
          <Link to={`/experiments/${id}`} className="back-link">
            ← Experiment
          </Link>
          <span className="eyebrow">SIDE-BY-SIDE · PHASE 4</span>
          <h1>{comparison.data.document.filename}</h1>
          <p>{runs.length}개 Parser 결과 비교 · 유사도는 정확도가 아닌 상대 일치도입니다.</p>
        </div>
        <button
          type="button"
          className="button ghost"
          disabled={exportCsv.isPending}
          onClick={() => exportCsv.mutate()}
        >
          ↓ 비교 결과 CSV
        </button>
      </header>
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
      <div className="compare-toolbar">
        {mode !== "diff" && mode !== "tables" && (
          <label className="toggle-label">
            <input type="checkbox" checked={wrap} onChange={() => setWrap(!wrap)} />
            줄바꿈
          </label>
        )}
        <span>
          {mode === "diff"
            ? "기준과 비교 Run을 선택해 상대적인 텍스트 차이를 확인합니다."
            : "각 Parser의 결과와 운영 지표, 수동 평가를 함께 확인합니다."}
        </span>
      </div>
      {exportCsv.isError && (
        <div className="error-banner">CSV 파일을 내려받지 못했습니다.</div>
      )}
      {mode === "diff" ? (
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
        <section
          className="comparison-grid"
          style={{
            gridTemplateColumns: `repeat(${Math.max(runs.length, 1)}, minmax(340px, 1fr))`,
          }}
        >
          {runs.map((run) => (
            <article
              className={`comparison-column ${run.evaluation?.is_preferred ? "preferred" : ""}`}
              key={run.run_id}
            >
              <div className="comparison-column-head">
                {run.evaluation?.is_preferred && (
                  <span className="preferred-ribbon">★ Preferred</span>
                )}
                <div>
                  <span className="eyebrow">{run.parser_version}</span>
                  <h2>{run.parser_name}</h2>
                </div>
                <StatusBadge status={run.parse_status} />
                <div className="metric-strip">
                  <span>
                    <strong>{formatDuration(run.metrics.latency_ms)}</strong>
                    처리 시간
                  </span>
                  <span>
                    <strong>{run.metrics.text_length.toLocaleString()}</strong>
                    글자
                  </span>
                  <span>
                    <strong>{run.metrics.table_count}</strong>
                    Tables
                  </span>
                  <span>
                    <strong>{formatBytes(run.metrics.result_size_bytes)}</strong>
                    결과 크기
                  </span>
                  {mode === "deidentified" && (
                    <span>
                      <strong>{run.deidentification?.masked_entity_count ?? "—"}</strong>
                      Masked
                    </span>
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
                      mode === "tables" ? "canonical" : mode,
                    )
                  }
                >
                  ↓ {mode === "tables" ? "canonical" : mode}
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
  const content =
    mode === "canonical"
      ? run.canonical
        ? JSON.stringify(run.canonical, null, 2)
        : null
      : run[mode];
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
