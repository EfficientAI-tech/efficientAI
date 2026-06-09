'use client';

import { RootProvider } from 'fumadocs-ui/provider/next';
import { DocsSearchDialog } from '@/components/docs-search-dialog';

export function DocsProvider({ children }: { children: React.ReactNode }) {
  return (
    <RootProvider
      search={{
        SearchDialog: DocsSearchDialog,
        options: {
          api: '/search-index.json',
          delayMs: 120,
        },
      }}
    >
      {children}
    </RootProvider>
  );
}
