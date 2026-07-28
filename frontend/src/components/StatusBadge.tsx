// Backend Workflow 상태를 일관된 한글 상태 Badge로 변환한다.
const labels: Record<string, string> = {
  PENDING: "대기",
  RUNNING: "실행 중",
  SUCCEEDED: "완료",
  COMPLETED: "완료",
  PARTIALLY_COMPLETED: "일부 완료",
  FAILED: "실패",
  INTERRUPTED: "중단",
  NOT_REQUESTED: "미실행",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`status status-${status.toLowerCase()}`}>
      <span className="status-dot" />
      {labels[status] ?? status}
    </span>
  );
}
