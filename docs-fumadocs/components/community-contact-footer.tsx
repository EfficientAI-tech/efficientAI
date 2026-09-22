import { communityLinks } from '@/lib/shared';

export function CommunityContactFooter() {
  return (
    <section className="not-prose mt-10 border-t border-fd-border/70 pt-6">
      <h2 className="text-2xl font-semibold tracking-tight text-fd-foreground">Community &amp; contact</h2>
      <ol className="mt-4 list-decimal space-y-3 pl-7 text-fd-muted-foreground">
        <li>
          Found a bug or have a feature request?{' '}
          <a
            href={communityLinks.githubIssues}
            target="_blank"
            rel="noreferrer"
            className="font-semibold text-fd-foreground underline decoration-fd-primary decoration-2 underline-offset-4"
          >
            Open a GitHub issue
          </a>
          .
        </li>
        <li>
          Join our{' '}
          <a
            href={communityLinks.discord}
            target="_blank"
            rel="noreferrer"
            className="font-semibold text-fd-foreground underline decoration-fd-primary decoration-2 underline-offset-4"
          >
            Discord
          </a>{' '}
          for faster replies!
        </li>
      </ol>
    </section>
  );
}
