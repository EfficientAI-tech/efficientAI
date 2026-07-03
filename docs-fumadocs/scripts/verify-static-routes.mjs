#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

const appRoot = process.cwd();
const docsRoot = path.join(appRoot, 'content', 'docs');
const outRoot = path.join(appRoot, 'out');

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

function expectedOutPath(slug) {
  return path.join(outRoot, 'docs', slug, 'index.html');
}

if (!fs.existsSync(outRoot)) {
  console.error('Missing out/ directory. Run `npm run build` first.');
  process.exit(1);
}

const errors = [];
for (const file of walkDocs(docsRoot)) {
  const slug = path.relative(docsRoot, file).replace(/\\/g, '/').replace(/\.mdx$/, '');
  const outFile = expectedOutPath(slug);
  if (!fs.existsSync(outFile)) {
    errors.push(`missing ${path.relative(appRoot, outFile)} for content/docs/${slug}.mdx`);
  }
}

if (!fs.existsSync(path.join(outRoot, '404.html'))) {
  errors.push('missing out/404.html (add app/not-found.tsx and rebuild)');
}

if (errors.length > 0) {
  for (const err of errors) {
    console.error(`- ${err}`);
  }
  process.exit(1);
}

const pageCount = walkDocs(docsRoot).length;
console.log(`Verified ${pageCount} static doc routes in out/`);
