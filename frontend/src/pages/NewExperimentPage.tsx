// 문서·Parser·Preset·파수를 설정하는 단계별 실험 생성 화면이다.
import { useMutation, useQueries, useQuery } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { EmptyState } from "../components/EmptyState";
import { ApiError, api } from "../lib/api";
import { formatBytes } from "../lib/format";
import type { DocumentItem, Parser, ParserPreset } from "../types";

export function NewExperimentPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [name, setName] = useState("Mock Parser 비교");
  const [description, setDescription] = useState("");
  const [documentId, setDocumentId] = useState(searchParams.get("document") ?? "");
  const [selected, setSelected] = useState<Set<string>>(new Set());
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
    if (parsers.data?.length && selected.size === 0) {
      setSelected(new Set(parsers.data.map((parser) => parser.id)));
    }
  }, [parsers.data, selected.size]);
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
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (!documentId || selected.size < 2) {
      setError("문서 1개와 비교할 Parser 2개 이상을 선택하세요.");
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
        description="실험은 하나의 원본 문서와 2개 이상의 Parser로 구성됩니다."
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
          <span className="eyebrow">NEW EXPERIMENT</span>
          <h1>비교 실험 만들기</h1>
          <p>API는 Run을 DB에 기록한 뒤 즉시 응답하고 작업은 백그라운드에서 실행됩니다.</p>
        </div>
        <button className="button primary" disabled={create.isPending}>
          {create.isPending ? "등록 중…" : "실험 실행 →"}
        </button>
      </header>
      {error && <div className="error-banner">{error}</div>}
      <div className="experiment-form">
        <section className="form-section">
          <span className="step-number">01</span>
          <div className="form-section-body">
            <h2>실험 정보</h2>
            <div className="field-grid">
              <label>
                실험 이름
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
            <h2>비교할 Parser</h2>
            <p className="muted">
              Parser별 Preset을 선택하고 이번 Run에만 적용할 Config를 덮어쓸 수 있습니다.
            </p>
            <div className="parser-choice-grid">
              {parsers.data?.map((parser, index) => (
                <div
                  className={`parser-choice-card ${selected.has(parser.id) ? "selected" : ""}`}
                  key={parser.id}
                >
                  <label className="parser-choice-head">
                    <input
                      type="checkbox"
                      checked={selected.has(parser.id)}
                      onChange={() =>
                        setSelected((current) => {
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
