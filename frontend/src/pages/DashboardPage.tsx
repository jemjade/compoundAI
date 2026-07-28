// Parser·문서·실험·Run 활동을 요약하는 Dashboard다.
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { EmptyState } from "../components/EmptyState";
import { StatusBadge } from "../components/StatusBadge";
import { api } from "../lib/api";
import { formatDate } from "../lib/format";
import type { DocumentItem, Experiment, Parser } from "../types";

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
  const runs = experiments.data?.reduce((sum, item) => sum + item.run_count, 0) ?? 0;

  return (
    <>
      <header className="page-header hero-header">
        <div>
          <span className="eyebrow">OVERVIEW</span>
          <h1>문서 처리 실험실</h1>
          <p>한 문서에 여러 파서를 실행하고 결과의 차이를 빠르게 찾습니다.</p>
        </div>
        <Link className="button primary" to="/experiments/new">
          ＋ 새 실험
        </Link>
      </header>

      <section className="stat-grid">
        <article className="stat-card accent">
          <span>Registered parsers</span>
          <strong>{parsers.data?.length ?? "—"}</strong>
          <small>비교 가능한 Adapter</small>
        </article>
        <article className="stat-card">
          <span>Documents</span>
          <strong>{documents.data?.length ?? "—"}</strong>
          <small>업로드된 원본 문서</small>
        </article>
        <article className="stat-card">
          <span>Parser runs</span>
          <strong>{runs}</strong>
          <small>누적 실행 단위</small>
        </article>
        <article className="stat-card">
          <span>Completed</span>
          <strong>
            {experiments.data?.filter((item) => item.status === "COMPLETED").length ?? "—"}
          </strong>
          <small>완료된 비교 실험</small>
        </article>
      </section>

      <section className="section-block">
        <div className="section-title">
          <div>
            <span className="eyebrow">RECENT ACTIVITY</span>
            <h2>최근 실험</h2>
          </div>
          <Link to="/experiments/new" className="text-link">
            실험 만들기 →
          </Link>
        </div>
        {experiments.isLoading ? (
          <div className="loading-panel">실험을 불러오는 중…</div>
        ) : experiments.data?.length ? (
          <div className="data-table">
            <div className="table-head">
              <span>실험</span>
              <span>문서</span>
              <span>Runs</span>
              <span>상태</span>
              <span>생성 시각</span>
            </div>
            {experiments.data.slice(0, 8).map((experiment) => (
              <Link
                className="table-row"
                to={`/experiments/${experiment.id}`}
                key={experiment.id}
              >
                <strong>{experiment.name}</strong>
                <span>{experiment.document_filename}</span>
                <span>{experiment.run_count}</span>
                <StatusBadge status={experiment.status} />
                <span>{formatDate(experiment.created_at)}</span>
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState
            title="아직 실험이 없습니다"
            description="문서를 업로드하고 두 Mock Parser의 결과를 비교해 보세요."
            action={
              <Link className="button primary" to="/experiments/new">
                첫 실험 만들기
              </Link>
            }
          />
        )}
      </section>
    </>
  );
}
