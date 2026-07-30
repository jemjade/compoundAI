// Parser Connector·상태 확인·Preset을 관리하는 관리자 Form이다.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, api } from "../lib/api";
import type { Parser, ParserPreset } from "../types";

const ADAPTERS = {
  BUILTIN: ["mock_parser", "pp_structure_v3"],
  HTTP: ["mineru_http", "docling_http", "generic_http", "synap_http"],
  COMMAND: ["docling_command", "generic_command"],
} as const;

type ExecutionType = keyof typeof ADAPTERS;

type ParserTemplate = {
  name: string;
  slug: string;
  description: string;
  provider: string;
  modelName: string;
  modelVersion: string;
  baseUrl?: string;
  commandTemplate?: string[];
  defaultConfig: Record<string, unknown>;
  configSchema: Record<string, unknown>;
  formats: string[];
  capabilities: string[];
  timeout: number;
};

const PARSER_TEMPLATES: Partial<Record<string, ParserTemplate>> = {
  pp_structure_v3: {
    name: "PaddleOCR PP-StructureV3",
    slug: "pp-structure-v3",
    description: "PaddleOCR 3.x 기반 로컬 문서 구조 분석 Parser",
    provider: "PaddlePaddle",
    modelName: "PP-StructureV3",
    modelVersion: "3.7.x",
    defaultConfig: {
      use_doc_orientation_classify: true,
      use_doc_unwarping: true,
      use_textline_orientation: true,
      use_table_recognition: true,
      use_formula_recognition: false,
      use_chart_recognition: false,
      use_seal_recognition: false,
    },
    configSchema: {
      type: "object",
      properties: {
        use_doc_orientation_classify: { type: "boolean" },
        use_doc_unwarping: { type: "boolean" },
        use_textline_orientation: { type: "boolean" },
        use_table_recognition: { type: "boolean" },
        use_formula_recognition: { type: "boolean" },
        use_chart_recognition: { type: "boolean" },
        use_seal_recognition: { type: "boolean" },
      },
      additionalProperties: false,
    },
    formats: ["pdf", "png", "jpg", "jpeg", "webp"],
    capabilities: ["TEXT", "MARKDOWN", "TABLE", "LAYOUT", "OCR"],
    timeout: 1800,
  },
  mineru_http: {
    name: "MinerU 3.x",
    slug: "mineru-3",
    description: "MinerU 3.x 공식 mineru-api 기반 문서 구조 분석 Parser",
    provider: "OpenDataLab",
    modelName: "MinerU",
    modelVersion: "3.x",
    baseUrl: "http://mineru:8000",
    defaultConfig: {
      backend: "pipeline",
      effort: "medium",
      parse_method: "auto",
      lang_list: ["korean"],
      formula_enable: true,
      table_enable: true,
      image_analysis: false,
      start_page_id: 0,
      end_page_id: 99999,
    },
    configSchema: {
      type: "object",
      properties: {
        backend: {
          type: "string",
          enum: ["hybrid-engine", "pipeline", "vlm-engine"],
        },
        effort: { type: "string", enum: ["medium", "high"] },
        parse_method: { type: "string", enum: ["auto", "ocr", "txt"] },
        lang_list: {
          type: "array",
          items: { type: "string", minLength: 1 },
          minItems: 1,
        },
        formula_enable: { type: "boolean" },
        table_enable: { type: "boolean" },
        image_analysis: { type: "boolean" },
        start_page_id: { type: "integer", minimum: 0 },
        end_page_id: { type: "integer", minimum: 0 },
      },
      additionalProperties: false,
    },
    formats: ["pdf", "png", "jpg", "jpeg", "webp", "docx", "pptx", "xlsx"],
    capabilities: ["TEXT", "MARKDOWN", "TABLE", "LAYOUT", "OCR", "FORMULA"],
    timeout: 1800,
  },
  docling_http: {
    name: "Docling",
    slug: "docling",
    description: "Docling Serve v1 기반 문서 변환 및 구조 분석 Parser",
    provider: "LF AI & Data",
    modelName: "Docling",
    modelVersion: "2.x",
    baseUrl: "http://docling:5001",
    defaultConfig: {
      do_ocr: true,
      force_ocr: false,
      ocr_lang: ["ko", "en"],
      table_mode: "accurate",
      image_export_mode: "placeholder",
    },
    configSchema: {
      type: "object",
      properties: {
        do_ocr: { type: "boolean" },
        force_ocr: { type: "boolean" },
        ocr_lang: {
          type: "array",
          items: { type: "string", minLength: 1 },
        },
        table_mode: { type: "string", enum: ["fast", "accurate"] },
        image_export_mode: {
          type: "string",
          enum: ["placeholder", "embedded", "referenced"],
        },
      },
      additionalProperties: false,
    },
    formats: [
      "pdf",
      "docx",
      "pptx",
      "xlsx",
      "html",
      "md",
      "txt",
      "png",
      "jpg",
      "jpeg",
      "tiff",
    ],
    capabilities: ["TEXT", "MARKDOWN", "TABLE", "LAYOUT", "OCR"],
    timeout: 900,
  },
  docling_command: {
    name: "Docling",
    slug: "docling",
    description: "Docling 2.x 로컬 문서 변환 및 구조 분석 Parser",
    provider: "LF AI & Data",
    modelName: "Docling",
    modelVersion: "2.x",
    commandTemplate: [
      "docling",
      "convert",
      "{input_path}",
      "--to",
      "md",
      "--to",
      "json",
      "--output",
      "{output_dir}",
    ],
    defaultConfig: {},
    configSchema: { type: "object", additionalProperties: false },
    formats: [
      "pdf",
      "docx",
      "pptx",
      "xlsx",
      "html",
      "md",
      "txt",
      "png",
      "jpg",
      "jpeg",
      "tiff",
    ],
    capabilities: ["TEXT", "MARKDOWN", "TABLE", "LAYOUT", "OCR"],
    timeout: 900,
  },
};
const DEFAULT_TEMPLATE = PARSER_TEMPLATES.mineru_http as ParserTemplate;

