#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

const DOCS_ROOT = path.join(process.cwd(), 'content', 'docs');
const OUTPUT_PATH = path.join(process.cwd(), 'public', 'search-index.json');

function walkDocs(dirPath, prefix = '') {
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    if (entry.name.startsWith('.')) continue;
    const relative = `${prefix}${entry.name}`;
    const absolute = path.join(dirPath, entry.name);
    if (entry.isDirectory()) {
      files.push(...walkDocs(absolute, `${relative}/`));
      continue;
    }
    if (entry.isFile() && entry.name.endsWith('.mdx')) {
      files.push({ relative, absolute });
    }
  }

  return files;
}

function stripFrontmatter(raw) {
  if (!raw.startsWith('---')) return { frontmatter: '', body: raw };
  const end = raw.indexOf('\n---', 3);
  if (end === -1) return { frontmatter: '', body: raw };
  return {
    frontmatter: raw.slice(3, end).trim(),
    body: raw.slice(end + 4).trim(),
  };
}

function parseTitle(frontmatter, body, fallback) {
  const frontmatterTitle = frontmatter.match(/^title:\s*(.+)$/m)?.[1]?.trim();
  if (frontmatterTitle) return frontmatterTitle.replace(/^['"]|['"]$/g, '');

  const heading = body.match(/^#\s+(.+)$/m)?.[1]?.trim();
  if (heading) return heading;

  return fallback;
}

function cleanContent(markdown) {
  return markdown
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`[^`]*`/g, ' ')
    .replace(/!\[[^\]]*]\([^)]*\)/g, ' ')
    .replace(/\[[^\]]*]\([^)]*\)/g, ' ')
    .replace(/[#>*_\-]/g, ' ')
    .replace(/\{[^}]*}/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 4000);
}

function toLabel(segment) {
  return segment
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function buildRecords() {
  const files = walkDocs(DOCS_ROOT);
  const records = files
    .filter(({ relative }) => !relative.startsWith('enterprise/'))
    .map(({ relative, absolute }) => {
    const raw = fs.readFileSync(absolute, 'utf8');
    const { frontmatter, body } = stripFrontmatter(raw);
    const featureId = relative.replace(/\.mdx$/, '');
    const fallbackTitle = toLabel(path.basename(featureId));
    const title = parseTitle(frontmatter, body, fallbackTitle);
    const segments = featureId.split('/');
    const breadcrumbs = segments.slice(0, -1).map(toLabel);
    const url = `/docs/${featureId}`;
    return {
      id: featureId,
      url,
      title,
      breadcrumbs,
      content: cleanContent(body),
    };
  });

  return records.sort((a, b) => a.url.localeCompare(b.url));
}

function main() {
  const records = buildRecords();
  const payload = {
    generatedAt: new Date().toISOString(),
    count: records.length,
    records,
  };

  fs.writeFileSync(OUTPUT_PATH, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  console.log(`Generated ${path.relative(process.cwd(), OUTPUT_PATH)} (${records.length} records)`);
}

main();
