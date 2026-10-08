import { Link } from 'react-router-dom';

import PageHeader from '../components/PageHeader';

/**
 * An address that goes nowhere, said so.
 *
 * It used to send you to Home without a word, so a mistyped or out-of-date
 * link looked like the app ignoring you (QA-26).
 */
export default function NotFound() {
  return (
    <>
      <PageHeader
        title="Page not found"
        description="Nothing lives at this address — the link may be old, or mistyped."
      />
      <Link to="/" className="text-brand hover:underline">
        Go to Home
      </Link>
    </>
  );
}
