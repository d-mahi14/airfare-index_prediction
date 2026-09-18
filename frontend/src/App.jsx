import { useState, useEffect, useCallback } from 'react'

// ─── MoSPI reference data (from mospi_airfare.csv) ───────────────────────────
const MOSPI_DATA = [
  { year: 2025, month: 'Jan', index: 111.31, inflation: null },
  { year: 2025, month: 'Feb', index: 128.31, inflation: null },
  { year: 2025, month: 'Mar', index: 105.51, inflation: null },
  { year: 2025, month: 'Apr', index: 106.81, inflation: null },
  { year: 2025, month: 'May', index: 108.50, inflation: null },
  { year: 2025, month: 'Jun', index: 107.52, inflation: null },
  { year: 2025, month: 'Jul', index: 101.25, inflation: null },
  { year: 2025, month: 'Aug', index: 110.16, inflation: null },
  { year: 2025, month: 'Sep', index: 102.46, inflation: null },
  { year: 2025, month: 'Oct', index: 110.62, inflation: null },
  { year: 2025, month: 'Nov', index: 111.39, inflation: null },
  { year: 2025, month: 'Dec', index: 117.73, inflation: null },
  { year: 2026, month: 'Jan', index: 114.80, inflation: 3.13 },
  { year: 2026, month: 'Feb', index: 116.99, inflation: -8.82 },
  { year: 2026, month: 'Mar', index: 115.52, inflation: 9.48 },
  { year: 2026, month: 'Apr', index: 117.01, inflation: 9.55 },
  { year: 2026, month: 'May', index: 122.61, inflation: 13.01 },
  { year: 2026, month: 'Jun', index: 120.55, inflation: 12.12 },
  { year: 2026, month: 'Jul', index: 119.60, inflation: 18.12 },
  { year: 2026, month: 'Aug', index: 127.20, inflation: 15.47 },
]

// ─── Synthetic route data (mock until live backend) ───────────────────────────
const ROUTE_DATA = [
  { route: 'BOM-DEL', name: 'Mumbai→Delhi',    apix: 121.4, prev: 118.7, fare: 5947, trend: 'up',   status: 'active' },
  { route: 'DEL-BOM', name: 'Delhi→Mumbai',    apix: 119.8, prev: 121.2, fare: 5480, trend: 'down', status: 'active' },
  { route: 'BOM-BLR', name: 'Mumbai→Bengaluru',apix: 114.2, prev: 113.0, fare: 4320, trend: 'up',   status: 'active' },
  { route: 'DEL-BLR', name: 'Delhi→Bengaluru', apix: 116.9, prev: 116.9, fare: 6100, trend: 'flat', status: 'active' },
  { route: 'BOM-HYD', name: 'Mumbai→Hyderabad',apix: null,  prev: null,  fare: null, trend: null,  status: 'pending' },
  { route: 'DEL-MAA', name: 'Delhi→Chennai',   apix: null,  prev: null,  fare: null, trend: null,  status: 'pending' },
]

const AIRLINE_DATA = [
  { name: 'IndiGo',           iata: '6E', fare: 5947, share: 42, color: '#3b82f6' },
  { name: 'Air India',        iata: 'AI', fare: 4661, share: 28, color: '#8b5cf6' },
  { name: 'SpiceJet',         iata: 'SG', fare: 9947, share: 16, color: '#f59e0b' },
  { name: 'Akasa Air',        iata: 'QP', fare: 9912, share: 14, color: '#10b981' },
]

const LEAD_DATA = {
  routes: ['BOM-DEL','DEL-BOM','BOM-BLR','DEL-BLR'],
  leads:  ['T+1','T+7','T+15','T+30','T+45'],
  values: [
    [9200, 5947, 4800, 4200, 3800],
    [8800, 5480, 4600, 4100, 3700],
    [7200, 4320, 3900, 3600, 3300],
    [9800, 6100, 5200, 4700, 4300],
  ],
}

