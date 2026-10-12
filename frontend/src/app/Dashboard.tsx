"use client";

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  PieChart, Pie, Cell, ResponsiveContainer,
  Tooltip as RechartsTooltip, Legend,
  LineChart, Line, XAxis, YAxis, CartesianGrid,
} from 'recharts';
import {
  Activity, BrainCircuit, Cpu, Database, Play, BarChart3,
  Clock, ShieldCheck, Zap, CheckCircle2, XCircle, AlertTriangle,
} from 'lucide-react';

const COLORS = ['#0f766e', '#d97706', '#2563eb', '#4f46e5', '#8b5cf6', '#0ea5e9', '#10b981', '#f59e0b', '#e11d48', '#06b6d4', '#84cc16', '#f43f5e'];

// Backend base URL; NEXT_PUBLIC_* values are inlined at build time.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';
const POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 300;

type StrategyResult = {
  weights: Record<string, number>;
  expected_return: number;
  volatility: number;
  sharpe_ratio: number;
  portfolio_objective?: number;
  budget_sum?: number;
  feasible?: boolean;
  violations?: string[];
  gap_to_optimal_pct?: number | null;
  success?: boolean;
  p_optimal?: number;
  uniform_p_optimal?: number;
};

type OptimizeResult = {
  classical: StrategyResult;
  exact: StrategyResult | null;
  sa: StrategyResult;
  quantum: StrategyResult;
  backtest_timeseries: { date: string; SLSQP: number; SA: number; QAOA: number; Exact?: number }[];
  qubo: {
    num_qubits: number; num_integer_vars: number; num_constraints: number;
    num_feasible_portfolios?: number | null;
  };
  qaoa_config: { reps: number; cvar_alpha: number; init: string; optimizer: string; shots: number; backend: string };
  execution_time: {
    classical_sec: number; exact_sec: number | null; sa_sec: number;
    quantum_sec: number; total_sec: number;
  };
};

