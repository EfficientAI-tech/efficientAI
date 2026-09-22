'use client';

import { ThemeSwitch } from 'fumadocs-ui/layouts/shared/slots/theme-switch';
import { ExternalLink } from 'lucide-react';
import { communityLinks } from '@/lib/shared';

export function NavHeaderActions() {
  return (
    <div className="flex items-center gap-2">
      <a
        href={communityLinks.githubRepo}
        target="_blank"
        rel="noreferrer"
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-fd-border/75 bg-fd-card px-2 text-xs text-fd-muted-foreground transition-colors hover:bg-fd-accent/60 hover:text-fd-foreground"
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" className="size-3.5 fill-current">
          <path d="M12 1.5a10.5 10.5 0 0 0-3.32 20.46c.52.1.7-.22.7-.5v-1.73c-2.86.62-3.46-1.21-3.46-1.21-.46-1.18-1.14-1.5-1.14-1.5-.94-.64.08-.62.08-.62 1.04.08 1.58 1.06 1.58 1.06.92 1.58 2.42 1.12 3.01.86.1-.67.36-1.12.66-1.38-2.28-.26-4.67-1.14-4.67-5.1 0-1.12.4-2.04 1.06-2.76-.1-.26-.46-1.3.1-2.72 0 0 .88-.28 2.88 1.06a10.02 10.02 0 0 1 5.24 0c2-1.34 2.88-1.06 2.88-1.06.56 1.42.2 2.46.1 2.72.66.72 1.06 1.64 1.06 2.76 0 3.96-2.4 4.84-4.68 5.1.38.32.72.94.72 1.9v2.82c0 .28.18.6.72.5A10.5 10.5 0 0 0 12 1.5Z" />
        </svg>
        <span>GitHub</span>
        <ExternalLink className="size-3" />
      </a>
      <ThemeSwitch mode="light-dark" className="h-8 rounded-md border-fd-border/75 bg-fd-card" />
    </div>
  );
}
