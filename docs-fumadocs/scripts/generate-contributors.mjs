#!/usr/bin/env node

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const REPO_ROOT = path.resolve(process.cwd(), '..');
const DOCS_APP_ROOT = process.cwd();
const LEGACY_DOCS_ROOT = 'EfficientAI-Docs/docs';
const CURRENT_DOCS_ROOT = 'docs-fumadocs/content/docs';
const CURRENT_DOCS_ABS_ROOT = path.join(DOCS_APP_ROOT, 'content', 'docs');
const OWNERS_PATH = path.join(DOCS_APP_ROOT, 'content', 'feature-owners.json');
const OUTPUT_PATH = path.join(DOCS_APP_ROOT, 'content', 'feature-contributors.json');
const MAX_CONTRIBUTORS = 5;
const MIN_COMMITS = 2;
const CHECK_MODE = process.argv.includes('--check');
const BOT_PATTERN = /(\[bot\]|dependabot|github-actions|renovate)/i;

function runGit(args) {
  return execFileSync('git', args, {
    cwd: REPO_ROOT,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
}

function fileExists(relativePath) {
  return fs.existsSync(path.join(REPO_ROOT, relativePath));
}

function discoverFeatureDocs(dirPath, prefix = '') {
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  const features = [];

  for (const entry of entries) {
    if (entry.name.startsWith('.')) continue;
    if (entry.isDirectory()) {
      features.push(...discoverFeatureDocs(path.join(dirPath, entry.name), `${prefix}${entry.name}/`));
      continue;
    }

    if (!entry.isFile() || !entry.name.endsWith('.mdx')) continue;
    features.push(`${prefix}${entry.name.slice(0, -4)}`);
  }

  return features.sort((a, b) => a.localeCompare(b));
}

function historyPathFor(featureId) {
  const current = `${CURRENT_DOCS_ROOT}/${featureId}.mdx`;
  if (fileExists(current)) return current;

  const legacy = `${LEGACY_DOCS_ROOT}/${featureId}.md`;
  if (fileExists(legacy)) return legacy;

  return current;
}

function isBotAuthor(name, email) {
  return BOT_PATTERN.test(name) || BOT_PATTERN.test(email);
}

function parseContributors(historyPath) {
  let output = '';
  try {
    output = runGit(['log', '--follow', '--format=%aN|%aE', '--', historyPath]);
  } catch {
    return [];
  }

  const counts = new Map();
  let skippedBots = 0;
  for (const line of output.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const [namePart, emailPart] = trimmed.split('|');
    const name = (namePart || '').trim();
    const email = (emailPart || '').trim().toLowerCase();
    if (!name || !email) continue;
    if (isBotAuthor(name, email)) {
      skippedBots += 1;
      continue;
    }
    const key = email;
    const existing = counts.get(key) || { name, email, commits: 0 };
    existing.commits += 1;
    counts.set(key, existing);
  }

  let contributors = Array.from(counts.values()).sort((a, b) => {
    if (b.commits !== a.commits) return b.commits - a.commits;
    return a.name.localeCompare(b.name);
  });

  const thresholdFiltered = contributors.filter((entry) => entry.commits >= MIN_COMMITS);
  if (thresholdFiltered.length > 0) {
    contributors = thresholdFiltered;
  } else {
    contributors = contributors.filter((entry) => entry.commits >= 1);
  }

  return {
    contributors: contributors.slice(0, MAX_CONTRIBUTORS),
    skippedBots,
  };
}

function readOwners() {
  if (!fs.existsSync(OWNERS_PATH)) return {};
  return JSON.parse(fs.readFileSync(OWNERS_PATH, 'utf8'));
}

function buildMetadata() {
  const ownersByFeature = readOwners();
  const featureDocs = discoverFeatureDocs(CURRENT_DOCS_ABS_ROOT);
  const now = new Date().toISOString().slice(0, 10);
  let totalContributors = 0;
  let totalSkippedBots = 0;

  const features = featureDocs.map((featureId) => {
    const docPath = `${CURRENT_DOCS_ROOT}/${featureId}.mdx`;
    const historyPath = historyPathFor(featureId);
    const { contributors, skippedBots } = parseContributors(historyPath);
    totalContributors += contributors.length;
    totalSkippedBots += skippedBots;

    return {
      featureId,
      docPath,
      historyPath,
      owners: Array.isArray(ownersByFeature[featureId]) ? ownersByFeature[featureId] : [],
      contributors,
      lastReviewed: now,
    };
  });

  return {
    source: 'git-history',
    maxContributors: MAX_CONTRIBUTORS,
    minCommits: MIN_COMMITS,
    features,
    summary: {
      featureCount: featureDocs.length,
      contributorCount: totalContributors,
      skippedBots: totalSkippedBots,
    },
  };
}

function main() {
  const nextData = `${JSON.stringify(buildMetadata(), null, 2)}\n`;

  if (CHECK_MODE) {
    if (!fs.existsSync(OUTPUT_PATH)) {
      console.error(`Missing generated file: ${OUTPUT_PATH}`);
      process.exit(1);
    }
    const existing = fs.readFileSync(OUTPUT_PATH, 'utf8');
    if (existing !== nextData) {
      console.error('feature-contributors.json is out of date. Run `npm run contributors:generate`.');
      process.exit(1);
    }
    return;
  }

  fs.writeFileSync(OUTPUT_PATH, nextData, 'utf8');
  const parsed = JSON.parse(nextData);
  console.log(
    `Generated ${path.relative(DOCS_APP_ROOT, OUTPUT_PATH)} (${parsed.summary.featureCount} features, ${parsed.summary.contributorCount} contributors, ${parsed.summary.skippedBots} bot commits skipped)`,
  );
}

main();
