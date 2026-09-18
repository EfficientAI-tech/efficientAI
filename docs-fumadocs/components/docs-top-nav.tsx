'use client';

import Link from 'fumadocs-core/link';
import { usePathname } from 'fumadocs-core/framework';
import { isLayoutTabActive } from 'fumadocs-ui/layouts/shared';
import type { ReactNode } from 'react';
import { Logo } from '@/components/logo';

interface DocsTopNavTab {
  title: ReactNode;
  url: string;
  urls?: Set<string>;
}

function TabLink({ href, active, children }: { href: string; active: boolean; children: ReactNode }) {
  return (
    <Link
      href={href}
      className={[
        'inline-flex items-center border-b-2 pb-1.5 text-sm font-medium transition-colors',
        active
          ? 'border-fd-primary text-fd-primary'
          : 'border-transparent text-fd-muted-foreground hover:text-fd-foreground',
      ].join(' ')}
    >
      {children}
    </Link>
  );
}

export function DocsTopNav({ tabs }: { tabs: DocsTopNavTab[] }) {
  const pathname = usePathname();

  return (
    <header id="nd-subnav" className="sticky [grid-area:header] top-(--fd-docs-row-1) z-40 flex flex-col px-3 py-2 md:px-5">
      <div
        data-header-body=""
        className="docs-glass-nav mx-auto flex h-14 w-full max-w-[110rem] items-center gap-2 rounded-2xl border px-4 md:px-6"
      >
        <div className="flex flex-1 items-center">
          <Link href="/docs/quickstart/" className="inline-flex items-center gap-2.5 font-semibold">
            <Logo />
          </Link>
        </div>

        <nav className="docs-top-nav-tabs hidden min-w-0 flex-1 items-center gap-6 lg:flex">
          {tabs.map((tab, idx) => (
            <TabLink key={idx} href={tab.url} active={isLayoutTabActive(tab, pathname)}>
              {tab.title}
            </TabLink>
          ))}
        </nav>

        <div className="flex flex-1 items-center justify-end" />
      </div>

      <div data-header-tabs="" className="docs-glass-nav mt-2 h-10 overflow-x-auto rounded-xl border px-4 lg:hidden">
        <div className="flex h-full items-end gap-5">
          {tabs.map((tab, idx) => (
            <TabLink key={idx} href={tab.url} active={isLayoutTabActive(tab, pathname)}>
              {tab.title}
            </TabLink>
          ))}
        </div>
      </div>
    </header>
  );
}
