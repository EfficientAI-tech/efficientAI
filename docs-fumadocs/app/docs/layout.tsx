import { source } from '@/lib/source';
import { baseOptions } from '@/lib/layout.shared';
import type * as PageTree from 'fumadocs-core/page-tree';
import type { LayoutTab } from 'fumadocs-ui/layouts/shared';
import { DocsShell } from '@/components/docs-shell';

function folderUrls(folder: PageTree.Folder): string[] {
  const urls: string[] = [];
  if (folder.index?.url) urls.push(folder.index.url);
  for (const child of folder.children) {
    if (child.type === 'page') urls.push(child.url);
    if (child.type === 'folder') urls.push(...folderUrls(child));
  }
  return urls;
}

function findRootFolder(tree: PageTree.Root, title: string): PageTree.Folder | undefined {
  return tree.children.find(
    (node): node is PageTree.Folder => node.type === 'folder' && node.name === title,
  );
}

export default async function Layout({ children }: LayoutProps<'/docs'>) {
  const options = baseOptions();
  const tree = source.getPageTree();
  const docsRoot = findRootFolder(tree, 'Docs');
  const apiRoot = findRootFolder(tree, 'API Reference');
  const changelogRoot = findRootFolder(tree, 'Changelog');
  const blogRoot = findRootFolder(tree, 'Blogs');
  const tabs: LayoutTab[] = [
    {
      title: 'Docs',
      url: '/docs/quickstart/',
      urls: new Set(docsRoot ? folderUrls(docsRoot) : ['/docs/', '/docs/quickstart/']),
    },
    {
      title: 'API Reference',
      url: '/docs/api-reference/',
      urls: new Set(apiRoot ? folderUrls(apiRoot) : ['/docs/api-reference/']),
    },
    {
      title: 'Enterprise',
      url: '/docs/enterprise/',
      urls: new Set(['/docs/enterprise/']),
    },
    {
      title: 'Changelog',
      url: '/docs/changelog/',
      urls: new Set(changelogRoot ? folderUrls(changelogRoot) : ['/docs/changelog/']),
    },
    {
      title: 'Blogs',
      url: '/docs/blog/',
      urls: new Set(blogRoot ? folderUrls(blogRoot) : ['/docs/blog/']),
    },
  ];

  return <DocsShell tree={tree} options={options} tabs={tabs}>{children}</DocsShell>;
}
