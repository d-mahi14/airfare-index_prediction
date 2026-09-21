import { useState, useEffect, useCallback } from 'react'

const AIRPORTS = [
  { code: 'DEL', city: 'Delhi', name: 'Indira Gandhi Intl (DEL)', covered: true },
  { code: 'BOM', city: 'Mumbai', name: 'Chhatrapati Shivaji Maharaj (BOM)', covered: true },
  { code: 'BLR', city: 'Bengaluru', name: 'Kempegowda Intl (BLR)', covered: true },
  { code: 'HYD', city: 'Hyderabad', name: 'Rajiv Gandhi Intl (HYD)', covered: true },
  { code: 'MAA', city: 'Chennai', name: 'Chennai Intl (MAA)', covered: true },
  { code: 'CCU', city: 'Kolkata', name: 'Netaji Subhash Chandra Bose (CCU)', covered: false },
  { code: 'GOI', city: 'Goa', name: 'Dabolim / Mopa (GOI)', covered: false },
  { code: 'AMD', city: 'Ahmedabad', name: 'Sardar Vallabhbhai Patel (AMD)', covered: true },
  { code: 'PNQ', city: 'Pune', name: 'Pune Airport (PNQ)', covered: true },
  { code: 'COK', city: 'Kochi', name: 'Cochin Intl (COK)', covered: true },
  { code: 'JAI', city: 'Jaipur', name: 'Jaipur Intl (JAI)', covered: true },
  { code: 'LKO', city: 'Lucknow', name: 'Chaudhary Charan Singh (LKO)', covered: true },
  { code: 'PAT', city: 'Patna', name: 'Jay Prakash Narayan (PAT)', covered: true },
  { code: 'IXC', city: 'Chandigarh', name: 'Shaheed Bhagat Singh (IXC)', covered: false },
  { code: 'GAU', city: 'Guwahati', name: 'Lokpriya Gopinath Bordoloi (GAU)', covered: false },
  { code: 'TRV', city: 'Thiruvananthapuram', name: 'Trivandrum Intl (TRV)', covered: false },
]

const QUICK_ROUTES = [
  { origin: 'DEL', destination: 'BOM', label: 'DEL ⇄ BOM' },
  { origin: 'BOM', destination: 'DEL', label: 'BOM ⇄ DEL' },
  { origin: 'DEL', destination: 'BLR', label: 'DEL ⇄ BLR' },
  { origin: 'BOM', destination: 'BLR', label: 'BOM ⇄ BLR' },
  { origin: 'DEL', destination: 'HYD', label: 'DEL ⇄ HYD' },
  { origin: 'CCU', destination: 'GOI', label: 'CCU ⇄ GOI (Uncovered)' },
]

const CARRIERS = [
  { code: '', name: 'All Airlines' },
  { code: '6E', name: 'IndiGo (6E)', color: '#3b82f6' },
  { code: 'AI', name: 'Air India (AI)', color: '#8b5cf6' },
  { code: 'QP', name: 'Akasa Air (QP)', color: '#10b981' },
  { code: 'SG', name: 'SpiceJet (SG)', color: '#f59e0b' },
]

const API_BASE_URL = 'http://127.0.0.1:8000'
const DEFAULT_API_KEY = 'apix_dev_key_2024'