function fareBgColor(val, min, max) {
  const pct = (val - min) / (max - min)
  if (pct < 0.33) return 'rgba(16,185,129,0.18)'
  if (pct < 0.66) return 'rgba(245,158,11,0.18)'
  return 'rgba(239,68,68,0.18)'
}

function fareTxtColor(val, min, max) {
  const pct = (val - min) / (max - min)
  if (pct < 0.33) return '#10b981'
  if (pct < 0.66) return '#f59e0b'
  return '#ef4444'
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function Header({ apiHealth, currentTime }) {
  return (
    <header className="header">
      <a className="header-logo" href="/">
        <div className="logo-badge">Ai</div>
        <div>
          <div className="logo-text">APIx Dashboard</div>
          <div className="logo-sub">Indian Airfare Price Index</div>
        </div>
      </a>
      <div className="header-spacer" />
      <div className={`status-pill ${apiHealth === 'healthy' ? 'live' : 'offline'}`}>
        <span className="status-dot" />
        {apiHealth === 'healthy' ? 'API Live' : 'API Offline'}
      </div>
      <div className="header-time">{currentTime}</div>
    </header>
  )
}

function Sidebar({ activeNav, setActiveNav }) {
  const navItems = [
    { id: 'overview',  icon: '◈', label: 'Overview' },
    { id: 'routes',    icon: '⊹', label: 'Routes',    badge: '4' },
    { id: 'airlines',  icon: '◎', label: 'Airlines',  badge: '4' },
    { id: 'leadtime',  icon: '⊷', label: 'Lead Time' },
    { id: 'mospi',     icon: '≡', label: 'MoSPI Benchmark' },
    { id: 'collector', icon: '⬡', label: 'Collector Status' },
  ]
  return (
    <nav className="sidebar">
      <div className="nav-section-label">Navigation</div>
      {navItems.map(item => (
        <div
          key={item.id}
          className={`nav-item ${activeNav === item.id ? 'active' : ''}`}
          onClick={() => setActiveNav(item.id)}
        >
          <span className="nav-icon">{item.icon}</span>
          {item.label}
          {item.badge && <span className="nav-badge">{item.badge}</span>}
        </div>
      ))}
    </nav>
  )
}

function KpiCards({ apiHealth }) {
  const currentApix = 121.4
  const prevApix = 118.7
  const change = ((currentApix - prevApix) / prevApix * 100).toFixed(2)

  return (
    <div className="kpi-grid fade-in">
      <div className="kpi-card blue">
        <div className="kpi-label">⬡ Today's APIx</div>
        <div className="kpi-value blue">{currentApix}</div>
        <div className={`kpi-change ${change > 0 ? 'up' : 'down'}`}>
          {change > 0 ? '▲' : '▼'} {Math.abs(change)}% vs yesterday
        </div>
        <div className="kpi-meta">Base year: 2024 = 100</div>
      </div>

      <div className="kpi-card green">
        <div className="kpi-label">✦ Observations Today</div>
        <div className="kpi-value green">16</div>
        <div className="kpi-change flat">4 routes × 4 airlines</div>
        <div className="kpi-meta">All valid, 0 rejected</div>
      </div>

      <div className="kpi-card purple">
        <div className="kpi-label">◎ MoSPI (Aug 2026)</div>
        <div className="kpi-value purple">127.2</div>
        <div className="kpi-change up">▲ 15.47% YoY</div>
        <div className="kpi-meta">Official CPI Airfare sub-index</div>
      </div>

      <div className="kpi-card orange">
        <div className="kpi-label">⊹ Active Routes</div>
        <div className="kpi-value orange">4</div>
        <div className="kpi-change flat">2 pending activation</div>
        <div className="kpi-meta">BOM-DEL, DEL-BOM, BOM-BLR, DEL-BLR</div>
      </div>
    </div>
  )
}

// APIx trend chart using SVG
function ApixTrendPanel() {
  const data = MOSPI_DATA.slice(-8)
  const vals = data.map(d => d.index)
  const minV = Math.min(...vals) - 2
  const maxV = Math.max(...vals) + 2
  const w = 480, h = 140, pad = { l: 8, r: 8, t: 10, b: 24 }

  const px = (i) => pad.l + (i / (vals.length - 1)) * (w - pad.l - pad.r)
  const py = (v) => h - pad.b - ((v - minV) / (maxV - minV)) * (h - pad.t - pad.b)

  const path = vals.map((v, i) => `${i === 0 ? 'M' : 'L'}${px(i)},${py(v)}`).join(' ')
  const area = path + ` L${px(vals.length - 1)},${h - pad.b} L${px(0)},${h - pad.b} Z`

  return (
    <div className="panel col-8 fade-in">
      <div className="panel-header">
        <div className="panel-title"><span className="panel-icon">◈</span> APIx / MoSPI Trend (last 8 months)</div>
        <span className="badge badge-blue">Base 2024=100</span>
      </div>
      <div className="panel-body">
        <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', height: 'auto', overflow: 'visible' }}>
          <defs>
            <linearGradient id="lineGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
            </linearGradient>
          </defs>
          {/* Grid lines */}
          {[minV, (minV+maxV)/2, maxV].map((v, i) => (
            <line key={i}
              x1={pad.l} y1={py(v)} x2={w - pad.r} y2={py(v)}
              stroke="rgba(255,255,255,0.04)" strokeWidth="1" />
          ))}
          {/* Area fill */}
          <path d={area} fill="url(#lineGrad)" />
          {/* Line */}
          <path d={path} fill="none" stroke="#3b82f6" strokeWidth="2.5"
            strokeLinejoin="round" strokeLinecap="round" />
          {/* Points */}
          {vals.map((v, i) => (
            <g key={i}>
              <circle cx={px(i)} cy={py(v)} r="4" fill="#080c14" stroke="#3b82f6" strokeWidth="2" />
              <title>{data[i].month} {data[i].year}: {v}</title>
            </g>
          ))}
          {/* X labels */}
          {data.map((d, i) => (
            <text key={i} x={px(i)} y={h - 4} textAnchor="middle"
              fontSize="9" fill="rgba(148,163,184,0.7)">
              {d.month}
            </text>
          ))}
        </svg>
        <div className="disclaimer" style={{ marginTop: 12 }}>
          ⚠ Chart shows official MoSPI CPI Airfare sub-index (base 2024=100) as the benchmark reference.
          Our independent APIx uses a different methodology — do not compare raw levels directly.
        </div>
      </div>
    </div>
  )
}

function RouteIndexPanel() {
  const active = ROUTE_DATA.filter(r => r.status === 'active')
  return (
    <div className="panel col-4 fade-in">
      <div className="panel-header">
        <div className="panel-title"><span className="panel-icon">⊹</span> Route Indices</div>
        <span className="badge badge-green">Live</span>
      </div>
      <div className="panel-body" style={{ padding: '0 0 8px' }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Route</th>
              <th>APIx</th>
              <th>Change</th>
            </tr>
          </thead>
          <tbody>
            {active.map(r => {
              const delta = r.apix - r.prev
              return (
                <tr key={r.route}>
                  <td><span className="route-pill">{r.route}</span></td>
                  <td style={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: '#60a5fa' }}>
                    {r.apix.toFixed(1)}
                  </td>
                  <td className={delta > 0 ? 'change-up' : delta < 0 ? 'change-down' : 'change-flat'}>
                    {delta > 0 ? '+' : ''}{delta.toFixed(1)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function AirlinePanel() {
  const maxFare = Math.max(...AIRLINE_DATA.map(a => a.fare))
  return (
    <div className="panel col-6 fade-in">
      <div className="panel-header">
        <div className="panel-title"><span className="panel-icon">◎</span> Airline Fare Distribution</div>
        <span className="badge badge-purple">BOM-DEL · T+7 · Economy</span>
      </div>
      <div className="panel-body">
        <div className="airline-list">
          {AIRLINE_DATA.map(a => (
            <div key={a.iata} className="airline-row">
              <div className="airline-name">{a.name}</div>
              <div className="airline-bar-wrap">
                <div className="airline-bar"
                  style={{ width: `${(a.fare / maxFare) * 100}%`, background: a.color }} />
              </div>
              <div className="airline-fare">₹{a.fare.toLocaleString('en-IN')}</div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {AIRLINE_DATA.map(a => (
            <span key={a.iata} style={{
              display: 'inline-flex', alignItems: 'center', gap: 5,
              fontSize: 11, color: 'var(--text-secondary)'
            }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: a.color, display: 'inline-block' }} />
              {a.name} {a.share}%
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

function LeadTimePanel() {
  const allVals = LEAD_DATA.values.flat()
  const minV = Math.min(...allVals)
  const maxV = Math.max(...allVals)

  return (
    <div className="panel col-6 fade-in">
      <div className="panel-header">
        <div className="panel-title"><span className="panel-icon">⊷</span> Lead-Time Fare Heatmap</div>
        <span className="badge badge-orange">Economy · INR</span>
      </div>
      <div className="panel-body">
        <div className="leadtime-grid">
          <div className="lt-header"></div>
          {LEAD_DATA.leads.map(l => (
            <div key={l} className="lt-header">{l}</div>
          ))}
          {LEAD_DATA.routes.map((route, ri) => (
            <>
              <div key={route} className="lt-route">{route}</div>
              {LEAD_DATA.values[ri].map((v, li) => (
                <div key={li} className="lt-cell"
                  style={{ background: fareBgColor(v, minV, maxV), color: fareTxtColor(v, minV, maxV) }}>
                  {(v/1000).toFixed(1)}k
                </div>
              ))}
            </>
          ))}
        </div>
        <div style={{ marginTop: 12, fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.5 }}>
          🟢 Low  🟡 Mid  🔴 High · Values in INR thousands · Lead = days before departure
        </div>
      </div>
    </div>
  )
}

function MoSPIPanel() {
  const recent = MOSPI_DATA.slice(-8).reverse()
  const maxIdx = Math.max(...recent.map(d => d.index))

  return (
    <div className="panel col-12 fade-in">
      <div className="panel-header">
        <div className="panel-title"><span className="panel-icon">≡</span> MoSPI CPI Airfare Benchmark</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <span className="badge badge-orange">Official Reference Only</span>
          <span className="badge badge-blue">Base 2024=100</span>
        </div>
      </div>
      <div className="panel-body">
        <div className="disclaimer" style={{ marginBottom: 16 }}>
          ℹ This is the <strong>official MoSPI CPI Urban Airfare sub-index</strong> (code 07.3.3.1.2.01, weight 0.01784 in CPI basket).
          It is NOT raw fare data. Our APIx is independently constructed from direct airfare observations.
          Index levels should NOT be directly compared — use percentage-change comparison for analysis.
        </div>
        <div className="mospi-compare">
          {recent.map((d, i) => (
            <div key={i} className="mospi-row">
              <div className="mospi-month">{d.month} {d.year}</div>
              <div className="mospi-bar-wrap">
                <div className="mospi-bar" style={{ width: `${(d.index / maxIdx) * 100}%` }} />
              </div>
              <div className="mospi-val">{d.index.toFixed(2)}</div>
              <div className={`mospi-infl ${d.inflation === null ? 'change-flat' : d.inflation > 0 ? 'change-up' : 'change-down'}`}>
                {d.inflation !== null ? `${d.inflation > 0 ? '+' : ''}${d.inflation}%` : '—'}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function CollectorPanel({ apiHealth }) {
  const collStats = [
    { label: 'Valid observations', count: 16, pct: 100, color: '#10b981' },
    { label: 'Rejected',           count: 0,  pct: 0,   color: '#ef4444' },
    { label: 'Duplicates',         count: 0,  pct: 0,   color: '#f59e0b' },
  ]

  return (
    <div className="panel col-12 fade-in">
      <div className="panel-header">
        <div className="panel-title"><span className="panel-icon">⬡</span> Data Collector Status</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <span className={`badge ${apiHealth === 'healthy' ? 'badge-green' : 'badge-red'}`}>
            {apiHealth === 'healthy' ? '● Backend Connected' : '● Backend Offline'}
          </span>
          <span className="badge badge-orange">MockCollector · Phase 1</span>
        </div>
      </div>
      <div className="panel-body">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 24 }}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 12 }}>
              Last Collection Run
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[
                ['Collector',    'MockCollector (synthetic)'],
                ['Route',        'BOM → DEL'],
                ['Travel date',  '2026-09-25 (T+7)'],
                ['Lead days',    '7'],
                ['Run ID',       '613f6679-b79e'],
                ['Timestamp',    '2026-09-18 10:23 UTC'],
              ].map(([k, v]) => (
                <div key={k} style={{ display: 'flex', gap: 12, fontSize: 12 }}>
                  <span style={{ color: 'var(--text-muted)', minWidth: 100 }}>{k}</span>
                  <span style={{ color: 'var(--text-primary)', fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>{v}</span>
                </div>
              ))}
            </div>
          </div>

          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 12 }}>
              Collection Quality
            </div>
            <div className="status-grid">
              {collStats.map(s => (
                <div key={s.label} className="status-row">
                  <div className="status-label">{s.label}</div>
                  <div className="status-bar-wrap">
                    <div className="status-bar"
                      style={{ width: `${s.pct || 3}%`, background: s.color }} />
                  </div>
                  <div className="status-count">{s.count}</div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 12 }}>
              Ethical Scraping Policy
            </div>
            {[
              ['✅', 'MockCollector — no live requests'],
              ['✅', 'Raw JSON saved to data/raw/'],
              ['✅', 'All observations auditable'],
              ['✅', 'No CAPTCHA bypass'],
              ['✅', 'No bot evasion'],
              ['⏳', 'Live collector — Phase 9'],
            ].map(([icon, txt]) => (
              <div key={txt} style={{ display: 'flex', gap: 8, fontSize: 12, marginBottom: 5 }}>
                <span>{icon}</span>
                <span style={{ color: 'var(--text-secondary)' }}>{txt}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [activeNav, setActiveNav] = useState('overview')
  const [apiHealth, setApiHealth] = useState('unknown')
  const [currentTime, setCurrentTime] = useState('')

  // Poll backend health
  const checkHealth = useCallback(async () => {
    try {
      const res = await fetch('http://localhost:8000/api/health', { signal: AbortSignal.timeout(3000) })
      if (res.ok) {
        const data = await res.json()
        setApiHealth(data.status)
      } else {
        setApiHealth('degraded')
      }
    } catch {
      setApiHealth('offline')
    }
  }, [])

  useEffect(() => {
    checkHealth()
    const healthTimer = setInterval(checkHealth, 15000)
    const clockTimer = setInterval(() => {
      setCurrentTime(new Date().toLocaleTimeString('en-IN', {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        timeZone: 'Asia/Kolkata'
      }) + ' IST')
    }, 1000)
    return () => { clearInterval(healthTimer); clearInterval(clockTimer) }
  }, [checkHealth])

  const renderContent = () => {
    switch (activeNav) {
      case 'overview':
        return (
          <>
            <KpiCards apiHealth={apiHealth} />
            <div className="panel-grid">
              <ApixTrendPanel />
              <RouteIndexPanel />
              <AirlinePanel />
              <LeadTimePanel />
            </div>
          </>
        )
      case 'routes':
        return (
          <div className="panel-grid">
            <div className="panel col-12 fade-in">
              <div className="panel-header">
                <div className="panel-title"><span className="panel-icon">⊹</span> All Routes</div>
              </div>
              <div className="panel-body" style={{ padding: 0 }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Route</th><th>Name</th><th>APIx</th><th>Prev</th>
                      <th>Change</th><th>Avg Fare (INR)</th><th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ROUTE_DATA.map(r => {
                      const delta = r.apix && r.prev ? (r.apix - r.prev).toFixed(1) : null
                      return (
                        <tr key={r.route}>
                          <td><span className="route-pill">{r.route}</span></td>
                          <td style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{r.name}</td>
                          <td style={{ fontWeight: 700, color: '#60a5fa', fontVariantNumeric: 'tabular-nums' }}>
                            {r.apix?.toFixed(1) ?? '—'}
                          </td>
                          <td style={{ color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
                            {r.prev?.toFixed(1) ?? '—'}
                          </td>
                          <td className={!delta ? 'change-flat' : delta > 0 ? 'change-up' : 'change-down'}>
                            {delta ? `${delta > 0 ? '+' : ''}${delta}` : '—'}
                          </td>
                          <td style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 12 }}>
                            {r.fare ? `₹${r.fare.toLocaleString('en-IN')}` : '—'}
                          </td>
                          <td>
                            <span className={`badge ${r.status === 'active' ? 'badge-green' : 'badge-orange'}`}>
                              {r.status}
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
            <LeadTimePanel />
          </div>
        )
      case 'airlines':
        return (
          <div className="panel-grid">
            <AirlinePanel />
            <div className="panel col-6 fade-in">
              <div className="panel-header">
                <div className="panel-title"><span className="panel-icon">◎</span> Airline Summary Table</div>
              </div>
              <div className="panel-body" style={{ padding: 0 }}>
                <table className="data-table">
                  <thead>
                    <tr><th>Airline</th><th>IATA</th><th>Avg Fare</th><th>Market Share</th></tr>
                  </thead>
                  <tbody>
                    {AIRLINE_DATA.map(a => (
                      <tr key={a.iata}>
                        <td>{a.name}</td>
                        <td style={{ fontFamily: "'JetBrains Mono',monospace" }}>{a.iata}</td>
                        <td style={{ fontFamily: "'JetBrains Mono',monospace" }}>₹{a.fare.toLocaleString('en-IN')}</td>
                        <td>
                          <div style={{ display:'flex', alignItems:'center', gap: 8 }}>
                            <div style={{ flex:1, height:4, background:'rgba(255,255,255,0.05)', borderRadius:2, overflow:'hidden' }}>
                              <div style={{ width:`${a.share}%`, height:'100%', background:a.color, borderRadius:2 }} />
                            </div>
                            <span style={{ fontSize:11, fontFamily:"'JetBrains Mono',monospace", color:'var(--text-secondary)' }}>
                              {a.share}%
                            </span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )
      case 'leadtime':
        return <div className="panel-grid"><LeadTimePanel /></div>
      case 'mospi':
        return <div className="panel-grid"><MoSPIPanel /></div>
      case 'collector':
        return <div className="panel-grid"><CollectorPanel apiHealth={apiHealth} /></div>
      default:
        return null
    }
  }

  const pageTitles = {
    overview:  ['Overview', 'Real-time APIx summary and key metrics'],
    routes:    ['Route Indices', 'Per-route APIx values and lead-time heatmap'],
    airlines:  ['Airline Analysis', 'Fare distribution across carriers'],
    leadtime:  ['Lead-Time Analysis', 'How fares change with booking horizon'],
    mospi:     ['MoSPI Benchmark', 'Official CPI Airfare reference comparison'],
    collector: ['Collector Status', 'Data collection audit and pipeline health'],
  }

  const [title, subtitle] = pageTitles[activeNav] || ['Dashboard', '']

  return (
    <div className="app-shell">
      <Header apiHealth={apiHealth} currentTime={currentTime} />
      <Sidebar activeNav={activeNav} setActiveNav={setActiveNav} />
      <main className="main-content">
        <div className="page-header">
          <div>
            <h1 className="page-title">{title}</h1>
            <p className="page-subtitle">{subtitle}</p>
          </div>
          <div className="page-actions">
            <button className="btn btn-outline" onClick={checkHealth}>↻ Refresh</button>
            <button className="btn btn-primary">▷ Run Collector</button>
          </div>
        </div>
        {renderContent()}
      </main>
    </div>
  )
}
