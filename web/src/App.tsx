import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { AuthProvider, RequireAuth, RequireCapability } from './auth';
import AppShell from './components/AppShell';
import AcceptInvite from './pages/AcceptInvite';
import Account from './pages/Account';
import AchievementRules from './pages/AchievementRules';
import Achievements from './pages/Achievements';
import ChannelEditor from './pages/ChannelEditor';
import Channels from './pages/Channels';
import CompetitionDetail from './pages/CompetitionDetail';
import Competitions from './pages/Competitions';
import ConnectSource from './pages/ConnectSource';
import Corrections from './pages/Corrections';
import Dashboard from './pages/Dashboard';
import DataSource from './pages/DataSource';
import DisplayFeed from './pages/DisplayFeed';
import PairScreen from './pages/PairScreen';
import GoalDetail from './pages/GoalDetail';
import Goals from './pages/Goals';
import Integrations from './pages/Integrations';
import IntegrationsHelp from './pages/IntegrationsHelp';
import Leaderboards from './pages/Leaderboards';
import LeaderboardView from './pages/LeaderboardView';
import Login from './pages/Login';
import Metrics from './pages/Metrics';
import NotFound from './pages/NotFound';
import Offices from './pages/Offices';
import ResetPassword from './pages/ResetPassword';
import ForgotPassword from './pages/ForgotPassword';
import Appearance from './pages/Appearance';
import Reporting from './pages/Reporting';
import Points from './pages/Points';
import Settings from './pages/Settings';
import Setup from './pages/Setup';
import Teams from './pages/Teams';
import UserDetail from './pages/UserDetail';
import Users from './pages/Users';
import Inbox from './pages/Inbox';
import Assets from './pages/Assets';
import ProfilePage from './pages/Profile';

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* Outside the shell: no nav should appear before sign-in. */}
          <Route path="/login" element={<Login />} />
          <Route path="/setup" element={<Setup />} />
          <Route path="/accept-invite" element={<AcceptInvite />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          {/* A wall screen: no session, no shell, nothing to click. The
              token in the path is the entire credential. */}
          <Route path="/display/:token" element={<DisplayFeed />} />
          {/* Short on purpose: it is the one address somebody keys in with a
              remote control, and every character is four arrow presses. */}
          <Route path="/pair" element={<PairScreen />} />

          {/* Everything below shares the shell. Nesting means the sidebar and
              top bar are mounted once and stay mounted across navigation —
              they don't re-render or refetch when the page changes. */}
          <Route
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route path="/" element={<Dashboard />} />
            {/* Everyone has an account, so no capability guards this. */}
            <Route path="/account" element={<Account />} />
            {/* No capability guard: everybody sees what the organization
                celebrates, and these rows already go on a public wall. */}
            <Route path="/announcements" element={<Achievements />} />
            {/* Recognition became Announcements (Phase 25): old links still work. */}
            <Route path="/recognition" element={<Navigate to="/announcements" replace />} />
            {/* The old addresses, still in bookmarks, emails and notification
                links. One name per thing (review §4): "Achievements" was the
                feed and "Announcements" the rules. */}
            <Route path="/achievements" element={<Navigate to="/announcements" replace />} />
            <Route path="/achievement-rules" element={<Navigate to="/celebrations" replace />} />
            <Route
              path="/leaderboards"
              element={
                <RequireCapability capability="leaderboards.view">
                  <Leaderboards />
                </RequireCapability>
              }
            />
            <Route
              path="/leaderboards/:id"
              element={
                <RequireCapability capability="leaderboards.view">
                  <LeaderboardView />
                </RequireCapability>
              }
            />
            <Route
              path="/goals"
              element={
                <RequireCapability capability="goals.view">
                  <Goals />
                </RequireCapability>
              }
            />
            <Route
              path="/goals/:id"
              element={
                <RequireCapability capability="goals.view">
                  <GoalDetail />
                </RequireCapability>
              }
            />
            <Route
              path="/reporting"
              element={
                <RequireCapability capability="reporting.view">
                  <Reporting />
                </RequireCapability>
              }
            />
            {/* No capability guard, deliberately. The points table is the
                one ranked thing everybody is on — a league narrowed per
                viewer is not a league. Admin-only panels inside it are
                guarded there. */}
            <Route path="/points" element={<Points />} />
            <Route
              // Not `/assets`: that is where the build's own scripts are
              // served from, and nginx answers it as a directory.
              path="/library"
              element={
                <RequireCapability capability="org.settings.edit">
                  <Assets />
                </RequireCapability>
              }
            />
            <Route
              path="/inbox"
              element={
                <RequireCapability capability="org.settings.edit">
                  <Inbox />
                </RequireCapability>
              }
            />
            <Route
              path="/points/setup"
              element={
                <RequireCapability capability="org.settings.edit">
                  <Points setup />
                </RequireCapability>
              }
            />
            <Route path="/teams" element={<Teams />} />
            {/* Guarded to match the nav and the API. The nav hides it; this
                stops a bookmarked URL rendering a page of errors instead. */}
            <Route
              path="/channels"
              element={
                <RequireCapability capability="integrations.manage">
                  <Channels />
                </RequireCapability>
              }
            />
            <Route
              path="/channels/:id"
              element={
                <RequireCapability capability="integrations.manage">
                  <ChannelEditor />
                </RequireCapability>
              }
            />
            <Route
              path="/competitions"
              element={
                <RequireCapability capability="competitions.view">
                  <Competitions />
                </RequireCapability>
              }
            />
            <Route
              path="/competitions/:id"
              element={
                <RequireCapability capability="competitions.view">
                  <CompetitionDetail />
                </RequireCapability>
              }
            />

            <Route
              path="/users"
              element={
                <RequireCapability capability="users.view">
                  <Users />
                </RequireCapability>
              }
            />
            {/* Everyone's: what a profile shows narrows by who is looking,
                on the server (Phase 9). */}
            <Route path="/people/:id" element={<ProfilePage />} />
            <Route
              path="/users/:id"
              element={
                <RequireCapability capability="users.view">
                  <UserDetail />
                </RequireCapability>
              }
            />
            <Route
              path="/corrections"
              element={
                <RequireCapability capability="metrics.correct">
                  <Corrections />
                </RequireCapability>
              }
            />
            <Route
              path="/celebrations"
              element={
                <RequireCapability capability="integrations.manage">
                  <AchievementRules />
                </RequireCapability>
              }
            />
            <Route
              path="/metrics"
              element={
                <RequireCapability capability="metrics.manage">
                  <Metrics />
                </RequireCapability>
              }
            />
            <Route
              path="/offices"
              element={
                <RequireCapability capability="offices.manage">
                  <Offices />
                </RequireCapability>
              }
            />
            <Route
              path="/integrations"
              element={
                <RequireCapability capability="integrations.manage">
                  <Integrations />
                </RequireCapability>
              }
            />
            <Route
              path="/integrations/help"
              element={
                <RequireCapability capability="integrations.manage">
                  <IntegrationsHelp />
                </RequireCapability>
              }
            />
            {/* Two paths into the same flow: a new source, and picking an
                abandoned setup back up where it stopped. */}
            <Route
              path="/integrations/connect"
              element={
                <RequireCapability capability="integrations.manage">
                  <ConnectSource />
                </RequireCapability>
              }
            />
            <Route
              path="/integrations/connect/:id"
              element={
                <RequireCapability capability="integrations.manage">
                  <ConnectSource />
                </RequireCapability>
              }
            />
            <Route
              path="/integrations/sources/:id"
              element={
                <RequireCapability capability="integrations.manage">
                  <DataSource />
                </RequireCapability>
              }
            />
            <Route
              path="/appearance"
              element={
                <RequireCapability capability="org.settings.edit">
                  <Appearance />
                </RequireCapability>
              }
            />
            <Route
              path="/settings"
              element={
                <RequireCapability capability="org.settings.edit">
                  <Settings />
                </RequireCapability>
              }
            />
            {/* Unknown URL: said, inside the shell (QA-26). Inside it, so
                RequireAuth still decides first whether somebody signed out
                belongs on the login page instead. */}
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
