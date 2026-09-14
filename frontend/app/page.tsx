'use client';

import { useEffect, useState } from 'react';
import { BarChart3, ChevronLeft, ChevronRight, Dna, FileOutput, LayoutDashboard,
  LogOut, Search, Settings2, TestTubes, UserRound } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { LiveLoginView, PasswordChangeView } from './live-login';
import { LiveGlcpView } from './live-exports';
import { LiveDashboardHome, LiveOperationsView } from './live-operations';
import { LiveQcView } from './live-qc';
import { api, resetSecurityContext, LiveRunListView } from './live-run-list';
import {
  LiveRunDetailView,
  LiveSampleDetailView,
  LiveSampleSearchView,
} from './live-results';

export type View =
  | 'home'
  | 'runs'
  | 'run-detail'
  | 'samples'
  | 'sample-detail'
  | 'qc'
  | 'glcp'
  | 'operations'
  | 'login';

const navigation = [
  { id: 'home' as const, label: 'Overview', icon: LayoutDashboard },
  { id: 'runs' as const, label: 'Run', icon: TestTubes },
  { id: 'samples' as const, label: 'Sample', icon: Search },
  { id: 'qc' as const, label: 'QC analysis', icon: BarChart3 },
  { id: 'glcp' as const, label: 'Export results', icon: FileOutput },
  { id: 'operations' as const, label: 'Administration', icon: Settings2 },
];

function primaryNavigationFor(view: View) {
  if (view === 'run-detail') return 'runs';
  if (view === 'sample-detail') return 'samples';
  return view;
}

function detailLocationFor(view: View) {
  if (view === 'run-detail') return 'Selected run';
  if (view === 'sample-detail') return 'Selected sample';
  return null;
}

