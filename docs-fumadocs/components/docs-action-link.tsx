import type { ComponentPropsWithoutRef, ReactNode } from 'react';

type DocsActionLinkProps = ComponentPropsWithoutRef<'a'> & {
  icon?: ReactNode;
};

export function DocsActionLink({ icon, className, children, ...props }: DocsActionLinkProps) {
  const mergedClassName = ['docs-action-link', className].filter(Boolean).join(' ');

  return (
    <a {...props} className={mergedClassName}>
      {icon}
      <span>{children}</span>
    </a>
  );
}