export function ParserFormPage() {
  const { id } = useParams();
  const editing = Boolean(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState(DEFAULT_TEMPLATE.name);
  const [slug, setSlug] = useState(DEFAULT_TEMPLATE.slug);
  const [description, setDescription] = useState(DEFAULT_TEMPLATE.description);
  const [provider, setProvider] = useState(DEFAULT_TEMPLATE.provider);
  const [modelName, setModelName] = useState(DEFAULT_TEMPLATE.modelName);
  const [modelVersion, setModelVersion] = useState(DEFAULT_TEMPLATE.modelVersion);
  const [executionType, setExecutionType] = useState<ExecutionType>("HTTP");
  const [adapterKey, setAdapterKey] = useState<string>("mineru_http");
  const [baseUrl, setBaseUrl] = useState(DEFAULT_TEMPLATE.baseUrl ?? "");
  const [commandTemplate, setCommandTemplate] = useState(
    JSON.stringify(DEFAULT_TEMPLATE.commandTemplate ?? [], null, 2),
  );
  const [defaultConfig, setDefaultConfig] = useState(
    JSON.stringify(DEFAULT_TEMPLATE.defaultConfig, null, 2),
  );
  const [configSchema, setConfigSchema] = useState(
    JSON.stringify(DEFAULT_TEMPLATE.configSchema, null, 2),
  );
  const [formats, setFormats] = useState(DEFAULT_TEMPLATE.formats.join(","));
  const [capabilities, setCapabilities] = useState(
    DEFAULT_TEMPLATE.capabilities.join(","),
  );
  const [timeout, setTimeoutValue] = useState(DEFAULT_TEMPLATE.timeout);
  const [active, setActive] = useState(true);
  const [error, setError] = useState("");
  const [presetName, setPresetName] = useState("");
  const [presetConfig, setPresetConfig] = useState("{}");

  const applyAdapterTemplate = (nextAdapter: string) => {
    setAdapterKey(nextAdapter);
    const template = PARSER_TEMPLATES[nextAdapter];
    if (!template || editing) return;
    setName(template.name);
    setSlug(template.slug);
    setDescription(template.description);
    setProvider(template.provider);
    setModelName(template.modelName);
    setModelVersion(template.modelVersion);
    setBaseUrl(template.baseUrl ?? "");
    setCommandTemplate(JSON.stringify(template.commandTemplate ?? [], null, 2));
    setDefaultConfig(JSON.stringify(template.defaultConfig, null, 2));
    setConfigSchema(JSON.stringify(template.configSchema, null, 2));
    setFormats(template.formats.join(","));
    setCapabilities(template.capabilities.join(","));
    setTimeoutValue(template.timeout);
  };

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
                      applyAdapterTemplate(ADAPTERS[next][0]);
                    }}
                  >
                    <option value="BUILTIN">BUILTIN</option>
                    <option value="HTTP">HTTP</option>
                    <option value="COMMAND">COMMAND</option>
                  </select>
                </label>
                <label>
                  Adapter
                  <select
                    value={adapterKey}
                    onChange={(event) => applyAdapterTemplate(event.target.value)}
                  >
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
                    placeholder={
                      adapterKey === "mineru_http"
                        ? "http://mineru:8000"
                        : adapterKey === "docling_http"
                          ? "http://docling:5001"
                        : "http://parser.internal"
                    }
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
