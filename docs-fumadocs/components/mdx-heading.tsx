'use client';

import type { ComponentPropsWithoutRef, ReactNode } from 'react';
import { useState } from 'react';

function headingText(node: ReactNode): string {
  if (typeof node === 'string') return node;
  if (typeof node === 'number') return String(node);
  if (!node) return '';
  if (Array.isArray(node)) return node.map(headingText).join('');
  if (typeof node === 'object' && 'props' in node) {
    const children = (node as { props?: { children?: ReactNode } }).props?.children;
    return headingText(children);
  }
  return '';
}

export function MdxHeading({
  level,
  ...props
}: ComponentPropsWithoutRef<'h2'> & { level: 2 | 3 }) {
  const [copied, setCopied] = useState(false);
  const text = headingText(props.children).trim();
  const prefix = level === 2 ? '##' : '###';

  async function copySectionHeading() {
    if (!text) return;
    await navigator.clipboard.writeText(`${prefix} ${text}\n\n`);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  const Tag = level === 2 ? 'h2' : 'h3';

  return (
    <Tag {...props} className={['group relative scroll-m-20', props.className].filter(Boolean).join(' ')}>
      <span className="pr-28">{props.children}</span>
      {text ? (
        <button
          type="button"
          onClick={copySectionHeading}
          className="absolute right-0 top-1/2 -translate-y-1/2 hidden rounded-md border border-fd-border/80 bg-fd-background px-2 py-0.5 text-[11px] font-medium text-fd-muted-foreground opacity-0 transition group-hover:opacity-100 group-focus-within:opacity-100 sm:inline-flex"
        >
          {copied ? 'Copied' : 'Copy as MD'}
        </button>
      ) : null}
    </Tag>
  );
}
