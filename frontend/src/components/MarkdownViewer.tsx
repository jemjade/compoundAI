import type { ReactNode } from "react";

function inlineCode(value: string): ReactNode[] {
  return value.split(/(`[^`]+`)/g).map((part, index) =>
    part.startsWith("`") && part.endsWith("`") ? (
      <code key={index}>{part.slice(1, -1)}</code>
    ) : (
      part
    ),
  );
}

export function MarkdownViewer({ value }: { value: string | null }) {
  if (!value) return <div className="empty-result">Markdown 결과가 비어 있습니다.</div>;
  let inCode = false;
  return (
    <div className="markdown-viewer">
      {value.split("\n").map((line, index) => {
        if (line.startsWith("```")) {
          inCode = !inCode;
          return <div className="code-fence-label" key={index}>{line.slice(3) || "code"}</div>;
        }
        if (inCode) return <pre className="markdown-code-line" key={index}>{line || " "}</pre>;
        if (line.startsWith("### ")) return <h4 key={index}>{inlineCode(line.slice(4))}</h4>;
        if (line.startsWith("## ")) return <h3 key={index}>{inlineCode(line.slice(3))}</h3>;
        if (line.startsWith("# ")) return <h2 key={index}>{inlineCode(line.slice(2))}</h2>;
        if (/^[-*] /.test(line)) return <div className="markdown-list" key={index}>• {inlineCode(line.slice(2))}</div>;
        if (/^\d+\. /.test(line)) return <div className="markdown-list ordered" key={index}>{inlineCode(line)}</div>;
        if (line.startsWith("> ")) return <blockquote key={index}>{inlineCode(line.slice(2))}</blockquote>;
        if (!line.trim()) return <div className="markdown-space" key={index} />;
        return <p key={index}>{inlineCode(line)}</p>;
      })}
    </div>
  );
}
