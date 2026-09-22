#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const docsRoot = path.resolve(__dirname, '..');
const changelogDir = path.join(docsRoot, 'content', 'docs', 'changelog');
const metaPath = path.join(changelogDir, 'meta.json');
const githubOwner = 'EfficientAI-tech';
const githubRepo = 'efficientAI';
const pullUrlPattern = /https:\/\/github\.com\/[^/\s]+\/[^/\s]+\/pull\/(\d+)/gi;

const RELEASES_BASE_URL =
  `https://api.github.com/repos/${githubOwner}/${githubRepo}/releases`;

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

function linkifyUrls(text) {
  return text.replace(/(?<!\]\()https:\/\/github\.com\/[^\s)]+/g, (url) => `[${url}](${url})`);
}

function parseSectionMap(body) {
  const sectionMap = new Map();
  let current = '__intro__';
  sectionMap.set(current, []);

  for (const rawLine of (body ?? '').split('\n')) {
    const heading = rawLine.match(/^##\s+(.+?)\s*$/);
    if (heading) {
      current = heading[1].trim().toLowerCase().replace(/[^\w]+/g, ' ').trim();
      sectionMap.set(current, []);
      continue;
    }

    sectionMap.get(current)?.push(rawLine);
  }

  return sectionMap;
}

function pickSection(sectionMap, candidates) {
  for (const candidate of candidates) {
    const normalized = candidate.toLowerCase().replace(/[^\w]+/g, ' ').trim();
    const lines = sectionMap.get(normalized);
    if (!lines) continue;
    const text = linkifyUrls(lines.join('\n').trim());
    if (text) return text;
  }
  return undefined;
}

function parsePrSections(body) {
  const sectionMap = parseSectionMap(body);
  return {
    whatChanged: pickSection(sectionMap, ['What Changed', 'Changes']),
    why: pickSection(sectionMap, ['Why']),
    howToTest: pickSection(sectionMap, ['How to Test', 'Testing', 'Test Plan']),
  };
}

function extractPullNumbers(text) {
  const numbers = new Set();
  for (const match of (text ?? '').matchAll(pullUrlPattern)) {
    const value = Number.parseInt(match[1] ?? '', 10);
    if (Number.isFinite(value)) numbers.add(value);
  }
  return [...numbers];
}

async function fetchPullRequest(pullNumber, token) {
  const response = await fetch(
    `https://api.github.com/repos/${githubOwner}/${githubRepo}/pulls/${pullNumber}`,
    {
      headers: {
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    },
  );

  if (!response.ok) {
    throw new Error(`PR request failed (${response.status}) for #${pullNumber}`);
  }

  return response.json();
}

function buildReleaseMdx(release, prDetails) {
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

  if (prDetails) {
    lines.push(
      `Primary pull request: [#${prDetails.number}](${prDetails.url}) by [@${prDetails.author}](https://github.com/${prDetails.author}).`,
      '',
    );
  }

  let hasDetailedSections = false;
  if (prDetails?.sections.whatChanged) {
    lines.push('## What changed', '');
    lines.push(prDetails.sections.whatChanged);
    lines.push('');
    hasDetailedSections = true;
  }

  if (prDetails?.sections.why) {
    lines.push('## Why', '');
    lines.push(prDetails.sections.why);
    lines.push('');
    hasDetailedSections = true;
  }

  if (prDetails?.sections.howToTest) {
    lines.push('## How to test', '');
    lines.push(prDetails.sections.howToTest);
    lines.push('');
    hasDetailedSections = true;
  }

  if (!hasDetailedSections && changes.length > 0) {
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

function hasCommittedReleasePages() {
  if (!fs.existsSync(changelogDir)) return false;
  return fs.readdirSync(changelogDir).some((entry) => /^v\d/.test(entry) && entry.endsWith('.mdx'));
}

async function fetchReleases() {
  const token = process.env.GITHUB_TOKEN?.trim();
  const headers = {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const releases = [];
  let page = 1;

  while (true) {
    const response = await fetch(`${RELEASES_BASE_URL}?per_page=100&page=${page}`, { headers });

    if (!response.ok) {
      if (hasCommittedReleasePages()) {
        console.warn(
          `Skipping changelog regeneration (GitHub releases request failed with ${response.status}); using committed pages.`,
        );
        process.exit(0);
      }
      throw new Error(`GitHub releases request failed (${response.status})`);
    }

    const batch = await response.json();
    if (!Array.isArray(batch) || batch.length === 0) break;
    releases.push(...batch);
    if (batch.length < 100) break;
    page += 1;
  }

  return releases;
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
const token = process.env.GITHUB_TOKEN?.trim();

const pages = ['index'];
for (const release of releases) {
  const slug = slugFromTag(release.tag_name);
  const pullNumbers = extractPullNumbers(release.body ?? '');
  let prDetails;

  if (pullNumbers.length > 0) {
    try {
      const primaryPr = await fetchPullRequest(pullNumbers[0], token);
      prDetails = {
        number: primaryPr.number,
        url: primaryPr.html_url,
        author: primaryPr.user?.login ?? 'unknown',
        sections: parsePrSections(primaryPr.body ?? ''),
      };
    } catch (error) {
      console.warn(
        `Skipping PR enrichment for ${release.tag_name}: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }

  pages.push(slug);
  fs.writeFileSync(path.join(changelogDir, `${slug}.mdx`), buildReleaseMdx(release, prDetails));
}

fs.writeFileSync(
  metaPath,
  `${JSON.stringify({ title: 'Changelog', pages }, null, 2)}\n`,
);

console.log(`Generated ${releases.length} changelog pages in ${path.relative(docsRoot, changelogDir)}`);
