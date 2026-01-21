import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';

export default function Home() {
  const { siteConfig } = useDocusaurusContext();
  return (
    <Layout
      title={`Hello from ${siteConfig.title}`}
      description="Description will go into a meta tag in <head />">
      <main style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        height: '80vh',
        textAlign: 'center'
      }}>
        <h1>EfficientAI Documentation</h1>
        <p>
          <Link
            className="button button--secondary button--lg"
            to="/docs/intro">
            Go to Documentation
          </Link>
        </p>
      </main>
    </Layout>
  );
}
