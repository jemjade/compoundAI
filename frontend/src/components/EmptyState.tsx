// 선택적 작업 버튼을 지원하는 재사용 가능한 빈 상태 Panel이다.
import type { ReactNode } from "react";

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-mark">∅</div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
