const PULL_URL_PATTERN = /https:\/\/github\.com\/[^/\s]+\/[^/\s]+\/pull\/(\d+)/gi;

function linkifyUrls(text: string): string {
  return text.replace(/(?<!\]\()https:\/\/github\.com\/[^\s)]+/g, (url) => `[${url}](${url})`);
}

function parseSectionMap(body: string): Map<string, string[]> {
  const sectionMap = new Map<string, string[]>();
  let current = '__intro__';
  sectionMap.set(current, []);

  for (const rawLine of body.split('\n')) {
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

function pickSection(
  sectionMap: Map<string, string[]>,
  candidates: string[],
): string | undefined {
  for (const candidate of candidates) {
    const normalized = candidate.toLowerCase().replace(/[^\w]+/g, ' ').trim();
    const lines = sectionMap.get(normalized);
    if (!lines) continue;
    const text = linkifyUrls(lines.join('\n').trim());
    if (text) return text;
  }
  return undefined;
}

export function extractPullNumbers(text: string): number[] {
  const numbers = new Set<number>();
  for (const match of text.matchAll(PULL_URL_PATTERN)) {
    const value = Number.parseInt(match[1] ?? '', 10);
    if (Number.isFinite(value)) numbers.add(value);
  }
  return [...numbers];
}

export function parsePrSections(body: string): {
  whatChanged?: string;
  why?: string;
  howToTest?: string;
} {
  const sectionMap = parseSectionMap(body);
  return {
    whatChanged: pickSection(sectionMap, ['What Changed', 'Changes']),
    why: pickSection(sectionMap, ['Why']),
    howToTest: pickSection(sectionMap, ['How to Test', 'Testing', 'Test Plan']),
  };
}
