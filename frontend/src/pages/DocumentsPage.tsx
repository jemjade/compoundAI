// 문서 업로드와 소유 문서 관리 화면이다.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ChangeEvent, useRef } from "react";
import { Link } from "react-router";
import { EmptyState } from "../components/EmptyState";
import { api } from "../lib/api";
import { formatBytes, formatDate } from "../lib/format";
import type { DocumentItem } from "../types";

export function DocumentsPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => api<DocumentItem[]>("/documents"),
  });
  const upload = useMutation({
    mutationFn: (file: File) => {
      const data = new FormData();
      data.append("file", file);
      return api<DocumentItem>("/documents", { method: "POST", body: data });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });
  const choose = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) upload.mutate(file);
    event.target.value = "";
  };

  return (
    <>
      <header className="page-header">
        <div>
          <span className="eyebrow">SOURCE LIBRARY</span>
          <h1>Documents</h1>
          <p>원본은 UUID 경로에 저장되고 메타데이터만 PostgreSQL에 기록됩니다.</p>
        </div>
        <button className="button primary" onClick={() => inputRef.current?.click()}>
          {upload.isPending ? "업로드 중…" : "↑ 문서 업로드"}
        </button>
        <input
          hidden
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.pptx,.xlsx,.txt,.md"
          onChange={choose}
        />
      </header>
      {upload.isError && (
        <div className="error-banner">문서를 업로드하지 못했습니다: {upload.error.message}</div>
      )}
      <section className="section-block">
        {documents.data?.length ? (
          <div className="document-grid">
            {documents.data.map((document) => (
              <article className="document-card" key={document.id}>
                <div className={`file-icon file-${document.extension}`}>
                  {document.extension.toUpperCase()}
                </div>
                <div className="document-copy">
                  <h3>{document.original_filename}</h3>
                  <p>
                    {formatBytes(document.file_size)} · {document.mime_type}
                  </p>
                  <small>{formatDate(document.created_at)}</small>
                </div>
                <Link
                  className="button ghost compact"
                  to={`/experiments/new?document=${document.id}`}
                >
                  실험
                </Link>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="비교할 문서를 올려주세요"
            description="PDF, Office, TXT, Markdown · 최대 크기는 Backend 환경변수로 제어됩니다."
            action={
              <button className="button primary" onClick={() => inputRef.current?.click()}>
                문서 선택
              </button>
            }
          />
        )}
      </section>
    </>
  );
}
