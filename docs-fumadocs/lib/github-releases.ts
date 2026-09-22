export type GitHubRelease = {
  tagName: string;
  name: string;
  publishedAt: string;
  htmlUrl: string;
  changes: string[];
  contributors: string[];
};

const RELEASES_URL =
  'https://api.github.com/repos/EfficientAI-tech/efficientAI/releases?per_page=30';

function parseReleaseBody(body: string): { changes: string[]; contributors: string[] } {
  const changes: string[] = [];
  const contributors = new Set<string>();

  for (const line of body.split('\n')) {
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

export async function fetchGitHubReleases(): Promise<GitHubRelease[]> {
  const response = await fetch(RELEASES_URL, {
    next: { revalidate: 3600 },
    headers: {
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
  });

  if (!response.ok) {
    throw new Error(`GitHub releases request failed (${response.status})`);
  }

  const data = (await response.json()) as Array<{
    tag_name: string;
    name: string;
    published_at: string;
    html_url: string;
    body: string | null;
  }>;

  return data.map((release) => {
    const parsed = parseReleaseBody(release.body ?? '');
    return {
      tagName: release.tag_name,
      name: release.name || release.tag_name,
      publishedAt: release.published_at,
      htmlUrl: release.html_url,
      changes: parsed.changes,
      contributors: parsed.contributors,
    };
  });
}
