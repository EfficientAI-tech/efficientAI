import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import { Logo } from '@/components/logo';

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      title: <Logo />,
      url: '/docs/quickstart/',
    },
    links: [],
    themeSwitch: {
      enabled: true,
      mode: 'light-dark',
    },
  };
}
