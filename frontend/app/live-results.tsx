'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, LoaderCircle, Search } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { api, type Run } from './live-run-list';

type Sample = {
  id: string;
  run_name: string;
  flowcell_id: string;
  sample_id: string;
  batch_name: string;
  sample_type: string;
  screen_type: string;
  sex_chrom: string;
  operational_classification: string;
  qc_flag: string;
  qc_reason: string;
  ff_raw: string;
  anomaly_description: string;
  class_sx: string;
  class_auto: string;
  approval_blocked: boolean;
  approval: { decision: string; approved_by: string; approved_at: string } | null;
};

type Metric = {
  metric_name: string;
  raw_value: string;
  numeric_value: number | null;
  text_value: string | null;
};

type SampleDetail = Sample & {
  qc_reason: string;
  ff_raw: string;
  ff_numeric: number | null;
  official_qc_outcome: string;
  metrics: Metric[];
  regions: Array<Metric & { region: string }>;
  sequencing: Record<string, unknown> | null;
  findings: Array<{
    id: string;
    finding_type: string;
    raw_classification: string;
    chromosome: string | null;
    consequence: string | null;
    region: string | null;
    start_zero_based: number | null;
    end_exclusive: number | null;
    candidates: Array<{ item_id: string; item_name: string; match_kind: 'EXACT' | 'REFERENCE'; overlap_bp: number | null; result_overlap_ratio: number | null; item_overlap_ratio: number | null }>;
  }>;
  active_approval: { decision: string; comment: string; selected_item_ids: string[]; secondary_findings: { description: string }[]; approved_by: string; approved_at: string } | null;
};

function QcBadge({ value }: { value: string }) {
  const style = value === 'PASS'
    ? 'bg-emerald-100 text-emerald-800'
    : value === 'FAIL'
      ? 'bg-red-100 text-red-800'
      : 'bg-amber-100 text-amber-800';
  return <Badge className={style}>{value}</Badge>;
}

function formatSampleMetric(name: string, value: string | number | null | undefined): string {
  if (value == null || String(value).trim() === '') return '—';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  if (['ff', 'fetal_fraction', 'frag_size_dist', 'NCV_X', 'NCV_Y'].includes(name)) {
    return numeric.toLocaleString('en-US', {
      useGrouping: false, minimumFractionDigits: 3, maximumFractionDigits: 3,
    });
  }
  if (['non_excluded_sites', 'number_of_cnv_events', 'number_of_cnv_event'].includes(name)) {
    return numeric.toLocaleString('en-US', { maximumFractionDigits: 20 });
  }
  return String(value);
}

