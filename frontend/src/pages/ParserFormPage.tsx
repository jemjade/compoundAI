// Parser Connector·상태 확인·Preset을 관리하는 관리자 Form이다.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, api } from "../lib/api";
import type { Parser, ParserPreset } from "../types";

const ADAPTERS = {
  BUILTIN: ["mock_parser", "pp_structure_v3"],
  HTTP: ["synap_http", "generic_http"],
  COMMAND: ["docling_command", "generic_command"],
} as const;

type ExecutionType = keyof typeof ADAPTERS;

export function ParserFormPage() {
  const { id } = useParams();
  const editing = Boolean(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [provider, setProvider] = useState("");
  const [modelName, setModelName] = useState("");
  const [modelVersion, setModelVersion] = useState("");
  const [executionType, setExecutionType] = useState<ExecutionType>("HTTP");
  const [adapterKey, setAdapterKey] = useState<string>("synap_http");
  const [baseUrl, setBaseUrl] = useState("");
  const [commandTemplate, setCommandTemplate] = useState(
    JSON.stringify(["docling", "{input_path}", "--output", "{output_dir}"], null, 2),
  );
  const [defaultConfig, setDefaultConfig] = useState("{}");
  const [configSchema, setConfigSchema] = useState("{}");
  const [formats, setFormats] = useState("pdf,docx,pptx");
  const [capabilities, setCapabilities] = useState("TEXT,MARKDOWN,TABLE,LAYOUT");
  const [timeout, setTimeoutValue] = useState(300);
  const [active, setActive] = useState(true);
  const [error, setError] = useState("");
  const [presetName, setPresetName] = useState("");
  const [presetConfig, setPresetConfig] = useState("{}");

  const parser = useQuery({
    queryKey: ["parser", id],
    queryFn: () => api<Parser>(`/parsers/${id}`),
    enabled: editing,
  });
  const presets = useQuery({
    queryKey: ["parser-presets", id],
    queryFn: () => api<ParserPreset[]>(`/parsers/${id}/presets`),
    enabled: editing,
  });

  useEffect(() => {
    if (!parser.data) return;
    const value = parser.data;
    setName(value.name);
    setSlug(value.slug);
    setDescription(value.description ?? "");
    setProvider(value.provider ?? "");
    setModelName(value.model_name ?? "");
    setModelVersion(value.model_version ?? "");
    setExecutionType(value.execution_type);
    setAdapterKey(value.adapter_key);
    setBaseUrl(value.base_url ?? "");
    setCommandTemplate(JSON.stringify(value.command_template ?? [], null, 2));
    setDefaultConfig(JSON.stringify(value.default_config, null, 2));
    setConfigSchema(JSON.stringify(value.config_schema, null, 2));
    setFormats(value.supported_formats.join(","));
    setCapabilities(value.capabilities.join(","));
    setTimeoutValue(value.timeout_seconds);
    setActive(value.is_active);
  }, [parser.data]);

  const save = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api<Parser>(editing ? `/parsers/${id}` : "/parsers", {
        method: editing ? "PATCH" : "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["parsers"] });
      navigate(`/parsers/${saved.id}`, { replace: true });
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : "Parser를 저장하지 못했습니다."),
  });
  const health = useMutation({
    mutationFn: () =>
      api<{ healthy: boolean; details: Record<string, unknown> }>(
        `/parsers/${id}/health-check`,
        { method: "POST" },
      ),
  });
  const createPreset = useMutation({
    mutationFn: () =>
      api<ParserPreset>(`/parsers/${id}/presets`, {
        method: "POST",
        body: JSON.stringify({
          name: presetName,
          config: JSON.parse(presetConfig),
        }),
      }),
    onSuccess: () => {
      setPresetName("");
      setPresetConfig("{}");
      queryClient.invalidateQueries({ queryKey: ["parser-presets", id] });
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : "Preset을 저장하지 못했습니다."),
  });
  const removePreset = useMutation({
    mutationFn: (presetId: string) =>
      api<void>(`/parser-presets/${presetId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["parser-presets", id] }),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      const payload = {
        name,
        slug,
        description: description || null,
        provider: provider || null,
        model_name: modelName || null,
        model_version: modelVersion || null,
        execution_type: executionType,
        adapter_key: adapterKey,
        base_url: executionType === "HTTP" ? baseUrl : null,
        command_template:
          executionType === "COMMAND" ? JSON.parse(commandTemplate) : null,
        default_config: JSON.parse(defaultConfig),
        config_schema: JSON.parse(configSchema),
        supported_formats: formats
          .split(",")
          .map((value) => value.trim().toLowerCase())
          .filter(Boolean),
        capabilities: capabilities
          .split(",")
          .map((value) => value.trim().toUpperCase())
          .filter(Boolean),
        timeout_seconds: timeout,
        ...(editing ? { is_active: active } : {}),
      };
      save.mutate(payload);
    } catch {
      setError("Command, Config 또는 Schema JSON 형식을 확인하세요.");
    }
  };

  return (
    <>
      <form onSubmit={submit}>
        <header className="page-header">
          <div>
            <Link to="/parsers" className="back-link">
              ← Parsers
            </Link>
            <span className="eyebrow">ADAPTER CONFIGURATION</span>
            <h1>{editing ? "Parser 설정" : "Parser 등록"}</h1>
            <p>HTTP와 Command 실행 정보는 Adapter Registry의 알려진 구현에만 연결됩니다.</p>
          </div>
          <div className="header-actions">
            {editing && (
              <button
                type="button"
                className="button ghost"
                onClick={() => health.mutate()}
                disabled={health.isPending}
              >
                Health check
              </button>
            )}
            <button className="button primary" disabled={save.isPending}>
              {save.isPending ? "저장 중…" : "설정 저장"}
            </button>
          </div>
        </header>
        {error && <div className="error-banner">{error}</div>}
        {health.data && (
          <div className={health.data.healthy ? "success-banner" : "error-banner"}>
            Health check: {health.data.healthy ? "healthy" : "unhealthy"} ·{" "}
            {JSON.stringify(health.data.details)}
          </div>
        )}
        <div className="config-layout">
          <section className="form-section compact-section">
            <span className="step-number">01</span>
            <div className="form-section-body">
              <h2>Identity</h2>
              <div className="field-grid">
                <label>
                  이름
                  <input value={name} onChange={(event) => setName(event.target.value)} required />
                </label>
                <label>
                  Slug
                  <input
                    value={slug}
                    onChange={(event) => setSlug(event.target.value)}
                    placeholder="synap-internal"
                    required
                  />
                </label>
                <label>
                  Provider
                  <input value={provider} onChange={(event) => setProvider(event.target.value)} />
                </label>
                <label>
                  Model
                  <input value={modelName} onChange={(event) => setModelName(event.target.value)} />
                </label>
                <label>
                  Version
                  <input
                    value={modelVersion}
                    onChange={(event) => setModelVersion(event.target.value)}
                  />
                </label>
                <label>
                  설명
                  <input
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </label>
              </div>
            </div>
          </section>
          <section className="form-section compact-section">
            <span className="step-number">02</span>
            <div className="form-section-body">
              <h2>Execution</h2>
              <div className="field-grid">
                <label>
                  실행 방식
                  <select
                    value={executionType}
                    onChange={(event) => {
                      const next = event.target.value as ExecutionType;
                      setExecutionType(next);
                      setAdapterKey(ADAPTERS[next][0]);
                    }}
                  >
                    <option value="BUILTIN">BUILTIN</option>
                    <option value="HTTP">HTTP</option>
                    <option value="COMMAND">COMMAND</option>
                  </select>
                </label>
                <label>
                  Adapter
                  <select value={adapterKey} onChange={(event) => setAdapterKey(event.target.value)}>
                    {ADAPTERS[executionType].map((adapter) => (
                      <option key={adapter}>{adapter}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Timeout (초)
                  <input
                    type="number"
                    min={1}
                    max={3600}
                    value={timeout}
                    onChange={(event) => setTimeoutValue(Number(event.target.value))}
                  />
                </label>
                <label>
                  지원 확장자
                  <input value={formats} onChange={(event) => setFormats(event.target.value)} />
                </label>
              </div>
              {executionType === "HTTP" && (
                <label className="full-field">
                  Base URL
                  <input
                    type="url"
                    value={baseUrl}
                    onChange={(event) => setBaseUrl(event.target.value)}
                    placeholder="http://synap.internal"
                    required
                  />
                </label>
              )}
              {executionType === "COMMAND" && (
                <label className="full-field">
                  Command Template JSON
                  <textarea
                    value={commandTemplate}
                    onChange={(event) => setCommandTemplate(event.target.value)}
                  />
                  <small>
                    허용 변수: {"{input_path}"}, {"{output_dir}"}, {"{config_path}"}
                  </small>
                </label>
              )}
            </div>
          </section>
          <section className="form-section compact-section">
            <span className="step-number">03</span>
            <div className="form-section-body">
              <h2>Configuration</h2>
              <label className="full-field">
                Capabilities
                <input
                  value={capabilities}
                  onChange={(event) => setCapabilities(event.target.value)}
                />
              </label>
              <div className="field-grid json-fields">
                <label>
                  Default Config JSON
                  <textarea
                    value={defaultConfig}
                    onChange={(event) => setDefaultConfig(event.target.value)}
                  />
                </label>
                <label>
                  Config Schema JSON
                  <textarea
                    value={configSchema}
                    onChange={(event) => setConfigSchema(event.target.value)}
                  />
                </label>
              </div>
              {editing && (
                <label className="active-check">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={(event) => setActive(event.target.checked)}
                  />
                  새 실험에서 이 Parser 사용
                </label>
              )}
            </div>
          </section>
        </div>
      </form>

      {editing && (
        <section className="section-block preset-section">
          <div className="section-title">
            <div>
              <span className="eyebrow">REUSABLE CONFIG</span>
              <h2>Presets</h2>
            </div>
          </div>
          <div className="preset-layout">
            <div className="preset-list">
              {presets.data?.map((preset) => (
                <article className="preset-card" key={preset.id}>
                  <div>
                    <strong>{preset.name}</strong>
                    <code>{JSON.stringify(preset.config)}</code>
                  </div>
                  <button
                    onClick={() => {
                      if (window.confirm(`${preset.name} Preset을 삭제할까요?`)) {
                        removePreset.mutate(preset.id);
                      }
                    }}
                  >
                    삭제
                  </button>
                </article>
              ))}
              {!presets.data?.length && <p className="muted">등록된 Preset이 없습니다.</p>}
            </div>
            <div className="preset-form">
              <label>
                Preset 이름
                <input
                  value={presetName}
                  onChange={(event) => setPresetName(event.target.value)}
                />
              </label>
              <label>
                Config JSON
                <textarea
                  value={presetConfig}
                  onChange={(event) => setPresetConfig(event.target.value)}
                />
              </label>
              <button
                className="button primary"
                onClick={() => {
                  setError("");
                  try {
                    JSON.parse(presetConfig);
                    createPreset.mutate();
                  } catch {
                    setError("Preset Config JSON 형식을 확인하세요.");
                  }
                }}
                disabled={!presetName || createPreset.isPending}
              >
                Preset 추가
              </button>
            </div>
          </div>
        </section>
      )}
    </>
  );
}
