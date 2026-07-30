import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link } from "react-router";
import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { api } from "../lib/api";
import { formatDate, formatDuration } from "../lib/format";
import type { DocumentItem, Experiment, ExperimentDetail, Parser } from "../types";

function dayKey(date: Date) {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

export function DashboardPage() {
  const experiments = useQuery({
    queryKey: ["experiments"],
    queryFn: () => api<Experiment[]>("/experiments"),
    refetchInterval: 4_000,
  });
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<DocumentItem[]>("/documents"),
  });
  const parsers = useQuery({
    queryKey: ["parsers"],
    queryFn: () => api<Parser[]>("/parsers"),
  });
  const details = useQueries({
    queries: (experiments.data ?? []).slice(0, 20).map((experiment) => ({
      queryKey: ["experiment", experiment.id],
      queryFn: () => api<ExperimentDetail>(`/experiments/${experiment.id}`),
      refetchInterval: ["PENDING", "RUNNING"].includes(experiment.status)
        ? 2_000
        : (false as const),
    })),
  });
  const runs = useMemo(
    () =>
      details.flatMap((query) =>
        query.data
          ? query.data.runs.map((run) => ({
              ...run,
              experimentId: query.data.id,
              experimentName: query.data.name,
              document: query.data.document_filename,
              createdAt: query.data.created_at,
            }))
          : [],
      ),
    [details],
  );
  const completedRuns = runs.filter((run) => run.parse_status === "SUCCEEDED");
  const failedRuns = runs.filter((run) => run.parse_status === "FAILED");
  const activeRuns = runs.filter(
    (run) =>
      ["PENDING", "RUNNING"].includes(run.parse_status) ||
      ["PENDING", "RUNNING"].includes(run.deidentification_status),
  );
  const successRate = runs.length ? (completedRuns.length / runs.length) * 100 : null;
  const averageLatency = completedRuns.length
    ? completedRuns.reduce((sum, run) => sum + (run.latency_ms ?? 0), 0) / completedRuns.length
    : null;
  const parserStats = Object.values(
    completedRuns.reduce<
      Record<string, { name: string; count: number; totalLatency: number; measured: number }>
    >((acc, run) => {
      const name = run.parser_snapshot.name;
      acc[name] ??= { name, count: 0, totalLatency: 0, measured: 0 };
      acc[name].count += 1;
      if (run.latency_ms !== null) {
        acc[name].totalLatency += run.latency_ms;
        acc[name].measured += 1;
      }
      return acc;
    }, {}),
  )
    .map((item) => ({
      ...item,
      average: item.measured ? item.totalLatency / item.measured : null,
    }))
    .sort((left, right) => right.count - left.count);
  const maxParserCount = Math.max(...parserStats.map((item) => item.count), 1);
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = new Date();
    date.setHours(0, 0, 0, 0);
    date.setDate(date.getDate() - (6 - index));
    const count = (experiments.data ?? [])
      .filter((experiment) => dayKey(new Date(experiment.created_at)) === dayKey(date))
      .reduce((sum, experiment) => sum + experiment.run_count, 0);
    return {
      label: new Intl.DateTimeFormat("ko-KR", { weekday: "short" }).format(date),
      count,
    };
  });
  const maxDailyCount = Math.max(...days.map((day) => day.count), 1);
  const initialLoading =
    experiments.isLoading || documents.isLoading || parsers.isLoading || details.some((query) => query.isLoading);
  const hasError = experiments.isError || documents.isError || parsers.isError;

  return (
    <>
      <PageHeader
        eyebrow="DOCUMENT INTELLIGENCE WORKSPACE"
        title="Overview"
        description="문서 단건 처리와 Parser 비교 실행 상태를 한눈에 확인하세요."
        actions={
          <div className="header-actions">
            <Link className="button ghost" to="/documents">
              <Icon name="upload" size={15} /> 문서 추가
            </Link>
            <Link className="button ghost" to="/experiments/new?mode=compare">
              <Icon name="compare" size={15} /> 새 비교
            </Link>
            <Link className="button primary" to="/experiments/new?mode=single">
              <Icon name="flask" size={15} /> 단건 처리
            </Link>
          </div>
        }
      />

      {hasError && (
        <div className="error-banner" role="alert">
          일부 워크스페이스 데이터를 불러오지 못했습니다. 연결 상태를 확인한 뒤 새로고침해 주세요.
        </div>
      )}

      <section className="overview-status">
        <article className="metric-card metric-card-primary">
          <div className="metric-card-heading">
            <span className="metric-kicker success">Run success rate</span>
            <Icon name="activity" size={18} />
          </div>
          <strong>{successRate === null ? "—" : `${successRate.toFixed(1)}%`}</strong>
          <p>{completedRuns.length} successful / {runs.length} total runs</p>
          <div className="metric-progress">
            <i style={{ width: `${successRate ?? 0}%` }} />
          </div>
        </article>
        <article className="metric-card">
          <span className="metric-kicker">Documents</span>
          <strong>{documents.data?.length ?? "—"}</strong>
          <p>분석 가능한 원본</p>
          <span className="metric-foot"><Icon name="document" size={13} /> Source library</span>
        </article>
        <article className="metric-card">
          <span className="metric-kicker active">Running now</span>
          <strong>{activeRuns.length}</strong>
          <p>대기 및 처리 중 작업</p>
          <Link className="metric-foot link" to="/tasks">Task monitor <Icon name="arrowRight" size={13} /></Link>
        </article>
        <article className="metric-card">
          <span className="metric-kicker">Average latency</span>
          <strong>{formatDuration(averageLatency)}</strong>
          <p>성공 Run 기준</p>
          <span className="metric-foot"><Icon name="clock" size={13} /> Parser execution</span>
        </article>
      </section>

      <section className="overview-insights">
        <article className="insight-panel throughput-panel">
          <header className="panel-header">
            <div>
              <span className="eyebrow">RUN VOLUME</span>
              <h2>최근 7일 처리량</h2>
            </div>
            <span>Runs / day</span>
          </header>
          <div className="throughput-summary">
            <strong>{days.reduce((sum, day) => sum + day.count, 0)}</strong>
            <span>runs this week</span>
          </div>
          <div className="bar-chart" aria-label="최근 7일 Run 처리량">
            {days.map((day) => (
              <div className="bar-item" key={day.label} title={`${day.label} ${day.count} runs`}>
                <span>{day.count || ""}</span>
                <div><i style={{ height: `${Math.max((day.count / maxDailyCount) * 100, 5)}%` }} /></div>
                <small>{day.label}</small>
              </div>
            ))}
          </div>
        </article>
        <article className="insight-panel parser-performance">
          <header className="panel-header">
            <div>
              <span className="eyebrow">PARSER PERFORMANCE</span>
              <h2>사용량과 평균 처리 시간</h2>
            </div>
            <Link to="/parsers">Registry <Icon name="arrowRight" size={12} /></Link>
          </header>
          {parserStats.length ? (
            <div className="parser-performance-list">
              {parserStats.slice(0, 5).map((parser) => (
                <div key={parser.name}>
                  <span className="parser-glyph">{parser.name.slice(0, 1)}</span>
                  <div>
                    <strong>{parser.name}</strong>
                    <span className="usage-track">
                      <i style={{ width: `${(parser.count / maxParserCount) * 100}%` }} />
                    </span>
                  </div>
                  <span>{parser.count} runs</span>
                  <strong>{formatDuration(parser.average)}</strong>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              compact
              icon="parser"
              title="아직 성능 데이터가 없습니다"
              description="첫 문서 처리가 완료되면 Parser별 실제 처리 시간이 표시됩니다."
            />
          )}
        </article>
      </section>

      <section className="overview-bottom">
        <article className="workspace-panel recent-activity">
          <header className="panel-header">
            <div>
              <span className="eyebrow">RECENT ACTIVITY</span>
              <h2>최근 실험</h2>
            </div>
            <Link to="/tasks">모든 작업 <Icon name="arrowRight" size={12} /></Link>
          </header>
          {initialLoading ? (
            <div className="table-skeleton" aria-label="최근 실험을 불러오는 중">
              <span /><span /><span /><span />
            </div>
          ) : experiments.data?.length ? (
            <div className="recent-table">
              <div className="recent-table-head">
                <span>Experiment</span>
                <span>Document</span>
                <span>Runs</span>
                <span>Status</span>
                <span>Created</span>
                <span />
              </div>
              {experiments.data.slice(0, 7).map((experiment) => (
                <Link
                  className="recent-table-row"
                  to={`/experiments/${experiment.id}`}
                  key={experiment.id}
                >
                  <strong>{experiment.name}</strong>
                  <span className="truncate" title={experiment.document_filename}>{experiment.document_filename}</span>
                  <span className="mono">{experiment.run_count}</span>
                  <StatusBadge status={experiment.status} compact />
                  <span>{formatDate(experiment.created_at)}</span>
                  <Icon name="arrowRight" size={14} />
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState
              compact
              icon="flask"
              title="아직 실험이 없습니다"
              description="문서와 Parser를 선택해 첫 작업을 실행하세요."
              action={<Link className="button primary" to="/experiments/new?mode=single">첫 작업 만들기</Link>}
            />
          )}
        </article>
        <aside className="system-panel">
          <header>
            <span className="eyebrow">SYSTEM STATUS</span>
            <span className="status status-succeeded"><Icon name="check" size={12} />Operational</span>
          </header>
          <h2>Workspace health</h2>
          <div className="system-list">
            <div><span><Icon name="activity" size={14} /> API connection</span><strong>Online</strong></div>
            <div><span><Icon name="parser" size={14} /> Active parsers</span><strong>{parsers.data?.filter((parser) => parser.is_active).length ?? "—"}</strong></div>
            <div><span><Icon name="circleAlert" size={14} /> Failed runs</span><strong className={failedRuns.length ? "error-text" : ""}>{failedRuns.length}</strong></div>
          </div>
          <p>실행 상태는 활성 작업이 끝날 때까지 2–4초 간격으로 자동 동기화됩니다.</p>
        </aside>
      </section>
    </>
  );
}
