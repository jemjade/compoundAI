// 로그인과 첫 계정 회원가입을 결합한 화면이다.
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router";
import { ApiError, api, setToken } from "../lib/api";

export function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("admin@parselab.local");
  const [password, setPassword] = useState("parselab123");
  const [name, setName] = useState("ParseLab Admin");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      if (mode === "signup") {
        await api("/auth/signup", {
          method: "POST",
          body: JSON.stringify({ email, password, name }),
        });
      }
      const token = await api<{ access_token: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(token.access_token);
      navigate("/");
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "로그인하지 못했습니다.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="login-page">
      <section className="login-story">
        <div className="story-grid" />
        <div className="story-content">
          <span className="eyebrow light">DOCUMENT INTELLIGENCE LAB</span>
          <h1>
            같은 문서,
            <br />
            더 선명한 <em>비교.</em>
          </h1>
          <p>
            여러 파서의 텍스트, 구조와 처리 시간을 하나의 실험으로
            확인하세요.
          </p>
          <div className="pipeline-preview">
            <span>DOC</span>
            <i />
            <span>PARSE × N</span>
            <i />
            <span>COMPARE</span>
          </div>
        </div>
      </section>
      <section className="login-panel">
        <form onSubmit={submit} className="login-form">
          <div className="mobile-brand">ParseLab</div>
          <span className="eyebrow">{mode === "login" ? "WELCOME BACK" : "FIRST RUN"}</span>
          <h2>{mode === "login" ? "워크벤치에 로그인" : "관리자 계정 만들기"}</h2>
          <p className="muted">
            {mode === "login"
              ? "문서 파싱 실험을 이어서 진행하세요."
              : "첫 계정에는 ADMIN 권한과 Mock Parser 2개가 자동 구성됩니다."}
          </p>
          {mode === "signup" && (
            <label>
              이름
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </label>
          )}
          <label>
            이메일
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          <label>
            비밀번호
            <input
              type="password"
              value={password}
              minLength={8}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error && <div className="error-banner">{error}</div>}
          <button className="button primary wide" disabled={pending}>
            {pending ? "처리 중…" : mode === "login" ? "로그인" : "계정 생성 후 로그인"}
          </button>
          <button
            type="button"
            className="switch-auth"
            onClick={() => {
              setMode(mode === "login" ? "signup" : "login");
              setError("");
            }}
          >
            {mode === "login"
              ? "처음인가요? 관리자 계정 만들기"
              : "이미 계정이 있나요? 로그인"}
          </button>
        </form>
      </section>
    </div>
  );
}
