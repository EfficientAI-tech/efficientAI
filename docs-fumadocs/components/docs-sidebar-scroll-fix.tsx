'use client';

import { usePathname } from 'fumadocs-core/framework';
import { useEffect } from 'react';

function enableSidebarScroll() {
  const sidebar = document.getElementById('nd-sidebar');
  if (!sidebar) return;

  const viewport = sidebar.querySelector('[data-radix-scroll-area-viewport]') as HTMLElement | null;
  if (!viewport) return;

  viewport.style.overflowY = 'auto';
  viewport.style.overflowX = 'hidden';
  viewport.style.maxHeight = '100%';
  viewport.style.height = '100%';
  viewport.style.mask = 'none';
  viewport.style.webkitMask = 'none';
}

export function DocsSidebarScrollFix() {
  const pathname = usePathname();

  useEffect(() => {
    enableSidebarScroll();

    const observer = new MutationObserver(() => {
      enableSidebarScroll();
    });

    const sidebar = document.getElementById('nd-sidebar');
    if (sidebar) {
      observer.observe(sidebar, { childList: true, subtree: true });
    }

    return () => observer.disconnect();
  }, [pathname]);

  return null;
}