function SampleTable({ samples, onOpen }: { samples: Sample[]; onOpen: (id: string) => void }) {
  return (
    <div className="overflow-x-auto">
    <Table className="min-w-[1300px]">
      <TableHeader><TableRow className="bg-muted/35"><TableHead>Sample ID</TableHead><TableHead>Run</TableHead><TableHead>sample_type</TableHead><TableHead>class_sx</TableHead><TableHead>class_auto</TableHead><TableHead>anomaly_description</TableHead><TableHead>qc_flag</TableHead><TableHead>qc_reason</TableHead><TableHead>ff</TableHead><TableHead className="sticky right-0 bg-muted">Approval</TableHead></TableRow></TableHeader>
      <TableBody>
        {samples.map((sample) => (
          <TableRow key={sample.id} className="cursor-pointer" onClick={() => onOpen(sample.id)}>
            <TableCell className="font-medium text-primary">{sample.sample_id}</TableCell>
            <TableCell>{sample.run_name}</TableCell>
            <TableCell>{sample.sample_type}</TableCell>
            <TableCell className="max-w-[240px] truncate" title={sample.class_sx}>{sample.class_sx || '—'}</TableCell>
            <TableCell className="max-w-[240px] truncate" title={sample.class_auto}>{sample.class_auto || '—'}</TableCell>
            <TableCell className="max-w-[320px] truncate" title={sample.anomaly_description}>{sample.anomaly_description || '—'}</TableCell>
            <TableCell><QcBadge value={sample.qc_flag} /></TableCell><TableCell className="max-w-[260px] truncate" title={sample.qc_reason}>{sample.qc_reason || 'NONE'}</TableCell><TableCell>{sample.ff_raw || '—'}</TableCell>
            <TableCell className="sticky right-0 bg-card"><span className="whitespace-nowrap text-sm">{sample.operational_classification !== 'ACTUAL' ? 'Not eligible' : sample.approval_blocked ? 'Approval blocked' : sample.approval ? (sample.approval.approved_by === 'system:auto-negative:v1' ? 'Automatic negative approval' : 'Approved') : 'Unapproved'}</span></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
    </div>
  );
}

export function LiveRunDetailView({ runId, onBack, onOpenSample }: { runId: string | null; onBack: () => void; onOpenSample: (id: string) => void }) {
  const [run, setRun] = useState<(Run & { qc_counts: Record<string, number>; sample_type_counts: Record<string, number> }) | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!runId) return;
    Promise.all([
      api<Run & { qc_counts: Record<string, number>; sample_type_counts: Record<string, number> }>(`/api/v1/runs/${runId}`),
      api<{ items: Sample[] }>(`/api/v1/runs/${runId}/samples?page_size=200`),
    ]).then(([runResult, sampleResult]) => { setRun(runResult); setSamples(sampleResult.items); }).catch((reason: Error) => setError(reason.message));
  }, [runId]);
  if (error) return <Alert variant="destructive"><AlertTitle>Could not load run.</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>;
  if (!run) return <div className="flex h-64 items-center justify-center"><LoaderCircle className="size-5 animate-spin" /></div>;
  return <div className="space-y-6">
    <Button variant="ghost" onClick={onBack}><ArrowLeft className="size-4" />Runs</Button>
    <div><p className="text-xs font-medium text-primary">RUN DETAIL · LIVE</p><h1 className="text-[28px] font-semibold">{run.run_name}</h1><p className="text-sm text-muted-foreground">Run start date {run.run_start_date ?? '—'} · Flowcell {run.flowcell_count ?? '—'} items</p></div>
    <div className="grid gap-4 md:grid-cols-4">
      <Summary label="All samples" value={String(run.sample_count ?? 0)} />
      <Summary label="Actual" value={String(run.sample_type_counts.ACTUAL ?? 0)} />
      <Summary label="PASS" value={String(run.qc_counts.PASS ?? 0)} />
      <Summary label="FAIL" value={String(run.qc_counts.FAIL ?? 0)} />
    </div>
    <Card className="shadow-none"><CardHeader><CardTitle className="text-base">Sample results</CardTitle></CardHeader><CardContent className="p-0"><SampleTable samples={samples} onOpen={onOpenSample} /></CardContent></Card>
  </div>;
}

export function LiveSampleSearchView({ onOpenSample }: { onOpenSample: (id: string) => void }) {
  const [samples, setSamples] = useState<Sample[]>([]);
  const [query, setQuery] = useState('');
  const [qc, setQc] = useState('');
  const [sampleType, setSampleType] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    async function loadAllSamples() {
      const first = await api<{ items: Sample[]; total: number }>('/api/v1/samples?page_size=200&page=1');
      const pageCount = Math.ceil(first.total / 200);
      if (pageCount <= 1) return first.items;
      const remaining = await Promise.all(Array.from({ length: pageCount - 1 }, (_, index) => api<{ items: Sample[] }>(`/api/v1/samples?page_size=200&page=${index + 2}`)));
      return [...first.items, ...remaining.flatMap((result) => result.items)];
    }
    loadAllSamples().then(setSamples).catch((reason: Error) => setError(reason.message)).finally(() => setLoading(false));
  }, []);
  const visible = useMemo(() => samples.filter((sample) => {
    const text = `${sample.sample_id} ${sample.run_name} ${sample.anomaly_description}`.toLowerCase();
    return (!query || text.includes(query.toLowerCase())) && (!qc || sample.qc_flag === qc) && (!sampleType || sample.sample_type === sampleType);
  }), [qc, query, sampleType, samples]);
  const sampleTypes = useMemo(() => [...new Set(samples.map((sample) => sample.sample_type).filter(Boolean))].sort(), [samples]);
  return <div className="space-y-6">
    <div><p className="text-xs font-medium text-primary">SAMPLE · LIVE</p><h1 className="text-[28px] font-semibold">Sample</h1><p className="text-sm text-muted-foreground">Search active NIPT results and open a sample for review and approval.</p></div>
    <Card className="shadow-none"><CardContent className="flex flex-wrap gap-2 p-4"><div className="relative min-w-72 flex-1"><Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"/><Input value={query} onChange={(event) => setQuery(event.target.value)} className="pl-9" placeholder="Search sample ID, run, or finding" /></div><select className="h-10 rounded-lg border bg-background px-3 text-sm" value={sampleType} onChange={(event) => setSampleType(event.target.value)}><option value="">All sample types</option>{sampleTypes.map((value) => <option key={value}>{value}</option>)}</select><select className="h-10 rounded-lg border bg-background px-3 text-sm" value={qc} onChange={(event) => setQc(event.target.value)}><option value="">All QC statuses</option><option>PASS</option><option>WARNING</option><option>FAIL</option><option>NTC_PASS</option><option>CANCELLED</option><option>INVALIDATED</option></select></CardContent></Card>
    {error ? <Alert variant="destructive"><AlertTitle>Query failed</AlertTitle><AlertDescription>{error}</AlertDescription></Alert> : <Card className="shadow-none"><CardHeader><CardTitle className="text-base">Search results {visible.length} records</CardTitle></CardHeader><CardContent className="p-0">{loading ? <div className="p-10 text-center"><LoaderCircle className="mx-auto animate-spin" /></div> : <SampleTable samples={visible} onOpen={onOpenSample} />}</CardContent></Card>}
  </div>;
}

