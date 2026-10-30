import { ChangelogBoard } from '@/components/changelog-board';
import { buildChangelogBoard } from '@/lib/changelog-board';
import { getChangelogFeedReleases } from '@/lib/changelog-feed';

export function ChangelogReleases() {
  const releases = getChangelogFeedReleases();

  if (releases.length === 0) {
    return (
      <p className="text-sm text-fd-muted-foreground">
        Recent releases are not available in this build. View them on{' '}
        <a
          href="https://github.com/EfficientAI-tech/efficientAI/releases"
          className="font-medium text-fd-primary underline-offset-4 hover:underline"
        >
          GitHub Releases
        </a>
        , or pick a version from the sidebar.
      </p>
    );
  }

  const board = buildChangelogBoard(releases);
  return <ChangelogBoard weeks={board.weeks} categories={board.categories} contributors={board.contributors} />;
}
