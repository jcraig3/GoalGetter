import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import { api, ApiError } from './api';
import { isMfaStep, type MfaStep } from './components/TwoStep';
import { applyAppearance, applyTheme, storedTheme } from './appearance';
import { forgetOrgAppearance, loadOrganization } from './orgAppearance';
import ChoosePassword from './pages/ChoosePassword';
import NotAllowed from './pages/NotAllowed';

export interface User {
  id: number;
  email: string;
  full_name: string;
  /** What people call them. Empty for almost everybody. */
  nickname: string;
  /** A month and a day, and deliberately no year. Both or neither. */
  birthday_month: number | null;
  birthday_day: number | null;
  org_role: string;
  organization_id: number;
  team_id: number | null;
  capabilities: string[];
  /** Content hash of their photo, or null for initials. */
  photo_digest: string | null;
  /** Whether "use the default" would change anything. */
  has_custom_photo: boolean;
  /** False for somebody who only signs in with Microsoft. */
  has_password?: boolean;
  /** Signed in with a password an admin set (11.2): nothing else until replaced. */
  must_change_password?: boolean;
}

interface AuthValue {
  user: User | null;
  setupRequired: boolean;
  loading: boolean;
  /** Does the signed-in user have this capability? Presentation only — every
   *  capability is enforced server-side as well. */
  can: (capability: string) => boolean;
  /**
   * Password sign-in. Resolves to the second step when two-step sign-in is
   * owed — the password was right, and there is no session yet.
   */
  login: (email: string, password: string) => Promise<MfaStep | null>;
  /** Finish a sign-in the second step completed. */
  signedIn: (user: User) => void;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [setupRequired, setSetupRequired] = useState(false);
  const [loading, setLoading] = useState(true);

  // Both answers are needed before the first render can decide what to show,
  // so they're fetched together rather than in sequence.
  const refresh = useCallback(async () => {
    const [me, setup] = await Promise.all([
      api<User>('/api/auth/me').catch((err) => {
        // 401 is the normal "not signed in" answer, not a failure.
        if (err instanceof ApiError && err.status === 401) return null;
        throw err;
      }),
      api<{ setup_required: boolean }>('/api/setup/status').catch(() => ({
        setup_required: false,
      })),
    ]);

    setUser(me);
    setSetupRequired(setup.setup_required);
    setLoading(false);

    // **The brand is fetched here rather than by each page that needs it.**
    // Every screen draws something in the organization's colours, so a page
    // that had to ask first would render grey and then repaint — which is the
    // flash of unbranded content this avoids. Silent on failure: a deployment
    // that has never opened the Appearance page has no appearance to apply.
    if (me) {
      // From the shared cache, which the header and every appearance control
      // also read — so a page load asks once, not twice (QA-28). Forgotten
      // first: whoever signed in may belong to another organization.
      forgetOrgAppearance();
      loadOrganization()
        .then((org) => applyAppearance(org.appearance_resolved))
        .catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // **Before anything renders, and separately from the brand.** The person's
  // light/dark choice lives in their own browser, so it needs no request and
  // must not wait for one — waiting would mean a dark-mode user watching the
  // app flash white on every load.
  useEffect(() => {
    applyTheme(storedTheme());
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const answer = await api<User | MfaStep>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    if (isMfaStep(answer)) return answer;
    setUser(answer);
    return null;
  }, []);

  const signedIn = useCallback((me: User) => setUser(me), []);

  const logout = useCallback(async () => {
    await api<void>('/api/auth/logout', { method: 'POST' });
    setUser(null);
  }, []);

  // Resolved on the server and sent with /api/auth/me, so components ask
  // "may I?" instead of re-deriving rules from a role string. Adding a role
  // later changes the server map and every component follows.
  const can = useCallback(
    (capability: string) => user?.capabilities?.includes(capability) ?? false,
    [user],
  );

  const value = useMemo(
    () => ({ user, setupRequired, loading, can, login, signedIn, logout, refresh }),
    [user, setupRequired, loading, can, login, signedIn, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>');
  return context;
}

/**
 * Wraps routes that need a signed-in user.
 *
 * This is a convenience, not a security control — it only decides what to
 * render. Every endpoint enforces authentication server-side, so bypassing
 * this in the browser gains nothing but an empty page.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, setupRequired, loading } = useAuth();
  const location = useLocation();

  if (loading) return <Loading />;
  if (setupRequired) return <Navigate to="/setup" replace />;
  if (!user) {
    // Remember where they were headed so login can send them back there.
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  // In place of every page, which the server would refuse anyway (11.2).
  if (user.must_change_password) return <ChoosePassword />;

  return <>{children}</>;
}

/**
 * Hides a route from roles that may not use it.
 *
 * Like RequireAuth, this is presentation only — the endpoints behind these
 * pages enforce the same rule, so bypassing this in the browser yields a page
 * that 403s on every request.
 *
 * Redirects home rather than showing "access denied": a link they shouldn't
 * have wasn't shown to them, so arriving here means a typed or stale URL, and
 * silently going somewhere useful is kinder than an error.
 */
export function RequireCapability({
  capability,
  children,
}: {
  capability: string;
  children: ReactNode;
}) {
  const { user, loading, can } = useAuth();

  if (loading) return <Loading />;
  if (!user) return <Navigate to="/" replace />;
  // Said, not redirected: landing on Home without a word left people to
  // guess why their link did nothing (7.1).
  if (!can(capability)) return <NotAllowed />;
  return <>{children}</>;
}

/**
 * Renders children only if the user holds the capability.
 *
 * A convenience for hiding buttons. It protects nothing — the endpoint behind
 * every one of these enforces the same rule, so removing this in DevTools
 * yields a control that 403s.
 */
export function Can({
  do: capability,
  children,
}: {
  do: string;
  children: ReactNode;
}) {
  const { can } = useAuth();
  return can(capability) ? <>{children}</> : null;
}

export function Loading() {
  return (
    <div className="grid min-h-screen place-items-center bg-bg">
      <p className="text-content-muted">Loading…</p>
    </div>
  );
}
