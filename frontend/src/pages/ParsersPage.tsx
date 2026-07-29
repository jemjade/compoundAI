import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { api } from "../lib/api";
import type { Parser, User } from "../types";

export function ParsersPage() {
  const [health, setHealth] = useState<Record<string, boolean>>({});
  const [search, setSearch] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/users/me"),
  });
  const parsers = useQuery({
    queryKey: ["parsers", me.data?.role],
    queryFn: () =>
      api<Parser[]>(`/parsers${me.data?.role === "ADMIN" ? "?include_inactive=true" : ""}`),
    enabled: Boolean(me.data),
  });
  const check = useMutation({
    mutationFn: (id: string) =>
      api<{ healthy: boolean }>(`/parsers/${id}/health-check`, { method: "POST" }),
    onSuccess: (result, id) => setHealth((value) => ({ ...value, [id]: result.healthy })),
  });
  const filtered = (parsers.data ?? []).filter((parser) => {
    const query = search.trim().toLowerCase();
    const matchesSearch =
      !query ||
      parser.name.toLowerCase().includes(query) ||
      parser.provider?.toLowerCase().includes(query) ||
      parser.adapter_key.toLowerCase().includes(query);
    return matchesSearch && (!activeOnly || parser.is_active);
  });

  return (
    <>
      <PageHeader
        eyebrow="MODEL & ADAPTER CATALOG"
        title="Parsers"
        description="Parser engine과 실행 profile을 구분하고 지원 형식, capability, 연결 상태를 관리합니다."
        actions={
          me.data?.role === "ADMIN" && (
            <Link className="button primary" to="/parsers/new">
              <Icon name="plus" size={15} /> Parser 등록
            </Link>
          )
        }
      />

      <section className="registry-summary">
        <div>
          <span className="metric-kicker">Registered</span>
          <strong>{parsers.data?.length ?? "—"}</strong>
          <small>Parser connectors</small>
        </div>
        <div>
          <span className="metric-kicker success">Available</span>
          <strong>{parsers.data?.filter((parser) => parser.is_active).length ?? "—"}</strong>
          <small>새 실행에 사용 가능</small>
        </div>
        <div>
          <span className="metric-kicker">Execution types</span>
          <strong>{new Set(parsers.data?.map((parser) => parser.execution_type)).size || "—"}</strong>
          <small>Builtin · HTTP · Command</small>
        </div>
      </section>

      <div className="filter-bar registry-filters">
        <label className="search-input">
          <Icon name="search" size={15} />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="이름, provider, adapter 검색"
            aria-label="Parser 검색"
          />
        </label>
        <label className="switch-label">
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={(event) => setActiveOnly(event.target.checked)}
          />
          <span />
          Available only
        </label>
        <span className="result-count">{filtered.length} parsers</span>
      </div>

      {check.isError && (
        <div className="error-banner" role="alert">
          Health check를 완료하지 못했습니다: {check.error.message}
        </div>
      )}

      {parsers.isLoading ? (
        <div className="parser-grid loading-grid" aria-label="Parser를 불러오는 중">
          <span /><span /><span /><span />
        </div>
      ) : filtered.length ? (
        <section className="parser-grid">
          {filtered.map((parser) => {
            const status = !parser.is_active
              ? "INTERRUPTED"
              : health[parser.id] === true
                ? "SUCCEEDED"
                : health[parser.id] === false
                  ? "FAILED"
                  : "PENDING";
            return (
              <article className="parser-card" key={parser.id}>
                <header className="parser-card-top">
                  <span className="adapter-symbol">{parser.name.slice(0, 1)}</span>
                  <StatusBadge status={status} />
                </header>
                <div className="parser-identity">
                  <span className="eyebrow">{parser.provider || "CUSTOM PROVIDER"}</span>
                  <h2>{parser.name}</h2>
                  <p>{parser.description || "설명이 등록되지 않은 Parser connector입니다."}</p>
                </div>
                <div className="engine-profile">
                  <div>
                    <span>Engine</span>
                    <strong>{parser.model_name || parser.adapter_key}</strong>
                  </div>
                  <div>
                    <span>Profile</span>
                    <strong>Default · {parser.model_version || "unversioned"}</strong>
                  </div>
                </div>
                <div className="tag-row">
                  {parser.capabilities.map((capability) => (
                    <span className="tag" key={capability}>{capability}</span>
                  ))}
                </div>
                <dl className="parser-specs">
                  <div><dt>Execution</dt><dd><code>{parser.execution_type}</code></dd></div>
                  <div><dt>Adapter</dt><dd><code>{parser.adapter_key}</code></dd></div>
                  <div><dt>Formats</dt><dd>{parser.supported_formats.join(" · ") || "—"}</dd></div>
                  <div><dt>Timeout</dt><dd>{parser.timeout_seconds}s</dd></div>
                </dl>
                <div className="parser-card-actions">
                  <button
                    className="button ghost"
                    type="button"
                    onClick={() => check.mutate(parser.id)}
                    disabled={check.isPending || !parser.is_active}
                  >
                    <Icon name="activity" size={14} />
                    {check.isPending && check.variables === parser.id ? "확인 중…" : "Health check"}
                  </button>
                  {me.data?.role === "ADMIN" && (
                    <Link
                      className="button ghost"
                      to={`/parsers/${parser.id}`}
                      aria-label={`${parser.name} 설정`}
                    >
                      <Icon name="settings" size={14} /> 설정
                    </Link>
                  )}
                </div>
              </article>
            );
          })}
        </section>
      ) : (
        <EmptyState
          icon="parser"
          title={parsers.data?.length ? "조건에 맞는 Parser가 없습니다" : "등록된 Parser가 없습니다"}
          description={parsers.data?.length ? "검색어 또는 available 필터를 변경하세요." : "문서 비교를 시작하려면 Parser connector가 필요합니다."}
          action={
            parsers.data?.length ? (
              <button className="button ghost" type="button" onClick={() => { setSearch(""); setActiveOnly(false); }}>필터 초기화</button>
            ) : me.data?.role === "ADMIN" ? (
              <Link className="button primary" to="/parsers/new">Parser 등록</Link>
            ) : undefined
          }
        />
      )}
    </>
  );
}
