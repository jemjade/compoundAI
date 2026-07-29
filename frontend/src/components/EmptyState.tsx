// 선택적 작업 버튼을 지원하는 재사용 가능한 빈 상태 Panel이다.
import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

export function EmptyState({
  title,
  description,
  action,
  icon = "document",
  compact = false,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  icon?: IconName;
  compact?: boolean;
}) {
  return (
    <div className={`empty-state ${compact ? "empty-state-compact" : ""}`}>
      <div className="empty-mark"><Icon name={icon} size={20} /></div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
