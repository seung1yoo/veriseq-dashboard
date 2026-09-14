'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  ArrowUpDown,
  CheckCircle2,
  Database,
  LoaderCircle,
  RefreshCw,
  Search,
} from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

export type Run = {
  id: string;
  run_name: string;
  run_start_date: string | null;
  source_status: 'READY' | 'INVALID' | 'MISSING' | 'DISCOVERED';
  ingestion_status: 'PENDING' | 'RUNNING' | 'READY' | 'FAILED' | 'STALE';
  file_count: number;
  flowcell_count: number | null;
  sample_count: number | null;
  error: { code: string; message: string } | null;
  last_ingested_at: string | null;
};

type Job = {
  id: string;
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
  stage: string;
  error: { code: string; message: string } | null;
};

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? '';
const DEV_USER_EMAIL = process.env.NEXT_PUBLIC_DEV_USER_EMAIL ?? '';

function apiHeaders(): Record<string, string> {
  return DEV_USER_EMAIL ? { 'X-Dev-User-Email': DEV_USER_EMAIL } : {};
}

let csrfToken: string | null | undefined;

export function resetSecurityContext() {
  csrfToken = undefined;
}

async function mutationHeaders(method: string): Promise<Record<string, string>> {
  if (DEV_USER_EMAIL || ['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase()) || method === 'AUTH') return {};
  if (csrfToken === undefined) {
    const response = await fetch(`${API_BASE}/api/v1/session`, { credentials: 'include' });
    if (!response.ok) throw new Error('Could not verify your session.');
    const payload = (await response.json()) as { csrf_token?: string | null };
    csrfToken = payload.csrf_token ?? null;
  }
  return csrfToken ? { 'X-CSRF-Token': csrfToken } : {};
}

export async function downloadFile(path: string, method = 'GET', body?: unknown) {
  const securityHeaders = await mutationHeaders(method);
  const options: RequestInit = {
    method,
    headers: { ...apiHeaders(), ...securityHeaders, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    credentials: 'include',
  };
  if (body !== undefined) options.body = JSON.stringify(body);
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const payload = (await response.json()) as { error?: { message?: string } };
    throw new Error(payload.error?.message ?? 'Could not generate the file.');
  }
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? 'download';
  return { filename, blob: await response.blob() };
}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const securityHeaders = await mutationHeaders(path === '/auth/login' ? 'AUTH' : method);
  const options: RequestInit = {
    method,
    headers: { ...apiHeaders(), ...securityHeaders, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    credentials: 'include',
  };
  if (body !== undefined) options.body = JSON.stringify(body);
  const response = await fetch(`${API_BASE}${path}`, options);
  const responseText = await response.text();
  const payload = (responseText ? JSON.parse(responseText) : {}) as {
    error?: { message?: string };
  };
  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new Event('veriseq-auth-required'));
    }
    throw new Error(payload?.error?.message ?? 'Could not process the request.');
  }
  return payload as T;
}

const sourceLabels: Record<Run['source_status'], string> = {
  READY: 'Ready to import',
  INVALID: 'Preparing',
  MISSING: 'Directory missing',
  DISCOVERED: 'Checking',
};

const ingestionLabels: Record<Run['ingestion_status'], string> = {
  PENDING: 'Pending',
  RUNNING: 'Importing',
  READY: 'Imported',
  FAILED: 'Import failed',
  STALE: 'New revision detected',
};

function RunBadge({ run }: { run: Run }) {
  const label = run.ingestion_status === 'PENDING'
    ? sourceLabels[run.source_status]
    : ingestionLabels[run.ingestion_status];
  const style =
    run.source_status === 'INVALID' || run.ingestion_status === 'FAILED'
      ? 'bg-red-100 text-red-800'
      : run.ingestion_status === 'READY'
        ? 'bg-emerald-100 text-emerald-800'
        : 'bg-cyan-100 text-cyan-800';
  return <Badge className={style}>{label}</Badge>;
}

