import defaultMdxComponents from 'fumadocs-ui/mdx';
import type { MDXComponents } from 'mdx/types';
import type { ComponentPropsWithoutRef } from 'react';
import { ExternalLink } from 'lucide-react';
import { Contributors } from './contributors';
import { ChangelogReleases } from './changelog-releases';
import { IntegrationProviderNav } from './integration-provider-nav';
import { MdxPre } from './mdx-pre';
import { MdxHeading } from './mdx-heading';
import { ScreenshotPlaceholder } from './screenshot-placeholder';
import { EnterpriseComparison, EnterpriseGatedFeatures } from './enterprise-comparison';

function DocsBodyLink({ className, ...props }: ComponentPropsWithoutRef<'a'>) {
  const mergedClassName = ['font-medium', className].filter(Boolean).join(' ');
  const href = typeof props.href === 'string' ? props.href : '';
  const isExternal = /^https?:\/\//.test(href);

  if (!isExternal) return <a {...props} className={mergedClassName} />;

  return (
    <a {...props} className={['inline-flex items-center gap-1', mergedClassName].join(' ')}>
      <span>{props.children}</span>
      <ExternalLink className="size-3.5 opacity-80" />
    </a>
  );
}

export function getMDXComponents(components?: MDXComponents) {
  return {
    ...defaultMdxComponents,
    a: DocsBodyLink,
    pre: MdxPre,
    h2: (props) => <MdxHeading level={2} {...props} />,
    h3: (props) => <MdxHeading level={3} {...props} />,
    Contributors,
    ChangelogReleases,
    IntegrationProviderNav,
    ScreenshotPlaceholder,
    EnterpriseComparison,
    EnterpriseGatedFeatures,
    ...components,
  } satisfies MDXComponents;
}

export const useMDXComponents = getMDXComponents;

declare global {
  type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
