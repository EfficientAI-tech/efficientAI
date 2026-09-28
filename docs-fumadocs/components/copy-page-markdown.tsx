'use client';

import { useState } from 'react';

type Props = {
  mdPath?: string;
  markdown?: string | null;
};

export function CopyPageMarkdown({ mdPath, markdown }: Props) {
  const [status, setStatus] = useState<'idle' | 'loading' | 'copied' | 'error'>('idle');

  async function handleCopy() {
    try {
      setStatus('loading');
      let text = markdown?.trim() ?? '';
      if (!text && mdPath) {
        const response = await fetch(mdPath, { cache: 'no-store' });
        if (!response.ok) throw new Error(`Failed to load markdown at ${mdPath}`);
        text = await response.text();
      }
      if (!text) throw new Error('No markdown available');
      await navigator.clipboard.writeText(text);
      setStatus('copied');
      window.setTimeout(() => setStatus('idle'), 1400);
    } catch {
      setStatus('error');
      window.setTimeout(() => setStatus('idle'), 1800);
    }
  }

  if (!markdown && !mdPath) return null;

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
