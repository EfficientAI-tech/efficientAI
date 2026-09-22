import { fetchGitHubReleases } from '@/lib/github-releases';

function formatReleaseDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export async function ChangelogReleases() {
  let releases: Awaited<ReturnType<typeof fetchGitHubReleases>> = [];

  try {
    releases = await fetchGitHubReleases();
  } catch {
    return (
      <p className="text-sm text-fd-muted-foreground">
        Release notes are temporarily unavailable. View them on{' '}
        <a
          href="https://github.com/EfficientAI-tech/efficientAI/releases"
          className="font-medium text-fd-primary underline-offset-4 hover:underline"
        >
          GitHub Releases
        </a>
        .
      </p>
    );
  }

  if (releases.length === 0) {
    return <p className="text-sm text-fd-muted-foreground">No releases found yet.</p>;
  }

  return (
    <div className="not-prose space-y-8">
      {releases.map((release) => (
        <section key={release.tagName} className="rounded-lg border border-fd-border/70 bg-fd-card/40 p-5">
          <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="text-lg font-semibold text-fd-foreground">{release.tagName}</h2>
            <time className="text-sm text-fd-muted-foreground">{formatReleaseDate(release.publishedAt)}</time>
            <a
              href={release.htmlUrl}
              className="text-sm font-medium text-fd-primary underline-offset-4 hover:underline"
            >
              View on GitHub
            </a>
          </div>

          {release.changes.length > 0 ? (
            <ul className="mb-4 list-disc space-y-1.5 pl-5 text-sm text-fd-foreground/90">
              {release.changes.map((change) => (
                <li key={change}>{change}</li>
              ))}
            </ul>
          ) : null}

          {release.contributors.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2 border-t border-fd-border/60 pt-3">
              <span className="text-xs font-medium uppercase tracking-wide text-fd-muted-foreground">
                Contributors
              </span>
              {release.contributors.map((handle) => (
                <a
                  key={handle}
                  href={`https://github.com/${handle}`}
                  className="inline-flex items-center rounded-full border border-fd-border/70 bg-fd-background px-2.5 py-0.5 text-xs font-medium text-fd-foreground hover:border-fd-primary/40"
                >
                  @{handle}
                </a>
              ))}
            </div>
          ) : null}
        </section>
      ))}
    </div>
  );
}
