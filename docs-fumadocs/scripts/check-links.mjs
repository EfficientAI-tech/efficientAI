#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

const appRoot = process.cwd();
const docsRoot = path.join(appRoot, 'content', 'docs');

const linkPattern = /\[[^\]]+\]\(([^)]+)\)/g;

function walkDocs(dir) {
  const files = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walkDocs(full));
      continue;
    }
    if (entry.name.endsWith('.mdx')) {
      files.push(full);
    }
  }
  return files;
}

function stripLinkDecorators(raw) {
  return raw.replace(/^<|>$/g, '').split('#')[0].split('?')[0].trim();
}

function routeExists(routePath) {
  const cleaned = routePath.replace(/^\/docs\/?/, '').replace(/\/$/, '');
  if (!cleaned) return true;
  const asFile = path.join(docsRoot, `${cleaned}.mdx`);
  const asDirMeta = path.join(docsRoot, cleaned, 'meta.json');
  return fs.existsSync(asFile) || fs.existsSync(asDirMeta);
}

function markdownTargetExists(fromFile, href) {
  const normalized = href.replace(/\.md$/, '.mdx');
  const fromDir = path.dirname(fromFile);
  const resolved = path.resolve(fromDir, normalized);
  if (fs.existsSync(resolved)) return true;
  if (normalized.endsWith('.mdx')) return false;
  return fs.existsSync(`${resolved}.mdx`);
}

function isSkippable(href) {
  return (
    href === '' ||
    href.startsWith('http://') ||
    href.startsWith('https://') ||
    href.startsWith('mailto:') ||
    href.startsWith('tel:') ||
    href.startsWith('#')
  );
}

const errors = [];
for (const file of walkDocs(docsRoot)) {
  const content = fs.readFileSync(file, 'utf8');
  const rel = path.relative(docsRoot, file).replace(/\\/g, '/');
  for (const match of content.matchAll(linkPattern)) {
    const originalHref = match[1] || '';
    const href = stripLinkDecorators(originalHref);
    if (isSkippable(href)) continue;

    if (href.startsWith('/docs')) {
      if (!routeExists(href)) {
        errors.push(`${rel}: broken docs route ${originalHref}`);
      }
      continue;
    }

    if (href.startsWith('/')) {
      continue;
    }

    if (!markdownTargetExists(file, href)) {
      errors.push(`${rel}: unresolved relative link ${originalHref}`);
    }
  }
}

if (errors.length > 0) {
  for (const err of errors) {
    console.error(`- ${err}`);
  }
  process.exit(1);
}

console.log('All markdown and docs-route links resolved.');
