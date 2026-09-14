'use client';

import { useEffect, useMemo, useState } from 'react';
import { Download, FileSpreadsheet, LoaderCircle } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

import { api, downloadFile, type Run } from './live-run-list';

type Sample = { id: string; sample_id: string; flowcell_id: string; sample_type: string; operational_classification: string; qc_flag: string; approval: { decision: string } | null };

function save(filename: string, blob: Blob) { const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); }

export function LiveGlcpView() {
  const [format, setFormat] = useState('csv');
  const [runs, setRuns] = useState<Run[]>([]); const [runId, setRunId] = useState(''); const [samples, setSamples] = useState<Sample[]>([]); const [flowcell, setFlowcell] = useState(''); const [selected, setSelected] = useState<string[]>([]); const [busy, setBusy] = useState(false); const [message, setMessage] = useState<string | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<{items:Run[]}>('/api/v1/runs?page_size=200').then((result)=>setRuns(result.items.filter((run)=>run.ingestion_status==='READY'))).catch((reason:Error)=>setError(reason.message)); },[]);
  useEffect(() => { if (!runId) return; api<{items:Sample[]}>(`/api/v1/runs/${runId}/samples?page_size=200`).then((result)=>{setSamples(result.items);setFlowcell('');setSelected([]);}).catch((reason:Error)=>setError(reason.message)); },[runId]);
  const flowcells=[...new Set(samples.map((sample)=>sample.flowcell_id))];
  const available=useMemo(()=>samples.filter((sample)=>sample.flowcell_id===flowcell&&sample.operational_classification==='ACTUAL'&&sample.approval&&['NEGATIVE','POSITIVE'].includes(sample.approval.decision)&&['PASS','WARNING'].includes(sample.qc_flag)),[flowcell,samples]);
  async function generate(){setBusy(true);setError(null);try{const file=await downloadFile(format==='glcp'?'/api/v1/exports/glcp':`/api/v1/exports/results?format=${format}`,'POST',{run_id:runId,flowcell_id:flowcell,sample_result_ids:selected});save(file.filename,file.blob);setMessage(`${selected.length} samples exported.`);}catch(reason){setError(reason instanceof Error?reason.message:'Export failed');}finally{setBusy(false);}}
  return <div className="space-y-6"><div><p className="text-xs font-medium text-primary">RESULT EXPORTS</p><h1 className="text-[28px] font-semibold">Export results</h1><p className="text-sm text-muted-foreground">Select a run and flowcell, then export approved samples in the selected format.</p></div>{message&&<Alert><AlertTitle>Export complete</AlertTitle><AlertDescription>{message}</AlertDescription></Alert>}{error&&<Alert variant="destructive"><AlertTitle>Review required</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}<Card className="shadow-none"><CardHeader><CardTitle className="text-base">1. Select scope</CardTitle></CardHeader><CardContent className="flex gap-3"><select className="h-10 min-w-64 rounded-lg border bg-background px-3 text-sm" value={runId} onChange={(event)=>setRunId(event.target.value)}><option value="">Select run</option>{runs.map((run)=><option key={run.id} value={run.id}>{run.run_name}</option>)}</select><select className="h-10 min-w-56 rounded-lg border bg-background px-3 text-sm" value={flowcell} onChange={(event)=>{setFlowcell(event.target.value);setSelected([]);}} disabled={!runId}><option value="">Select flowcell</option>{flowcells.map((id)=><option key={id}>{id}</option>)}</select></CardContent></Card><Card className="shadow-none"><CardHeader><CardTitle className="text-base">2. Select approved samples</CardTitle></CardHeader><CardContent className="p-0"><Table><TableHeader><TableRow><TableHead className="w-12"></TableHead><TableHead>Sample ID</TableHead><TableHead>QC</TableHead><TableHead>Final decision</TableHead></TableRow></TableHeader><TableBody>{available.map((sample)=><TableRow key={sample.id}><TableCell><Checkbox checked={selected.includes(sample.id)} onCheckedChange={()=>setSelected((current)=>current.includes(sample.id)?current.filter((id)=>id!==sample.id):[...current,sample.id])}/></TableCell><TableCell>{sample.sample_id}</TableCell><TableCell><Badge variant="secondary">{sample.qc_flag}</Badge></TableCell><TableCell>{sample.approval?.decision}</TableCell></TableRow>)}</TableBody></Table>{flowcell&&available.length===0&&<p className="p-8 text-center text-sm text-muted-foreground">No reportable approved samples in this flowcell.</p>}</CardContent></Card><select aria-label="Export format" value={format} onChange={(event)=>setFormat(event.target.value)} className="rounded-lg border p-2"><option value="csv">Common CSV</option><option value="tsv">Common TSV</option><option value="glcp">GLCP TSV</option></select><Button size="lg" disabled={busy||selected.length===0} onClick={()=>void generate()}><Download className="size-4"/>{busy?'Exporting':`${selected.length} samples: export`}</Button></div>;
}

export function MonthlyQcExport({ period, month }: { period: 'all' | 'month'; month: string }) {
  const [busy,setBusy]=useState(false); const [error,setError]=useState<string|null>(null);
  const label=period==='all'?'All time':month;
  async function generate(){setBusy(true);setError(null);try{const query=period==='all'?'':(()=>{const [year,value]=month.split('-').map(Number);return `?year=${year}&month=${value}`;})();const file=await downloadFile(`/api/v1/exports/monthly-qc${query}`);save(file.filename,file.blob);}catch(reason){setError(reason instanceof Error?reason.message:'Download failed');}finally{setBusy(false);}}
  return <Card className="shadow-none"><CardHeader><CardTitle className="flex items-center gap-2 text-base"><FileSpreadsheet className="size-4"/>QC source values</CardTitle></CardHeader><CardContent className="flex flex-wrap items-center justify-between gap-4"><div><p className="text-sm font-medium">Same scope as the current charts: {label}</p><p className="mt-1 text-sm text-muted-foreground">Export one CSV row per actual sample, filtered by run start date. Change the period above.</p></div><Button disabled={busy||(period==='month'&&!month)} onClick={()=>void generate()}>{busy&&<LoaderCircle className="animate-spin"/>}{label} Download CSV</Button>{error&&<p className="w-full text-sm text-red-700">{error}</p>}</CardContent></Card>;
}