export function FareExplorer() {
  const getDefaultDate = () => {
    const d = new Date()
    d.setDate(d.getDate() + 15)
    return d.toISOString().split('T')[0]
  }

  const [origin, setOrigin] = useState('DEL')
  const [destination, setDestination] = useState('BOM')
  const [travelDate, setTravelDate] = useState(getDefaultDate)
  const [carrier, setCarrier] = useState('')
  const [demoMode, setDemoMode] = useState(false)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)
  const [validationError, setValidationError] = useState('')

  const [watchlistStatus, setWatchlistStatus] = useState(null)
  const [selectedBreakup, setSelectedBreakup] = useState(null)

  const executeSearch = useCallback(async (searchOrigin, searchDest, searchDate, searchCarrier, searchDemo) => {
    setValidationError('')
    setError(null)
    setWatchlistStatus(null)

    // Validation checks
    if (!searchOrigin || !searchDest) {
      setValidationError('Please select both an origin and a destination.')
      return
    }
    if (searchOrigin === searchDest) {
      setValidationError('Origin and destination cannot be the same airport.')
      return
    }
    if (!searchDate) {
      setValidationError('Please select a valid travel date.')
      return
    }

    const todayStr = new Date().toISOString().split('T')[0]
    if (searchDate < todayStr) {
      setValidationError('Travel date cannot be in the past. Please select today or a future date.')
      return
    }

    setLoading(true)

    try {
      const queryParams = new URLSearchParams({
        origin: searchOrigin,
        destination: searchDest,
        date: searchDate,
      })

      if (searchCarrier) {
        queryParams.append('carrier', searchCarrier)
      }
      if (searchDemo) {
        queryParams.append('demo_mode', 'true')
      }

      const url = `${API_BASE_URL}/fares/search?${queryParams.toString()}`
      const response = await fetch(url, {
        headers: {
          'X-API-Key': DEFAULT_API_KEY,
          'Accept': 'application/json',
        },
      })

      const json = await response.json()

      if (!response.ok) {
        if (response.status === 404 && json.detail?.status === 'not_covered') {
          setData({
            not_covered: true,
            route_code: json.detail.route_code || `${searchOrigin}-${searchDest}`,
            message: json.detail.message || `Route ${searchOrigin}-${searchDest} is not currently covered in the APIx basket.`,
            watchlist_registered: json.detail.watchlist_registered,
          })
          setWatchlistStatus(json.detail.watchlist_registered ? 'registered' : null)
        } else {
          setError(json.detail?.message || json.detail || `Server returned status ${response.status}`)
          setData(null)
        }
      } else {
        setData(json)
      }
    } catch (err) {
      setError(`Failed to connect to fare service at ${API_BASE_URL}. Ensure backend is running. (${err.message})`)
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial search on mount
  useEffect(() => {
    executeSearch(origin, destination, travelDate, carrier, demoMode)
  }, [executeSearch])

  const handleSearchSubmit = (e) => {
    e.preventDefault()
    executeSearch(origin, destination, travelDate, carrier, demoMode)
  }

  const handleQuickRoute = (r) => {
    setOrigin(r.origin)
    setDestination(r.destination)
    executeSearch(r.origin, r.destination, travelDate, carrier, demoMode)
  }

  const handleSwapAirports = () => {
    const temp = origin
    setOrigin(destination)
    setDestination(temp)
    executeSearch(destination, temp, travelDate, carrier, demoMode)
  }

  const handleTrackRoute = async () => {
    setWatchlistStatus('tracking')
    setTimeout(() => {
      setWatchlistStatus('confirmed')
    }, 400)
  }

  return (
    <div className="fare-explorer-container fade-in">
      {/* ─── Synthetic Demo Mode Banner ─── */}
      {(demoMode || data?.is_synthetic || data?.banner) && (
        <div className="synthetic-banner" role="alert">
          <span className="banner-icon">⚠️</span>
          <div>
            <strong>SYNTHETIC DEMO DATA ACTIVE</strong>
            <span className="banner-sub"> — Showing simulated airfares for development and UI inspection. Not used for official price index calculation.</span>
          </div>
        </div>
      )}

      {/* ─── Search Controls Panel ─── */}
      <div className="panel col-12 search-panel">
        <div className="panel-header">
          <div className="panel-title">
            <span className="panel-icon">✈</span> Observed Fare Explorer
          </div>
          <div className="search-header-tags">
            <label className="demo-toggle-label">
              <input
                type="checkbox"
                checked={demoMode}
                onChange={(e) => {
                  setDemoMode(e.target.checked)
                  executeSearch(origin, destination, travelDate, carrier, e.target.checked)
                }}
              />
              <span className="toggle-custom" />
              <span className="toggle-text">Allow Synthetic Demo Data</span>
            </label>
          </div>
        </div>

        <div className="panel-body">
          {/* Quick Route Chips */}
          <div className="quick-routes-bar">
            <span className="quick-routes-label">Popular Baskets:</span>
            {QUICK_ROUTES.map((r) => (
              <button
                key={`${r.origin}-${r.destination}`}
                type="button"
                className={`quick-route-chip ${origin === r.origin && destination === r.destination ? 'active' : ''}`}
                onClick={() => handleQuickRoute(r)}
              >
                {r.label}
              </button>
            ))}
          </div>

          <form className="search-form" onSubmit={handleSearchSubmit}>
            <div className="form-group">
              <label htmlFor="origin-select">Origin Airport</label>
              <select
                id="origin-select"
                className="form-control"
                value={origin}
                onChange={(e) => setOrigin(e.target.value)}
              >
                {AIRPORTS.map((a) => (
                  <option key={`origin-${a.code}`} value={a.code}>
                    {a.name} {a.covered ? '' : '(Uncovered)'}
                  </option>
                ))}
              </select>
            </div>

            <button
              type="button"
              className="swap-btn"
              title="Swap Origin & Destination"
              onClick={handleSwapAirports}
              aria-label="Swap airports"
            >
              ⇄
            </button>

            <div className="form-group">
              <label htmlFor="dest-select">Destination Airport</label>
              <select
                id="dest-select"
                className="form-control"
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
              >
                {AIRPORTS.map((a) => (
                  <option key={`dest-${a.code}`} value={a.code}>
                    {a.name} {a.covered ? '' : '(Uncovered)'}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="date-input">Travel Date</label>
              <input
                id="date-input"
                type="date"
                className="form-control"
                value={travelDate}
                onChange={(e) => setTravelDate(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label htmlFor="carrier-select">Airline (Optional)</label>
              <select
                id="carrier-select"
                className="form-control"
                value={carrier}
                onChange={(e) => setCarrier(e.target.value)}
              >
                {CARRIERS.map((c) => (
                  <option key={`carrier-${c.code}`} value={c.code}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group form-submit">
              <button type="submit" className="btn btn-primary search-submit-btn" disabled={loading}>
                {loading ? 'Searching...' : '🔍 Search Fares'}
              </button>
            </div>
          </form>

          {/* Validation Error Message */}
          {validationError && (
            <div className="validation-alert" role="alert">
              <span className="alert-icon">⚠️</span> {validationError}
            </div>
          )}
        </div>
      </div>

      {/* ─── Loading State ─── */}
      {loading && (
        <div className="panel col-12 loading-panel">
          <div className="loading-spinner" />
          <div className="loading-text">Validating observed airfare quotes through FareGate...</div>
        </div>
      )}

      {/* ─── General Error State ─── */}
      {!loading && error && (
        <div className="panel col-12 error-panel">
          <div className="error-icon">✕</div>
          <div className="error-title">Query Error</div>
          <div className="error-message">{error}</div>
          <button
            className="btn btn-outline"
            style={{ marginTop: 12 }}
            onClick={() => executeSearch(origin, destination, travelDate, carrier, demoMode)}
          >
            ↻ Retry Query
          </button>
        </div>
      )}

      {/* ─── Uncovered Route / Watchlist State ─── */}
      {!loading && data?.not_covered && (
        <div className="panel col-12 not-covered-panel">
          <div className="not-covered-badge">BASKET NOTICE</div>
          <h2 className="not-covered-title">Route {data.route_code} is Not Covered in the Active Basket</h2>
          <p className="not-covered-desc">
            The APIx domestic index currently monitors the top 20 DGCA route corridors.
            {origin} → {destination} is not in the live collection schedule.
          </p>

          <div className="watchlist-action-box">
            <div className="watchlist-info">
              <span className="watchlist-icon">📋</span>
              <div>
                <strong>Expansion Watchlist Tracking</strong>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                  Requesting this route registers it in the collection expansion candidate list.
                </div>
              </div>
            </div>

            <button
              className="btn btn-primary watchlist-btn"
              onClick={handleTrackRoute}
              disabled={watchlistStatus === 'confirmed'}
            >
              {watchlistStatus === 'confirmed' ? '✓ Tracked on Watchlist' : '★ Track This Route for Expansion'}
            </button>
          </div>

          {watchlistStatus === 'confirmed' && (
            <div className="watchlist-success-note">
              ✓ Route {data.route_code} successfully logged in expansion queue. When compliance permissions allow, this corridor will be evaluated for basket inclusion.
            </div>
          )}
        </div>
      )}

      {/* ─── Successful Fares Data Results ─── */}
      {!loading && data && !data.not_covered && (
        <>
          {/* Estimated Nearest Window Banner */}
          {data.lead_time_position?.is_estimated && (
            <div className="estimated-alert" role="status">
              <span className="estimated-badge">⏱ ESTIMATED WINDOW FALLBACK</span>
              <div className="estimated-text">{data.lead_time_position.explanation}</div>
            </div>
          )}

          {/* Metric Summary Cards */}
          <div className="summary-cards-grid">
            <div className="metric-card">
              <div className="metric-label">Cheapest Observed Fare</div>
              <div className="metric-value price-green">
                {data.summary?.cheapest_fare ? `₹${data.summary.cheapest_fare.toLocaleString('en-IN')}` : '—'}
              </div>
              <div className="metric-sub">Lowest verified non-outlier quote</div>
            </div>

            <div className="metric-card">
              <div className="metric-label">Typical (Median) Fare</div>
              <div className="metric-value price-blue">
                {data.summary?.typical_fare ? `₹${Math.round(data.summary.typical_fare).toLocaleString('en-IN')}` : '—'}
              </div>
              <div className="metric-sub">Central market tendency</div>
            </div>

            <div className="metric-card">
              <div className="metric-label">Lead Horizon</div>
              <div className="metric-value">
                T+{data.lead_time_position?.lead_days ?? '—'}
              </div>
              <div className="metric-sub">
                Target bucket: T+{data.lead_time_position?.target_lead_window ?? '15'} days
              </div>
            </div>

            <div className="metric-card">
              <div className="metric-label">Observation Coverage</div>
              <div className="metric-value">
                {data.summary?.n_flights ?? 0} <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>quotes</span>
              </div>
              <div className="metric-sub">
                Sources: {data.coverage?.active_sources?.join(', ') || 'Compliant Capture'}
              </div>
            </div>
          </div>

          {/* Flights Table */}
          <div className="panel col-12 flights-table-panel">
            <div className="panel-header">
              <div className="panel-title">
                <span className="panel-icon">◈</span> Verified Flight Quotes ({data.flights?.length || 0})
              </div>
              <div className="panel-subtitle-meta">
                {data.route?.origin} → {data.route?.destination} · Travel Date: {data.query?.requested_date}
              </div>
            </div>

            <div className="panel-body" style={{ padding: 0 }}>
              {data.flights?.length === 0 ? (
                <div className="empty-table-state">
                  <div className="empty-icon">✈</div>
                  <div className="empty-title">No Valid Quotes Available</div>
                  <div className="empty-sub">
                    No active observations met FareGate freshness and consistency standards for this query.
                  </div>
                </div>
              ) : (
                <div className="table-responsive">
                  <table className="data-table flights-table">
                    <thead>
                      <tr>
                        <th>Flight</th>
                        <th>Departure</th>
                        <th>Stops & Duration</th>
                        <th>Observed Total</th>
                        <th>Fare Breakdown</th>
                        <th>Confidence</th>
                        <th>Source & Freshness</th>
                        <th>Gate Warnings</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.flights.map((f, idx) => {
                        const carrierColor =
                          f.airline_iata === '6E' ? '#3b82f6' :
                          f.airline_iata === 'AI' ? '#8b5cf6' :
                          f.airline_iata === 'QP' ? '#10b981' :
                          f.airline_iata === 'SG' ? '#f59e0b' : '#94a3b8'

                        return (
                          <tr key={`${f.flight_number}-${idx}`} className="flight-row">
                            <td>
                              <div className="flight-carrier-cell">
                                <span className="carrier-badge" style={{ backgroundColor: `${carrierColor}25`, color: carrierColor, borderColor: `${carrierColor}50` }}>
                                  {f.airline_iata || 'AIR'}
                                </span>
                                <div>
                                  <div className="flight-num">{f.flight_number}</div>
                                  <div className="airline-name">{f.airline_name}</div>
                                </div>
                              </div>
                            </td>

                            <td>
                              <div className="dep-time-val">{f.dep_time ? f.dep_time.slice(0, 5) : '—'}</div>
                              <div className="dep-band-tag">{f.dep_band || 'standard'}</div>
                            </td>

                            <td>
                              <div className="stops-val">{f.stops === 0 ? 'Non-stop' : `${f.stops} stop(s)`}</div>
                              <div className="duration-val">{f.duration_min ? `${Math.floor(f.duration_min / 60)}h ${f.duration_min % 60}m` : '—'}</div>
                            </td>

                            <td>
                              <div className="total-fare-highlight">
                                ₹{f.pricing?.total_fare?.toLocaleString('en-IN')}
                              </div>
                              <div className="fare-class-tag">{f.fare_class || 'Economy'}</div>
                            </td>

                            <td>
                              <button
                                type="button"
                                className="breakup-preview-btn"
                                onClick={() => setSelectedBreakup(selectedBreakup === idx ? null : idx)}
                              >
                                {selectedBreakup === idx ? 'Hide Breakup' : 'View Breakup ▾'}
                              </button>

                              {selectedBreakup === idx && (
                                <div className="breakup-popover">
                                  <div className="breakup-row">
                                    <span>Base Fare:</span>
                                    <strong>₹{f.pricing?.base_fare?.toLocaleString('en-IN') || '—'}</strong>
                                  </div>
                                  <div className="breakup-row">
                                    <span>GST / Taxes:</span>
                                    <span>₹{f.pricing?.taxes?.toLocaleString('en-IN') || '0'}</span>
                                  </div>
                                  <div className="breakup-row">
                                    <span>UDF & PSF:</span>
                                    <span>₹{f.pricing?.udf_psf?.toLocaleString('en-IN') || '0'}</span>
                                  </div>
                                  <div className="breakup-row">
                                    <span>Convenience Fee:</span>
                                    <span>₹{f.pricing?.convenience_fee?.toLocaleString('en-IN') || '0'}</span>
                                  </div>
                                  <div className="breakup-row total-row">
                                    <span>Total Payable:</span>
                                    <strong>₹{f.pricing?.total_fare?.toLocaleString('en-IN')}</strong>
                                  </div>
                                </div>
                              )}
                            </td>

                            <td>
                              <span className={`confidence-pill confidence-${f.confidence || 'medium'}`}>
                                ● {f.confidence?.toUpperCase() || 'MEDIUM'}
                              </span>
                            </td>

                            <td>
                              <div className="source-tag">{f.sources?.join(', ') || 'Recorded'}</div>
                              <div className="age-tag">{f.age_minutes != null ? `${f.age_minutes}m ago` : 'verified'}</div>
                            </td>

                            <td>
                              {(!f.warnings || f.warnings.length === 0) ? (
                                <span className="warning-clean">✓ Passed</span>
                              ) : (
                                <div className="warnings-list">
                                  {f.warnings.map((w, wIdx) => (
                                    <span key={wIdx} className="warning-chip">
                                      {w.replace(/_/g, ' ')}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          {/* ─── Observed Quotes Disclaimer ─── */}
          <div className="fare-disclaimer-box">
            <span className="disclaimer-icon">ℹ️</span>
            <div>
              <strong>Observed Data Disclaimer:</strong>
              <div style={{ color: 'var(--text-secondary)', marginTop: 2 }}>
                Displayed fares represent independent, observed airline market quotes captured for price index construction and research.
                They are historical and current empirical samples, not direct commercial booking offers or fare guarantees.
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
