#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const docsRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const serverFile = path.join(docsRoot, '.source', 'server.ts');
const contentRoot = path.join(docsRoot, 'content', 'docs');

function isValidCollectionsFile() {
  if (!fs.existsSync(serverFile)) return false;
  const content = fs.readFileSync(serverFile, 'utf8').trim();
  return content.length > 0 && content.includes('export const docs');
}

function walkContentFiles(dir, files = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkContentFiles(full, files);
      continue;
    }
    if (entry.name.endsWith('.mdx') || entry.name === 'meta.json') {
      files.push(full);
    }
  }
  return files;
}

function isCollectionsStale() {
  if (!fs.existsSync(serverFile)) return true;
  const serverMtime = fs.statSync(serverFile).mtimeMs;
  for (const file of walkContentFiles(contentRoot)) {
    if (fs.statSync(file).mtimeMs > serverMtime) {
      return true;
    }
  }
  return false;
}

if (!isValidCollectionsFile() || isCollectionsStale()) {
  console.log('Generating docs collections (missing or stale .source/server.ts)...');
  execSync('npx fumadocs-mdx', { cwd: docsRoot, stdio: 'inherit' });
}

if (!isValidCollectionsFile()) {
  console.error('Failed to generate docs collections. Run `npx fumadocs-mdx` in docs-fumadocs.');
  process.exit(1);
}
