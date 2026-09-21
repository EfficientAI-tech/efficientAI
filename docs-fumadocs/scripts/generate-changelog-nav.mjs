#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const docsRoot = path.resolve(__dirname, '..');
const changelogDir = path.join(docsRoot, 'content', 'docs', 'changelog');
const metaPath = path.join(changelogDir, 'meta.json');

const RELEASES_URL =
  'https://api.github.com/repos/EfficientAI-tech/efficientAI/releases?per_page=30';

function parseReleaseBody(body) {
  const changes = [];
  const contributors = new Set();

  for (const line of (body ?? '').split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    const contributorMatch = trimmed.match(/^[*-]\s*@([A-Za-z0-9-]+)/);
    if (contributorMatch) {
      contributors.add(contributorMatch[1]);
      continue;
    }

    const inlineContributor = trimmed.match(/\sby\s@([A-Za-z0-9-]+)\s/i);
    if (inlineContributor) {
      contributors.add(inlineContributor[1]);
    }

    if (/^[*-]\s/.test(trimmed) && !trimmed.startsWith('**Full Changelog')) {
      changes.push(trimmed.replace(/^[*-]\s*/, ''));
    }
  }

  return { changes, contributors: [...contributors] };
}

function formatReleaseDate(iso) {
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function escapeMdx(text) {
  return text.replace(/\{/g, '\\{').replace(/\}/g, '\\}');
}

function slugFromTag(tagName) {
  return tagName.replace(/^\//, '').replace(/\//g, '-');
}

function buildReleaseMdx(release) {
  const { changes, contributors } = parseReleaseBody(release.body);
  const date = formatReleaseDate(release.published_at);
  const lines = [
    '---',
    `title: ${release.tag_name}`,
    `description: Release notes for ${release.tag_name}.`,
    '---',
    '',
    `# ${release.tag_name}`,
    '',
    `Released ${date}. [View on GitHub](${release.html_url}).`,
    '',
  ];

  if (changes.length > 0) {
    lines.push('## What changed', '');
    for (const change of changes) {
      lines.push(`- ${escapeMdx(change)}`);
    }
    lines.push('');
  }

  if (contributors.length > 0) {
    lines.push('## Contributors', '');
    for (const handle of contributors) {
      lines.push(`- [@${handle}](https://github.com/${handle})`);
    }
    lines.push('');
  }

  return `${lines.join('\n')}\n`;
}

async function fetchReleases() {
  const response = await fetch(RELEASES_URL, {
    headers: {
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
  });

  if (!response.ok) {
    throw new Error(`GitHub releases request failed (${response.status})`);
  }

  return response.json();
}

function cleanupGeneratedReleasePages() {
  if (!fs.existsSync(changelogDir)) return;

  for (const entry of fs.readdirSync(changelogDir)) {
    if (entry === 'index.mdx' || entry === 'meta.json') continue;
    if (entry.endsWith('.mdx')) {
      fs.rmSync(path.join(changelogDir, entry), { force: true });
    }
  }
}

const releases = await fetchReleases();
cleanupGeneratedReleasePages();

const pages = ['index'];
for (const release of releases) {
  const slug = slugFromTag(release.tag_name);
  pages.push(slug);
  fs.writeFileSync(path.join(changelogDir, `${slug}.mdx`), buildReleaseMdx(release));
}

fs.writeFileSync(
  metaPath,
  `${JSON.stringify({ title: 'Changelog', pages }, null, 2)}\n`,
);

console.log(`Generated ${releases.length} changelog pages in ${path.relative(docsRoot, changelogDir)}`);
