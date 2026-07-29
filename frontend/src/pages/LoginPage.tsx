// 로그인과 첫 계정 회원가입을 결합한 화면이다.
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router";
import { Icon } from "../components/Icon";
import { ApiError, api, setToken } from "../lib/api";

export function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
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
        caught instanceof ApiError ? caught.message : "Unable to sign in.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="login-page">
      <section className="login-story">
        <div className="story-grid" />
        <div className="login-ambient" aria-hidden="true">
          <span className="ambient-document ambient-document-a">
            <Icon name="document" size={24} />
            <i /><i /><i />
          </span>
          <span className="ambient-document ambient-document-b">
            <Icon name="document" size={20} />
            <i /><i />
          </span>
          <span className="ambient-document ambient-document-c">
            <Icon name="document" size={18} />
            <i /><i />
          </span>
          <span className="ambient-spark ambient-spark-a" />
          <span className="ambient-spark ambient-spark-b" />
          <span className="ambient-spark ambient-spark-c" />
        </div>
        <div className="story-content">
          <div className="brand-signal" aria-hidden="true">
            <span className="brand-signal-document">
              <Icon name="document" size={18} />
            </span>
            <i />
            <span>DOCUMENT INTELLIGENCE / 01</span>
          </div>
          <h1 className="login-wordmark">
            Parse<span>LAB</span>
          </h1>
          <p className="login-product-copy">
            Run multiple parsers on the same source, inspect structured outputs side by side,
            evaluate quality, and de-identify sensitive content in one precise workspace.
          </p>
          <div className="login-capabilities" aria-label="ParseLAB capabilities">
            <span>PARSE</span>
            <i />
            <span>COMPARE</span>
            <i />
            <span>EVALUATE</span>
            <i />
            <span>DE-IDENTIFY</span>
          </div>
        </div>
      </section>
      <section className="login-panel">
        <form onSubmit={submit} className="login-form">
          <div className="mobile-brand">Parse<span>LAB</span></div>
          <span className="eyebrow">{mode === "login" ? "WELCOME BACK" : "CREATE ACCOUNT"}</span>
          <h2>{mode === "login" ? "Sign in to ParseLAB" : "Create your account"}</h2>
          <p className="muted">
            {mode === "login"
              ? "Continue to your document intelligence workspace."
              : "The first account becomes an admin. Additional accounts are created as users."}
          </p>
          {mode === "signup" && (
            <label>
              Name
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                autoComplete="name"
                placeholder="Your name"
                required
              />
            </label>
          )}
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              placeholder="name@company.com"
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              minLength={8}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              placeholder="At least 8 characters"
              required
            />
          </label>
          {error && <div className="error-banner">{error}</div>}
          <button className="button primary wide" disabled={pending}>
            {pending ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
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
              ? "New to ParseLAB? Create an account"
              : "Already have an account? Sign in"}
          </button>
        </form>
      </section>
    </div>
  );
}
