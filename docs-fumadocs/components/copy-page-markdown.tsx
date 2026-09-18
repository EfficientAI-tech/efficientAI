'use client';

import { useState } from 'react';

export function CopyPageMarkdown({ mdPath }: { mdPath: string }) {
  const [status, setStatus] = useState<'idle' | 'loading' | 'copied' | 'error'>('idle');

  async function handleCopy() {
    try {
      setStatus('loading');
      const response = await fetch(mdPath, { cache: 'no-store' });
      if (!response.ok) throw new Error(`Failed to load markdown at ${mdPath}`);
      const markdown = await response.text();
      await navigator.clipboard.writeText(markdown);
      setStatus('copied');
      window.setTimeout(() => setStatus('idle'), 1400);
    } catch {
      setStatus('error');
      window.setTimeout(() => setStatus('idle'), 1800);
    }
  }

  return (
    <button type="button" className="docs-action-link" onClick={handleCopy}>
      {status === 'loading'
        ? 'Copying...'
        : status === 'copied'
          ? 'Copied markdown'
          : status === 'error'
            ? 'Copy failed'
            : 'Copy as Markdown'}
    </button>
  );
}
