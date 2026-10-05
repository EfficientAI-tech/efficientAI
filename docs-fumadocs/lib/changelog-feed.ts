import feed from '@/data/changelog-releases-feed.json';
import type { GitHubRelease } from '@/lib/github-releases';

export type ChangelogFeedRelease = GitHubRelease & {
  docsSlug: string;
};

export function getChangelogFeedReleases(): ChangelogFeedRelease[] {
  if (!Array.isArray(feed)) return [];
  return feed as ChangelogFeedRelease[];
}
