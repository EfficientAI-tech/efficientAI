import type { ChangelogFeedRelease } from '@/lib/changelog-feed';

export const CHANGELOG_CATEGORIES = [
  'Security',
  'Observability',
  'Voice',
  'Usage',
  'Evaluation',
  'API',
  'Docs',
  'Platform',
  'Fixes',
  'Release',
] as const;

export type ChangelogCategory = (typeof CHANGELOG_CATEGORIES)[number];

export type ChangelogBoardUpdate = {
  id: string;
  title: string;
  category: ChangelogCategory;
  contributor: string;
  version: string;
  href: string;
  publishedAt: string;
  year: number;
  month: number;
  day: number;
};

export type ChangelogBoardWeek = {
  id: string;
  title: string;
  updates: ChangelogBoardUpdate[];
};

export type ChangelogMonthTick = {
  key: string;
  label: string;
  year: number;
  month: number;
  start: number;
  end: number;
  hasUpdates: boolean;
};

const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
] as const;

const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] as const;

const ROMAN = ['', 'I', 'II', 'III', 'IV', 'V'] as const;

const ADJECTIVES = ['jaw-dropping', 'awe-inspiring', 'groundbreaking', 'revolutionary'] as const;

const SECTION_LABELS = new Set(['what changed', 'why', 'how to test', 'contributors']);

const CATEGORY_RULES: Array<[ChangelogCategory, RegExp]> = [
  ['Security', /\b(csp|csrf|ssrf|hsts|rbac|auth|cookie|password|secret|trustedhost)\b/i],
  ['Observability', /\b(trace|traces|otlp|observability|waterfall)\b/i],
  ['Voice', /\b(pipecat|stt|tts|voice|webrtc)\b/i],
  ['Usage', /\b(usage|token|tokens|redis|rollup)\b/i],
  ['Evaluation', /\b(evaluator|metric|persona|scenario)\b/i],
  ['API', /\b(api|endpoint|openapi)\b/i],
  ['Docs', /\b(docs|readme|changelog|screenshot|sidebar|footer|mdx)\b/i],
  ['Platform', /\b(frontend|playground|workspace|ui)\b/i],
  ['Fixes', /\bfix(ed|es)?\b/i],
];

const DATE_PARTS = new Intl.DateTimeFormat('en-US', {
  timeZone: 'Asia/Kolkata',
  year: 'numeric',
  month: 'numeric',
  day: 'numeric',
});

export function changelogCalendar(iso: string): { year: number; month: number; day: number } {
  const parts = DATE_PARTS.formatToParts(new Date(iso));
  const read = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((part) => part.type === type)?.value);
  return { year: read('year'), month: read('month'), day: read('day') };
}

function linkHost(url: string): string {
  try {
    return new URL(url.replace(/[),.]+$/, '')).host.replace(/^www\./, '');
  } catch {
    return '';
  }
}

export function changelogUpdateTitle(raw: string): string | null {
  let text = raw
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\s+by\s+@[\w-]+(?:\s+in\s+https?:\/\/\S+)?/gi, '')
    .replace(/[#*`]/g, '')
    .replace(/https?:\/\/\S+/g, (url) => linkHost(url))
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[.:]\s*$/, '');

  text = text.replace(/^(fix|feat|chore|docs|refactor|perf|test):\s*/i, '');
  if (!text) return null;
  text = text.charAt(0).toUpperCase() + text.slice(1);
  if (SECTION_LABELS.has(text.toLowerCase())) return null;

  const colon = text.indexOf(':');
  if (colon >= 10 && colon <= 72) {
    const head = text.slice(0, colon).trim();
    if (head.split(/\s+/).length <= 8) text = head;
  }

  if (text.length > 96) {
    const cut = text.slice(0, 92);
    const space = cut.lastIndexOf(' ');
    text = `${(space > 48 ? cut.slice(0, space) : cut).trimEnd()}…`;
  }

  return text;
}

