import { Link } from 'react-router-dom';

import PageHeader from '../components/PageHeader';

/**
 * A page somebody's role does not include, said so (7.1).
 *
 * It used to send them to Home without a word — an agent following a link
 * to Reporting, or a manager to Celebrations, landed somewhere else and was
 * left to guess why, exactly as an unknown address once did (QA-26).
 */
export default function NotAllowed() {
  return (
    <>
      <PageHeader
        title="Not part of your role"
        description="This page is for people who set up and run GoalGetter. If you need it, ask an admin."
      />
      <Link to="/" className="text-brand hover:underline">
        Go to Home
      </Link>
    </>
  );
}
