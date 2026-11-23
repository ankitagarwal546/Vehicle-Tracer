import { Component, type ErrorInfo, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("View failed to render", error, info.componentStack);
  }

  componentDidUpdate(previous: { resetKey: string }) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="panel px-4 py-8 text-center">
        <div className="text-xs font-semibold text-rose-800">This view could not be displayed</div>
        <p className="mt-1 text-xs text-muted">Your case data is safe. Reload the page or open another view.</p>
        <button className="btn mt-3" onClick={() => window.location.reload()}>Reload</button>
      </div>
    );
  }
}
