'use client';

import { ThemeSwitch } from 'fumadocs-ui/layouts/shared/slots/theme-switch';
import { ExternalLink } from 'lucide-react';
import { gitConfig } from '@/lib/shared';

const githubUrl = `https://github.com/${gitConfig.user}/${gitConfig.repo}`;

export function TocHeaderControls() {
  return (
    <div className="mb-2 flex items-center gap-2">
      <a
        href={githubUrl}
        target="_blank"
        rel="noreferrer"
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-fd-border/75 bg-fd-card px-2 text-xs text-fd-muted-foreground transition-colors hover:bg-fd-accent/60 hover:text-fd-foreground"
      >
        <span>GitHub</span>
        <ExternalLink className="size-3" />
      </a>
      <ThemeSwitch mode="light-dark" className="h-8 rounded-md border-fd-border/75 bg-fd-card" />
    </div>
  );
}
