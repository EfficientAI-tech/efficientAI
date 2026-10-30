import fs from 'node:fs';
import path from 'node:path';

export function getChangelogSidebarDates(): Record<string, string> {
  const dir = path.join(process.cwd(), 'content', 'docs', 'changelog');
  const dates: Record<string, string> = {};
  if (!fs.existsSync(dir)) return dates;

  for (const file of fs.readdirSync(dir)) {
    if (!file.endsWith('.mdx') || file === 'index.mdx') continue;
    const text = fs.readFileSync(path.join(dir, file), 'utf8');
    const match = text.match(/^Released\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})\./m);
    if (!match) continue;
    const slug = file.slice(0, -'.mdx'.length);
    dates[`/docs/changelog/${slug}/`] = match[1];
  }

  return dates;
}
