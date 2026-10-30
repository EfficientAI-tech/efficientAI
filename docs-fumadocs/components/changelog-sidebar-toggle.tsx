'use client';

import { usePathname } from 'fumadocs-core/framework';
import { useSidebar } from 'fumadocs-ui/components/sidebar/base';
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';

const buttonClass =
  'inline-flex size-7 shrink-0 items-center justify-center rounded-md text-fd-muted-foreground hover:bg-fd-accent hover:text-fd-foreground';

export function ChangelogSidebarCollapse() {
  const { setCollapsed } = useSidebar();

  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-sm font-semibold text-fd-foreground">Versions</span>
      <button type="button" className={buttonClass} aria-label="Collapse version list" onClick={() => setCollapsed(true)}>
        <PanelLeftClose className="size-4" />
      </button>
    </div>
  );
}

export function ChangelogSidebarExpand() {
  const pathname = usePathname();
  const { collapsed, setCollapsed } = useSidebar();
  if (!pathname.startsWith('/docs/changelog') || !collapsed) return null;

  return (
    <button type="button" className={buttonClass} aria-label="Expand version list" onClick={() => setCollapsed(false)}>
      <PanelLeftOpen className="size-4" />
    </button>
  );
}
