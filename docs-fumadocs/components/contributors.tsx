import data from '@/content/feature-contributors.json';
import profiles from '@/content/contributor-profiles.json';
import { resolveFeatureId } from '@/lib/resolve-feature-id';
import { fetchGitHubReleases } from '@/lib/github-releases';
import { DocsActionLink } from './docs-action-link';

type ContributorEntry = {
  name: string;
  email: string;
  commits: number;
};

type FeatureContributorEntry = {
  featureId: string;
  owners: string[];
  contributors: ContributorEntry[];
  lastReviewed: string;
};

type ContributorProfile = {
  github?: string;
};

type ContributorItem = {
  name: string;
  url: string;
};

const featureMap = new Map(
  (data.features as FeatureContributorEntry[]).map((entry) => [entry.featureId, entry]),
);

const profileMap = profiles as Record<string, ContributorProfile>;

const DEFAULT_OWNERS = ['aadhar-EAI', 'Tejas Narayan'];

function toGithubUrl(name: string, email?: string) {
  const mapped = profileMap[name]?.github;
  if (mapped) return `https://github.com/${mapped}`;

  // Parse GitHub noreply emails when present.
  if (email && email.includes('users.noreply.github.com')) {
    const username = email.split('@')[0].split('+').at(-1)?.trim();
    if (username) return `https://github.com/${username}`;
  }

  return `https://github.com/search?q=${encodeURIComponent(name)}&type=users`;
}

function uniqueContributors(values: ContributorItem[]) {
  const seen = new Set<string>();
  const items: ContributorItem[] = [];
  for (const value of values) {
    const key = value.name.trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    items.push(value);
  }
  return items;
}

function defaultContributors(): ContributorItem[] {
  return DEFAULT_OWNERS.map((name) => ({
    name,
    url: toGithubUrl(name),
  }));
}

export function getFeatureContributors(slugPath: string): ContributorItem[] {
  const featureId = resolveFeatureId(slugPath);
  const feature = featureMap.get(featureId);

  if (!feature) {
    return defaultContributors();
  }

  const ownerEntries = feature.owners.map((name) => ({
    name,
    url: toGithubUrl(name),
  }));
  const gitEntries = feature.contributors.map((contributor) => ({
    name: contributor.name,
    url: toGithubUrl(contributor.name, contributor.email),
  }));

  const resolved = uniqueContributors([...ownerEntries, ...gitEntries]);
  return (resolved.length > 0 ? resolved : defaultContributors()).slice(0, 6);
}

async function getChangelogContributors(): Promise<ContributorItem[]> {
  try {
    const releases = await fetchGitHubReleases();
    const handles = new Set<string>();
    for (const release of releases) {
      for (const handle of release.contributors) {
        handles.add(handle);
      }
    }

    if (handles.size === 0) return defaultContributors();

    return [...handles].slice(0, 8).map((handle) => ({
      name: `@${handle}`,
      url: `https://github.com/${handle}`,
    }));
  } catch {
    return defaultContributors();
  }
}

async function resolveContributors(slugPath: string): Promise<ContributorItem[]> {
  if (slugPath === 'changelog' || slugPath.startsWith('changelog/')) {
    return getChangelogContributors();
  }

  return getFeatureContributors(slugPath);
}

export function Contributors({ featureId }: { featureId: string }) {
  const contributors = getFeatureContributors(featureId);

  if (contributors.length === 0) {
    return (
      <p className="text-sm text-fd-muted-foreground">
        Contributor data is pending for this feature.
      </p>
    );
  }

  return (
    <div className="rounded-lg border border-fd-border/75 bg-fd-card/65 p-4">
      <h4 className="m-0 text-sm font-semibold">Contributors</h4>
      <ul className="mt-3 flex flex-wrap gap-2">
        {contributors.map((contributor) => (
          <li key={`${featureId}-${contributor.name}`} className="max-w-full">
            <DocsActionLink
              href={contributor.url}
              target="_blank"
              rel="noreferrer"
              className="max-w-full truncate"
            >
              {contributor.name}
            </DocsActionLink>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function FloatingContributors({ featureId }: { featureId: string }) {
  const contributors = getFeatureContributors(featureId);
  if (contributors.length === 0) return null;

  return (
    <aside className="fixed bottom-4 right-4 z-40 hidden min-w-56 rounded-lg border border-fd-border/80 bg-fd-card/90 p-3 text-sm shadow-sm backdrop-blur md:block">
      <p className="mb-2 font-semibold">Contributors</p>
      <ul className="space-y-1">
        {contributors.map((contributor) => (
          <li key={`${featureId}-floating-${contributor.name}`}>
            <DocsActionLink
              href={contributor.url}
              target="_blank"
              rel="noreferrer"
              className="w-full justify-start"
            >
              {contributor.name}
            </DocsActionLink>
          </li>
        ))}
      </ul>
    </aside>
  );
}

export function DocsBottomMeta({
  featureId,
}: {
  featureId: string;
}) {
  const contributors = getFeatureContributors(featureId);
  if (contributors.length === 0) return null;

  return (
    <section className="mt-10 -mx-4 border-t border-fd-border px-4 pt-5 md:-mx-6 md:px-6 xl:-mx-8 xl:px-8">
      <div className="ml-auto w-full max-w-sm rounded-md border border-fd-border/70 bg-fd-card px-3 py-2 text-sm">
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-fd-muted-foreground">
          Contributors
        </p>
        <ul className="space-y-1.5">
          {contributors.map((contributor) => (
            <li key={`${featureId}-rail-${contributor.name}`}>
              <DocsActionLink
                href={contributor.url}
                target="_blank"
                rel="noreferrer"
                className="w-full justify-start"
              >
                {contributor.name}
              </DocsActionLink>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export async function ContributorsTocFooter({ featureId }: { featureId: string }) {
  const contributors = await resolveContributors(featureId);

  return (
    <div className="mt-auto border-t border-fd-border/70 pt-4">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-fd-muted-foreground">
        Contributors
      </p>
      <ul className="space-y-1">
        {contributors.map((contributor) => (
          <li key={`${featureId}-toc-${contributor.name}`}>
            <DocsActionLink
              href={contributor.url}
              target="_blank"
              rel="noreferrer"
              className="w-full justify-start px-1.5 py-1 text-xs"
            >
              {contributor.name}
            </DocsActionLink>
          </li>
        ))}
      </ul>
    </div>
  );
}
