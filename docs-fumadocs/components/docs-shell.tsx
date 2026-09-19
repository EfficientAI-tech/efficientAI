'use client';

import type * as PageTree from 'fumadocs-core/page-tree';
import { usePathname } from 'fumadocs-core/framework';
import type { BaseLayoutProps, LayoutTab } from 'fumadocs-ui/layouts/shared';
import { DocsLayout } from 'fumadocs-ui/layouts/notebook';
import type { ReactNode } from 'react';
import { DocsTopNav } from '@/components/docs-top-nav';

function findRootFolder(tree: PageTree.Root, title: string): PageTree.Folder | undefined {
  return tree.children.find(
    (node): node is PageTree.Folder => node.type === 'folder' && node.name === title,
  );
}

function routeMode(pathname: string): 'docs' | 'api' | 'enterprise' | 'changelog' | 'blog' {
  if (pathname.startsWith('/docs/api-reference')) return 'api';
  if (pathname.startsWith('/docs/enterprise')) return 'enterprise';
  if (pathname.startsWith('/docs/changelog')) return 'changelog';
  if (pathname.startsWith('/docs/blog')) return 'blog';
  return 'docs';
}

function matchesModeUrl(url: string, mode: ReturnType<typeof routeMode>): boolean {
  if (mode === 'api') return url.startsWith('/docs/api-reference/');
  if (mode === 'enterprise') return url.startsWith('/docs/enterprise/');
  if (mode === 'changelog') return url.startsWith('/docs/changelog/');
  if (mode === 'blog') return url.startsWith('/docs/blog/');
  return (
    url.startsWith('/docs/') &&
    !url.startsWith('/docs/api-reference/') &&
    !url.startsWith('/docs/enterprise/') &&
    !url.startsWith('/docs/changelog/') &&
    !url.startsWith('/docs/blog/')
  );
}

function filterNodeByMode(node: PageTree.Node, mode: ReturnType<typeof routeMode>): PageTree.Node | null {
  if (node.type === 'page') return matchesModeUrl(node.url, mode) ? node : null;

  if (node.type === 'folder') {
    const filteredChildren = node.children
      .map((child) => filterNodeByMode(child, mode))
      .filter((child): child is PageTree.Node => child !== null);
    const keepIndex = node.index && matchesModeUrl(node.index.url, mode);
    if (!keepIndex && filteredChildren.length === 0) return null;
    return {
      ...node,
      index: keepIndex ? node.index : undefined,
      children: filteredChildren,
    };
  }

  return null;
}

function makeSidebarTree(tree: PageTree.Root, mode: ReturnType<typeof routeMode>): PageTree.Root {
  if (mode === 'enterprise') return { ...tree, children: [] };

  const byName =
    mode === 'api'
      ? findRootFolder(tree, 'API Reference')
      : mode === 'docs'
        ? findRootFolder(tree, 'Docs')
        : mode === 'changelog'
          ? findRootFolder(tree, 'Changelog')
          : findRootFolder(tree, 'Blogs');
  if (byName) return { ...tree, children: byName.children };

  const filteredChildren = tree.children
    .map((node) => filterNodeByMode(node, mode))
    .filter((node): node is PageTree.Node => node !== null);

  const filteredTree: PageTree.Root = { ...tree, children: filteredChildren };
  if (filteredTree.children.length === 1 && filteredTree.children[0]?.type === 'folder') {
    return { ...filteredTree, children: filteredTree.children[0].children };
  }
  return filteredTree;
}

export function DocsShell({
  tree,
  options,
  tabs,
  children,
}: {
  tree: PageTree.Root;
  options: BaseLayoutProps;
  tabs: LayoutTab[];
  children: ReactNode;
}) {
  const pathname = usePathname();
  const mode = routeMode(pathname);
  const sidebarTree = makeSidebarTree(tree, mode);
  const isNoSidebar = mode === 'enterprise';

  return (
    <div
      className={[
        isNoSidebar ? 'docs-no-sidebar' : '',
        `docs-mode-${mode}`,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <DocsLayout
        key={mode}
        tree={sidebarTree}
        {...options}
        tabMode="navbar"
        nav={{
          ...options.nav,
          mode: 'top',
          component: <DocsTopNav tabs={tabs} />,
        }}
        tabs={tabs}
      >
        {children}
      </DocsLayout>
    </div>
  );
}
