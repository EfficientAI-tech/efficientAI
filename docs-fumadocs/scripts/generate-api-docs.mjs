#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createOpenAPI } from 'fumadocs-openapi/server';
import { generateFiles } from 'fumadocs-openapi';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const docsRoot = path.resolve(__dirname, '..');
const apiContentDir = path.join(docsRoot, 'content', 'docs', 'api-reference');
const schemaFile = path.join(docsRoot, 'openapi', 'efficientai.json');
const authoredPages = ['index', 'authentication', 'errors'];
const tagSlugMap = new Map([
  ['Authentication', 'authentication'],
  ['Workspaces', 'workspaces'],
  ['Integrations', 'integrations'],
  ['agents', 'agents'],
  ['personas', 'personas'],
  ['scenarios', 'scenarios'],
  ['evaluators', 'evaluators'],
  ['evaluator-suites', 'evaluator-suites'],
  ['evaluator-results', 'evaluator-results'],
  ['metrics', 'metrics'],
  ['observability', 'observability'],
  ['Call Imports', 'call-imports'],
  ['voicebundles', 'voice-bundles'],
  ['aiproviders', 'ai-providers'],
]);

if (!fs.existsSync(schemaFile)) {
  throw new Error(`Missing curated OpenAPI schema at ${schemaFile}. Run npm run openapi:enrich first.`);
}

const openapi = createOpenAPI({
  input: { efficientai: schemaFile },
});

fs.mkdirSync(apiContentDir, { recursive: true });
cleanupGeneratedEntries();

await generateFiles({
  input: openapi,
  output: apiContentDir,
  per: 'operation',
  groupBy: 'tag',
  name: { algorithm: 'v2' },
  slugify: (value) => tagSlugMap.get(value) ?? defaultSlugify(value),
  includeDescription: true,
  meta: true,
  beforeWrite(files) {
    for (const file of files) {
      if (file.path === 'meta.json') {
        const meta = JSON.parse(file.content);
        const generatedPages = (meta.pages ?? []).filter((entry) => !authoredPages.includes(entry));
        meta.title = 'API Reference';
        meta.pages = [...authoredPages, ...generatedPages];
        file.content = `${JSON.stringify(meta, null, 2)}\n`;
        continue;
      }
      if (file.path.endsWith('.mdx') && file.path.includes('/')) {
        file.content = injectMdPath(file.content, `/api-md/${file.path.replace(/\.mdx$/, '.md')}`);
      }
    }
  },
});

console.log(`Generated API docs in ${path.relative(docsRoot, apiContentDir)}`);

function cleanupGeneratedEntries() {
  const entries = fs.readdirSync(apiContentDir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(apiContentDir, entry.name);
    if (entry.isDirectory()) {
      fs.rmSync(fullPath, { recursive: true, force: true });
      continue;
    }
    if (entry.name === 'openapi.mdx' || entry.name === 'openapi.json') {
      fs.rmSync(fullPath, { force: true });
    }
  }
}

function injectMdPath(content, mdPath) {
  const normalized = content.replace(/\r\n/g, '\n');
  if (!normalized.startsWith('---\n')) return content;
  const closing = normalized.indexOf('\n---\n', 4);
  if (closing === -1) return content;
  const frontmatter = normalized.slice(4, closing);
  if (/^mdPath:/m.test(frontmatter)) return content;

  const updated = `${normalized.slice(0, closing)}\nmdPath: ${JSON.stringify(mdPath)}${normalized.slice(closing)}`;
  return content.includes('\r\n') ? updated.replace(/\n/g, '\r\n') : updated;
}

function defaultSlugify(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
