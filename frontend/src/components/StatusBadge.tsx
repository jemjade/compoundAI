// Backend Workflow 상태를 색상, 아이콘, 텍스트로 함께 전달한다.
import { Icon, type IconName } from "./Icon";

const labels: Record<string, string> = {
  PENDING: "대기",
  RUNNING: "실행 중",
  SUCCEEDED: "완료",
  COMPLETED: "완료",
  PARTIALLY_COMPLETED: "일부 완료",
  FAILED: "실패",
  INTERRUPTED: "중단",
  CANCELLED: "취소됨",
  NOT_REQUESTED: "미실행",
};

const icons: Record<string, IconName> = {
  PENDING: "clock",
  RUNNING: "activity",
  SUCCEEDED: "check",
  COMPLETED: "check",
  PARTIALLY_COMPLETED: "circleAlert",
  FAILED: "circleAlert",
  INTERRUPTED: "stop",
  CANCELLED: "stop",
  NOT_REQUESTED: "pause",
};

export function StatusBadge({
  status,
  compact = false,
}: {
  status: string;
  compact?: boolean;
}) {
  return (
    <span className={`status status-${status.toLowerCase()} ${compact ? "status-compact" : ""}`}>
      <Icon name={icons[status] ?? "info"} size={12} />
      <span>{labels[status] ?? status}</span>
    </span>
  );
}