export default function Home() {
  const [collapsed, setCollapsed] = useState(false);
  const [view, setView] = useState<View>('home');
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedSampleId, setSelectedSampleId] = useState<string | null>(null);
  const [authState, setAuthState] = useState<'checking' | 'login' | 'change' | 'manual-change' | 'ready'>('checking');
  const [currentUser, setCurrentUser] = useState<{ email: string; display_name: string | null; role: string } | null>(null);
  const activeNavigation = primaryNavigationFor(view);
  const detailLocation = detailLocationFor(view);

  useEffect(() => {
    api<{ user: { email: string; display_name: string | null; role: string }; must_change_password: boolean }>('/api/v1/session')
      .then((session) => { setCurrentUser(session.user); setAuthState(session.must_change_password ? 'change' : 'ready'); })
      .catch(() => setAuthState('login'));
    const requireLogin = () => { resetSecurityContext(); setCurrentUser(null); setAuthState('login'); };
    window.addEventListener('veriseq-auth-required', requireLogin);
    return () => window.removeEventListener('veriseq-auth-required', requireLogin);
  }, []);

  async function refreshSession() {
    resetSecurityContext();
    const session = await api<{ user: { email: string; display_name: string | null; role: string }; must_change_password: boolean }>('/api/v1/session');
    setCurrentUser(session.user); setAuthState(session.must_change_password ? 'change' : 'ready'); setView('home');
  }

  async function logout() {
    try { await api('/api/v1/logout', 'POST'); } finally { resetSecurityContext(); setCurrentUser(null); setAuthState('login'); }
  }

  // Keep the server output empty until the session check finishes. Some browser
  // extensions inject helper nodes into the first rendered element before React
  // hydrates it, which otherwise turns this transient loading view into a hard
  // hydration mismatch.
  if (authState === 'checking') return null;
  if (authState === 'login') return <LiveLoginView onAuthenticated={(mustChange) => { if (mustChange) setAuthState('change'); else void refreshSession(); }} />;
  if (authState === 'change') return <PasswordChangeView onChanged={() => void refreshSession()} />;
  if (authState === 'manual-change') return <PasswordChangeView required={false} onChanged={() => void refreshSession()} />;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <aside
        className={`fixed inset-y-0 left-0 z-30 hidden border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200 lg:flex lg:flex-col ${
          collapsed ? 'w-[76px]' : 'w-[248px]'
        }`}
      >
        <div className="flex h-16 items-center gap-3 border-b border-sidebar-border px-5">
          <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <Dna className="size-5" />
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold tracking-tight text-sidebar-foreground">
                VeriSeq Dashboard
              </p>
              <p className="text-[11px] text-sidebar-foreground/55">
                NIPT results
              </p>
            </div>
          )}
        </div>

        <nav className="flex-1 space-y-1 p-3" aria-label="Navigation">
          {!collapsed && (
            <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-sidebar-foreground/45">
              Navigation
            </p>
          )}
          {navigation.map((item) => {
            const Icon = item.icon;
            const active = activeNavigation === item.id;
            return (
              <div key={item.id} className="relative">
                <button
                  type="button"
                  title={collapsed ? item.label : undefined}
                  aria-current={active ? 'page' : undefined}
                  onClick={() => setView(item.id)}
                  className={`relative flex h-11 w-full items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors ${
                    active
                      ? 'bg-sidebar-primary text-sidebar-primary-foreground shadow-sm ring-1 ring-white/10'
                      : 'text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground'
                  } ${collapsed ? 'justify-center' : ''}`}
                >
                  {active && (
                    <span className="absolute -left-1 top-2.5 h-6 w-1 rounded-r-full bg-cyan-300" />
                  )}
                  <span
                    className={`grid size-7 shrink-0 place-items-center rounded-md ${active ? 'bg-white/12' : ''}`}
                  >
                    <Icon className="size-[18px]" />
                  </span>
                  {!collapsed && (
                    <>
                      <span className="flex-1 text-left">{item.label}</span>
                      {active && !detailLocation && (
                        <span className="rounded-full bg-white/15 px-2 py-0.5 text-[9px] font-semibold">
                          Current
                        </span>
                      )}
                    </>
                  )}
                </button>
                {!collapsed && active && detailLocation && (
                  <div className="ml-7 mt-1 flex items-center gap-2 border-l border-sidebar-foreground/20 py-2 pl-4 text-[11px] text-sidebar-foreground/75">
                    <ChevronRight className="size-3" />
                    <span className="truncate">{detailLocation}</span>
                    <span className="ml-auto mr-2 rounded-full bg-cyan-300/15 px-2 py-0.5 font-semibold text-cyan-200">
                      Current
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        <div className="border-t border-sidebar-border p-3">
          <button
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            className="flex h-9 w-full items-center justify-center rounded-lg text-sidebar-foreground/55 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
            aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
          >
            {collapsed ? (
              <ChevronRight className="size-4" />
            ) : (
              <ChevronLeft className="size-4" />
            )}
            {!collapsed && <span className="ml-2 text-xs">Collapse navigation</span>}
          </button>
        </div>
      </aside>

      <div
        className={`transition-[padding] duration-200 ${collapsed ? 'lg:pl-[76px]' : 'lg:pl-[248px]'}`}
      >
        <header className="sticky top-0 z-20 flex h-16 items-center gap-4 border-b bg-background/95 px-5 backdrop-blur md:px-7">
          <select aria-label="Navigation" className="rounded border p-2 lg:hidden" value={activeNavigation} onChange={(event)=>setView(event.target.value as View)}>
            {navigation.map(item=><option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={() => setAuthState('manual-change')}
              className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-muted"
              title="Change password"
            >
              <span className="grid size-8 place-items-center rounded-full bg-primary/10 text-primary">
                <UserRound className="size-4" />
              </span>
              <span className="hidden text-left md:block">
                <span className="block max-w-40 truncate text-xs font-medium">{currentUser?.display_name || currentUser?.email || 'User'}</span>
                <span className="block text-[10px] text-muted-foreground">
                  {currentUser?.role === 'ADMIN' ? 'Administrator' : 'Operator'}
                </span>
              </span>
            </button>
            <Button variant="ghost" size="icon" aria-label="Sign out" title="Sign out" onClick={() => void logout()}><LogOut className="size-4" /></Button>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1560px] px-5 py-7 md:px-7 md:py-8">
          <CurrentView
            view={view}
            setView={setView}
            selectedRunId={selectedRunId}
            selectedSampleId={selectedSampleId}
            onOpenRun={(id) => { setSelectedRunId(id); setView('run-detail'); }}
            onOpenSample={(id) => { setSelectedSampleId(id); setView('sample-detail'); }}
          />
        </main>
      </div>
    </div>
  );
}

function CurrentView({
  view,
  setView,
  selectedRunId,
  selectedSampleId,
  onOpenRun,
  onOpenSample,
}: {
  view: View;
  setView: (view: View) => void;
  selectedRunId: string | null;
  selectedSampleId: string | null;
  onOpenRun: (id: string) => void;
  onOpenSample: (id: string) => void;
}) {
  switch (view) {
    case 'home':
      return <LiveDashboardHome onNavigate={(next) => setView(next)} />;
    case 'runs':
      return <LiveRunListView onOpenRun={onOpenRun} />;
    case 'run-detail':
      return (
        <LiveRunDetailView
          runId={selectedRunId}
          onBack={() => setView('runs')}
          onOpenSample={onOpenSample}
        />
      );
    case 'samples':
      return <LiveSampleSearchView onOpenSample={onOpenSample} />;
    case 'sample-detail':
      return <LiveSampleDetailView sampleId={selectedSampleId} onBack={() => setView('samples')} />;
    case 'qc':
      return <LiveQcView />;
    case 'glcp':
      return <LiveGlcpView />;
    case 'operations':
      return <LiveOperationsView />;
    default:
      return null;
  }
}