export default function Dashboard() {
  const [tickers, setTickers] = useState<string[]>([]);
  const [budgetResolution, setBudgetResolution] = useState<number>(2);
  const [targetDuration, setTargetDuration] = useState<number>(4.0);
  const [maxSectorExposure, setMaxSectorExposure] = useState<number>(0.60);
  const [maxAssetExposure, setMaxAssetExposure] = useState<number>(0.50);
  const [minCET1, setMinCET1] = useState<number>(0.0);
  const [minLCR, setMinLCR] = useState<number>(0.0);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [results, setResults] = useState<OptimizeResult | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/universe`)
      .then(res => res.json())
      .then(data => setTickers(data.tickers))
      .catch(err => console.error('Failed to fetch universe', err));
  }, []);

  const runOptimization = async () => {
    setIsOptimizing(true);
    setLogs(['Submitting optimization request...']);
    setResults(null);

    try {
      const res = await fetch(`${API_BASE}/api/optimize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tickers,
          start_date: '2020-01-01',
          end_date: '2023-01-01',
          backtest_start_date: '2023-01-01',
          backtest_end_date: '2024-01-01',
          budget_resolution: budgetResolution,
          q_factor: 0.5,
          target_duration: targetDuration,
          max_sector_exposure: maxSectorExposure,
          max_asset_exposure: maxAssetExposure,
          min_cet1: minCET1,
          min_lcr: minLCR,
        }),
      });

      if (!res.ok) {
        const detail = await res.text();
        setLogs(prev => [...prev, `ERROR: request rejected (${res.status}): ${detail}`]);
        setIsOptimizing(false);
        return;
      }
      const { task_id } = await res.json();
      setLogs(prev => [...prev, `Task accepted (ID: ${task_id.slice(0, 8)}...). Backend runs: data → SLSQP → Exact → SA → QAOA → backtest.`]);

      // Only the backend's real task status is shown; it does not report per-step progress.
      let status = 'PENDING';
      let lastStatus = '';
      let pollCount = 0;
      while ((status === 'PENDING' || status === 'RUNNING') && pollCount < MAX_POLLS) {
        await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
        pollCount++;
        const statusRes = await fetch(`${API_BASE}/api/task/${task_id}`);
        if (!statusRes.ok) {
          setLogs(prev => [...prev, `ERROR: task lookup failed (${statusRes.status}).`]);
          break;
        }
        const statusData = await statusRes.json();
        status = statusData.status;
        const elapsed = (pollCount * POLL_INTERVAL_MS) / 1000;

        if (status !== lastStatus || pollCount % 5 === 0) {
          if (status === 'PENDING' || status === 'RUNNING') {
            setLogs(prev => [...prev, `Status: ${status} (${elapsed.toFixed(0)}s elapsed)`]);
          }
          lastStatus = status;
        }
        if (status === 'COMPLETED') {
          setLogs(prev => [...prev, `✓ Completed in ${statusData.result.execution_time.total_sec.toFixed(1)}s.`]);
          setResults(statusData.result);
          break;
        }
        if (status === 'FAILED') {
          setLogs(prev => [...prev, `ERROR: ${statusData.error}`]);
          break;
        }
      }
      if ((status === 'PENDING' || status === 'RUNNING') && pollCount >= MAX_POLLS) {
        setLogs(prev => [...prev, `ERROR: gave up waiting after ${(MAX_POLLS * POLL_INTERVAL_MS) / 1000}s; the task may still be running.`]);
      }
    } catch {
      setLogs(prev => [...prev, 'Error connecting to backend.']);
    }
    setIsOptimizing(false);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans selection:bg-amber-500/30">
      {/* Background */}
      <div className="fixed inset-0 z-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] rounded-full bg-slate-800/20 blur-[150px]" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[50%] h-[50%] rounded-full bg-blue-900/10 blur-[150px]" />
      </div>

      <div className="relative z-10 max-w-[1400px] mx-auto p-6 space-y-8">
        {/* Header */}
        <header className="flex items-center justify-between pb-6 border-b border-slate-800">
          <div className="flex items-center gap-4">
            <div className="p-3 rounded-xl bg-gradient-to-br from-slate-800 to-slate-900 border border-slate-700 shadow-xl">
              <BrainCircuit className="w-7 h-7 text-amber-500" />
            </div>
            <div>
              <h1 className="text-3xl font-bold tracking-tight text-white">
                Quantum Portfolio <span className="text-amber-500">Optimizer</span>
              </h1>
              <p className="text-sm text-slate-400 mt-1 font-medium tracking-wide uppercase">
                CVaR-QAOA vs. Simulated Annealing vs. Exact · Same QUBO · Noiseless simulation
              </p>
            </div>
          </div>
          {results && (
            <div className="flex gap-3 text-xs">
              <Stat label="Qubits"      value={String(results.qubo.num_qubits)} />
              <Stat label="Vars"        value={String(results.qubo.num_integer_vars)} />
              <Stat label="Constraints" value={String(results.qubo.num_constraints)} />
              <Stat label="Feasible"    value={results.qubo.num_feasible_portfolios == null ? '—' : String(results.qubo.num_feasible_portfolios)} />
            </div>
          )}
        </header>

        <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
          {/* Controls (col-4) */}
          <div className="md:col-span-4 space-y-6">
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
              className="p-6 rounded-2xl bg-slate-900/60 backdrop-blur-xl border border-slate-800 shadow-2xl">
              <h2 className="text-lg font-semibold mb-6 flex items-center gap-2 text-white">
                <Database className="w-5 h-5 text-blue-400" /> Model Configuration
              </h2>
              <div className="space-y-6">
                <Slider label="Budget Resolution" hint="Weights are multiples of 1/R. Qubits per asset = ⌊log₂(max slices)⌋+1."
                  unit="slices" value={budgetResolution} min={1} max={5} step={1}
                  onChange={v => setBudgetResolution(v)} display={v => `${v}`} />
                <Slider label="Target Duration" hint="Equality on durations rounded to whole years (zero slack qubits)."
                  unit="yrs" value={targetDuration} min={1} max={10} step={0.5}
                  onChange={setTargetDuration} display={v => v.toFixed(1)} />
                <Slider label="Max Sector Exposure" hint="Bounded inequality (minimal slack qubits)."
                  unit="%" value={maxSectorExposure} min={0.1} max={1.0} step={0.05}
                  onChange={setMaxSectorExposure} display={v => `${(v * 100).toFixed(0)}`} />
                <Slider label="Max Asset Exposure" hint="Variable upper bound (zero qubit overhead)."
                  unit="%" value={maxAssetExposure} min={0.05} max={1.0} step={0.05}
                  onChange={setMaxAssetExposure} display={v => `${(v * 100).toFixed(0)}`} />
              </div>
            </motion.div>

            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
              className="p-6 rounded-2xl bg-slate-900/60 backdrop-blur-xl border border-slate-800 shadow-2xl relative overflow-hidden">
              <div className="absolute top-0 right-0 p-3 bg-blue-500/10 rounded-bl-2xl border-b border-l border-blue-500/20">
                <ShieldCheck className="w-4 h-4 text-blue-400" />
              </div>
              <h2 className="text-lg font-semibold mb-6 flex items-center gap-2 text-white">Basel III Soft Penalties</h2>
              <div className="space-y-6">
                <Slider label="Min CET1 (portfolio-weighted)" hint="Soft penalty λ(c·w − min)², λ=10, off at 0. Stylised, not a Basel rule for investors."
                  unit="%" value={minCET1} min={0.0} max={0.20} step={0.01}
                  onChange={setMinCET1} display={v => `${(v * 100).toFixed(1)}`} accent="blue" />
                <Slider label="Min LCR (portfolio-weighted)" hint="Soft penalty λ(l·w − min)², λ=10, off at 0. Two-sided: also penalises exceeding the minimum."
                  unit="%" value={minLCR} min={0.0} max={1.5} step={0.05}
                  onChange={setMinLCR} display={v => `${(v * 100).toFixed(0)}`} accent="blue" />
              </div>
            </motion.div>

            <button onClick={runOptimization} disabled={isOptimizing || tickers.length === 0}
              className="w-full py-4 px-4 rounded-xl font-semibold flex items-center justify-center gap-2 transition-all
                       bg-slate-100 hover:bg-white text-slate-950 shadow-xl disabled:opacity-50 disabled:cursor-not-allowed
                       ring-1 ring-white/50">
              {isOptimizing ? <Activity className="w-5 h-5 animate-pulse" /> : <Play className="w-5 h-5 fill-current" />}
              {isOptimizing ? 'Running solvers...' : 'Run All Four Solvers'}
            </button>
          </div>

          {/* Right: terminal + 2x2 results + backtest (col-8) */}
          <div className="md:col-span-8 space-y-6">
            {/* Terminal */}
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}
              className="p-5 rounded-2xl bg-[#050505] border border-slate-800 shadow-2xl h-[220px] flex flex-col font-mono">
              <div className="flex items-center justify-between mb-3 border-b border-slate-800 pb-3">
                <span className="text-xs text-slate-500 flex items-center gap-2 uppercase tracking-widest font-semibold">
                  <Cpu className="w-4 h-4" /> Runtime Console
                </span>
                <div className="flex gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-slate-700" />
                  <div className="w-2.5 h-2.5 rounded-full bg-slate-700" />
                  <div className="w-2.5 h-2.5 rounded-full bg-slate-700" />
                </div>
              </div>
              <div className="flex-1 overflow-y-auto space-y-1.5 text-sm pl-1 pr-4 custom-scrollbar">
                {logs.length === 0 ? (
                  <div className="text-slate-600 italic">Awaiting parameters...</div>
                ) : (
                  <AnimatePresence>
                    {logs.map((log, i) => (
                      <motion.div key={i} initial={{ opacity: 0, x: -5 }} animate={{ opacity: 1, x: 0 }}
                        className={`text-[13px] ${log.includes('ERROR') ? 'text-red-400' : log.includes('✓') ? 'text-emerald-400' : 'text-slate-300'}`}>
                        <span className="text-amber-500 mr-2 opacity-70">{'>'}</span> {log}
                      </motion.div>
                    ))}
                  </AnimatePresence>
                )}
                {isOptimizing && (
                  <motion.div animate={{ opacity: [1, 0, 1] }} transition={{ repeat: Infinity, duration: 0.8 }} className="text-amber-500">_</motion.div>
                )}
              </div>
            </motion.div>

            {/* 2x2 Results Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <StrategyCard
                title="Classical SLSQP" subtitle="Continuous relaxation · SciPy"
                icon={<BarChart3 className="w-3.5 h-3.5" />}
                strategy={results?.classical} time={results?.execution_time.classical_sec}
                accent="slate" />
              <StrategyCard
                title="Exact QUBO" subtitle="NumPyMinimumEigensolver · ground truth"
                icon={<Zap className="w-3.5 h-3.5" />}
                strategy={results?.exact ?? undefined} time={results?.execution_time.exact_sec ?? undefined}
                accent="emerald" />
              <StrategyCard
                title="Simulated Annealing" subtitle="dimod · same QUBO · classical heuristic"
                icon={<Cpu className="w-3.5 h-3.5" />}
                strategy={results?.sa} time={results?.execution_time.sa_sec}
                accent="blue" />
              <StrategyCard
                title={`CVaR-QAOA (p=${results?.qaoa_config.reps ?? 3})`}
                subtitle={results
                  ? `α=${results.qaoa_config.cvar_alpha} · linear-ramp · best feasible of ${results.qaoa_config.shots} shots`
                  : 'CVaR-α aggregation · linear-ramp init · noiseless Aer simulation'}
                icon={<BrainCircuit className="w-3.5 h-3.5" />}
                strategy={results?.quantum} time={results?.execution_time.quantum_sec}
                accent="amber" highlight />
            </div>

            {/* Backtest */}
            {results && results.backtest_timeseries && results.backtest_timeseries.length > 0 && (
              <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }}
                className="p-6 rounded-2xl bg-slate-900/60 backdrop-blur-xl border border-slate-800 shadow-2xl h-[360px] flex flex-col">
                <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
                  <Clock className="w-4 h-4 text-slate-400" /> Out-of-Sample Backtest (2023 → 2024)
                </h3>
                <div className="flex-1 min-h-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={results.backtest_timeseries} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                      <XAxis dataKey="date" stroke="#64748b" fontSize={10} tickMargin={10} minTickGap={40} />
                      <YAxis stroke="#64748b" fontSize={10} tickFormatter={v => `${(v * 100).toFixed(0)}%`} />
                      <RechartsTooltip formatter={(v) => `${(Number(v) * 100).toFixed(2)}%`}
                        labelStyle={{ color: '#94a3b8', fontSize: 12, marginBottom: 4 }}
                        contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', borderRadius: 8 }} />
                      <Legend iconType="circle" wrapperStyle={{ fontSize: 12, paddingTop: 10 }} />
                      <Line type="monotone" dataKey="SLSQP" stroke="#94a3b8" strokeWidth={1.5} dot={false} />
                      {results.exact && <Line type="monotone" dataKey="Exact" stroke="#10b981" strokeWidth={1.5} dot={false} />}
                      <Line type="monotone" dataKey="SA"    stroke="#3b82f6" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="QAOA"  stroke="#f59e0b" strokeWidth={2.5} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </motion.div>
            )}

            {/* QAOA config footer */}
            {results && (
              <div className="text-[11px] text-slate-500 font-mono pl-2">
                qaoa: reps={results.qaoa_config.reps}, cvar_α={results.qaoa_config.cvar_alpha}, init={results.qaoa_config.init}, opt={results.qaoa_config.optimizer}, backend={results.qaoa_config.backend}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* =========================================================================
 * Sub-components
 * ========================================================================= */
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-3 py-1.5 rounded-lg bg-slate-900/60 border border-slate-800">
      <div className="text-[9px] uppercase tracking-widest text-slate-500">{label}</div>
      <div className="text-sm font-mono text-amber-400">{value}</div>
    </div>
  );
}

