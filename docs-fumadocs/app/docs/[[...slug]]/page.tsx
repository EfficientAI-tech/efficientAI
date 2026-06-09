import { source } from '@/lib/source';
import { DocsBody, DocsPage } from 'fumadocs-ui/layouts/docs/page';
import { notFound } from 'next/navigation';
import { getMDXComponents } from '@/components/mdx';
import type { Metadata } from 'next';
import { createRelativeLink } from 'fumadocs-ui/mdx';
import { ContributorsTocFooter } from '@/components/contributors';
import { TocHeaderControls } from '@/components/toc-header-controls';
import type { ComponentPropsWithoutRef } from 'react';
import { ExternalLink } from 'lucide-react';

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

  const MDX = page.data.body;

  return (
    <DocsPage
      toc={page.data.toc}
      full={page.data.full}
      breadcrumb={{ enabled: false }}
      tableOfContent={{
        header: <TocHeaderControls />,
        footer: <ContributorsTocFooter featureId={page.slugs.join('/')} />,
      }}
      tableOfContentPopover={{
        header: <TocHeaderControls />,
        footer: <ContributorsTocFooter featureId={page.slugs.join('/')} />,
      }}
    >
      <DocsBody>
        <MDX
          components={getMDXComponents({
            // this allows you to link to other pages with relative file paths
            a: (props) => <DocsRelativeLink {...props} resolver={createRelativeLink(source, page)} />,
          })}
        />
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
