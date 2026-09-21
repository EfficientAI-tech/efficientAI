#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const docsRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const serverFile = path.join(docsRoot, '.source', 'server.ts');

function isValidCollectionsFile() {
  if (!fs.existsSync(serverFile)) return false;
  const content = fs.readFileSync(serverFile, 'utf8').trim();
  return content.length > 0 && content.includes('export const docs');
}

if (!isValidCollectionsFile()) {
  console.log('Generating docs collections (missing or stale .source/server.ts)...');
  execSync('npx fumadocs-mdx', { cwd: docsRoot, stdio: 'inherit' });
}

if (!isValidCollectionsFile()) {
  console.error('Failed to generate docs collections. Run `npx fumadocs-mdx` in docs-fumadocs.');
  process.exit(1);
}
