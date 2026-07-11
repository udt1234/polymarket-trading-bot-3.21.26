"use client";

import { Component, ReactNode } from "react";

// Contain a single panel's crash so one bad component never blanks the whole
// dashboard (e.g. a charting-lib assertion on odd data).
export default class ErrorBoundary extends Component<
  { children: ReactNode; label?: string },
  { err: boolean }
> {
  state = { err: false };

  static getDerivedStateFromError() {
    return { err: true };
  }

  render() {
    if (this.state.err) {
      return (
        <div className="p-3 text-xs text-term-red">
          panel error{this.props.label ? `: ${this.props.label}` : ""}
        </div>
      );
    }
    return this.props.children;
  }
}
