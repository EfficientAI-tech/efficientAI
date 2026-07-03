/**
 * CloudFront Function (viewer request) for Next.js static export on S3.
 *
 * Maps pretty URLs to index.html objects, e.g.:
 *   /docs/getting-started/integrations/ -> /docs/getting-started/integrations/index.html
 *   /docs/getting-started/integrations  -> /docs/getting-started/integrations/index.html
 *
 * Deploy: CloudFront -> Functions -> Create -> Publish -> attach to distribution
 *         Behaviors -> Default (*) -> Function associations -> Viewer request
 *
 * Also remove any Custom Error Response that maps 404/403 -> /index.html with 200.
 */
function handler(event) {
  var request = event.request;
  var uri = request.uri;

  if (uri.includes('.')) {
    return request;
  }

  if (uri.endsWith('/')) {
    request.uri += 'index.html';
  } else {
    request.uri += '/index.html';
  }

  return request;
}
