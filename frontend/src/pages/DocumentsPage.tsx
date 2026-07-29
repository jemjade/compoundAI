import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ChangeEvent, type DragEvent, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { EmptyState } from "../components/EmptyState";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { api, downloadDocument } from "../lib/api";
import { formatBytes, formatDate } from "../lib/format";
import type { DocumentItem, Experiment } from "../types";

const accepted = ".pdf,.docx,.pptx,.xlsx,.txt,.md,.png,.jpg,.jpeg,.webp";

export function DocumentsPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const [dragging, setDragging] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<DocumentItem[]>("/documents"),
  });
  const experiments = useQuery({
    queryKey: ["experiments"],
    queryFn: () => api<Experiment[]>("/experiments"),
  });
  const upload = useMutation({
    mutationFn: (file: File) => {
      const data = new FormData();
      data.append("file", file);
      return api<DocumentItem>("/documents", { method: "POST", body: data });
    },
    onSuccess: (document) => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      setSelectedId(document.id);
    },
  });
  const choose = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) upload.mutate(file);
    event.target.value = "";
  };
  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) upload.mutate(file);
  };
  const filtered = (documents.data ?? []).filter((document) =>
    document.original_filename.toLowerCase().includes(search.trim().toLowerCase()),
  );
  const selected =
    documents.data?.find((document) => document.id === selectedId) ?? null;
  const selectedHistory = useMemo(
    () =>
      (experiments.data ?? []).filter(
        (experiment) => experiment.document_id === selected?.id,
      ),
    [experiments.data, selected?.id],
  );
  const latestByDocument = useMemo(() => {
    const result = new Map<string, Experiment>();
    for (const experiment of experiments.data ?? []) {
      if (!result.has(experiment.document_id)) result.set(experiment.document_id, experiment);
    }
    return result;
  }, [experiments.data]);

  return (
    <>
      <PageHeader
        eyebrow="SOURCE LIBRARY"
        title="Documents"
        description="원본 문서를 안전하게 보관하고 Parser 비교 이력과 연결해 관리합니다."
        actions={
          <button className="button primary" type="button" onClick={() => inputRef.current?.click()}>
            <Icon name="upload" size={15} />
            {upload.isPending ? "업로드 중…" : "문서 업로드"}
          </button>
        }
      />
      <input hidden ref={inputRef} type="file" accept={accepted} onChange={choose} />
      {upload.isError && (
        <div className="error-banner" role="alert">
          문서를 업로드하지 못했습니다: {upload.error.message}
        </div>
      )}

      <div
        className={`compact-dropzone ${dragging ? "is-dragging" : ""}`}
        onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => {
          if (event.currentTarget === event.target) setDragging(false);
        }}
        onDrop={drop}
      >
        <span className="dropzone-icon"><Icon name="upload" size={18} /></span>
        <div>
          <strong>문서를 이곳에 놓아 바로 업로드</strong>
          <span>PDF, Office, image, text · 파일당 1개씩</span>
        </div>
        <button type="button" className="button ghost compact" onClick={() => inputRef.current?.click()}>
          파일 선택
        </button>
      </div>

      <section className="document-workspace">
        <div className="workspace-panel document-list-panel">
          <div className="filter-bar">
            <label className="search-input">
              <Icon name="search" size={15} />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="문서명 검색"
                aria-label="문서 검색"
              />
            </label>
            <span className="result-count">{filtered.length} documents</span>
          </div>
          {documents.isLoading ? (
            <div className="table-skeleton" aria-label="문서를 불러오는 중">
              <span /><span /><span /><span /><span />
            </div>
          ) : filtered.length ? (
            <div className="document-table" role="table" aria-label="문서 목록">
              <div className="document-table-head">
                <span>Document</span>
                <span>Pages</span>
                <span>Size</span>
                <span>Uploaded</span>
                <span>Latest run</span>
                <span />
              </div>
              {filtered.map((document) => {
                const latest = latestByDocument.get(document.id);
                return (
                  <button
                    type="button"
                    className={`document-table-row ${selected?.id === document.id ? "selected" : ""}`}
                    key={document.id}
                    onClick={() => setSelectedId(document.id)}
                  >
                    <span className="document-identity">
                      <span className={`file-type file-${document.extension}`}>
                        <Icon name="file" size={18} />
                      </span>
                      <span className="document-name">
                        <strong title={document.original_filename}>{document.original_filename}</strong>
                        <small>.{document.extension} · <code>{document.sha256.slice(0, 10)}</code></small>
                      </span>
                    </span>
                    <span>{document.page_count ?? "—"}</span>
                    <span>{formatBytes(document.file_size)}</span>
                    <span>{formatDate(document.created_at)}</span>
                    <span>{latest ? <StatusBadge status={latest.status} compact /> : "—"}</span>
                    <span className="row-chevron"><Icon name="arrowRight" size={14} /></span>
                  </button>
                );
              })}
            </div>
          ) : (
            <EmptyState
              compact
              icon="document"
              title={documents.data?.length ? "검색 결과가 없습니다" : "비교할 문서를 올려주세요"}
              description={documents.data?.length ? "다른 문서명으로 검색해 보세요." : "지원 파일을 업로드하면 즉시 비교 실험에 사용할 수 있습니다."}
              action={
                documents.data?.length ? (
                  <button className="button ghost" type="button" onClick={() => setSearch("")}>검색 초기화</button>
                ) : (
                  <button className="button primary" type="button" onClick={() => inputRef.current?.click()}>문서 선택</button>
                )
              }
            />
          )}
        </div>

        {selected ? (
          <aside className="document-detail" aria-label={`${selected.original_filename} 상세`}>
            <header>
              <span className={`file-type large file-${selected.extension}`}>
                <Icon name="file" size={22} />
              </span>
              <button
                type="button"
                className="icon-button"
                aria-label="상세 패널 닫기"
                onClick={() => setSelectedId(null)}
              >
                <Icon name="x" size={15} />
              </button>
            </header>
            <h2 title={selected.original_filename}>{selected.original_filename}</h2>
            <p>{selected.mime_type}</p>
            <div className="detail-actions">
              <Link className="button primary" to={`/experiments/new?document=${selected.id}`}>
                <Icon name="flask" size={14} /> 비교 실행
              </Link>
              <button
                type="button"
                className="button ghost"
                onClick={() => downloadDocument(selected.id, selected.original_filename)}
              >
                <Icon name="download" size={14} /> 원본
              </button>
            </div>
            <section>
              <span className="eyebrow">METADATA</span>
              <dl className="metadata-list">
                <div><dt>Format</dt><dd>{selected.extension.toUpperCase()}</dd></div>
                <div><dt>Pages</dt><dd>{selected.page_count ?? "—"}</dd></div>
                <div><dt>File size</dt><dd>{formatBytes(selected.file_size)}</dd></div>
                <div><dt>Uploaded</dt><dd>{formatDate(selected.created_at)}</dd></div>
                <div><dt>Document ID</dt><dd><code title={selected.id}>{selected.id.slice(0, 12)}</code></dd></div>
                <div><dt>SHA-256</dt><dd><code title={selected.sha256}>{selected.sha256.slice(0, 12)}</code></dd></div>
              </dl>
            </section>
            <section>
              <div className="detail-section-title">
                <span className="eyebrow">PARSING HISTORY</span>
                <span>{selectedHistory.length}</span>
              </div>
              {selectedHistory.length ? (
                <div className="history-list">
                  {selectedHistory.slice(0, 5).map((experiment) => (
                    <Link to={`/experiments/${experiment.id}`} key={experiment.id}>
                      <span><Icon name="flask" size={14} /></span>
                      <div>
                        <strong>{experiment.name}</strong>
                        <small>{formatDate(experiment.created_at)}</small>
                      </div>
                      <StatusBadge status={experiment.status} compact />
                    </Link>
                  ))}
                </div>
              ) : (
                <p className="detail-empty">이 문서로 실행한 비교가 없습니다.</p>
              )}
            </section>
          </aside>
        ) : (
          <aside className="document-detail detail-placeholder">
            <Icon name="layers" size={24} />
            <strong>문서를 선택하세요</strong>
            <p>메타데이터와 비교 이력을 확인할 수 있습니다.</p>
          </aside>
        )}
      </section>
    </>
  );
}
