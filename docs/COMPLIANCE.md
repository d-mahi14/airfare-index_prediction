# APIx Data Collection Compliance & Robots.txt Audit

> **Audit Date**: 2026-09-19 18:58:43 UTC  
> **Auditing User-Agent**: `APIxBot/1.0 (+https://github.com/d-mahi14/airfare-index_prediction; research-compliance@apix.internal)`  
> **Policy Enforcement**: Strict ethical scraping. No evasion, no CAPTCHA solving, rate-limited.

---

## 1. Executive Summary Table

| Source | Type | Collection Mode | Robots.txt Status | Crawl-Delay | Search Path Permissions | ToS Review Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **IndiGo** | airline | `recorded_fixture` | ❌ Error: The read operation timed out | None | `/flight-search`: ❌<br>`/booking`: ❌<br>`/flights`: ❌ | **TO BE REVIEWED BY HUMAN** |
| **Air India** | airline | `recorded_fixture` | ❌ Error: The read operation timed out | None | `/en-in/book-flight`: ❌<br>`/flight-search`: ❌<br>`/booking`: ❌ | **TO BE REVIEWED BY HUMAN** |
| **Air India Express** | airline | `recorded_fixture` | ✅ Reachable | None | `/booking`: ✅<br>`/flights`: ✅<br>`/search`: ✅ | **TO BE REVIEWED BY HUMAN** |
| **Akasa Air** | airline | `recorded_fixture` | ✅ Reachable | None | `/flight-search`: ✅<br>`/booking`: ✅<br>`/search`: ✅ | **TO BE REVIEWED BY HUMAN** |
| **SpiceJet** | airline | `recorded_fixture` | ✅ Reachable | None | `/flight-search`: ✅<br>`/booking`: ✅<br>`/flights`: ✅ | **TO BE REVIEWED BY HUMAN** |
| **MakeMyTrip** | ota | `recorded_fixture` | ❌ Error: The read operation timed out | None | `/flight/search`: ❌<br>`/flights/`: ❌<br>`/api/flight`: ❌ | **TO BE REVIEWED BY HUMAN** |
| **Yatra** | ota | `recorded_fixture` | ❌ Error: The read operation timed out | None | `/flight-search`: ❌<br>`/flights`: ❌<br>`/air-search`: ❌ | **TO BE REVIEWED BY HUMAN** |
| **EaseMyTrip** | ota | `recorded_fixture` | ✅ Reachable | None | `/FlightList`: ✅<br>`/flight-search`: ✅<br>`/flights`: ✅ | **TO BE REVIEWED BY HUMAN** |
| **Cleartrip** | ota | `recorded_fixture` | ✅ Reachable | None | `/flights/results`: ✅<br>`/flights`: ✅<br>`/flight-search`: ✅ | **TO BE REVIEWED BY HUMAN** |
| **Ixigo** | ota | `recorded_fixture` | ✅ Reachable | None | `/search/result/flight`: ✅<br>`/flights`: ✅<br>`/api/flight`: ✅ | **TO BE REVIEWED BY HUMAN** |
| **Goibibo** | ota | `recorded_fixture` | ✅ Reachable | None | `/flights/air-`: ✅<br>`/flights/`: ✅<br>`/flight-search`: ✅ | **TO BE REVIEWED BY HUMAN** |

---

## 2. Ethical Data Collection Commitments

1. **Pre-Fetch Verification**: Robots.txt rules are evaluated before any collector request.
2. **Zero Evasion**: We do not solve CAPTCHAs, bypass Cloudflare/Akamai bot challenges, rotate proxies, or disguise User-Agents.
3. **Human Terms of Service Review**: All sources default to `recorded_fixture` mode with `tos_notes: 'TO BE REVIEWED BY HUMAN'`. Live scraping is never activated without formal human authorization.
4. **Fail-Closed Permissions**: If a domain's `robots.txt` cannot be fetched (HTTP 4xx/5xx or timeout), all search paths are treated as disallowed (`unknown != allowed`).

---

## 3. Raw Robots.txt Excerpts by Source

