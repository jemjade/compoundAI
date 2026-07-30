// 문서·Parser·Preset·파수를 설정하는 단계별 실험 생성 화면이다.
import { useMutation, useQueries, useQuery } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { EmptyState } from "../components/EmptyState";
import { ApiError, api } from "../lib/api";
import { formatBytes } from "../lib/format";
import type { DocumentItem, Parser, ParserPreset } from "../types";

type ExecutionMode = "single" | "compare";

const defaultName = (mode: ExecutionMode) =>
  mode === "single" ? "문서 단건 처리" : "Parser 비교";

export function NewExperimentPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialMode: ExecutionMode =
    searchParams.get("mode") === "compare" ? "compare" : "single";
  const [mode, setMode] = useState<ExecutionMode>(initialMode);
  const [name, setName] = useState(defaultName(initialMode));
  const [description, setDescription] = useState("");
  const [documentId, setDocumentId] = useState(searchParams.get("document") ?? "");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectionInitialized, setSelectionInitialized] = useState(false);
  const [presetByParser, setPresetByParser] = useState<Record<string, string>>({});
  const [overrideByParser, setOverrideByParser] = useState<Record<string, string>>({});
  const [runDeidentification, setRunDeidentification] = useState(true);
  const [error, setError] = useState("");
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<DocumentItem[]>("/documents"),
  });
  const parsers = useQuery({
    queryKey: ["parsers"],
    queryFn: () => api<Parser[]>("/parsers"),
  });
  const presetQueries = useQueries({
    queries: (parsers.data ?? []).map((parser) => ({
      queryKey: ["parser-presets", parser.id],
      queryFn: () => api<ParserPreset[]>(`/parsers/${parser.id}/presets`),
    })),
  });
  useEffect(() => {
    if (parsers.data?.length && !selectionInitialized) {
      setSelected(
        new Set(
          mode === "single"
            ? [parsers.data[0].id]
            : parsers.data.map((parser) => parser.id),
        ),
      );
      setSelectionInitialized(true);
    }
  }, [mode, parsers.data, selectionInitialized]);
  useEffect(() => {
    if (!documentId && documents.data?.[0]) setDocumentId(documents.data[0].id);
  }, [documentId, documents.data]);

  const create = useMutation({
    mutationFn: (
      parserRuns: Array<{
        parser_connector_id: string;
        parser_preset_id: string | null;
        config_override: Record<string, unknown>;
      }>,
    ) =>
      api<{ experiment_id: string }>("/experiments", {
        method: "POST",
        body: JSON.stringify({
          name,
          description: description || null,
          document_id: documentId,
          run_deidentification: runDeidentification,
          parser_runs: parserRuns,
        }),
      }),
    onSuccess: (result) => navigate(`/experiments/${result.experiment_id}`),
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : "실험을 만들지 못했습니다."),
  });
  const changeMode = (nextMode: ExecutionMode) => {
    if (nextMode === mode) return;
    setMode(nextMode);
    setError("");
    setName((current) => (current === defaultName(mode) ? defaultName(nextMode) : current));
    setSelected((current) => {
      if (nextMode === "compare" || current.size <= 1) return current;
      return new Set([[...current][0]]);
    });
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("mode", nextMode);
    setSearchParams(nextParams, { replace: true });
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (!documentId) {
      setError("처리할 문서를 선택하세요.");
      return;
    }
    if (mode === "single" && selected.size !== 1) {
      setError("단건 처리에 사용할 Parser 1개를 선택하세요.");
      return;
    }
    if (mode === "compare" && selected.size < 2) {
      setError("비교할 Parser를 2개 이상 선택하세요.");
      return;
    }
    try {
      const parserRuns = [...selected].map((parser_connector_id) => ({
        parser_connector_id,
        parser_preset_id: presetByParser[parser_connector_id] || null,
        config_override: JSON.parse(overrideByParser[parser_connector_id] || "{}") as Record<
          string,
          unknown
        >,
      }));
      create.mutate(parserRuns);
    } catch {
      setError("Parser Config Override JSON 형식을 확인하세요.");
    }
  };

  if (documents.data?.length === 0) {
    return (
      <EmptyState
        title="먼저 문서가 필요합니다"
        description="문서를 업로드한 뒤 Parser 단건 처리 또는 비교 실행을 시작할 수 있습니다."
        action={
          <Link className="button primary" to="/documents">
            문서 업로드
          </Link>
        }
      />
    );
  }

  return (
    <form onSubmit={submit}>
      <header className="page-header">
        <div>
          <span className="eyebrow">NEW TASK</span>
          <h1>{mode === "single" ? "문서 단건 처리" : "Parser 비교 실행"}</h1>
          <p>
            {mode === "single"
              ? "하나의 Parser로 문서를 처리하고 필요하면 Fasoo 비식별화까지 연속 실행합니다."
              : "같은 문서를 여러 Parser로 처리해 결과와 성능을 비교합니다."}
          </p>
        </div>
        <button className="button primary" disabled={create.isPending}>
          {create.isPending
            ? "등록 중…"
            : mode === "single"
              ? "단건 처리 실행 →"
              : "비교 실행 →"}
        </button>
      </header>
      {error && <div className="error-banner">{error}</div>}
      <div className="experiment-form">
        <section className="execution-mode-panel" aria-label="실행 방식">
          <button
            type="button"
            className={mode === "single" ? "active" : ""}
            onClick={() => changeMode("single")}
            aria-pressed={mode === "single"}
          >
            <strong>단건 처리</strong>
            <span>문서 1개 · Parser 1개</span>
          </button>
          <button
            type="button"
            className={mode === "compare" ? "active" : ""}
            onClick={() => changeMode("compare")}
            aria-pressed={mode === "compare"}
          >
            <strong>비교 실행</strong>
            <span>문서 1개 · Parser 2개 이상</span>
          </button>
        </section>
        <section className="form-section">
          <span className="step-number">01</span>
          <div className="form-section-body">
            <h2>작업 정보</h2>
            <div className="field-grid">
              <label>
                작업 이름
                <input value={name} onChange={(event) => setName(event.target.value)} required />
              </label>
              <label>
                설명
                <input
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="선택 사항"
                />
              </label>
            </div>
          </div>
        </section>
        <section className="form-section">
          <span className="step-number">02</span>
          <div className="form-section-body">
            <h2>원본 문서</h2>
            <div className="choice-grid">
              {documents.data?.map((document) => (
                <label
                  className={`choice-card ${documentId === document.id ? "selected" : ""}`}
                  key={document.id}
                >
                  <input
                    type="radio"
                    name="document"
                    checked={documentId === document.id}
                    onChange={() => setDocumentId(document.id)}
                  />
                  <span className="mini-file">{document.extension.toUpperCase()}</span>
                  <span>
                    <strong>{document.original_filename}</strong>
                    <small>{formatBytes(document.file_size)}</small>
                  </span>
                </label>
              ))}
            </div>
          </div>
        </section>
        <section className="form-section">
          <span className="step-number">03</span>
          <div className="form-section-body">
            <h2>{mode === "single" ? "사용할 Parser" : "비교할 Parser"}</h2>
            <p className="muted">
              {mode === "single"
                ? "Parser 1개를 선택하세요. Preset과 이번 Run 전용 Config를 설정할 수 있습니다."
                : "Parser를 2개 이상 선택하세요. Parser별 Preset과 Config를 설정할 수 있습니다."}
            </p>
            <div className="parser-choice-grid">
              {parsers.data?.map((parser, index) => (
                <div
                  className={`parser-choice-card ${selected.has(parser.id) ? "selected" : ""}`}
                  key={parser.id}
                >
                  <label className="parser-choice-head">
                    <input
                      type={mode === "single" ? "radio" : "checkbox"}
                      name={mode === "single" ? "parser" : undefined}
                      checked={selected.has(parser.id)}
                      onChange={() =>
                        setSelected((current) => {
                          if (mode === "single") return new Set([parser.id]);
                          const next = new Set(current);
                          if (next.has(parser.id)) next.delete(parser.id);
                          else next.add(parser.id);
                          return next;
                        })
                      }
                    />
                    <span className="adapter-symbol small">{parser.name.slice(0, 1)}</span>
                    <span>
                      <strong>{parser.name}</strong>
                      <small>
                        {parser.execution_type} · {parser.adapter_key}
                      </small>
                    </span>
                  </label>
                  {selected.has(parser.id) && (
                    <div className="parser-run-config">
                      <label>
                        Preset
                        <select
                          value={presetByParser[parser.id] ?? ""}
                          onChange={(event) =>
                            setPresetByParser((current) => ({
                              ...current,
                              [parser.id]: event.target.value,
                            }))
                          }
                        >
                          <option value="">Default config</option>
                          {presetQueries[index]?.data?.map((preset) => (
                            <option key={preset.id} value={preset.id}>
                              {preset.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Config Override JSON
                        <textarea
                          value={overrideByParser[parser.id] ?? "{}"}
                          onChange={(event) =>
                            setOverrideByParser((current) => ({
                              ...current,
                              [parser.id]: event.target.value,
                            }))
                          }
                        />
                      </label>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </section>
        <section className="form-section">
          <span className="step-number">04</span>
          <div className="form-section-body">
            <h2>비식별화</h2>
            <label
              className={`deidentification-option ${runDeidentification ? "selected" : ""}`}
            >
              <input
                type="checkbox"
                checked={runDeidentification}
                onChange={(event) => setRunDeidentification(event.target.checked)}
              />
              <span>
                <strong>파싱 후 비식별화 실행</strong>
                <small>
                  현재 설정에 따라 Mock Fasoo 또는 Fasoo HTTP Adapter를 사용합니다. 비식별화
                  실패는 파싱 성공 상태에 영향을 주지 않습니다.
                </small>
              </span>
            </label>
          </div>
        </section>
      </div>
    </form>
  );
}
