// Adapter·상태·활성화 정보를 요약하는 Parser Registry 목록이다.
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { StatusBadge } from "../components/StatusBadge";
import { api } from "../lib/api";
import type { Parser, User } from "../types";

export function ParsersPage() {
  const [health, setHealth] = useState<Record<string, boolean>>({});
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
      api<{ healthy: boolean }>(`/parsers/${id}/health-check`, {
        method: "POST",
      }),
    onSuccess: (result, id) => setHealth((value) => ({ ...value, [id]: result.healthy })),
  });
  return (
    <>
      <header className="page-header">
        <div>
          <span className="eyebrow">ADAPTER REGISTRY</span>
          <h1>Parsers</h1>
          <p>비즈니스 흐름은 Adapter 구현과 분리되어 있습니다.</p>
        </div>
        <div className="header-actions">
          <span className="phase-pill">Phase 2 · HTTP / COMMAND</span>
          {me.data?.role === "ADMIN" && (
            <Link className="button primary" to="/parsers/new">
              ＋ Parser 등록
            </Link>
          )}
        </div>
      </header>
      <section className="parser-grid">
        {parsers.data?.map((parser) => (
          <article className="parser-card" key={parser.id}>
            <div className="parser-card-top">
              <span className="adapter-symbol">{parser.name.slice(0, 1)}</span>
              <StatusBadge
                status={
                  !parser.is_active
                    ? "INTERRUPTED"
                  : health[parser.id] === true
                    ? "SUCCEEDED"
                    : health[parser.id] === false
                      ? "FAILED"
                      : "PENDING"
                }
              />
            </div>
            <span className="eyebrow">{parser.provider}</span>
            <h2>{parser.name}</h2>
            <p>{parser.description}</p>
            <div className="tag-row">
              {parser.capabilities.map((capability) => (
                <span className="tag" key={capability}>
                  {capability}
                </span>
              ))}
            </div>
            <dl>
              <div>
                <dt>Adapter</dt>
                <dd>{parser.adapter_key}</dd>
              </div>
              <div>
                <dt>Version</dt>
                <dd>{parser.model_version}</dd>
              </div>
              <div>
                <dt>Formats</dt>
                <dd>{parser.supported_formats.join(", ")}</dd>
              </div>
            </dl>
            <button
              className="button ghost wide"
              onClick={() => check.mutate(parser.id)}
              disabled={check.isPending}
            >
              Health check
            </button>
            {me.data?.role === "ADMIN" && (
              <Link className="button ghost wide parser-edit-link" to={`/parsers/${parser.id}`}>
                설정 및 Preset
              </Link>
            )}
          </article>
        ))}
      </section>
    </>
  );
}
