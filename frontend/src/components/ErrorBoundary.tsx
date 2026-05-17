import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  context?: string;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    const tag = this.props.context ? `:${this.props.context}` : "";
    // eslint-disable-next-line no-console
    console.error(`[ErrorBoundary${tag}]`, error, errorInfo);
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    if (this.props.fallback) return this.props.fallback;

    return (
      <div
        role="alert"
        style={{
          padding: 24,
          margin: 16,
          border: "1px solid #ef4444",
          borderRadius: 8,
          background: "#fef2f2",
        }}
      >
        <h2 style={{ color: "#991b1b", marginTop: 0 }}>
          ⚠️ コンポーネントの描画に失敗しました
        </h2>
        <p style={{ color: "#7f1d1d", whiteSpace: "pre-wrap" }}>
          {this.props.context ? `(${this.props.context}) ` : ""}
          {this.state.error?.message || "不明なエラー"}
        </p>
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <button
            type="button"
            onClick={this.handleReset}
            style={{
              padding: "6px 12px",
              border: "1px solid #d1d5db",
              borderRadius: 6,
              background: "white",
              cursor: "pointer",
            }}
          >
            再試行
          </button>
          <button
            type="button"
            onClick={this.handleReload}
            style={{
              padding: "6px 12px",
              border: "1px solid #d1d5db",
              borderRadius: 6,
              background: "white",
              cursor: "pointer",
            }}
          >
            ページを再読み込み
          </button>
        </div>
      </div>
    );
  }
}