export function LiveRunListView({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [query, setQuery] = useState('');
  const [descending, setDescending] = useState(true);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [activeRun, setActiveRun] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    const result = await api<{ items: Run[] }>('/api/v1/runs?page_size=200');
    setRuns(result.items);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api<{ items: Run[] }>('/api/v1/runs?page_size=200')
      .then((result) => {
        if (!cancelled) setRuns(result.items);
      })
      .catch((reason: Error) => {
        if (!cancelled) setError(reason.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const visibleRuns = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return runs
      .filter((run) => !normalized || run.run_name.toLowerCase().includes(normalized))
      .sort((left, right) =>
        (left.run_name.localeCompare(right.run_name) * (descending ? -1 : 1)),
      );
  }, [descending, query, runs]);

  async function scan() {
    setScanning(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api<{ discovered: number; changed: number; invalid: number }>(
        '/api/v1/source/scan',
        'POST',
      );
      await loadRuns();
      setMessage(
        `Scan complete: new ${result.discovered} records; changed ${result.changed} records; preparing ${result.invalid} records`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Run scan failed.');
    } finally {
      setScanning(false);
    }
  }

  async function importRun(run: Run) {
    setActiveRun(run.id);
    setError(null);
    setMessage(null);
    try {
      await api(`/api/v1/runs/${run.id}/import-preflight`, 'POST');
      const job = await api<Job>(`/api/v1/runs/${run.id}/imports`, 'POST');
      let current = job;
      while (current.status === 'QUEUED' || current.status === 'RUNNING') {
        await new Promise((resolve) => window.setTimeout(resolve, 800));
        current = await api<Job>(`/api/v1/jobs/${job.id}`);
      }
      if (current.status === 'FAILED') {
        throw new Error(current.error?.message ?? 'Run import failed.');
      }
      await loadRuns();
      setMessage('Run import complete.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Run import failed.');
    } finally {
      setActiveRun(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="mb-1 text-xs font-medium text-primary">RUN MANAGEMENT · LIVE</p>
          <h1 className="text-[28px] font-semibold tracking-tight">Run</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Check source readiness and import validated reports into the database.
          </p>
        </div>
        <Button onClick={scan} disabled={scanning || activeRun !== null} className="gap-2">
          {scanning ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
          Scan source
        </Button>
      </div>

      {message && (
        <Alert className="border-emerald-200 bg-emerald-50/70">
          <CheckCircle2 className="text-emerald-700" />
          <AlertTitle>Task complete</AlertTitle>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      )}
      {error && (
        <Alert className="border-red-200 bg-red-50/70">
          <AlertCircle className="text-red-700" />
          <AlertTitle>Review required</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card className="shadow-none">
        <CardContent className="p-4">
          <div className="relative max-w-xl">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="pl-9"
              placeholder="Search run name"
              aria-label="Search run name"
            />
          </div>
        </CardContent>
      </Card>

      <Card className="shadow-none">
        <CardHeader className="flex-row items-center justify-between border-b">
          <CardTitle className="text-base">Runs</CardTitle>
          <span className="text-xs text-muted-foreground">Total {visibleRuns.length} records</span>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
              <LoaderCircle className="size-4 animate-spin" /> Loading runs.
            </div>
          ) : visibleRuns.length === 0 ? (
            <div className="flex h-48 flex-col items-center justify-center text-center">
              <Database className="mb-3 size-8 text-muted-foreground" />
              <p className="text-sm font-medium">No runs to display.</p>
              <p className="mt-1 text-xs text-muted-foreground">Scan the source directory to discover runs.</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/35">
                  <TableHead>
                    <button className="flex items-center gap-1" onClick={() => setDescending((value) => !value)}>
                      Run <ArrowUpDown className="size-3" />
                    </button>
                  </TableHead>
                  <TableHead>Run start date</TableHead>
                  <TableHead>Flowcell</TableHead>
                  <TableHead>Sample</TableHead>
                  <TableHead>Files</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Task</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleRuns.map((run) => {
                  const importing = activeRun === run.id;
                  const canImport = run.source_status === 'READY' && run.ingestion_status !== 'READY';
                  return (
                    <TableRow key={run.id} className="cursor-pointer" onClick={() => onOpenRun(run.id)}>
                      <TableCell className="font-medium text-primary">{run.run_name}</TableCell>
                      <TableCell>{run.run_start_date ?? '—'}</TableCell>
                      <TableCell>{run.flowcell_count ?? '—'}</TableCell>
                      <TableCell>{run.sample_count ?? '—'}</TableCell>
                      <TableCell>{run.file_count}</TableCell>
                      <TableCell><RunBadge run={run} /></TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="sm"
                          variant={canImport ? 'default' : 'outline'}
                          disabled={!canImport || activeRun !== null}
                          onClick={(event) => {
                            event.stopPropagation();
                            void importRun(run);
                          }}
                        >
                          {importing && <LoaderCircle className="size-4 animate-spin" />}
                          {run.ingestion_status === 'READY' ? 'Complete' : 'Import'}
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
