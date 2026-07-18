import React, { useEffect, useMemo, useRef, useState, useCallback } from "react";
import Chart from "chart.js/auto";
import { API, apiErr } from "../lib/api";
import { toast } from "sonner";
import "./LeadPulse.css";

const fmt = (n) => (n ?? 0).toLocaleString("en-IN");
const pctStr = (n, d) => (d ? (((n / d) * 100).toFixed((n / d) * 100 < 10 ? 1 : 0)) + "%" : "—");
const pctInt = (n, d) => (d ? Math.round((n / d) * 100) : 0);

Chart.defaults.font.family = "'Albert Sans',sans-serif";
Chart.defaults.color = "#42506A";

export default function KpiOverview() {
  const [data, setData] = useState(null);
  const [month, setMonth] = useState("");
  const [funnelMode, setFunnelMode] = useState("mtd");
  const [clock, setClock] = useState("");

  const donutRef = useRef(null);
  const closedRef = useRef(null);
  const paceRef = useRef(null);
  const charts = useRef({});

  useEffect(() => {
    const tick = () => {
      const n = new Date();
      setClock(
        n.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) + ", " +
        n.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true })
      );
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const load = useCallback((m) => {
    API.get("/reports/kpi-overview", { params: m ? { month: m } : {} })
      .then(({ data }) => setData(data))
      .catch((e) => toast.error(apiErr(e)));
  }, []);

  useEffect(() => { load(month); }, [month, load]);

  // auto-refresh the live (current-month) view every 5 minutes
  useEffect(() => {
    if (!data || !data.is_current) return;
    const id = setInterval(() => load(month), 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [data, month, load]);

  // ---------- derived numbers ----------
  const D = useMemo(() => {
    if (!data) return null;
    const stageBy = (k) => data.stages.find((s) => s.key === k) || { totals: { ftd: 0, mtd: 0, ytd: 0 }, rows: [] };
    const findRow = (k, name) => (stageBy(k).rows || []).find((r) => r.name === name) || { ftd: 0, mtd: 0, ytd: 0 };
    const total = data.total;

    const validRows = [
      findRow("contacted", "Call back for appointment"),
      findRow("contacted", "OPD Booked"),
      findRow("converted", "OPD Done"),
      findRow("closed", "Valid Not Interested"),
    ];
    const valid = {
      ftd: validRows.reduce((a, r) => a + r.ftd, 0),
      mtd: validRows.reduce((a, r) => a + r.mtd, 0),
      ytd: validRows.reduce((a, r) => a + r.ytd, 0),
    };

    const opdBooked = findRow("contacted", "OPD Booked");
    const opdDone = findRow("converted", "OPD Done");
    const regDone = findRow("converted", "Registration Done");
    const treat = findRow("converted", "Treatment Started");
    const contacted = stageBy("contacted").totals;
    const converted = stageBy("converted").totals;

    const funnelFor = (f) => ([
      ["Leads received", total[f]],
      ["Engaged (Contacted+)", contacted[f] + converted[f]],
      ["OPD Booked+", opdBooked[f] + converted[f]],
      ["OPD Done+", converted[f]],
      ["Registered+", Math.max(converted[f] - opdDone[f], 0)],
      ["Treatment Started", treat[f]],
    ]);
    const funnel = { ftd: funnelFor("ftd"), mtd: funnelFor("mtd"), ytd: funnelFor("ytd") };

    const convFor = (f) => {
      const v = valid[f];
      const bookedPlus = opdBooked[f] + converted[f];
      const donePlus = converted[f];
      const regPlus = Math.max(converted[f] - opdDone[f], 0);
      return {
        v2b: pctInt(bookedPlus, v),
        b2d: pctInt(donePlus, bookedPlus),
        d2r: pctInt(regPlus, donePlus),
        r2s: pctInt(treat[f], regPlus),
      };
    };
    const cm = convFor("mtd"), cy = convFor("ytd");
    const conversion = [
      ["Valid to OPD Booked", cm.v2b, cy.v2b],
      ["OPD Booked to OPD Done", cm.b2d, cy.b2d],
      ["OPD Done to Registration", cm.d2r, cy.d2r],
      ["Registration to Stimulation start", cm.r2s, cy.r2s],
    ];

    const pulseBase = (f) => data.stages.reduce((a, s) => a + s.totals[f], 0) || 1;

    const kpis = [
      { label: data.is_current ? "Today Total Leads" : "Leads / Day (avg)", f: total.ftd, m: total.mtd, y: total.ytd, k: "#0E8A83" },
      { label: "OPD Booked (Current)", f: opdBooked.ftd, m: opdBooked.mtd, y: opdBooked.ytd, k: "#E7A23C" },
      { label: "OPD Done", f: opdDone.ftd, m: opdDone.mtd, y: opdDone.ytd, k: "#11A07B" },
      { label: "Registration", f: regDone.ftd, m: regDone.mtd, y: regDone.ytd, k: "#2F6DE0" },
    ];

    return { total, valid, funnel, conversion, pulseBase, kpis, dayLbl: data.day_label, monLbl: data.month_label };
  }, [data]);

  // ---------- charts ----------
  useEffect(() => {
    if (!data || !D) return;
    Object.values(charts.current).forEach((c) => c && c.destroy());
    charts.current = {};
    const stages = data.stages;
    const totalMtd = data.total.mtd || 1;

    charts.current.donut = new Chart(donutRef.current, {
      type: "doughnut",
      data: {
        labels: stages.map((s) => s.name),
        datasets: [{ data: stages.map((s) => s.totals.mtd), backgroundColor: stages.map((s) => s.hex), borderWidth: 2, borderColor: "#fff" }],
      },
      options: {
        maintainAspectRatio: false, cutout: "62%",
        plugins: {
          legend: { position: "right", labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: { callbacks: { label: (c) => ` ${fmt(c.parsed)} (${pctStr(c.parsed, totalMtd)})` } },
        },
      },
    });

    const closedSorted = [...stages.find((s) => s.key === "closed").rows].sort((a, b) => b.mtd - a.mtd).slice(0, 10);
    charts.current.closed = new Chart(closedRef.current, {
      type: "bar",
      data: {
        labels: closedSorted.map((r) => r.name),
        datasets: [{ data: closedSorted.map((r) => r.mtd), backgroundColor: "#D64562", borderRadius: 5, barThickness: 14 }],
      },
      options: {
        indexAxis: "y", maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` ${fmt(c.parsed.x)} leads (${pctStr(c.parsed.x, totalMtd)})` } } },
        scales: { x: { grid: { color: "#EEF1F5" } }, y: { grid: { display: false }, ticks: { font: { size: 11 } } } },
      },
    });

    let ds;
    if (data.is_current) {
      const el = data.elapsed_days || 1;
      ds = [
        { label: "FTD (today)", data: stages.map((s) => s.totals.ftd), backgroundColor: "#0F1B2D", borderRadius: 5 },
        { label: "MTD daily avg", data: stages.map((s) => Math.round(s.totals.mtd / el)), backgroundColor: "#B9C3D2", borderRadius: 5 },
      ];
    } else {
      const dm = data.days_in_month || 1;
      const pm = data.prev_month;
      ds = [
        { label: `${data.month} avg/day`, data: stages.map((s) => Math.round(s.totals.mtd / dm)), backgroundColor: "#0F1B2D", borderRadius: 5 },
      ];
      if (pm) ds.push({ label: `${pm.label} avg/day`, data: stages.map((s) => Math.round((pm.stage_totals[s.key] || 0) / (pm.days || 1))), backgroundColor: "#B9C3D2", borderRadius: 5 });
    }
    charts.current.pace = new Chart(paceRef.current, {
      type: "bar",
      data: { labels: stages.map((s) => s.name.split(" —")[0]), datasets: ds },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { labels: { boxWidth: 12, font: { size: 11 } } } },
        scales: { x: { grid: { display: false } }, y: { grid: { color: "#EEF1F5" } } },
      },
    });

    return () => { Object.values(charts.current).forEach((c) => c && c.destroy()); charts.current = {}; };
  }, [data, D]);

  if (!data || !D) {
    return (
      <div className="leadpulse" data-testid="kpi-overview-page">
        <div className="lp-loading">Loading Lead Pulse dashboard…</div>
      </div>
    );
  }

  const { total, dayLbl, monLbl } = D;
  const cur = data.is_current;

  const StageTable = ({ s }) => (
    <div className="stage" data-testid={`kpi-stage-${s.key}`}>
      <div className="stage-head" style={{ background: s.hex }}>
        <h3>{s.name}</h3>
        <div className="mini num">{dayLbl} {fmt(s.totals.ftd)} · {monLbl} {fmt(s.totals.mtd)} · YTD {fmt(s.totals.ytd)}</div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Disposition</th>
            <th>{dayLbl}</th><th>% {dayLbl}</th>
            <th>{monLbl}</th><th>% {monLbl}</th>
            <th className="ytd">YTD</th><th className="ytd">% YTD</th>
          </tr>
        </thead>
        <tbody>
          {s.rows.map((r) => (
            <tr key={r.name}>
              <td>{r.name}</td>
              <td className="num">{fmt(r.ftd)}</td><td className="pct num">{pctStr(r.ftd, total.ftd)}</td>
              <td className="num">{fmt(r.mtd)}</td><td className="pct num">{pctStr(r.mtd, total.mtd)}</td>
              <td className="num ytd">{fmt(r.ytd)}</td><td className="pct num ytd">{pctStr(r.ytd, total.ytd)}</td>
            </tr>
          ))}
          <tr className="total">
            <td>Total</td>
            <td className="num">{fmt(s.totals.ftd)}</td><td className="num">{pctStr(s.totals.ftd, total.ftd)}</td>
            <td className="num">{fmt(s.totals.mtd)}</td><td className="num">{pctStr(s.totals.mtd, total.mtd)}</td>
            <td className="num ytd">{fmt(s.totals.ytd)}</td><td className="num ytd">{pctStr(s.totals.ytd, total.ytd)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );

  const funnelData = D.funnel[funnelMode];
  const funnelBase = funnelData[0][1] || 1;

  return (
    <div className="leadpulse" data-testid="kpi-overview-page">
      {/* top bar */}
      <div className="topbar">
        <div>
          <h1>Lead Pulse · Performance Dashboard <span className="clock">({clock})</span></h1>
          <div className="sub">
            {cur
              ? `FTD = today · MTD = 01 ${data.month.slice(5)} – today · YTD = 01 Jan – today · % against total leads of that period`
              : `Viewing full month ${data.months.find((m) => m.value === data.month)?.label || data.month} · Avg/Day = month total ÷ ${data.days_in_month} days · YTD = 01 Jan – end of month`}
          </div>
        </div>
        <div className="topcontrols">
          <div className="monthpick">
            <label htmlFor="kpi-month">Month</label>
            <select id="kpi-month" data-testid="kpi-month-select" value={data.month}
              onChange={(e) => setMonth(e.target.value)}>
              {data.months.map((m) => (
                <option key={m.value} value={m.value}>{m.label}{m.current ? " (current)" : ""}</option>
              ))}
            </select>
          </div>
          <div className="daychip">
            <div>{cur ? "FTD" : "Avg/Day"} <b className="num">{fmt(total.ftd)}</b></div>
            <div>{monLbl} <b className="num">{fmt(total.mtd)}</b></div>
            <div>YTD <b className="num">{fmt(total.ytd)}</b></div>
          </div>
        </div>
      </div>

      {!cur && (
        <div className="viewnote" data-testid="kpi-closed-month-note">
          Viewing closed month: {data.months.find((m) => m.value === data.month)?.label || data.month} (full-month totals).
          FTD is replaced by the month's daily average. Switch back to the current month for live today's data.
        </div>
      )}

      {/* KPI strip */}
      <div className="kpis">
        {D.kpis.map((k, i) => (
          <div className="kpi" style={{ "--k": k.k }} key={i} data-testid={`kpi-box-${i}`}>
            <div className="label">{k.label}</div>
            <div className="big num">{fmt(k.f)}</div>
            <div className="cmp">{monLbl} <b className="num">{fmt(k.m)}</b> · YTD <b className="num">{fmt(k.y)}</b></div>
          </div>
        ))}
      </div>

      {/* pipeline pulse */}
      <div className="pulse">
        <h2>Pipeline pulse — where every lead sits</h2>
        <div className="hint">One bar = 100% of leads for the period. Segment width = share of leads in that stage.</div>
        {[["ftd", cur ? "FTD" : "Avg/Day"], ["mtd", monLbl], ["ytd", "YTD"]].map(([f, lbl]) => {
          const base = D.pulseBase(f);
          return (
            <div className="pulse-row" key={f}>
              <div className="tag">{lbl}</div>
              <div className="bar">
                {data.stages.map((s) => {
                  const v = s.totals[f];
                  const p = (v / base) * 100;
                  return (
                    <div className="seg" key={s.key} style={{ width: `${p}%`, background: s.hex }}
                      title={`${s.name}: ${fmt(v)} (${pctStr(v, base)})`}>
                      <span>{p > 9 ? `${s.name.split(" ")[0]} ${pctStr(v, base)}` : ""}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
        <div className="legend">
          {data.stages.map((s) => (
            <span key={s.key}><i style={{ background: s.hex }} />{s.name}</span>
          ))}
        </div>
      </div>

      {/* main grid */}
      <div className="grid">
        <div className="col">
          {/* valid leads */}
          <div className="valid" data-testid="kpi-valid">
            <div className="valid-head">
              <div className="vt">
                <span className="dot" />
                <div>
                  <h3>VALID LEADS</h3>
                  <div className="logic">Call back for appointment + OPD Booked + OPD Done + Valid Not Interested</div>
                </div>
              </div>
              <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <span className="valid-badge num">{monLbl} {fmt(D.valid.mtd)}</span>
                <span className="valid-badge num" style={{ background: "#B98A1F" }}>YTD {fmt(D.valid.ytd)}</span>
              </span>
            </div>
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>{dayLbl}</th><th>% {dayLbl}</th>
                  <th>{monLbl}</th><th>% {monLbl}</th>
                  <th className="ytd">YTD</th><th className="ytd">% YTD</th>
                </tr>
              </thead>
              <tbody>
                <tr className="total">
                  <td>Total Valid Leads</td>
                  <td className="num">{fmt(D.valid.ftd)}</td><td className="num">{pctStr(D.valid.ftd, total.ftd)}</td>
                  <td className="num">{fmt(D.valid.mtd)}</td><td className="num">{pctStr(D.valid.mtd, total.mtd)}</td>
                  <td className="num ytd">{fmt(D.valid.ytd)}</td><td className="num ytd">{pctStr(D.valid.ytd, total.ytd)}</td>
                </tr>
              </tbody>
            </table>
          </div>

          {data.stages.map((s) => <StageTable key={s.key} s={s} />)}
        </div>

        <div className="col">
          {/* conversion metrics */}
          <div className="card">
            <h3>Conversion Metrics</h3>
            <div className="hint">Step-to-step conversion rates (cumulative) for {cur ? "the month" : data.month} and the year.</div>
            <table className="conv">
              <thead><tr><th>Conversion Metrics</th><th>{monLbl}</th><th>YTD</th></tr></thead>
              <tbody>
                {D.conversion.map((r) => (
                  <tr key={r[0]}><td>{r[0]}</td><td className="mtd num">{r[1]}%</td><td className="ytdc num">{r[2]}%</td></tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* funnel */}
          <div className="card">
            <h3>Conversion funnel</h3>
            <div className="hint">Cumulative — each step includes everyone who reached it or went further.</div>
            <div className="toggle">
              {[["ftd", cur ? "FTD" : "Avg/Day"], ["mtd", monLbl], ["ytd", "YTD"]].map(([m, lbl]) => (
                <button key={m} data-testid={`kpi-funnel-${m}`} className={funnelMode === m ? "active" : ""}
                  onClick={() => setFunnelMode(m)}>{lbl}</button>
              ))}
            </div>
            <div>
              {funnelData.map((step, i) => {
                const conv = i ? `${Math.round((step[1] / (funnelData[i - 1][1] || 1)) * 100)}% of previous step` : "100%";
                return (
                  <div className="fstep" key={step[0]}>
                    <div className="frow"><span>{step[0]}</span><b className="num">{fmt(step[1])} · {pctStr(step[1], funnelBase)}</b></div>
                    <div className="ftrack"><i style={{ width: `${Math.max((step[1] / funnelBase) * 100, 1.2)}%` }} /></div>
                    <div className="fdrop">{conv}</div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* donut */}
          <div className="card">
            <h3>Stage mix — {data.months.find((m) => m.value === data.month)?.label || data.month}</h3>
            <div className="hint">Share of the selected month's leads by stage.</div>
            <div className="chartbox" style={{ height: 230 }}><canvas ref={donutRef} /></div>
          </div>

          {/* top closed reasons */}
          <div className="card">
            <h3>Top closed reasons — {data.months.find((m) => m.value === data.month)?.label || data.month}</h3>
            <div className="hint">Why leads are lost. Fix the top 3 first.</div>
            <div className="chartbox" style={{ height: 320 }}><canvas ref={closedRef} /></div>
          </div>

          {/* daily pace */}
          <div className="card">
            <h3>{cur ? "FTD vs MTD daily average" : `Daily average by stage — ${data.month}`}</h3>
            <div className="hint">{cur ? "Today's stage counts vs the month's per-day average." : "Per-day average lead counts vs previous month."}</div>
            <div className="chartbox" style={{ height: 220 }}><canvas ref={paceRef} /></div>
          </div>
        </div>
      </div>

      <div className="footnote">Live data · All periods recalculate when the month filter changes · Auto-refresh every 5 min (current month)</div>
    </div>
  );
}
