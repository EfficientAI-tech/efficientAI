/**
 * CloudFront Function (viewer request) for Next.js static export on S3.
 *
 * Maps pretty URLs to index.html objects, e.g.:
 *   /docs/getting-started/integrations/ -> /docs/getting-started/integrations/index.html
 *   /docs/changelog/v1.5.33/           -> /docs/changelog/v1.5.33/index.html
 *   /docs/getting-started/integrations  -> /docs/getting-started/integrations/index.html
 *
 * Deploy: CloudFront -> Functions -> Create -> Publish -> attach to distribution
 *         Behaviors -> Default (*) -> Function associations -> Viewer request
 *
 * Also remove any Custom Error Response that maps 404/403 -> /index.html with 200.
 */
function handler(event) {
  var request = event.request;
  var uri = request.uri.split('?')[0];

  // Only pass through URLs that end with a static asset extension.
  // Do NOT use uri.includes('.') — version slugs like /docs/changelog/v1.5.33/
  // contain dots but still need index.html rewriting.
  if (/\.(html|css|js|json|png|jpe?g|gif|webp|svg|ico|woff2?|ttf|map|txt|xml|pdf|md)$/i.test(uri)) {
    return request;
  }

  if (uri.endsWith('/')) {
    request.uri += 'index.html';
  } else {
    request.uri += '/index.html';
  }

  return request;
}
