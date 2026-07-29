import type { ReactNode } from "react";

function JsonNode({ name, value, depth }: { name?: string; value: unknown; depth: number }) {
  const label = name === undefined ? null : <span className="json-key">"{name}"</span>;
  if (value === null) {
    return <div className="json-line">{label && <>{label}: </>}<span className="json-null">null</span></div>;
  }
  if (typeof value === "string") {
    return <div className="json-line">{label && <>{label}: </>}<span className="json-string">"{value}"</span></div>;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return <div className="json-line">{label && <>{label}: </>}<span className="json-value">{String(value)}</span></div>;
  }
  if (Array.isArray(value)) {
    return (
      <details className="json-branch" open={depth < 2}>
        <summary>{label && <>{label}: </>}<span className="json-bracket">Array({value.length})</span></summary>
        <div className="json-children">
          {value.map((item, index) => (
            <JsonNode key={index} name={String(index)} value={item} depth={depth + 1} />
          ))}
        </div>
      </details>
    );
  }
  const entries = Object.entries(value as Record<string, unknown>);
  return (
    <details className="json-branch" open={depth < 2}>
      <summary>{label && <>{label}: </>}<span className="json-bracket">Object({entries.length})</span></summary>
      <div className="json-children">
        {entries.map(([key, item]) => (
          <JsonNode key={key} name={key} value={item} depth={depth + 1} />
        ))}
      </div>
    </details>
  );
}

export function JsonViewer({ value, empty }: { value: unknown; empty?: ReactNode }) {
  if (value === null || value === undefined) {
    return <div className="empty-result">{empty ?? "JSON 결과가 비어 있습니다."}</div>;
  }
  return (
    <div className="json-viewer" role="tree" aria-label="접을 수 있는 JSON 결과">
      <JsonNode value={value} depth={0} />
    </div>
  );
}
