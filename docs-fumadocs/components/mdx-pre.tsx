'use client';

import type { ComponentPropsWithoutRef, ReactNode } from 'react';
import { useMemo, useState } from 'react';

function collectText(node: ReactNode): string {
  if (typeof node === 'string') return node;
  if (typeof node === 'number') return String(node);
  if (!node) return '';
  if (Array.isArray(node)) return node.map(collectText).join('');
  if (typeof node === 'object' && 'props' in node) {
    const children = (node as { props?: { children?: ReactNode } }).props?.children;
    return collectText(children);
  }
  return '';
}

function inferLanguage(className?: string): string {
  if (!className) return '';
  const langToken = className
    .split(/\s+/)
    .find((token) => token.startsWith('language-') || token.startsWith('lang-'));
  if (!langToken) return '';
  return langToken.replace(/^language-/, '').replace(/^lang-/, '').trim();
}

export function MdxPre(props: ComponentPropsWithoutRef<'pre'>) {
  const [copied, setCopied] = useState(false);

  const extracted = useMemo(() => {
    const codeNode = Array.isArray(props.children)
      ? props.children.find((child) => typeof child === 'object' && child && 'props' in child)
      : props.children;

    const codeClassName =
      typeof codeNode === 'object' && codeNode && 'props' in codeNode
        ? ((codeNode as { props?: { className?: string } }).props?.className ?? '')
        : '';
    const language = inferLanguage(codeClassName);
    const code = collectText(props.children).replace(/\n+$/, '');
    const markdown = ['```' + language, code, '```'].join('\n');

    return { markdown };
  }, [props.children]);

  async function copyMarkdown() {
    await navigator.clipboard.writeText(extracted.markdown);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <div className="docs-code-block not-prose">
      <div className="docs-code-block-toolbar">
        <button type="button" onClick={copyMarkdown} className="docs-code-copy-markdown">
          {copied ? 'Copied' : 'Copy as Markdown'}
        </button>
      </div>
      <pre {...props} />
    </div>
  );
}
