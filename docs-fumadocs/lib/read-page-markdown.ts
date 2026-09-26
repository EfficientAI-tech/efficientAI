import fs from 'node:fs';
import path from 'node:path';

const DOCS_ROOT = path.join(process.cwd(), 'content/docs');

function stripFrontmatter(source: string): string {
  if (!source.startsWith('---')) return source.trim();
  const end = source.indexOf('\n---', 3);
  if (end === -1) return source.trim();
  return source.slice(end + 4).trimStart();
}

export function readDocPageMarkdown(slugs: string[]): string | null {
  if (slugs.length === 0) return null;

  const segments = slugs.join('/');
  const candidates = [
    path.join(DOCS_ROOT, segments + '.mdx'),
    path.join(DOCS_ROOT, '(docs)', segments + '.mdx'),
    path.join(DOCS_ROOT, segments, 'index.mdx'),
    path.join(DOCS_ROOT, '(docs)', segments, 'index.mdx'),
  ];

  for (const filePath of candidates) {
    if (!fs.existsSync(filePath)) continue;
    const raw = fs.readFileSync(filePath, 'utf8');
    return stripFrontmatter(raw);
  }

  return null;
}
