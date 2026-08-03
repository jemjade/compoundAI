import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
};

type State = {
  failed: boolean;
};

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("React rendering failed", error, info);
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="error-state" role="alert">
          <h1>화면을 표시하지 못했습니다</h1>
          <p>새로고침하면 최신 화면으로 다시 연결됩니다.</p>
          <button className="button primary" type="button" onClick={() => window.location.reload()}>
            새로고침
          </button>
        </main>
      );
    }

    return this.props.children;
  }
}
