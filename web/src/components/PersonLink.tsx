import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { useAuth } from '../auth';

/**
 * A person's name, as a link to their profile (9.3) — where this viewer can
 * open profiles, and plain text where they cannot.
 *
 * **Never a dead end.** Whether names are links is the server's answer
 * (`people.view` in the session), worked out so every link it allows opens:
 * with profiles closed, only an admin, who sees everyone, still gets them.
 */
export default function PersonLink({
  id,
  children,
  className = '',
}: {
  id: number | null | undefined;
  children: ReactNode;
  className?: string;
}) {
  const { can } = useAuth();
  if (!id || !can('people.view')) return <span className={className}>{children}</span>;
  return (
    <Link to={`/people/${id}`} className={`hover:text-brand hover:underline ${className}`}>
      {children}
    </Link>
  );
}
