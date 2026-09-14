'use client';

// oxlint-disable jsx-a11y/prefer-tag-over-role

import { useEffect, useState } from 'react';
import { LoaderCircle } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

import { api } from './live-run-list';
import { MonthlyQcExport } from './live-exports';

type Point = { sample_result_id: string; value: number };
type Distribution = { n: number; missing_n: number; min: number | null; q1: number | null; median: number | null; q3: number | null; max: number | null; points: Point[] };
type QcData = {
  period: 'all' | 'month';
  population: string;
  denominator: number;
  qc_counts: Record<string, number>;
  positive: { positive: number; trisomy: number; monosomy: number; deletion: number; duplication: number; rate: number | null };
  sample_distributions: Record<string, Distribution>;
  ncv_scatter: Array<{ sample_result_id: string; x: number; y: number; class_sx: string }>;
};

const labels: Record<string, string> = { fetal_fraction: 'Fetal fraction', frag_size_dist: 'Fragment size distribution', non_excluded_sites: 'Non-excluded sites' };

export function LiveQcView() {
  const now = new Date();
  const [period, setPeriod] = useState<'all' | 'month'>('all');
  const [month, setMonth] = useState(`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`);
  const [data, setData] = useState<QcData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const [year, monthNumber] = month.split('-');
    const query = period === 'all' ? 'period=all' : `period=month&year=${year}&month=${monthNumber}`;
    api<QcData>(`/api/v1/qc/overview?${query}`).then(result => { if (!cancelled) setData(result); }).catch((reason: Error) => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [month, period]);
  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-medium text-primary">QUALITY CONTROL · LIVE</p><h1 className="text-[28px] font-semibold">QC analysis</h1><p className="text-sm text-muted-foreground">Explore QC distributions and positive findings for actual samples.</p></div><div className="flex items-center gap-2 rounded-xl border bg-card p-2"><span className="px-1 text-xs font-medium text-muted-foreground">Analysis and export period</span><select className="h-9 rounded-lg border bg-background px-3 text-sm" value={period} onChange={(event) => {setData(null);setError(null);setPeriod(event.target.value as typeof period);}}><option value="all">All time</option><option value="month">Select month</option></select>{period==='month'&&<input type="month" className="h-9 rounded-lg border bg-background px-3 text-sm" value={month} onChange={(event)=>{setData(null);setError(null);setMonth(event.target.value);}}/>}</div></div>
    {error && <Alert variant="destructive"><AlertTitle>Could not load QC</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>}
    {!data ? <div className="flex h-64 items-center justify-center"><LoaderCircle className="animate-spin" /></div> : <>
      <div className="grid gap-4 md:grid-cols-4"><Stat label="Population" value={`${data.denominator} records`} detail="Actual sample"/><Stat label="Positive rate" value={data.positive.rate == null ? '—' : `${(data.positive.rate * 100).toFixed(2)}%`} detail={`${data.positive.positive} / ${data.denominator}`}/><Stat label="PASS" value={String(data.qc_counts.PASS ?? 0)} detail="Official qc_flag"/><Stat label="FAIL" value={String(data.qc_counts.FAIL ?? 0)} detail="Official qc_flag"/></div>
      <Card className="shadow-none"><CardHeader><CardTitle className="text-base">Positive findings</CardTitle></CardHeader><CardContent className="grid gap-3 sm:grid-cols-4"><Stat label="Trisomy" value={String(data.positive.trisomy)} detail="Categories may overlap"/><Stat label="Monosomy" value={String(data.positive.monosomy)} detail="Categories may overlap"/><Stat label="CNV deletion" value={String(data.positive.deletion)} detail="Categories may overlap"/><Stat label="CNV duplication" value={String(data.positive.duplication)} detail="Categories may overlap"/></CardContent></Card>
      <div className="grid gap-4 xl:grid-cols-3">{Object.entries(data.sample_distributions).map(([name, distribution]) => <Raincloud key={name} title={labels[name] ?? name} distribution={distribution}/>)}</div>
      <NcvScatter points={data.ncv_scatter}/>
      <MonthlyQcExport period={period} month={month} />
    </>}
  </div>;
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) { return <Card className="shadow-none"><CardContent className="p-5"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-2xl font-semibold">{value}</p><p className="mt-1 text-[11px] text-muted-foreground">{detail}</p></CardContent></Card>; }

function Raincloud({ title, distribution }: { title: string; distribution: Distribution }) {
  const min = distribution.min ?? 0; const max = distribution.max ?? 1; const span = max - min || 1;
  const x = (value: number) => 24 + ((value - min) / span) * 312;
  return <Card className="shadow-none"><CardHeader><CardTitle className="text-sm">{title}</CardTitle></CardHeader><CardContent><svg viewBox="0 0 360 150" className="w-full" role="img" aria-label={`${title} raincloud plot`}><line x1="24" y1="112" x2="336" y2="112" stroke="currentColor" opacity=".25"/><rect x={x(distribution.q1 ?? min)} y="54" width={Math.max(2, x(distribution.q3 ?? max)-x(distribution.q1 ?? min))} height="34" rx="8" fill="var(--color-primary)" opacity=".16"/><line x1={x(distribution.median ?? min)} x2={x(distribution.median ?? min)} y1="50" y2="92" stroke="var(--color-primary)" strokeWidth="3"/><line x1={x(min)} x2={x(max)} y1="71" y2="71" stroke="var(--color-primary)"/><g>{distribution.points.map((point, index) => <circle key={point.sample_result_id} cx={x(point.value)} cy={105+(index%5)*5} r="2.8" fill="var(--color-info)" opacity=".55"/>)}</g><text x="24" y="145" fontSize="10" fill="currentColor" opacity=".6">{min.toPrecision(4)}</text><text x="336" y="145" textAnchor="end" fontSize="10" fill="currentColor" opacity=".6">{max.toPrecision(4)}</text></svg><div className="grid grid-cols-4 text-center text-[11px]"><span>n {distribution.n}</span><span>Missing {distribution.missing_n}</span><span>Median {distribution.median?.toPrecision(4) ?? '—'}</span><span>IQR {distribution.q1?.toPrecision(3)}–{distribution.q3?.toPrecision(3)}</span></div></CardContent></Card>;
}

function signedLog2(value: number) { return Math.sign(value) * Math.log2(1 + Math.abs(value)); }
function NcvScatter({ points }: { points: QcData['ncv_scatter'] }) {
  const transformed = points.map((point) => ({ ...point, tx: signedLog2(point.x), ty: signedLog2(point.y) }));
  const extent = Math.max(1, ...transformed.flatMap((point) => [Math.abs(point.tx), Math.abs(point.ty)]));
  const scaleX = (value: number) => 330 + (value / extent) * 285; const scaleY = (value: number) => 310 - (value / extent) * 265;
  const classes = [...new Set(points.map((point) => point.class_sx))]; const colors = ['#4f46e5','#0891b2','#059669','#d97706','#a21caf','#dc2626'];
  return <Card className="shadow-none"><CardHeader><CardTitle className="text-base">NCV_X vs NCV_Y by class_sx · signed log2 scale</CardTitle></CardHeader><CardContent><div className="flex flex-wrap gap-3 pb-3 text-xs">{classes.map((name,index)=><span key={name} className="flex items-center gap-1"><i className="size-2 rounded-full" style={{backgroundColor:colors[index%colors.length]}}/>{name}</span>)}</div><svg viewBox="0 0 660 340" className="max-h-[520px] w-full" role="img" aria-label="NCV X and NCV Y scatter plot"><line x1="45" y1="310" x2="620" y2="310" stroke="currentColor" opacity=".25"/><line x1="45" y1="45" x2="45" y2="310" stroke="currentColor" opacity=".25"/><line x1={scaleX(0)} y1="45" x2={scaleX(0)} y2="310" stroke="currentColor" opacity=".12"/><line x1="45" y1={scaleY(0)} x2="620" y2={scaleY(0)} stroke="currentColor" opacity=".12"/>{transformed.map((point)=><circle key={point.sample_result_id} cx={scaleX(point.tx)} cy={scaleY(point.ty)} r="3.2" fill={colors[classes.indexOf(point.class_sx)%colors.length]} opacity=".68"/>)}<text x="330" y="335" textAnchor="middle" fontSize="11">NCV_X · signed log2</text><text x="13" y="175" textAnchor="middle" fontSize="11" transform="rotate(-90 13 175)">NCV_Y · signed log2</text></svg><p className="text-xs text-muted-foreground">Each point is an actual sample; color represents class_sx. n={points.length}</p></CardContent></Card>;
}