### IndiGo (`https://www.goindigo.in`)
- **Type**: airline
- **Robots URL**: [https://www.goindigo.in/robots.txt](https://www.goindigo.in/robots.txt)
- **Collection Mode**: `recorded_fixture`
- **ToS Review Notes**: `TO BE REVIEWED BY HUMAN`

```txt
Unable to fetch robots.txt (Error: The read operation timed out)
```

### Air India (`https://www.airindia.com`)
- **Type**: airline
- **Robots URL**: [https://www.airindia.com/robots.txt](https://www.airindia.com/robots.txt)
- **Collection Mode**: `recorded_fixture`
- **ToS Review Notes**: `TO BE REVIEWED BY HUMAN`

```txt
Unable to fetch robots.txt (Error: The read operation timed out)
```

### Air India Express (`https://www.airindiaexpress.com`)
- **Type**: airline
- **Robots URL**: [https://www.airindiaexpress.com/robots.txt](https://www.airindiaexpress.com/robots.txt)
- **Collection Mode**: `recorded_fixture`
- **ToS Review Notes**: `TO BE REVIEWED BY HUMAN`

```txt
User-agent: *
```

### Akasa Air (`https://www.akasaair.com`)
- **Type**: airline
- **Robots URL**: [https://www.akasaair.com/robots.txt](https://www.akasaair.com/robots.txt)
- **Collection Mode**: `recorded_fixture`
- **ToS Review Notes**: `TO BE REVIEWED BY HUMAN`

```txt
User-Agent: *
```

### SpiceJet (`https://www.spicejet.com`)
- **Type**: airline
- **Robots URL**: [https://www.spicejet.com/robots.txt](https://www.spicejet.com/robots.txt)
- **Collection Mode**: `recorded_fixture`
- **ToS Review Notes**: `TO BE REVIEWED BY HUMAN`

```txt
User-agent: googlebot-mobile
User-agent: MSNBot
User-agent: Slurp
User-agent: Teoma
User-agent: Gigabot
User-agent: Robozilla
User-agent: Nutch
User-agent: ia_archiver
User-agent: baiduspider
User-agent: yahoo-mmcrawler
User-agent: yahoo-blogs/v3.9
User-agent: *
```

### MakeMyTrip (`https://www.makemytrip.com`)
- **Type**: ota
- **Robots URL**: [https://www.makemytrip.com/robots.txt](https://www.makemytrip.com/robots.txt)
- **Collection Mode**: `recorded_fixture`
- **ToS Review Notes**: `TO BE REVIEWED BY HUMAN`

```txt
Unable to fetch robots.txt (Error: The read operation timed out)
```

### Yatra (`https://www.yatra.com`)
- **Type**: ota
- **Robots URL**: [https://www.yatra.com/robots.txt](https://www.yatra.com/robots.txt)
- **Collection Mode**: `recorded_fixture`
- **ToS Review Notes**: `TO BE REVIEWED BY HUMAN`

```txt
Unable to fetch robots.txt (Error: The read operation timed out)
```

### EaseMyTrip (`https://www.easemytrip.com`)
- **Type**: ota
- **Robots URL**: [https://www.easemytrip.com/robots.txt](https://www.easemytrip.com/robots.txt)
- **Collection Mode**: `recorded_fixture`
- **ToS Review Notes**: `TO BE REVIEWED BY HUMAN`

```txt
User-Agent: *
```

### Cleartrip (`https://www.cleartrip.com`)
- **Type**: ota
- **Robots URL**: [https://www.cleartrip.com/robots.txt](https://www.cleartrip.com/robots.txt)
- **Collection Mode**: `recorded_fixture`
- **ToS Review Notes**: `TO BE REVIEWED BY HUMAN`

```txt
User-agent: *
Disallow: /flights/search*
Disallow: /m/flights/search*
Disallow: /m/flights/international/results
Disallow: /m/flights/international/results
Disallow: /flights/international/search
Disallow: /flights/itinerary/*
Disallow: /flights/results/itinerary/loading*
User-agent: bingbot
```

### Ixigo (`https://www.ixigo.com`)
- **Type**: ota
- **Robots URL**: [https://www.ixigo.com/robots.txt](https://www.ixigo.com/robots.txt)
- **Collection Mode**: `recorded_fixture`
- **ToS Review Notes**: `TO BE REVIEWED BY HUMAN`

```txt
User-agent: *
Disallow: /flights/search
Disallow: /flights/review
User-agent: AdIdxBot
User-agent: MSNBot
crawl-delay: 10
User-agent: Yandex
User-agent: Baiduspider
User-agent: Bingbot
```

### Goibibo (`https://www.goibibo.com`)
- **Type**: ota
- **Robots URL**: [https://www.goibibo.com/robots.txt](https://www.goibibo.com/robots.txt)
- **Collection Mode**: `recorded_fixture`
- **ToS Review Notes**: `TO BE REVIEWED BY HUMAN`

```txt
User-agent: google-hoteladsverifier
User-agent: *
Disallow: /flights/*?mode=*
Disallow: /flights/*?PageSpeed*
Disallow: /flights/new/
Disallow: /flights/air-*
Disallow: /flights/*?*
User-agent: Googlebot
User-agent: GPTBot
User-agent: PerplexityBot
User-agent: Google-Extended
User-agent: Googlebot-Extended
```
