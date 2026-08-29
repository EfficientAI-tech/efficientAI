import { Component, type ErrorInfo, type ReactNode } from 'react'

interface RouteErrorBoundaryProps {
  children: ReactNode
}

interface RouteErrorBoundaryState {
  hasError: boolean
  errorMessage: string
}

export default class RouteErrorBoundary extends Component<
  RouteErrorBoundaryProps,
  RouteErrorBoundaryState
> {
  constructor(props: RouteErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, errorMessage: '' }
  }

  static getDerivedStateFromError(error: unknown): RouteErrorBoundaryState {
    return {
      hasError: true,
      errorMessage: error instanceof Error ? error.message : 'Unknown rendering error',
    }
  }

  componentDidCatch(error: unknown, errorInfo: ErrorInfo) {
    console.error('Route render error:', error, errorInfo)
  }

  private handleReload = () => {
    window.location.reload()
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children
    }

    return (
      <div className="max-w-2xl mx-auto px-4 py-12">
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-6">
          <h2 className="text-base font-semibold text-rose-800">This page hit a rendering error</h2>
          <p className="text-sm text-rose-700 mt-2">
            We captured the error and prevented a blank screen. Please reload once.
          </p>
          <p className="text-xs font-mono text-rose-600 mt-3 break-words">{this.state.errorMessage}</p>
          <button
            type="button"
            onClick={this.handleReload}
            className="mt-4 inline-flex items-center rounded-lg bg-rose-600 px-3 py-2 text-sm font-medium text-white hover:bg-rose-700"
          >
            Reload page
          </button>
        </div>
      </div>
    )
  }
}

