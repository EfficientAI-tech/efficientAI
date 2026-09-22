#!/usr/bin/env node

function rewriteUri(uri) {
  const pathOnly = uri.split('?')[0];

  if (/\.(html|css|js|json|png|jpe?g|gif|webp|svg|ico|woff2?|ttf|map|txt|xml|pdf|md)$/i.test(pathOnly)) {
    return uri;
  }

  if (pathOnly.endsWith('/')) {
    return uri + 'index.html';
  }

  return uri + '/index.html';
}

const cases = [
  ['/docs/changelog/v1.5.33/', '/docs/changelog/v1.5.33/index.html'],
  ['/docs/changelog/v1.5.4/', '/docs/changelog/v1.5.4/index.html'],
  ['/docs/advanced/iam/', '/docs/advanced/iam/index.html'],
  ['/_next/static/chunks/app.js', '/_next/static/chunks/app.js'],
  ['/efficientai_logo_light.png', '/efficientai_logo_light.png'],
  ['/docs/changelog/v1.5.33/index.html', '/docs/changelog/v1.5.33/index.html'],
];

for (const [input, expected] of cases) {
  const actual = rewriteUri(input);
  if (actual !== expected) {
    console.error(`FAIL ${input}\n  expected: ${expected}\n  actual:   ${actual}`);
    process.exit(1);
  }
}

console.log(`CloudFront URI rewrite: ${cases.length} cases passed.`);
