import { source } from '@/lib/source';
import { DocsBody, DocsPage } from 'fumadocs-ui/layouts/notebook/page';
import { notFound } from 'next/navigation';
import { getMDXComponents } from '@/components/mdx';
import type { Metadata } from 'next';
import { createRelativeLink } from 'fumadocs-ui/mdx';
import { ContributorsTocFooter } from '@/components/contributors';
import { OpenAPIPage } from '@/components/api-page';
import { CopyPageMarkdown } from '@/components/copy-page-markdown';
import { CommunityContactFooter } from '@/components/community-contact-footer';
import type { ComponentPropsWithoutRef, ComponentType } from 'react';
import { ExternalLink } from 'lucide-react';
import type { TOCItemType } from 'fumadocs-core/toc';
import { openapi } from '@/lib/openapi';

function DocsRelativeLink(props: ComponentPropsWithoutRef<'a'> & { resolver: ReturnType<typeof createRelativeLink> }) {
  const { resolver, className, ...rest } = props;
  const href = typeof rest.href === 'string' ? rest.href : '';
  const isExternal = /^https?:\/\//.test(href);

  if (isExternal) {
    return (
      <a
        {...rest}
        className={['inline-flex items-center gap-1 font-medium', className].filter(Boolean).join(' ')}
      >
        <span>{props.children}</span>
        <ExternalLink className="size-3.5 opacity-80" />
      </a>
    );
  }

  return resolver({
    ...rest,
    className: ['font-medium', className].filter(Boolean).join(' '),
  });
}

export default async function Page(props: PageProps<'/docs/[[...slug]]'>) {
  const params = await props.params;
  const page = source.getPage(params.slug);
  if (!page) notFound();

  const pageData = page.data as typeof page.data & {
    body: ComponentType<{ components?: ReturnType<typeof getMDXComponents> }>;
    toc?: TOCItemType[];
    full?: boolean;
    _openapi?: { method?: string };
  };
  const MDX = pageData.body;
  const markdownPath =
    page.slugs[0] === 'api-reference' && page.slugs.length > 2 && pageData._openapi?.method
      ? `/api-md/${page.slugs.slice(1).join('/')}.md`
      : null;
  const isEnterprisePage = (page.slugs[0] ?? '') === 'enterprise';
  const showToc = !isEnterprisePage;
  const toc = showToc ? pageData.toc : undefined;
  const full = isEnterprisePage || Boolean(pageData.full);

  return (
    <DocsPage
      toc={toc}
      full={full}
      breadcrumb={{ enabled: !isEnterprisePage }}
      tableOfContent={
        showToc
          ? {
              footer: <ContributorsTocFooter featureId={page.slugs.join('/')} />,
            }
          : undefined
      }
      tableOfContentPopover={
        showToc
          ? {
              footer: <ContributorsTocFooter featureId={page.slugs.join('/')} />,
            }
          : undefined
      }
    >
      <DocsBody className={isEnterprisePage ? 'enterprise-doc' : undefined}>
        {markdownPath ? (
          <div className="not-prose mb-4 flex justify-end">
            <CopyPageMarkdown mdPath={markdownPath} />
          </div>
        ) : null}
        <MDX
          components={getMDXComponents({
            // this allows you to link to other pages with relative file paths
            a: (props) => <DocsRelativeLink {...props} resolver={createRelativeLink(source, page)} />,
            OpenAPIPage: async (props) => (
              <OpenAPIPage {...(await openapi.preloadOpenAPIPage(page))} {...props} />
            ),
          })}
        />
        {!isEnterprisePage ? <CommunityContactFooter /> : null}
      </DocsBody>
    </DocsPage>
  );
}

export async function generateStaticParams() {
  return source.generateParams();
}

export async function generateMetadata(props: PageProps<'/docs/[[...slug]]'>): Promise<Metadata> {
  const params = await props.params;
  const page = source.getPage(params.slug);
  if (!page) notFound();

  return {
    title: page.data.title,
    description: page.data.description,
  };
}
