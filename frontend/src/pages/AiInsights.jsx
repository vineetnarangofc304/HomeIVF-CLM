import React, { useEffect, useRef, useState } from "react";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Legend, PieChart, Pie, Cell, Cell as RCell,
} from "recharts";
import { Sparkle, PaperPlaneTilt, TrendUp, Users, Target, MapPin } from "@phosphor-icons/react";
import { API, apiErr } from "../lib/api";
import { toast } from "sonner";

const PIE = ["#4A90E2", "#8B5CF6", "#10b981", "#f59e0b", "#f43f5e", "#06b6d4", "#a855f7", "#84cc16"];
const nf = (n) => (n ?? 0).toLocaleString("en-IN");

const Card = ({ title, icon: Icon, children, testid, span }) => (
  <div className={`hivf-card p-4 ${span || ""}`} data-testid={testid}>
    <div className="mb-3 flex items-center gap-2">
      {Icon && <Icon size={16} weight="bold" className="text-[#4A90E2]" />}
      <h3 className="font-display text-sm font-extrabold text-slate-800">{title}</h3>
    </div>
    {children}
  </div>
);

const Kpi = ({ label, value, suffix, testid }) => (
  <div className="hivf-card p-4" data-testid={testid}>
    <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">{label}</p>
    <p className="mt-1 font-display text-3xl font-extrabold text-slate-900">{value}{suffix}</p>
  </div>
);

