#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

const appRoot = process.cwd();
const docsRoot = path.join(appRoot, 'content', 'docs');
const featureMetaPath = path.join(appRoot, 'content', 'feature-contributors.json');
const featureDocs = new Set([
  'products/agents',
  'products/personas',
  'products/scenarios',
  'products/evaluators',
  'products/metrics',
  'products/playground',
  'products/voice-playground',
  'products/call-imports',
  'products/alerting',
  'products/prompt-optimization',
  'products/prompt-partials',
  'monitoring/calls',
  'monitoring/alerting',
  'monitoring/cron-jobs',
]);

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
  const featureId = rel.replace(/\.mdx$/, '');
  const content = fs.readFileSync(file, 'utf8');
  const frontmatter = parseFrontmatter(content);
  if (!frontmatter) {
    errors.push(`${rel}: missing YAML frontmatter`);
    continue;
  }
  if (!frontmatter.get('title')) {
    errors.push(`${rel}: missing frontmatter title`);
  }

  // Feature pages now render contributors from a shared bottom-right widget.
  // Keep validation focused on metadata presence rather than inline page markers.
}

if (!fs.existsSync(featureMetaPath)) {
  errors.push('content/feature-contributors.json does not exist');
} else {
  const featureMeta = JSON.parse(fs.readFileSync(featureMetaPath, 'utf8'));
  const found = new Set((featureMeta.features || []).map((item) => item.featureId));
  for (const featureId of featureDocs) {
    if (!found.has(featureId)) {
      errors.push(`feature-contributors.json missing entry for ${featureId}`);
    }
  }
}

if (errors.length > 0) {
  fail(errors);
}

console.log(`Validated ${docs.length} docs pages and contributor metadata.`);