export function changelogCategory(text: string): ChangelogCategory {
  for (const [category, pattern] of CATEGORY_RULES) {
    if (pattern.test(text)) return category;
  }
  return 'Release';
}

export function updateCountLabel(weekId: string, count: number): string {
  const parts = weekId.split('-');
  const month = Number(parts[1] ?? 0);
  const week = Number(parts[2] ?? 0);
  const adjective = ADJECTIVES[(month + week) % ADJECTIVES.length];
  return `${count} ${adjective} ${count === 1 ? 'update' : 'updates'}`;
}

function monthKey(year: number, month: number): number {
  return year * 12 + (month - 1);
}

function weekTitle(year: number, month: number, day: number): { id: string; title: string } {
  const week = Math.min(5, Math.ceil(day / 7));
  return {
    id: `${year}-${month}-${week}`,
    title: `${MONTHS[month - 1]} ${year} - Week ${ROMAN[week]}`,
  };
}

export function buildChangelogBoard(releases: ChangelogFeedRelease[]): {
  weeks: ChangelogBoardWeek[];
  categories: ChangelogCategory[];
  contributors: string[];
} {
  const weeks = new Map<string, ChangelogBoardWeek>();
  const categories = new Set<ChangelogCategory>();
  const contributors = new Set<string>();

  for (const release of releases) {
    const contributor = release.contributors[0] ?? 'EfficientAI';
    contributors.add(contributor);
    const calendar = changelogCalendar(release.publishedAt);
    const week = weekTitle(calendar.year, calendar.month, calendar.day);
    const bucket = weeks.get(week.id) ?? { id: week.id, title: week.title, updates: [] };
    const entries = release.changes.flatMap((change, index) => {
      const title = changelogUpdateTitle(change);
      if (!title) return [];
      return [{ id: `${release.tagName}-${index}`, title, category: changelogCategory(change) }];
    });
    const seen = entries.length > 0 ? entries : [{ id: release.tagName, title: `Release ${release.tagName}`, category: 'Release' as const }];

    for (const entry of seen) {
      categories.add(entry.category);
      bucket.updates.push({
        ...entry,
        contributor,
        version: release.tagName,
        href: `/docs/changelog/${release.docsSlug}/`,
        publishedAt: release.publishedAt,
        ...calendar,
      });
    }

    weeks.set(week.id, bucket);
  }

  const ordered = [...weeks.values()].sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }));

  return {
    weeks: ordered,
    categories: CHANGELOG_CATEGORIES.filter((category) => categories.has(category)),
    contributors: [...contributors].sort((a, b) => a.localeCompare(b)),
  };
}

export function buildMonthAxis(updates: Array<{ year: number; month: number }>): ChangelogMonthTick[] {
  if (updates.length === 0) return [];

  let start = monthKey(updates[0].year, updates[0].month);
  let end = start;
  const occupied = new Set<number>();

  for (const update of updates) {
    const key = monthKey(update.year, update.month);
    occupied.add(key);
    start = Math.min(start, key);
    end = Math.max(end, key);
  }

  const span = end - start + 1;
  if (span < 8) {
    const extra = 8 - span;
    const before = Math.floor(extra / 2);
    start -= before;
    end += extra - before;
  }

  const ticks: ChangelogMonthTick[] = [];
  for (let key = start; key <= end; key += 1) {
    const year = Math.floor(key / 12);
    const month = (key % 12) + 1;
    ticks.push({
      key: `${year}-${month}`,
      label: MONTHS_SHORT[month - 1],
      year,
      month,
      start: key,
      end: key + 1,
      hasUpdates: occupied.has(key),
    });
  }
  return ticks;
}

export function calendarRatio(
  year: number,
  month: number,
  day: number,
  axisStart: number,
  axisEnd: number,
): number {
  const days = new Date(year, month, 0).getDate();
  const position = monthKey(year, month) + (day - 1) / days;
  const span = axisEnd - axisStart;
  if (span <= 0) return 0;
  return Math.min(1, Math.max(0, (position - axisStart) / span));
}
