'use client';

import { useEffect, useState } from 'react';

const UNLOCK_ACTION = '/docs/enterprise/unlock/';
const DEFAULT_RETURN = '/docs/enterprise/overview/';

function sanitizeReturnPath(value: string | null): string {
  if (!value) return DEFAULT_RETURN;
  if (!value.startsWith('/docs/enterprise/')) return DEFAULT_RETURN;
  if (value.startsWith(UNLOCK_ACTION)) return DEFAULT_RETURN;
  return value.endsWith('/') ? value : `${value}/`;
}

export function EnterpriseUnlockForm() {
  const [returnPath, setReturnPath] = useState(DEFAULT_RETURN);
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setReturnPath(sanitizeReturnPath(params.get('return')));
    setHasError(params.get('error') === 'invalid');
  }, []);

  return (
    <form
      method="POST"
      action={UNLOCK_ACTION}
      className="not-prose mx-auto mt-8 max-w-md space-y-4 rounded-xl border border-fd-border bg-fd-card p-6 shadow-sm"
    >
      <div className="space-y-2">
        <label htmlFor="enterprise-docs-password" className="text-sm font-medium text-fd-foreground">
          Documentation password
        </label>
        <input
          id="enterprise-docs-password"
          name="password"
          type="password"
          required
          autoComplete="current-password"
          className="w-full rounded-lg border border-fd-border bg-fd-background px-3 py-2 text-sm text-fd-foreground outline-none ring-fd-ring focus:ring-2"
          placeholder="Enter password"
        />
      </div>

      <input type="hidden" name="return" value={returnPath} />

      {hasError ? (
        <p className="text-sm text-red-600" role="alert">
          Incorrect password. Try again or contact EfficientAI support.
        </p>
      ) : null}

      <button
        type="submit"
        className="w-full rounded-lg bg-fd-primary px-4 py-2 text-sm font-medium text-fd-primary-foreground transition-opacity hover:opacity-90"
      >
        Unlock enterprise docs
      </button>
    </form>
  );
}
