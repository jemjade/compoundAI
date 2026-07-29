// 인증 API Client와 Browser 다운로드 도우미를 한곳에서 제공한다.
const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public code = "REQUEST_FAILED",
    public status = 0,
  ) {
    super(message);
  }
}

export function getToken() {
  return localStorage.getItem("parselab_token");
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem("parselab_token", token);
  else localStorage.removeItem("parselab_token");
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(
      payload?.error?.message ??
        payload?.detail?.[0]?.msg ??
        (typeof payload?.detail === "string" ? payload.detail : null) ??
        "요청을 처리하지 못했습니다.",
      payload?.error?.code ?? "VALIDATION_ERROR",
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function downloadArtifact(runId: string, artifact: string) {
  const response = await fetch(`${API_URL}/runs/${runId}/${artifact}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!response.ok) throw new ApiError("결과 파일을 내려받지 못했습니다.");
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const fallback = `${artifact}.${artifact === "markdown" ? "md" : artifact === "text" ? "txt" : "json"}`;
  const name = disposition.match(/filename="?([^"]+)"?/)?.[1] ?? fallback;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function downloadComparisonCsv(experimentId: string) {
  const response = await fetch(`${API_URL}/experiments/${experimentId}/export.csv`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!response.ok) throw new ApiError("CSV 파일을 내려받지 못했습니다.");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `parselab-comparison-${experimentId}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function downloadDocument(documentId: string, fallbackName: string) {
  const response = await fetch(`${API_URL}/documents/${documentId}/download`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
  if (!response.ok) throw new ApiError("원본 문서를 내려받지 못했습니다.");
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const name = disposition.match(/filename="?([^"]+)"?/)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}
