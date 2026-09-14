'use client';

import { useMemo, useState } from 'react';
import { CheckCircle2, Dna, KeyRound } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';

import { API_BASE, api, resetSecurityContext } from './live-run-list';

type LoginResult = { must_change_password: boolean };

export function LiveLoginView({ onAuthenticated }: { onAuthenticated: (mustChange: boolean) => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function login() {
    setLoading(true); setError(null);
    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ email, password }),
      });
      const body = (await response.json()) as LoginResult & { error?: { message?: string } };
      if (!response.ok) throw new Error(body.error?.message ?? 'Check your email or password.');
      resetSecurityContext();
      onAuthenticated(body.must_change_password);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Check your email or password.');
    } finally { setLoading(false); }
  }

  return <AuthFrame title="Sign in" description="Sign in with an account issued by your laboratory administrator.">
    {error && <Alert variant="destructive"><AlertTitle>Sign-in failed</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
    <label htmlFor="login-email" className="space-y-2 text-sm"><span className="font-medium">Email</span><Input id="login-email" type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" /></label>
    <label htmlFor="login-password" className="space-y-2 text-sm"><span className="font-medium">Password</span><Input id="login-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && email && password) void login(); }} /></label>
    <Button className="w-full" size="lg" disabled={loading || !email || !password} onClick={() => void login()}><KeyRound className="size-4" />{loading ? 'Checking' : 'Sign in'}</Button>
    <p className="text-center text-xs text-muted-foreground">Forgot your password? Contact your dashboard administrator.</p>
  </AuthFrame>;
}

export function PasswordChangeView({ onChanged, required = true }: { onChanged: () => void; required?: boolean }) {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const rules = useMemo(() => [
    ['At least 12 characters', newPassword.length >= 12],
    ['Include letters', /[A-Za-z]/.test(newPassword)],
    ['Include numbers', /\d/.test(newPassword)],
    ['Include symbols', /[^A-Za-z0-9]/.test(newPassword)],
    ['Passwords match', Boolean(newPassword) && newPassword === confirmPassword],
  ] as const, [confirmPassword, newPassword]);
  const valid = rules.every(([, matched]) => matched);
  async function change() {
    setLoading(true); setError(null);
    try {
      await api('/auth/password', 'POST', { current_password: currentPassword, new_password: newPassword });
      onChanged();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not change password.'); }
    finally { setLoading(false); }
  }
  return <AuthFrame title="Set a new password" description={required ? 'You signed in with a temporary password. Change it to continue.' : 'Enter your current password and choose a new one.'}>
    {error && <Alert variant="destructive"><AlertTitle>Change failed</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
    <label htmlFor="current-password" className="space-y-2 text-sm"><span className="font-medium">Current password</span><Input id="current-password" type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label>
    <label htmlFor="new-password" className="space-y-2 text-sm"><span className="font-medium">New password</span><Input id="new-password" type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></label>
    <label htmlFor="confirm-password" className="space-y-2 text-sm"><span className="font-medium">Confirm new password</span><Input id="confirm-password" type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} /></label>
    <div className="grid grid-cols-2 gap-2 rounded-lg bg-muted/60 p-3">{rules.map(([label, matched]) => <span key={label} className={`flex items-center gap-1.5 text-xs ${matched ? 'text-emerald-700' : 'text-muted-foreground'}`}><CheckCircle2 className="size-3.5" />{label}</span>)}</div>
    <Button className="w-full" size="lg" disabled={loading || !currentPassword || !valid} onClick={() => void change()}>{loading ? 'Changing' : 'Change password'}</Button>
  </AuthFrame>;
}

function AuthFrame({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return <div className="grid min-h-screen place-items-center bg-background p-6"><Card className="w-full max-w-md"><CardHeader className="text-center"><div className="mx-auto grid size-12 place-items-center rounded-2xl bg-primary text-primary-foreground"><Dna /></div><CardTitle className="mt-3 text-2xl">{title}</CardTitle><p className="text-sm text-muted-foreground">{description}</p></CardHeader><CardContent className="space-y-4">{children}</CardContent></Card></div>;
}
