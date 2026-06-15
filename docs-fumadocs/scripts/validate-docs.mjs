#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

const appRoot = process.cwd();
const docsRoot = path.join(appRoot, 'content', 'docs');

function walkDocs(dir) {
  const results = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...walkDocs(full));
      continue;
    }
    if (entry.name.endsWith('.mdx')) {
      results.push(full);
    }
  }
  return results;
}

function parseFrontmatter(content) {
  const normalized = content.replace(/\r\n/g, '\n');
  if (!normalized.startsWith('---\n')) return null;
  const endIndex = normalized.indexOf('\n---\n', 4);
  if (endIndex === -1) return null;
  const raw = normalized.slice(4, endIndex).trim();
  const map = new Map();
  for (const line of raw.split('\n')) {
    const idx = line.indexOf(':');
    if (idx === -1) continue;
    map.set(line.slice(0, idx).trim(), line.slice(idx + 1).trim());
  }
  return map;
}

function fail(errors) {
  for (const err of errors) {
    console.error(`- ${err}`);
  }
  process.exit(1);
}

const errors = [];
const docs = walkDocs(docsRoot);
for (const file of docs) {
  const rel = path.relative(docsRoot, file).replace(/\\/g, '/');
  const content = fs.readFileSync(file, 'utf8');
  const frontmatter = parseFrontmatter(content);
  if (!frontmatter) {
    errors.push(`${rel}: missing YAML frontmatter`);
    continue;
  }
  if (!frontmatter.get('title')) {
    errors.push(`${rel}: missing frontmatter title`);
  }
}

if (errors.length > 0) {
  fail(errors);
}

console.log(`Validated ${docs.length} docs pages.`);
