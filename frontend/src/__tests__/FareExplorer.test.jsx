import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { FareExplorer } from '../components/FareExplorer'

describe('FareExplorer Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renders search form inputs and disclaimer', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'ok',
          query: { origin: 'DEL', destination: 'BOM', requested_date: '2026-10-06' },
          route: { origin: 'DEL', destination: 'BOM', route_code: 'DEL-BOM' },
          lead_time_position: { lead_days: 15, target_lead_window: 15, is_estimated: false },
          summary: { cheapest_fare: 4500, typical_fare: 5200, n_flights: 0 },
          coverage: { active_sources: ['RecordedFixture'] },
          flights: [],
        }),
      })
    )

    render(<FareExplorer />)

    expect(screen.getByText('Observed Fare Explorer')).toBeInTheDocument()
    expect(screen.getByLabelText('Origin Airport')).toBeInTheDocument()
    expect(screen.getByLabelText('Destination Airport')).toBeInTheDocument()
    expect(screen.getByLabelText('Travel Date')).toBeInTheDocument()
    expect(screen.getByLabelText('Airline (Optional)')).toBeInTheDocument()

    // Wait for initial search to resolve
    const searchBtn = await screen.findByRole('button', { name: /search fares/i })
    expect(searchBtn).toBeInTheDocument()
    expect(screen.getByText(/Observed Data Disclaimer:/i)).toBeInTheDocument()
  })

  it('shows validation error when origin and destination are the same', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'ok',
          query: { origin: 'DEL', destination: 'BOM', requested_date: '2026-10-06' },
          route: { origin: 'DEL', destination: 'BOM', route_code: 'DEL-BOM' },
          lead_time_position: { lead_days: 15, target_lead_window: 15, is_estimated: false },
          summary: { cheapest_fare: 4500, typical_fare: 5200, n_flights: 0 },
          coverage: { active_sources: [] },
          flights: [],
        }),
      })
    )

    render(<FareExplorer />)

    const searchBtn = await screen.findByRole('button', { name: /search fares/i })
    const destSelect = screen.getByLabelText('Destination Airport')
    fireEvent.change(destSelect, { target: { value: 'DEL' } })

    fireEvent.click(searchBtn)

    await waitFor(() => {
      expect(screen.getByText(/Origin and destination cannot be the same airport/i)).toBeInTheDocument()
    })
  })

  it('shows validation error for past travel dates', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'ok',
          query: { origin: 'DEL', destination: 'BOM', requested_date: '2026-10-06' },
          route: { origin: 'DEL', destination: 'BOM', route_code: 'DEL-BOM' },
          lead_time_position: { lead_days: 15, target_lead_window: 15, is_estimated: false },
          summary: { cheapest_fare: 4500, typical_fare: 5200, n_flights: 0 },
          coverage: { active_sources: [] },
          flights: [],
        }),
      })
    )

    render(<FareExplorer />)

    const searchBtn = await screen.findByRole('button', { name: /search fares/i })
    const dateInput = screen.getByLabelText('Travel Date')
    fireEvent.change(dateInput, { target: { value: '2020-01-01' } })

    fireEvent.click(searchBtn)

    await waitFor(() => {
      expect(screen.getByText(/Travel date cannot be in the past/i)).toBeInTheDocument()
    })
  })

  it('displays flights table, fare breakup, confidence badge, and summary metrics on successful search', async () => {
    const mockFlightResponse = {
      status: 'ok',
      query: { origin: 'DEL', destination: 'BOM', requested_date: '2026-10-06' },
      route: { origin: 'DEL', destination: 'BOM', route_code: 'DEL-BOM' },
      lead_time_position: { lead_days: 15, target_lead_window: 15, is_estimated: false },
      summary: { cheapest_fare: 4500, typical_fare: 5480, n_flights: 1 },
      coverage: { active_sources: ['MockRecorded'] },
      flights: [
        {
          airline_name: 'IndiGo',
          airline_iata: '6E',
          flight_number: '6E-205',
          dep_time: '08:30',
          dep_band: 'morning',
          stops: 0,
          duration_min: 135,
          fare_class: 'Economy',
          pricing: {
            base_fare: 3500,
            taxes: 450,
            udf_psf: 350,
            convenience_fee: 200,
            total_fare: 4500,
          },
          sources: ['MockRecorded'],
          age_minutes: 12,
          confidence: 'high',
          status: 'ok',
          warnings: [],
        },
      ],
    }

    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => mockFlightResponse,
      })
    )

    render(<FareExplorer />)

    await waitFor(() => {
      expect(screen.getByText('6E-205')).toBeInTheDocument()
    })

    expect(screen.getByText('IndiGo')).toBeInTheDocument()
    expect(screen.getAllByText('₹4,500').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('₹5,480')).toBeInTheDocument()
    expect(screen.getAllByText(/T\+15/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('● HIGH')).toBeInTheDocument()
    expect(screen.getByText('✓ Passed')).toBeInTheDocument()

    // Test View Breakup toggle
    const breakupBtn = screen.getByRole('button', { name: /view breakup/i })
    fireEvent.click(breakupBtn)

    expect(screen.getByText('Base Fare:')).toBeInTheDocument()
    expect(screen.getByText('₹3,500')).toBeInTheDocument()
    expect(screen.getByText('GST / Taxes:')).toBeInTheDocument()
    expect(screen.getByText('₹450')).toBeInTheDocument()
    expect(screen.getByText('UDF & PSF:')).toBeInTheDocument()
    expect(screen.getByText('₹350')).toBeInTheDocument()
    expect(screen.getByText('Convenience Fee:')).toBeInTheDocument()
    expect(screen.getByText('₹200')).toBeInTheDocument()
  })

  it('renders "Not covered" state and handles "Track this route" watchlist action', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: false,
        status: 404,
        json: async () => ({
          detail: {
            status: 'not_covered',
            route_code: 'CCU-GOI',
            message: 'Route CCU-GOI is not currently covered in the APIx basket.',
            watchlist_registered: true,
          },
        }),
      })
    )

    render(<FareExplorer />)

    await waitFor(() => {
      expect(screen.getByText(/Route CCU-GOI is Not Covered in the Active Basket/i)).toBeInTheDocument()
    })

    expect(screen.getByText(/BASKET NOTICE/i)).toBeInTheDocument()
    const trackBtn = screen.getByRole('button', { name: /track this route for expansion/i })
    expect(trackBtn).toBeInTheDocument()

    fireEvent.click(trackBtn)

    await waitFor(() => {
      expect(screen.getByText(/✓ Tracked on Watchlist/i)).toBeInTheDocument()
    })
  })

  it('renders synthetic demo banner when demo mode is enabled', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'ok',
          is_synthetic: true,
          query: { origin: 'DEL', destination: 'BOM', requested_date: '2026-10-06' },
          route: { origin: 'DEL', destination: 'BOM', route_code: 'DEL-BOM' },
          lead_time_position: { lead_days: 15, target_lead_window: 15, is_estimated: false },
          summary: { cheapest_fare: 4500, typical_fare: 5480, n_flights: 0 },
          coverage: { active_sources: [] },
          flights: [],
        }),
      })
    )

    render(<FareExplorer />)

    const demoCheckbox = screen.getByRole('checkbox')
    fireEvent.click(demoCheckbox)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/SYNTHETIC DEMO DATA ACTIVE/i)
    })
  })

  it('renders estimated fallback badge and explanation when date is estimated', async () => {
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'ok',
          query: { origin: 'DEL', destination: 'BOM', requested_date: '2026-10-18' },
          route: { origin: 'DEL', destination: 'BOM', route_code: 'DEL-BOM' },
          lead_time_position: {
            lead_days: 27,
            target_lead_window: 30,
            is_estimated: true,
            explanation: 'No direct observations collected for date 2026-10-18 (T+27). Displaying nearest standard horizon T+30 fares.',
          },
          summary: { cheapest_fare: 4100, typical_fare: 4600, n_flights: 0 },
          coverage: { active_sources: ['RecordedFixture'] },
          flights: [],
        }),
      })
    )

    render(<FareExplorer />)

    await waitFor(() => {
      expect(screen.getByText('⏱ ESTIMATED WINDOW FALLBACK')).toBeInTheDocument()
    })
    expect(screen.getByText(/No direct observations collected for date 2026-10-18/i)).toBeInTheDocument()
  })
})