type SliderProps = {
  label: string; hint: string; unit: string;
  value: number; min: number; max: number; step: number;
  onChange: (v: number) => void;
  display: (v: number) => string;
  accent?: 'amber' | 'blue';
};
function Slider({ label, hint, unit, value, min, max, step, onChange, display, accent = 'amber' }: SliderProps) {
  const chipCls = accent === 'blue' ? 'text-blue-400 bg-blue-500/10' : 'text-amber-500 bg-amber-500/10';
  const accentCls = accent === 'blue' ? 'accent-blue-500' : 'accent-amber-500';
  return (
    <div>
      <div className="flex justify-between items-end mb-1">
        <label className="text-sm font-medium text-slate-300">{label}</label>
        <span className={`text-xs font-mono px-2 py-0.5 rounded ${chipCls}`}>
          {display(value)}{unit && ` ${unit}`}
        </span>
      </div>
      <p className="text-[11px] text-slate-500 mb-3 leading-tight">{hint}</p>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className={`w-full ${accentCls}`} />
    </div>
  );
}

type StrategyCardProps = {
  title: string; subtitle: string;
  icon: React.ReactNode;
  strategy?: StrategyResult; time?: number | null;
  accent: 'slate' | 'emerald' | 'blue' | 'amber';
  highlight?: boolean;
};
function StrategyCard({ title, subtitle, icon, strategy, time, accent, highlight }: StrategyCardProps) {
  const accentMap = {
    slate: { text: 'text-slate-400', chip: 'bg-slate-800 text-slate-400' },
    emerald: { text: 'text-emerald-400', chip: 'bg-emerald-500/10 text-emerald-400' },
    blue: { text: 'text-blue-400', chip: 'bg-blue-500/10 text-blue-400' },
    amber: { text: 'text-amber-500', chip: 'bg-amber-500/10 text-amber-400' },
  }[accent];
  const cardCls = highlight
    ? 'bg-gradient-to-br from-slate-900 to-slate-800 border-slate-700 shadow-xl'
    : 'bg-slate-900/40 border-slate-800';

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
      className={`p-5 rounded-2xl border flex flex-col h-[340px] relative overflow-hidden ${cardCls}`}>
      {highlight && <div className="absolute top-0 right-0 w-32 h-32 bg-amber-500/10 blur-[50px] pointer-events-none" />}
      <div className="flex justify-between items-start mb-1 relative z-10">
        <h3 className={`text-[11px] font-semibold uppercase tracking-widest flex items-center gap-1.5 ${accentMap.text}`}>
          {icon} {title}
        </h3>
        {strategy && time != null && (
          <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${accentMap.chip}`}>{time.toFixed(3)}s</span>
        )}
      </div>
      <p className="text-[10px] text-slate-600 mb-2">{subtitle}</p>

      {/* feasibility / objective */}
      <div className="flex items-center gap-3 mb-2 relative z-10 min-h-[18px]">
        {strategy && strategy.feasible !== undefined && (
          strategy.feasible
            ? <span className="text-[10px] text-emerald-400 flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> feasible</span>
            : <span className="text-[10px] text-amber-400 flex items-center gap-1" title={(strategy.violations ?? []).join(' · ')}>
                <AlertTriangle className="w-3 h-3" /> {strategy.violations?.length ?? 0} violation{(strategy.violations?.length ?? 0) === 1 ? '' : 's'}
              </span>
        )}
        {strategy && strategy.gap_to_optimal_pct != null && (
          <span className="text-[10px] font-mono text-slate-500">Δ {strategy.gap_to_optimal_pct >= 0 ? '+' : ''}{strategy.gap_to_optimal_pct.toFixed(2)}%</span>
        )}
        {strategy && strategy.gap_to_optimal_pct == null && strategy.feasible === false && (
          <span className="text-[10px] font-mono text-red-400 flex items-center gap-1"><XCircle className="w-3 h-3" /> Δ n/a</span>
        )}
        {strategy && strategy.success === false && (
          <span className="text-[10px] font-mono text-red-400">solver did not converge</span>
        )}
      </div>
      {strategy && strategy.p_optimal != null && (
        <p className="text-[10px] font-mono text-slate-500 mb-1 relative z-10"
          title="Probability the final QAOA state puts on the optimal portfolio, vs. uniform random guessing">
          P(optimum) {(strategy.p_optimal * 100).toFixed(1)}%
          {strategy.uniform_p_optimal != null && ` vs ${(strategy.uniform_p_optimal * 100).toFixed(1)}% random`}
        </p>
      )}

      <div className="flex-1 min-h-0 relative z-10">
        {!strategy ? (
          <div className="absolute inset-0 flex items-center justify-center text-slate-600 italic text-sm">No data</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={formatChartData(strategy.weights)} innerRadius="55%" outerRadius="80%" paddingAngle={2} dataKey="value" stroke="none">
                {formatChartData(strategy.weights).map((_, i) => (
                  <Cell key={`c-${title}-${i}`} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <RechartsTooltip formatter={(v) => `${(Number(v) * 100).toFixed(1)}%`}
                contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, fontSize: 11 }} />
              <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 10, color: '#94a3b8' }} />
            </PieChart>
          </ResponsiveContainer>
        )}
      </div>

      {strategy && (
        <div className="grid grid-cols-3 gap-2 mt-4 pt-3 border-t border-slate-800/50 relative z-10">
          <Metric label="Return" value={`${(strategy.expected_return * 100).toFixed(2)}%`} />
          <Metric label="Risk"   value={`${(strategy.volatility * 100).toFixed(2)}%`} />
          <Metric label="Sharpe" value={strategy.sharpe_ratio.toFixed(2)} />
        </div>
      )}
    </motion.div>
  );
}

function formatChartData(weights: Record<string, number> | undefined) {
  if (!weights) return [];
  return Object.entries(weights).map(([name, value]) => ({ name, value: Number(value) }));
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-0.5">{label}</div>
      <div className="text-sm font-light text-white">{value}</div>
    </div>
  );
}