export default function AiInsights() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [asking, setAsking] = useState(false);
  const [chat, setChat] = useState([]);
  const sessionId = useRef("s-" + Math.random().toString(36).slice(2, 9));
  const scroller = useRef(null);

  useEffect(() => {
    API.get("/ai/analytics").then(({ data }) => setData(data))
      .catch((e) => toast.error(apiErr(e))).finally(() => setLoading(false));
  }, []);

  useEffect(() => { scroller.current?.scrollTo(0, scroller.current.scrollHeight); }, [chat, asking]);

  const ask = async (question) => {
    const text = (question ?? q).trim();
    if (!text || asking) return;
    setQ("");
    setChat((c) => [...c, { role: "user", text }]);
    setAsking(true);
    try {
      const { data } = await API.post("/ai/brain", { question: text, session_id: sessionId.current });
      setChat((c) => [...c, { role: "ai", ...data }]);
    } catch (e) {
      setChat((c) => [...c, { role: "ai", answer: "Sorry, I couldn't answer that: " + apiErr(e) }]);
    } finally { setAsking(false); }
  };

  const SUGGESTIONS = [
    "How many leads converted by source?",
    "Top callers by conversion rate",
    "Leads per month this year",
    "Conversion rate by lead stage",
  ];

  const renderChart = (chart) => {
    if (!chart || !chart.data?.length || chart.type === "number") return null;
    const d = chart.data.slice(0, 12);
    if (chart.type === "line")
      return (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={d}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#64748b" }} />
            <YAxis tick={{ fontSize: 10, fill: "#64748b" }} width={40} />
            <Tooltip />
            <Line type="monotone" dataKey="value" stroke="#4A90E2" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      );
    if (chart.type === "pie")
      return (
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie data={d} dataKey="value" nameKey="label" outerRadius={80} label={(e) => e.label}>
              {d.map((r, i) => <Cell key={i} fill={PIE[i % PIE.length]} />)}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      );
    return (
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={d} layout="vertical" margin={{ left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 10, fill: "#64748b" }} />
          <YAxis type="category" dataKey="label" tick={{ fontSize: 10, fill: "#64748b" }} width={120} />
          <Tooltip />
          <Bar dataKey="value" radius={[0, 4, 4, 0]}>
            {d.map((r, i) => <RCell key={i} fill={PIE[i % PIE.length]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  };

  return (
    <div className="space-y-5" data-testid="ai-insights-page">
        <div className="flex items-center gap-2">
          <Sparkle size={22} weight="fill" className="text-[#8B5CF6]" />
          <h1 className="font-display text-2xl font-extrabold text-slate-900">AI Insights</h1>
        </div>

        {/* AI Brain */}
        <div className="hivf-card overflow-hidden p-0" data-testid="ai-brain-panel">
          <div className="flex items-center gap-2 border-b border-slate-100 bg-gradient-to-r from-[#8B5CF6]/10 to-[#4A90E2]/10 px-4 py-3">
            <Sparkle size={16} weight="fill" className="text-[#8B5CF6]" />
            <span className="font-display text-sm font-extrabold text-slate-800">AI Brain — ask about your data</span>
          </div>
          <div ref={scroller} className="max-h-[360px] space-y-3 overflow-y-auto px-4 py-4" data-testid="ai-chat-log">
            {chat.length === 0 && (
              <div className="text-sm text-slate-400">
                Ask a question in plain English. Try:
                <div className="mt-2 flex flex-wrap gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} onClick={() => ask(s)} data-testid="ai-suggestion"
                      className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 hover:border-[#8B5CF6] hover:text-[#8B5CF6]">{s}</button>
                  ))}
                </div>
              </div>
            )}
            {chat.map((m, i) => (
              <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
                {m.role === "user" ? (
                  <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-[#4A90E2] px-3 py-2 text-sm text-white" data-testid="ai-user-msg">{m.text}</div>
                ) : (
                  <div className="max-w-[92%] rounded-2xl rounded-bl-sm bg-slate-50 px-3 py-2" data-testid="ai-answer">
                    <p className="text-sm text-slate-700" dangerouslySetInnerHTML={{ __html: (m.answer || "").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>") }} />
                    {m.chart && renderChart(m.chart) && (
                      <div className="mt-3">{renderChart(m.chart)}</div>
                    )}
                  </div>
                )}
              </div>
            ))}
            {asking && <div className="text-sm text-slate-400" data-testid="ai-thinking">AI is thinking…</div>}
          </div>
          <div className="flex items-center gap-2 border-t border-slate-100 px-4 py-3">
            <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()}
              placeholder="e.g. Which source has the best conversion rate?" data-testid="ai-input"
              className="flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm focus:border-[#8B5CF6] focus:outline-none" />
            <button onClick={() => ask()} disabled={asking} data-testid="ai-send-button"
              className="hivf-btn-primary flex items-center gap-1 !py-2">
              <PaperPlaneTilt size={16} weight="bold" /> Ask
            </button>
          </div>
        </div>

        {loading ? (
          <div className="hivf-card p-10 text-center text-slate-400">Loading analytics…</div>
        ) : data && (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Kpi label="Total Leads" value={nf(data.kpis.total)} testid="kpi-total" />
              <Kpi label="Converted" value={nf(data.kpis.converted)} testid="kpi-converted" />
              <Kpi label="Conversion Rate" value={data.kpis.conversion_rate} suffix="%" testid="kpi-rate" />
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Card title="Conversion Funnel" icon={Target} testid="chart-funnel">
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={data.funnel} layout="vertical" margin={{ left: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 10, fill: "#64748b" }} />
                    <YAxis type="category" dataKey="label" tick={{ fontSize: 11, fill: "#64748b" }} width={110} />
                    <Tooltip />
                    <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                      {data.funnel.map((r, i) => <RCell key={i} fill={PIE[i % PIE.length]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </Card>

              <Card title="Leads Trend (last 30 days)" icon={TrendUp} testid="chart-trend">
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={data.trend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 9, fill: "#64748b" }} tickFormatter={(v) => v.slice(5)} />
                    <YAxis tick={{ fontSize: 10, fill: "#64748b" }} width={40} />
                    <Tooltip /><Legend />
                    <Line type="monotone" dataKey="total" name="Leads" stroke="#4A90E2" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="converted" name="Converted" stroke="#10b981" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </Card>

              <Card title="Source Performance (leads vs converted)" icon={Sparkle} testid="chart-source">
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={data.source.slice(0, 8)}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 9, fill: "#64748b" }} interval={0} angle={-15} textAnchor="end" height={50} />
                    <YAxis tick={{ fontSize: 10, fill: "#64748b" }} width={44} />
                    <Tooltip /><Legend />
                    <Bar dataKey="total" name="Leads" fill="#4A90E2" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="converted" name="Converted" fill="#10b981" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </Card>

              <Card title="Caller Performance (conversion %)" icon={Users} testid="chart-caller">
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={data.caller.slice(0, 10)} layout="vertical" margin={{ left: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 10, fill: "#64748b" }} unit="%" />
                    <YAxis type="category" dataKey="label" tick={{ fontSize: 10, fill: "#64748b" }} width={130} />
                    <Tooltip formatter={(v, n) => [n === "rate" ? v + "%" : v, n]} />
                    <Bar dataKey="rate" name="Conv %" radius={[0, 4, 4, 0]}>
                      {data.caller.slice(0, 10).map((r, i) => <RCell key={i} fill={PIE[i % PIE.length]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </Card>

              <Card title="Ad Platform Split" icon={Sparkle} testid="chart-platform">
                <ResponsiveContainer width="100%" height={240}>
                  <PieChart>
                    <Pie data={data.platform.slice(0, 6)} dataKey="total" nameKey="label" outerRadius={80} label={(e) => e.label}>
                      {data.platform.slice(0, 6).map((r, i) => <Cell key={i} fill={PIE[i % PIE.length]} />)}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </Card>

              <Card title="Top States" icon={MapPin} testid="chart-geo">
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={data.geo.slice(0, 10)} layout="vertical" margin={{ left: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 10, fill: "#64748b" }} />
                    <YAxis type="category" dataKey="label" tick={{ fontSize: 10, fill: "#64748b" }} width={70} />
                    <Tooltip />
                    <Bar dataKey="value" fill="#8B5CF6" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </Card>
            </div>
          </>
        )}
      </div>
  );
}