const decisionLabels: Record<string, string> = { NEGATIVE: 'Negative', POSITIVE: 'Positive', FAIL: 'FAIL', RETEST: 'Retest required' };

export function LiveSampleDetailView(props: { sampleId: string | null; onBack: () => void }) {
  return <SampleDetailContent key={props.sampleId} {...props} />;
}

function SampleDetailContent({ sampleId, onBack }: { sampleId: string | null; onBack: () => void }) {
  const [sample, setSample] = useState<SampleDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decision, setDecision] = useState('');
  const [comment, setComment] = useState('');
  const [selectedItems, setSelectedItems] = useState<string[]>([]);
  const [secondaryFinding, setSecondaryFinding] = useState('');
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<string>('result');
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const saveLock = useRef(false);
  useEffect(() => {
    let cancelled = false;
    if (sampleId) api<SampleDetail>(`/api/v1/samples/${sampleId}`).then((value) => {
      if (!cancelled) setSample(value);
    }).catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [sampleId]);
  if (error) return <Alert variant="destructive"><AlertTitle>Could not load sample.</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>;
  if (!sample) return <div className="flex h-64 items-center justify-center"><LoaderCircle className="animate-spin" /></div>;
  const sampleMetrics = Object.fromEntries(sample.metrics.map((metric) => [metric.metric_name, metric.raw_value]));
  const classifiedRegions = sample.regions.filter((metric) => metric.metric_name === 'region_classification');
  const approval = sample.active_approval;
  const actual = sample.operational_classification === 'ACTUAL';
  const readOnly = !!approval && !editing;
  const canEdit = actual && !sample.approval_blocked && !readOnly && !saving;
  const displayedIds = readOnly ? approval.selected_item_ids : selectedItems;
  const displayedDecision = readOnly ? approval.decision : decision;
  const displayedSecondary = readOnly ? approval.secondary_findings.map((f) => f.description).join('\n') : secondaryFinding;
  const candidateNames = new Map(sample.findings.flatMap((f) => f.candidates.map((c) => [c.item_id, c.item_name] as const)));
  const selectedNames = displayedIds.map((id) => candidateNames.get(id) ?? id);
  const allowed = (value: string) => value === 'RETEST' || (value === 'FAIL' ? sample.qc_flag.trim().toUpperCase() === 'FAIL' : ['PASS', 'WARNING'].includes(sample.qc_flag.trim().toUpperCase()));
  const ready = canEdit && !!decision && allowed(decision) && !!comment.trim() && comment.length <= 2000 && (decision !== 'POSITIVE' || selectedItems.length > 0 || !!secondaryFinding.trim());
  function startEditing() {
    if (!approval) return;
    setDecision(approval.decision); setComment(approval.comment);
    setSelectedItems(approval.selected_item_ids);
    setSecondaryFinding(approval.secondary_findings.map((f) => f.description).join('\n'));
    setEditing(true); setSaveError(null);
  }
  async function approve() {
    if (!sample || !ready || saveLock.current) return;
    saveLock.current = true; setSaving(true); setSaveError(null);
    let saved = false;
    try {
      await api(`/api/v1/samples/${sample.id}/approvals`, 'POST', { decision, comment, selected_item_ids: decision === 'POSITIVE' ? selectedItems : [], secondary_findings: decision === 'POSITIVE' && secondaryFinding.trim() ? (approval && secondaryFinding === approval.secondary_findings.map((f) => f.description).join('\n') ? approval.secondary_findings : [{ description: secondaryFinding.trim() }]) : [] });
      saved = true;
      setSample(await api<SampleDetail>(`/api/v1/samples/${sample.id}`));
      setEditing(false); setConfirming(false);
    } catch (reason) {
      setConfirming(false);
      if (saved) {
        setError('Approval was saved, but results could not be refreshed. Reload to verify.');
      } else setSaveError(reason instanceof Error ? reason.message : 'Approval failed.');
    } finally { saveLock.current = false; setSaving(false); }
  }
  return <div className="space-y-6">
    <Button variant="ghost" onClick={onBack}><ArrowLeft className="size-4" />Back</Button>
    <div className="flex items-end justify-between"><div><p className="text-xs font-medium text-primary">SAMPLE DETAIL · LIVE</p><h1 className="text-[28px] font-semibold">{sample.sample_id}</h1><p className="text-sm text-muted-foreground">{sample.run_name} · {sample.flowcell_id}</p></div><QcBadge value={sample.qc_flag} /></div>
    <div className="flex flex-wrap items-center gap-3 text-sm" aria-live="polite">
      <Badge variant="secondary">{!actual ? 'Not eligible' : sample.approval_blocked ? 'Approval blocked' : approval ? (approval.approved_by === 'system:auto-negative:v1' ? 'Automatic negative approval' : 'Approved') : 'Unapproved'}</Badge>
      {approval && <span>{decisionLabels[approval.decision] ?? approval.decision} · {approval.approved_by === 'system:auto-negative:v1' ? 'System automatic approval' : approval.approved_by} · {new Date(approval.approved_at).toLocaleString('ko-KR')}</span>}
    </div>
    <div className="grid gap-4 md:grid-cols-4"><Summary label="Sample type" value={sample.sample_type}/><Summary label="Fetal fraction" value={formatSampleMetric('fetal_fraction', sampleMetrics.fetal_fraction ?? sample.ff_raw)}/><Summary label="Fragment size" value={formatSampleMetric('frag_size_dist', sampleMetrics.frag_size_dist)}/><Summary label="Non-excluded sites" value={formatSampleMetric('non_excluded_sites', sampleMetrics.non_excluded_sites)}/></div>
    <Tabs value={tab} onValueChange={(value) => setTab(String(value))}><TabsList className="max-w-full overflow-x-auto"><TabsTrigger value="result">Result evidence</TabsTrigger><TabsTrigger value="matching">Syndrome matching</TabsTrigger><TabsTrigger value="regions">All regions</TabsTrigger><TabsTrigger value="raw">Source metrics</TabsTrigger><TabsTrigger value="review">Review and approve</TabsTrigger></TabsList>
      <TabsContent value="result" className="space-y-4 pt-4"><Card><CardHeader><CardTitle className="text-base">Official result</CardTitle></CardHeader><CardContent className="grid gap-4 md:grid-cols-2"><Key label="Autosomal" value={sample.class_auto}/><Key label="Sex chromosomes" value={sample.class_sx}/><Key label="Finding" value={sample.anomaly_description || 'None'}/><Key label="QC reason" value={sample.qc_reason || 'NONE'}/></CardContent></Card><Card><CardHeader><CardTitle className="text-base">Detected regions</CardTitle></CardHeader><CardContent>{classifiedRegions.length ? classifiedRegions.map((region) => <div key={region.region} className="flex border-b py-2 text-sm"><span className="w-32 font-medium">{region.region}</span><span>{region.raw_value}</span></div>) : <p className="text-sm text-muted-foreground">No region results.</p>}</CardContent></Card></TabsContent>
      <TabsContent value="matching" className="space-y-4 pt-4"><Card><CardHeader><CardTitle className="text-base">Compare VeriSeq findings with syndromes</CardTitle></CardHeader><CardContent className="space-y-4">{sample.findings.length === 0 ? <p className="text-sm text-muted-foreground">No findings require matching.</p> : sample.findings.map((finding) => <div key={finding.id} className="rounded-lg border p-4"><div className="font-medium">{finding.raw_classification}</div><div className="mt-1 text-xs text-muted-foreground">{finding.chromosome} · {finding.consequence} · {finding.region ?? 'whole chromosome'}</div><div className="mt-3 space-y-2">{finding.candidates.map((candidate) => <label key={candidate.item_id} className={`flex items-center gap-3 rounded-md border p-3 ${candidate.match_kind === 'REFERENCE' ? 'opacity-60' : ''}`}><Checkbox disabled={!canEdit || candidate.match_kind !== 'EXACT'} checked={displayedIds.includes(candidate.item_id)} onCheckedChange={() => setSelectedItems((current) => current.includes(candidate.item_id) ? current.filter((id) => id !== candidate.item_id) : [...current, candidate.item_id])}/><span className="flex-1 text-sm">{candidate.item_name}</span><Badge variant="secondary">{candidate.match_kind === 'EXACT' ? 'Eligible candidates' : 'Reference candidates'}</Badge>{candidate.overlap_bp != null && <span className="text-xs text-muted-foreground">Result {(100*(candidate.result_overlap_ratio ?? 0)).toFixed(1)}% of result; syndrome {(100*(candidate.item_overlap_ratio ?? 0)).toFixed(1)}%</span>}</label>)}</div></div>)}</CardContent></Card></TabsContent>
      <TabsContent value="regions" className="pt-4"><Card><CardContent className="max-h-[520px] overflow-auto p-0"><Table><TableHeader><TableRow><TableHead>Region</TableHead><TableHead>Metric</TableHead><TableHead>Source value</TableHead></TableRow></TableHeader><TableBody>{sample.regions.map((metric, index) => <TableRow key={`${metric.region}-${metric.metric_name}-${index}`}><TableCell>{metric.region}</TableCell><TableCell>{metric.metric_name}</TableCell><TableCell>{metric.raw_value}</TableCell></TableRow>)}</TableBody></Table></CardContent></Card></TabsContent>
      <TabsContent value="raw" className="pt-4"><Card><CardContent className="p-0"><Table><TableHeader><TableRow><TableHead>Metric</TableHead><TableHead>Source value</TableHead><TableHead>Numeric value</TableHead></TableRow></TableHeader><TableBody>{sample.metrics.map((metric) => <TableRow key={metric.metric_name}><TableCell>{metric.metric_name}</TableCell><TableCell>{metric.raw_value || '(empty)'}</TableCell><TableCell>{formatSampleMetric(metric.metric_name, metric.numeric_value)}</TableCell></TableRow>)}</TableBody></Table></CardContent></Card></TabsContent>
      <TabsContent value="review" className="pt-4">
        <div className="divide-y rounded-lg border bg-card px-6">
          <section className="space-y-4 py-6" aria-labelledby="review-qc">
            <h2 id="review-qc" className="text-lg font-semibold">Sample and QC</h2>
            <div className="grid gap-4 sm:grid-cols-3"><Key label="Sample ID" value={sample.sample_id}/><Key label="Sample type" value={sample.sample_type}/><Key label="Source QC" value={sample.qc_flag}/></div>
            <Key label="QC reason" value={sample.qc_reason || 'NONE'}/>
            {sample.approval_blocked && <Alert variant="destructive"><AlertTitle>Approval blocked</AlertTitle><AlertDescription>Resolve data warnings before approval. Review result evidence and source QC.</AlertDescription></Alert>}
            {!actual && <p className="text-sm text-muted-foreground">Not eligible: only actual samples can be approved.</p>}
          </section>
          <section className="space-y-4 py-6" aria-labelledby="review-findings">
            <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="review-findings" className="text-lg font-semibold">Detected findings and selected syndromes</h2><Button variant="outline" onClick={() => setTab('matching')}>Select syndromes</Button></div>
            <Key label="Source finding" value={sample.anomaly_description || 'None'}/>
            {sample.findings.map((finding) => <div key={finding.id} className="space-y-2 border-l-2 border-primary/30 pl-4">
              <p className="text-sm font-medium">{finding.raw_classification}</p>
              {finding.candidates.filter((c) => displayedIds.includes(c.item_id)).map((c) => <p key={c.item_id} className="text-sm">{c.item_name}{c.overlap_bp != null && <span className="ml-2 text-muted-foreground">Detected interval {(100 * (c.result_overlap_ratio ?? 0)).toFixed(1)}% of result; syndrome interval {(100 * (c.item_overlap_ratio ?? 0)).toFixed(1)}%</span>}</p>)}
              {!finding.candidates.some((c) => displayedIds.includes(c.item_id)) && <p className="text-sm text-muted-foreground">No syndrome selected</p>}
            </div>)}
            {displayedIds.filter((id) => !candidateNames.has(id)).map((id) => <p key={id} className="text-sm">Previously approved syndromes: {id}</p>)}
            {displayedDecision !== 'POSITIVE' && displayedIds.length > 0 && <p className="text-sm text-muted-foreground">Syndrome selections apply only to positive approvals.</p>}
          </section>
          {actual && <>
            <section className="space-y-4 py-6" aria-labelledby="review-decision">
              <h2 id="review-decision" className="text-lg font-semibold">Operator decision</h2>
              {readOnly ? <p className="font-medium">{decisionLabels[approval.decision] ?? approval.decision}</p> : <fieldset disabled={!canEdit} className="grid gap-3 sm:grid-cols-4"><legend className="sr-only">Select a decision</legend>{Object.entries(decisionLabels).map(([value, label]) => <label key={value} className={`flex items-center gap-3 rounded-lg border p-4 text-sm ${decision === value ? 'border-primary bg-primary/5' : ''} ${!allowed(value) ? 'opacity-50' : ''}`}><input type="radio" name="decision" value={value} checked={decision === value} disabled={!allowed(value)} onChange={() => setDecision(value)}/>{label}</label>)}</fieldset>}
              {!readOnly && <p className="text-sm text-muted-foreground">Negative or positive requires QC PASS or WARNING. Failed requires QC FAIL.</p>}
              {displayedDecision === 'POSITIVE' && <div className="space-y-2"><label htmlFor="secondary-finding" className="text-sm font-medium">Secondary finding</label>{readOnly ? <p className="whitespace-pre-wrap text-sm">{displayedSecondary || 'None'}</p> : <Textarea id="secondary-finding" disabled={!canEdit} value={secondaryFinding} onChange={(event) => setSecondaryFinding(event.target.value)} placeholder="Enter a finding if no suitable syndrome is available."/>}<p className="text-sm text-muted-foreground">Positive approval requires a syndrome or secondary finding.</p></div>}
            </section>
            <section className="space-y-4 py-6" aria-labelledby="review-approval">
              <h2 id="review-approval" className="text-lg font-semibold">Review comments and approval</h2>
              {readOnly ? <><p className="whitespace-pre-wrap text-sm">{approval.comment}</p><p className="text-sm text-muted-foreground">{approval.approved_by === 'system:auto-negative:v1' ? 'System automatic approval' : approval.approved_by} · {new Date(approval.approved_at).toLocaleString('ko-KR')}</p><Button variant="outline" disabled={sample.approval_blocked} onClick={startEditing}>Revise decision</Button></> : <><label htmlFor="review-comment" className="text-sm font-medium">Review comment (required)</label><Textarea id="review-comment" maxLength={2000} disabled={!canEdit} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Enter your review evidence and decision rationale."/>{saveError && <Alert variant="destructive"><AlertTitle>Could not save approval.</AlertTitle><AlertDescription>{saveError}</AlertDescription></Alert>}<div className="flex gap-3"><Button disabled={!ready} onClick={() => setConfirming(true)}>{saving ? 'Saving' : approval ? 'Approve revised decision' : 'Approve decision'}</Button>{editing && <Button variant="outline" disabled={saving} onClick={() => { setEditing(false); setSaveError(null); }}>Cancel revision</Button>}</div></>}
            </section>
          </>}
        </div>
      </TabsContent>
    </Tabs>
    <Dialog open={confirming} onOpenChange={(open) => { if (!saving) setConfirming(open); }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg" showCloseButton={!saving}>
        <DialogHeader><DialogTitle>Confirm approval</DialogTitle><DialogDescription>Verify the sample and decision before approving.</DialogDescription></DialogHeader>
        <Key label="Sample ID" value={sample.sample_id}/><Key label="Decision" value={decisionLabels[decision] ?? 'Not selected'}/>
        {decision === 'POSITIVE' && <><Key label="Selected syndromes" value={selectedNames.join(', ') || 'None'}/><Key label="Secondary finding" value={secondaryFinding || 'None'}/></>}
        <div className="whitespace-pre-wrap"><Key label="Review comment" value={comment}/></div>
        {approval && <p className="text-sm text-muted-foreground">Previous approvals are preserved; a new approval revision will be saved.</p>}
        <DialogFooter><Button variant="outline" disabled={saving} onClick={() => setConfirming(false)}>Cancel</Button><Button disabled={!ready || saving} onClick={() => void approve()}>{saving ? 'Saving' : 'Confirm approval'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>;
}

function Summary({ label, value }: { label: string; value: string }) { return <Card className="shadow-none"><CardContent className="p-5"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-2 text-2xl font-semibold">{value}</p></CardContent></Card>; }
function Key({ label, value }: { label: string; value: string }) { return <div><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-sm font-medium">{value}</p></div>; }
