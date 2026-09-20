# H2 source inventory review

## Checkpoint

- Phase: 2 — Company source inventory
- Checkpoint: H2 — approve sources and first-release scope
- Status: **APPROVED — proceed instruction received 2026-09-20**
- Discovery batch: `canonical-seed-2026-09-20`
- Discovery timestamp: `2026-09-20T12:40:52+05:30`
- Canonical scope: 330 of 330 companies; no company is removed or enabled

## Decision summary

- Recommend accepting 267 read-only verified sources as the source baseline, still disabled until their adapters pass later phase gates.
- Keep 0 access-concern sources disabled. Do not bypass login, CAPTCHA, rate-limit, robots, or other access controls.
- Keep 63 conflicting or non-enumerating sources disabled in the custom-discovery backlog; none is proposed for removal.
- Carry 0 responsive but oversized structured boards into adapter implementation with bounded streaming/pagination tests.
- Recommend the adapter order: Ashby, Greenhouse, Lever, Workday, Darwinbox, Eightfold, SmartRecruiters, Oracle Cloud, SuccessFactors, then Jobvite.
- Preserve all 330 companies in first-release accounting. Priority changes work order and reporting only, never inclusion.

## Inventory accounting

| Metric | Count | Percent of 330 |
|---|---:|---:|
| Read-only auto-verified | 267 | 80.9% |
| Access concern | 0 | 0.0% |
| Conflict / non-enumerating | 63 | 19.1% |
| Responsive but oversized | 0 | 0.0% |
| High confidence | 55 | 16.7% |
| Medium confidence | 212 | 64.2% |
| Low confidence | 63 | 19.1% |

## Adapter coverage and priority

Known reusable ATS families cover 90 companies (27.3%). The remaining 236 search-only records are an explicit custom/source-family backlog; 4 conflicts have no usable adapter classification.

| Priority | Adapter | Total | Verified | Access | Conflict | Pending | Projected registry coverage |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `ashby` | 25 | 25 | 0 | 0 | 0 | 7.6% |
| 2 | `greenhouse` | 25 | 25 | 0 | 0 | 0 | 7.6% |
| 3 | `lever` | 12 | 11 | 0 | 1 | 0 | 3.6% |
| 4 | `workday` | 13 | 13 | 0 | 0 | 0 | 3.9% |
| 5 | `darwinbox` | 4 | 4 | 0 | 0 | 0 | 1.2% |
| 6 | `eightfold` | 3 | 3 | 0 | 0 | 0 | 0.9% |
| 7 | `smartrecruiters` | 3 | 3 | 0 | 0 | 0 | 0.9% |
| 8 | `oracle_cloud` | 2 | 2 | 0 | 0 | 0 | 0.6% |
| 9 | `successfactors` | 2 | 2 | 0 | 0 | 0 | 0.6% |
| 10 | `jobvite` | 1 | 1 | 0 | 0 | 0 | 0.3% |
| backlog | `search_only` | 236 | 178 | 0 | 58 | 0 | 71.5% |
| backlog | `unresolved` | 4 | 0 | 0 | 4 | 0 | 1.2% |

Ashby and Greenhouse have now passed full adapter-group validation for all 25 current mappings in each family. The next approved adapter family is Lever.

### Representative boards

- `ashby`: Deeptune (0), Kognitos (7), Kong (72), Cerebras Systems (113)
- `greenhouse`: APT Portfolio (1), Glean (123), Motive (151), Qube Research (202)
- `lever`: 100ms (8), Doxel (13), Bazaarvoice (29)
- `workday`: Fractal Analytics, CrowdStrike
- `darwinbox`: Rapido, ClearTax, Porter, Unacademy
- `eightfold`: NVIDIA, Millennium Management, PayPal

## Unsupported or blocked proposals

None are proposed as unsupported or removed at H2. Any access-concern or conflict companies remain in scope and disabled pending the approved disposition and later adapter-specific evidence.

## Responsive but oversized structured boards

| Rank | Priority | Company | Adapter | Direct URL | Evidence / limitation |
|---:|---|---|---|---|---|
| — | — | None | — | — | — |

## Access-policy concerns requiring approval

Recommendation: keep disabled, do not bypass the observed control, and attempt only a documented public structured endpoint, custom public adapter, or native employer alert in later phases.

| Rank | Priority | Company | Adapter | Direct URL | Evidence / limitation |
|---:|---|---|---|---|---|
| — | — | None | — | — | — |

## Conflicting or non-enumerating proposals requiring inspection

Recommendation: keep every company in scope but disabled; treat these as custom source-discovery work unless the listed evidence supports a correction.

| Rank | Priority | Company | Adapter | Direct URL | Evidence / limitation |
|---:|---|---|---|---|---|
| 16 | P1 | Zenskar | `unresolved` | none | Seed hint is a third-party listing; official source is not verified. |
| 19 | P1 | Google | `search_only` | [open](https://support.google.com/googlecareers/answer/9018529?hl=en) | Official help page does not expose an enumerable job inventory. |
| 22 | P1 | Zerodha | `search_only` | [open](https://careers.zerodhafundhouse.com/jobs) | Candidate belongs to Zerodha Fund House, not verified as the complete Zerodha company source. |
| 23 | P1 | Amazon / AWS | `search_only` | [open](https://aws.amazon.com/careers/life-at-aws-empowering-women-and-non-binary-employees-to-thrive-at-Amazon-and-AWS/) | Candidate is a regional editorial careers page, not a complete India job inventory. |
| 31 | P1 | Confluent | `search_only` | [open](https://careers.confluent.io/jobs/job/fd9f602f-9741-4360-946d-430f1515ebf9) | HTTP 429 |
| 57 | P1 | Maxim AI | `search_only` | [open](https://www.getmaxim.ai/jobs/member-of-technical-staff) | HTTP 404 |
| 58 | P1 | Salesforce | `search_only` | [open](https://www.salesforce.com/company/careers/locations/japac/japan/) | Official India careers URL redirected the bounded probe to a Japan page; India inventory remains unverified. |
| 79 | P1 | Zomato / Blinkit | `search_only` | [open](https://www.zomato.com/policies/privacy/) | network error: [WinError 10054] An existing connection was forcibly closed by the remote host |
| 83 | P1 | D. E. Shaw India | `search_only` | [open](https://www.grapevine.in/tal/jobs/c3ee6a7b-6614-4312-903a-d0d944f99e03) | Candidate redirected to a third-party job copy and no official source was verified. |
| 85 | P1 | Mayhem Studios | `search_only` | [open](https://www.mayhem-studios.com/) | network error: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch, certificate is not valid for 'www.mayhem-studios.com'. (_ssl.c:1000) |
| 86 | P1 | Mrsool | `search_only` | [open](https://help.sa.mrsool.co/en/articles/8345205-how-can-i-apply-for-a-job-at-mrsool) | Official help article explains applying but does not enumerate current jobs. |
| 87 | P1 | NK Securities | `search_only` | [open](https://www.nksecurities.com/) | Company homepage does not expose a verified enumerable careers source. |
| 88 | P1 | Quadeye | `search_only` | [open](https://www.quadeye.com/) | Company homepage does not expose a verified enumerable careers source. |
| 92 | P1 | X | `search_only` | [open](https://quantboxresearch.com/careers/) | Search candidate belonged to Quantbox or Google X, not the intended company X. |
| 103 | P2 | Simplismart | `unresolved` | none | Seed hint is a third-party listing; official source is not verified. |
| 111 | P2 | Qualcomm | `search_only` | [open](https://www.qualcomm.com/company/careers/internships-and-early-in-career-opportunities) | Early-career information page is not a complete job inventory. |
| 112 | P2 | Samsung R&D | `search_only` | [open](https://www.samsung-srj.co.jp/career/) | Candidate belonged to Samsung R&D Japan, not the intended India source. |
| 115 | P2 | AQR Capital Management | `search_only` | [open](https://www.aqr.com/) | Company homepage was found, but no complete careers inventory was verified. |
| 121 | P2 | Squarepoint Capital | `search_only` | [open](https://www.efinancialcareers.ch/en/jobs/applications/at-squarepoint-capital) | Candidate was a third-party finance job page; official careers inventory remains unverified. |
| 125 | P2 | AarogyaAI | `search_only` | [open](https://aarogyaai.com/EnhancedPortalLogin) | Search result was a login portal, not a public careers inventory. |
| 128 | P2 | Altimate.ai | `search_only` | [open](https://altimate.ai/company) | Company page does not expose a verified careers inventory. |
| 129 | P2 | Arbix AI | `search_only` | [open](https://arbixai.com/contact/) | Contact page does not enumerate public job openings. |
| 132 | P2 | Athina AI | `search_only` | [open](https://www.athina.ai/) | Company homepage does not expose a verified careers inventory. |
| 135 | P2 | Blend AI | `search_only` | [open](https://blend-ai.com/book-a-demo) | Only a third-party job copy was found; official company identity remains ambiguous. |
| 136 | P2 | Boltzmann Labs | `search_only` | [open](https://boltzmann.co/scientistinresidence) | Only a single program or third-party job was found, not a complete inventory. |
| 137 | P2 | BrainsightAI | `search_only` | [open](https://www.brainsightai.com/contact-us) | Team page does not enumerate public job openings. |
| 141 | P2 | DIAGNO Systems | `search_only` | [open](https://www.diagnointelligent.com/iosteoporo_screen_app/) | Search result was an unrelated product page, not a careers source. |
| 146 | P2 | FinbotsAI | `search_only` | [open](https://www.crunchbase.com/organization/finbots-ai/profiles_and_contacts) | Search result redirected to a third-party company profile. |
| 147 | P2 | Flutura | `search_only` | [open](https://flutura-academy.com/flutura-academy-hap-konkurs-punesimi-per-koordinator-e-per-qendren-e-flutura-academy-ne-podujeve/) | Search result belonged to an unrelated organization with the same name. |
| 155 | P2 | KOGO AI | `search_only` | [open](https://kogo.ai/about) | About page does not expose a verified careers inventory. |
| 156 | P2 | Krutrim | `search_only` | [open](https://www.krutriminsights.com/) | Search results belonged to a different company named Krutrim Insights. |
| 161 | P2 | Murf AI | `search_only` | [open](https://murf.ai/partner-with-us/voice-actors) | Voice-partner page is not the employee job inventory. |
| 162 | P2 | Nektar AI | `search_only` | [open](https://nektar.ai/llm-info/) | Machine-readable company information page is not a careers inventory. |
| 165 | P2 | Neuralzome | `search_only` | [open](https://storage.googleapis.com/b2match-as-1/CbFVKaCSFzu38ce868NBAWAr) | Search result was a conference profile, not an official careers source. |
| 169 | P2 | Nurix AI | `search_only` | [open](https://mark91-old-nurix-web.webflow.io/company) | Hosted job evidence uses a different parent board; complete ownership and coverage need inspection. |
| 173 | P2 | Portkey | `search_only` | [open](https://www.portkeygames.com) | Search result belonged to Portkey Games, not Portkey AI. |
| 177 | P2 | RagaAI | `unresolved` | none | Only social job posts were found; no official public careers inventory was verified. |
| 181 | P2 | SciSpace | `search_only` | [open](https://scispace.com/) | HTTP 403 |
| 183 | P2 | SigTuple | `search_only` | [open](https://sigtuple.com/) | Company homepage does not expose a verified careers inventory. |
| 186 | P2 | Slang Labs | `search_only` | [open](https://www.uplers.com/company/slang-labs-9457) | Only recruiter and social copies were found; no official current source was verified. |
| 196 | P2 | Vayavya Labs | `search_only` | [open](https://www.glassdoor.co.in/Jobs/Vayavya-Labs-Jobs-E608414.htm) | Careers candidate redirected to a third-party job site. |
| 199 | P2 | Xanadu.ai | `search_only` | [open](https://www.xanadu.ai) | Company homepage does not expose a verified enumerable careers source. |
| 216 | P3 | Morgan Stanley | `search_only` | [open](https://www.morganstanley.com/people) | People page is not a complete job search source. |
| 225 | P3 | Cisco | `search_only` | [open](https://www.cisco.com/c/en/us/about/careers/job-areas/engineering.html) | HTTP 404 |
| 226 | P3 | Clazar | `search_only` | [open](https://www.levels.fyi/companies/clazar/jobs) | Only third-party job copies were found; official careers source remains unverified. |
| 239 | P3 | MongoDB | `search_only` | [open](https://www.mongodb.com/company/careers/see-jobs) | response exceeded 2000000 bytes |
| 260 | P3 | KLA | `search_only` | [open](https://klaindustries.com/career-opportunities/) | Search result belonged to KLA Industries, not KLA semiconductor. |
| 263 | P3 | MediaTek | `search_only` | [open](https://careers.mediatek.com/en) | HTTP 307 |
| 269 | P3 | Western Digital / SanDisk | `search_only` | [open](https://www.sandisk.com/en-kw/support/wdc) | Support page is not a careers inventory. |
| 271 | P3 | Ather Energy | `search_only` | [open](https://www.atherenergy.com/about) | About page is not a careers inventory. |
| 276 | P3 | GreyOrange | `search_only` | [open](https://www.greyorange.com/gstore/contact) | Search candidate redirected to a contact page and did not enumerate jobs. |
| 280 | P3 | Mercedes-Benz Research and Development India | `search_only` | [open](https://group.mercedes-benz.com/karriere/ueber-uns/standorte/standort-detailseite-18185.html) | Location profile is not a complete jobs inventory. |
| 281 | P3 | Minus Zero | `search_only` | [open](https://plusminuszero.com.sg/products/-official-website-exclusive-combo-xjc-y010-cordless-vacuum-cleaner-xqs-b320-dc-circulator) | Search result belonged to an unrelated similarly named company. |
| 291 | P3 | Apna | `search_only` | [open](https://www.apna.co/) | Consumer job marketplace homepage is not Apna's employee careers inventory. |
| 292 | P3 | BillDesk | `search_only` | [open](https://www.billdesk.com/web/job_description/jd%3DBD11) | Single job detail does not provide a complete enumerable company inventory. |
| 298 | P3 | CoinSwitch | `search_only` | [open](https://coinswitch.co/ventures) | Ventures page is not the CoinSwitch employee careers inventory. |
| 300 | P3 | Dream11 / Dream Sports | `lever` | [open](https://jobs.lever.co/dreamsports/5695908e-b004-4c11-966f-d410f3c5e959/apply) | Former Lever board now returns 404; current official site requires custom discovery. |
| 303 | P3 | Games24x7 | `search_only` | [open](https://www.games24x7.com/contact) | Contact page does not enumerate public job openings. |
| 305 | P3 | Info Edge | `unresolved` | none | No current official employee careers inventory was found. |
| 313 | P3 | Myntra | `search_only` | [open](https://govhelp.in/find/job/myntra-customer-service-online-jobs-work-from-home/?export-pdf=88) | network error: [WinError 10054] An existing connection was forcibly closed by the remote host |
| 316 | P3 | OYO | `search_only` | [open](https://seek.oyorooms.com/) | Candidate source could not be verified as the current public employee job inventory. |
| 321 | P3 | Practo | `search_only` | [open](https://www.practo.com/company/careers/aisquad/lead-ai-engineer) | Single job detail does not provide a complete enumerable company inventory. |
| 324 | P3 | Udaan | `search_only` | [open](https://clientlogin.udaanindia.com/careers.html) | network error: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired (_ssl.c:1000) |

## Verified search-only sources requiring custom adapters or deeper family detection

These official pages passed read-only checks but exposed no single supported hosted ATS fingerprint. They are recommended as the custom-adapter backlog, not as a claim that one generic scraper can safely cover all of them.

| Rank | Priority | Company | Adapter | Direct URL | Evidence / limitation |
|---:|---|---|---|---|---|
| 4 | P1 | Adobe | `search_only` | [open](https://careers.adobe.com/us/en) | Automated search proposal; requires read-only verification and H2 review. |
| 7 | P1 | Meta | `search_only` | [open](https://ai.meta.com/join-us/) | Automated search proposal; requires read-only verification and H2 review. |
| 8 | P1 | Atlassian | `search_only` | [open](https://www.atlassian.com/company/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 10 | P1 | Sanas | `search_only` | [open](https://www.sanas.ai/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 12 | P1 | Moloco | `search_only` | [open](https://www.moloco.com/company/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 13 | P1 | Postman | `search_only` | [open](https://www.postman.com/company/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 14 | P1 | Rippling | `search_only` | [open](https://www.rippling.com/en-IN/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 15 | P1 | Rubrik | `search_only` | [open](https://www.rubrik.com/company/careers?gh_src=2c3b02b81us) | Automated search proposal; requires read-only verification and H2 review. |
| 17 | P1 | GitLab | `search_only` | [open](https://about.gitlab.com/jobs/all-jobs/) | Automated search proposal; requires read-only verification and H2 review. |
| 18 | P1 | Slack | `search_only` | [open](https://slack.com/intl/en-in/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 20 | P1 | Microsoft | `search_only` | [open](https://careers.microsoft.com/v2/global/en/locations/india.html?trk=public_post_main-feed-card_reshare_feed-article-content) | Automated search proposal; requires read-only verification and H2 review. |
| 21 | P1 | Oracle / OCI | `search_only` | [open](https://www.oracle.com/in/careers/opportunities/oracle-cloud-infrastructure/) | Automated search proposal; requires read-only verification and H2 review. |
| 24 | P1 | Apple | `search_only` | [open](https://jobs.apple.com/en-us/search?location=india-INDC) | Automated search proposal; requires read-only verification and H2 review. |
| 25 | P1 | InMobi | `search_only` | [open](https://www.inmobi.com/company/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 29 | P1 | Broadcom | `search_only` | [open](https://www.broadcom.com/company/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 30 | P1 | Cockroach Labs | `search_only` | [open](https://www.cockroachlabs.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 36 | P1 | Kore.ai | `search_only` | [open](https://www.kore.ai/careers) | Generated from an unverified canonical seed URL hint; H2 review is required. |
| 39 | P1 | Yellow.ai | `search_only` | [open](https://yellow.ai/career/) | Generated from an unverified canonical seed URL hint; H2 review is required. |
| 40 | P1 | LinkedIn | `search_only` | [open](https://careers.linkedin.com/) | Automated search proposal; requires read-only verification and H2 review. |
| 46 | P1 | Qure.ai | `search_only` | [open](https://jobs.qure.ai/) | Generated from an unverified canonical seed URL hint; H2 review is required. |
| 49 | P1 | TrueFoundry | `search_only` | [open](https://www.truefoundry.com/careers) | Generated from an unverified canonical seed URL hint; H2 review is required. |
| 51 | P1 | Airbnb | `search_only` | [open](https://careers.airbnb.com/positions/) | Automated search proposal; requires read-only verification and H2 review. |
| 52 | P1 | FalconX | `search_only` | [open](https://www.falconx.io/open-roles) | Automated search proposal; requires read-only verification and H2 review. |
| 53 | P1 | Stripe | `search_only` | [open](https://stripe.com/careers/search) | Replaced one job detail with Stripe's complete job search. |
| 56 | P1 | Intuit | `search_only` | [open](https://www.intuit.com/in/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 60 | P1 | ServiceNow | `search_only` | [open](https://careers.servicenow.com/locations/apj/india/?page=3) | Automated search proposal; requires read-only verification and H2 review. |
| 62 | P1 | Booking.com | `search_only` | [open](https://jobs.booking.com/booking/jobs) | Automated search proposal; requires read-only verification and H2 review. |
| 63 | P1 | Coupang | `search_only` | [open](https://www.coupang.jobs/en/locations/bengaluru/) | Automated search proposal; requires read-only verification and H2 review. |
| 65 | P1 | Okta | `search_only` | [open](https://www.okta.com/company/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 66 | P1 | Twilio | `search_only` | [open](https://jobs.twilio.com/careers?domain=twilio.com&hl=en) | Automated search proposal; requires read-only verification and H2 review. |
| 71 | P1 | Index Exchange | `search_only` | [open](https://www.indexexchange.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 72 | P1 | Roku | `search_only` | [open](https://www.weareroku.com/bengaluru) | Automated search proposal; requires read-only verification and H2 review. |
| 73 | P1 | Eightfold AI | `search_only` | [open](https://app.eightfold.ai/careers?start=0) | Generated from an unverified canonical seed URL hint; H2 review is required. |
| 74 | P1 | Flipkart | `search_only` | [open](https://www.flipkartcareers.com/jobslist) | Automated search proposal; requires read-only verification and H2 review. |
| 75 | P1 | Meesho | `search_only` | [open](https://www.meesho.io/jobs?i=true) | Automated search proposal; requires read-only verification and H2 review. |
| 76 | P1 | PhonePe | `search_only` | [open](https://www.phonepe.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 78 | P1 | Swiggy | `search_only` | [open](https://careers.swiggy.com/) | Automated search proposal; requires read-only verification and H2 review. |
| 91 | P1 | Tower Research Capital | `search_only` | [open](https://tower-research.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 94 | P1 | CRED | `search_only` | [open](https://careers.cred.club/openings) | Automated search proposal; requires read-only verification and H2 review. |
| 95 | P1 | Navi | `search_only` | [open](https://navi.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 99 | P2 | Noon | `search_only` | [open](https://www.noon.ai/careers) | Replaced a different company's Ashby board with Noon's official careers page. |
| 101 | P2 | Walmart Global Tech | `search_only` | [open](https://tech.walmart.com/content/walmart-global-tech/en_us/careers.html) | Automated search proposal; requires read-only verification and H2 review. |
| 108 | P2 | Tenstorrent | `search_only` | [open](https://tenstorrent.madebyhowler.com/careers/) | Generated from an unverified canonical seed URL hint; H2 review is required. |
| 109 | P2 | AMD | `search_only` | [open](https://www.amd.com/en/corporate/careers.html) | Automated search proposal; requires read-only verification and H2 review. |
| 110 | P2 | Intel | `search_only` | [open](https://www.intel.com/content/www/us/en/jobs/locations.html) | Automated search proposal; requires read-only verification and H2 review. |
| 113 | P2 | Quantiphi | `search_only` | [open](https://quantiphi.com/careers/) | Generated from an unverified canonical seed URL hint; H2 review is required. |
| 114 | P2 | Tiger Analytics | `search_only` | [open](https://www.tigeranalytics.com/about-us/current-openings/) | Generated from an unverified canonical seed URL hint; H2 review is required. |
| 116 | P2 | Dolat Capital | `search_only` | [open](https://dolatcapital.in/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 117 | P2 | IMC Trading | `search_only` | [open](https://www.imc.com/in/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 119 | P2 | Optiver | `search_only` | [open](https://www.optiver.com/join-us/) | Automated search proposal; requires read-only verification and H2 review. |
| 120 | P2 | Point72 | `search_only` | [open](https://point72.com/working-here/) | Automated search proposal; requires read-only verification and H2 review. |
| 122 | P2 | Trexquant Investment | `search_only` | [open](https://trexquant.com/careers?q=int) | Automated search proposal; requires read-only verification and H2 review. |
| 123 | P2 | WorldQuant | `search_only` | [open](https://www.worldquant.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 126 | P2 | Aganitha | `search_only` | [open](https://www.aganitha.ai/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 131 | P2 | Arya.ai | `search_only` | [open](https://arya.ai/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 134 | P2 | Binocs | `search_only` | [open](https://binocsco.notion.site/Binocs-Open-positions-13dc18d836c34031a6108082e4986676) | Automated search proposal; requires read-only verification and H2 review. |
| 138 | P2 | Cognite | `search_only` | [open](https://www.cognite.com/en/company/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 139 | P2 | CoRover | `search_only` | [open](https://corover.ai/company/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 140 | P2 | CropIn | `search_only` | [open](https://www.cropin.com/career/) | Automated search proposal; requires read-only verification and H2 review. |
| 148 | P2 | Forus Health | `search_only` | [open](https://forushealth.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 149 | P2 | GalaxEye | `search_only` | [open](https://galaxeye.space/job-portal) | Automated search proposal; requires read-only verification and H2 review. |
| 150 | P2 | Gnani.ai | `search_only` | [open](https://careers.gnani.ai/) | Automated search proposal; requires read-only verification and H2 review. |
| 152 | P2 | Hyperleap AI | `search_only` | [open](https://hyperleap.ai/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 153 | P2 | HyperVerge | `search_only` | [open](https://hyperverge.co/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 154 | P2 | InVideo | `search_only` | [open](https://careers.invideo.io/) | Automated search proposal; requires read-only verification and H2 review. |
| 157 | P2 | LimeChat | `search_only` | [open](https://limechat.zohorecruit.in/jobs/Careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 158 | P2 | Locus | `search_only` | [open](https://dynamiclink.locus-dev.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 159 | P2 | Mad Street Den | `search_only` | [open](https://careers.swglobalventures.in/company/mad-street-den/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 160 | P2 | Miko | `search_only` | [open](https://in.miko.ai/pages/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 163 | P2 | Netra | `search_only` | [open](https://www.netratechnosys.com/career) | Automated search proposal; requires read-only verification and H2 review. |
| 164 | P2 | NeuralGarage | `search_only` | [open](https://jobs.pyjamahr.com/neuralgarage) | Automated search proposal; requires read-only verification and H2 review. |
| 166 | P2 | Nexstem | `search_only` | [open](https://sites.google.com/nexstem.ai/careers/home) | Automated search proposal; requires read-only verification and H2 review. |
| 167 | P2 | Neysa | `search_only` | [open](https://neysa.ai/careers/job-openings/) | Replaced a contact page with the official openings page. |
| 168 | P2 | Niramai | `search_only` | [open](https://niramai.com/career/) | Automated search proposal; requires read-only verification and H2 review. |
| 170 | P2 | Peptris | `search_only` | [open](https://www.peptris.com/careers.html) | Automated search proposal; requires read-only verification and H2 review. |
| 171 | P2 | Perceptyne | `search_only` | [open](https://www.perceptyne.com/career) | Automated search proposal; requires read-only verification and H2 review. |
| 172 | P2 | Poppulo | `search_only` | [open](https://www.poppulo.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 174 | P2 | Predii | `search_only` | [open](https://predii.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 175 | P2 | QpiAI | `search_only` | [open](https://www.qpiai.tech/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 176 | P2 | Quant AI | `search_only` | [open](https://www.quant.ai/en/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 179 | P2 | Ripik.AI | `search_only` | [open](https://www.ripik.ai/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 180 | P2 | Saptang Labs | `search_only` | [open](https://saptanglabs.com/) | Automated search proposal; requires read-only verification and H2 review. |
| 182 | P2 | Signzy | `search_only` | [open](https://www.signzy.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 184 | P2 | Skild AI | `search_only` | [open](https://www.skild.ai/career?job=13) | Automated search proposal; requires read-only verification and H2 review. |
| 185 | P2 | Skit.ai | `search_only` | [open](https://skit.ai/in/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 188 | P2 | Steps AI | `search_only` | [open](https://stepsai.co/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 189 | P2 | Supervity | `search_only` | [open](https://www.supervity.ai/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 190 | P2 | Tekion | `search_only` | [open](https://tekion.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 191 | P2 | TheMathCompany | `search_only` | [open](https://mathco.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 192 | P2 | Tredence | `search_only` | [open](https://www.tredence.com/careers/greatest-of-ai) | Automated search proposal; requires read-only verification and H2 review. |
| 193 | P2 | Tricog | `search_only` | [open](https://tricog.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 194 | P2 | Upscale AI | `search_only` | [open](https://www.upscale.ai/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 197 | P2 | Writesonic | `search_only` | [open](https://writesonic.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 198 | P2 | Wysa | `search_only` | [open](https://www.wysa.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 200 | P2 | ZestIot | `search_only` | [open](https://www.zestiot.com/company/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 202 | P2 | Zoniqx | `search_only` | [open](https://www.zoniqx.com/contact) | Automated search proposal; requires read-only verification and H2 review. |
| 203 | P3 | American Express | `search_only` | [open](https://careers.americanexpress.com/en/sites/CX_1/jobs?inav=au_sitefooter_careers&lastSelectedFacet=POSTING_DATES&selectedPostingDatesFacet=30utm_medium) | Automated search proposal; requires read-only verification and H2 review. |
| 206 | P3 | BlackRock / Aladdin | `search_only` | [open](https://careers.blackrock.com/location/india-jobs/45831/1269750/2/6) | Automated search proposal; requires read-only verification and H2 review. |
| 207 | P3 | Citi | `search_only` | [open](https://jobs.citi.com/search-jobs?k=india) | Multiple hosted ATS configurations detected; H2 inspection required. |
| 208 | P3 | Deutsche Bank | `search_only` | [open](https://careers.db.com/professionals/search-roles/) | Automated search proposal; requires read-only verification and H2 review. |
| 209 | P3 | Fidelity Investments | `search_only` | [open](https://jobs.fidelity.com/in/) | Automated search proposal; requires read-only verification and H2 review. |
| 210 | P3 | Goldman Sachs | `search_only` | [open](https://www.goldmansachs.com/worldwide/india/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 211 | P3 | HSBC | `search_only` | [open](https://www.hsbc.com/careers/where-we-hire/india) | Automated search proposal; requires read-only verification and H2 review. |
| 214 | P3 | Mastercard | `search_only` | [open](https://careers.mastercard.com/us/en/mumbai-india) | Automated search proposal; requires read-only verification and H2 review. |
| 218 | P3 | PayU | `search_only` | [open](https://payu.hire.trakstar.com/) | Automated search proposal; requires read-only verification and H2 review. |
| 219 | P3 | S&P Global | `search_only` | [open](https://careers.spglobal.com/jobs/locations) | Automated search proposal; requires read-only verification and H2 review. |
| 220 | P3 | UBS | `search_only` | [open](https://www.ubs.com/global/en/careers/about-us/locations/india.html) | Automated search proposal; requires read-only verification and H2 review. |
| 222 | P3 | Wells Fargo | `search_only` | [open](https://www.wellsfargojobs.com/?utm_medium=www-redirect&utm_source=about--careers--index) | Automated search proposal; requires read-only verification and H2 review. |
| 223 | P3 | Arista Networks | `search_only` | [open](https://www.arista.com/en/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 224 | P3 | Automattic | `search_only` | [open](https://automattic.com/work-with-us/jobs/) | Automated search proposal; requires read-only verification and H2 review. |
| 228 | P3 | Cloudflare | `search_only` | [open](https://www.cloudflare.com/careers/jobs/) | Automated search proposal; requires read-only verification and H2 review. |
| 229 | P3 | Cohesity | `search_only` | [open](https://www.cohesity.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 230 | P3 | Coinbase | `search_only` | [open](https://www.coinbase.com/en-in/careers/positions?location=remote+india) | Automated search proposal; requires read-only verification and H2 review. |
| 231 | P3 | Compass | `search_only` | [open](https://www.compass.com/careers/?gh_board=compassindia) | Automated search proposal; requires read-only verification and H2 review. |
| 232 | P3 | Crunchyroll | `search_only` | [open](https://www.crunchyroll.com/about/jobs) | Replaced a Brazil-localized URL with the global official jobs page. |
| 233 | P3 | Druva | `search_only` | [open](https://www.druva.com/why-druva/explore/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 234 | P3 | Elastic | `search_only` | [open](https://www.elastic.co/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 236 | P3 | GitHub | `search_only` | [open](https://www.github.careers/life-at-github) | Automated search proposal; requires read-only verification and H2 review. |
| 237 | P3 | Kredivo | `search_only` | [open](https://kredivocorp.com/careers/?Job=159) | Automated search proposal; requires read-only verification and H2 review. |
| 238 | P3 | Media.net | `search_only` | [open](https://careers.media.net/) | Automated search proposal; requires read-only verification and H2 review. |
| 240 | P3 | Navan | `search_only` | [open](https://navan.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 241 | P3 | Nutanix | `search_only` | [open](https://careers.nutanix.com/en/locations/india/) | Automated search proposal; requires read-only verification and H2 review. |
| 242 | P3 | Opendoor | `search_only` | [open](https://www.opendoor.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 243 | P3 | p0 | `search_only` | [open](https://p0.dev/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 247 | P3 | SentinelOne | `search_only` | [open](https://www.sentinelone.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 249 | P3 | Skillz | `search_only` | [open](https://ts.skillz.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 250 | P3 | Snowflake | `search_only` | [open](https://careers.snowflake.com/us/en) | Automated search proposal; requires read-only verification and H2 review. |
| 251 | P3 | TestGorilla | `search_only` | [open](https://www.testgorilla.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 252 | P3 | ThoughtSpot | `search_only` | [open](https://www.thoughtspot.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 253 | P3 | Toptal | `search_only` | [open](https://www.toptal.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 255 | P3 | Zscaler | `search_only` | [open](https://www.zscaler.com/careers/engineering) | Automated search proposal; requires read-only verification and H2 review. |
| 257 | P3 | Applied Materials | `search_only` | [open](https://jobs.appliedmaterials.com/location/india-jobs/95/1269750/2/8) | Automated search proposal; requires read-only verification and H2 review. |
| 258 | P3 | Arm | `search_only` | [open](https://careers.arm.com/search-jobs?acm=ALL&alrpm=ALL) | Multiple hosted ATS configurations detected; H2 inspection required. |
| 261 | P3 | Lam Research | `search_only` | [open](https://www.lamresearch.com/careers/global-opportunities/india/) | Automated search proposal; requires read-only verification and H2 review. |
| 262 | P3 | Marvell | `search_only` | [open](https://www.marvell.com/company/careers.html) | Automated search proposal; requires read-only verification and H2 review. |
| 264 | P3 | Micron | `search_only` | [open](https://careers.micron.com/careers/?location=india) | Automated search proposal; requires read-only verification and H2 review. |
| 266 | P3 | Renesas | `search_only` | [open](https://jobs.renesas.com/india) | Automated search proposal; requires read-only verification and H2 review. |
| 267 | P3 | Synopsys | `search_only` | [open](https://www.synopsys.com/careers/global/south-asia/india.html) | Automated search proposal; requires read-only verification and H2 review. |
| 268 | P3 | Texas Instruments | `search_only` | [open](https://edbz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/jobs?country=IN&location=India) | Automated search proposal; requires read-only verification and H2 review. |
| 270 | P3 | Aptiv | `search_only` | [open](https://www.aptiv.com/en/jobs/working-here/global-locations/india) | Automated search proposal; requires read-only verification and H2 review. |
| 272 | P3 | Ati Motors | `search_only` | [open](https://careers.swglobalventures.in/company/ati-motors/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 274 | P3 | CynLr | `search_only` | [open](https://www.cynlr.com/careers/in/solutions/robotics-solutions-eng) | Automated search proposal; requires read-only verification and H2 review. |
| 275 | P3 | Detect Technologies | `search_only` | [open](https://detecttechnologies.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 277 | P3 | Harman | `search_only` | [open](https://jobsearch.harman.com/en_US/careers/SearchJobs/?2039=%5B59985%5D&2039_format=2669&jobOffset=120&jobRecordsPerPage=20&listFilterMode=1) | Automated search proposal; requires read-only verification and H2 review. |
| 278 | P3 | ideaForge | `search_only` | [open](https://ideaforgetech.com/career) | Automated search proposal; requires read-only verification and H2 review. |
| 279 | P3 | KPIT | `search_only` | [open](https://www.kpit.com/careers-overview/) | Automated search proposal; requires read-only verification and H2 review. |
| 282 | P3 | Myelin Foundry | `search_only` | [open](https://www.myelinfoundry.ai/careers/) | Replaced a company profile page with the official careers page. |
| 284 | P3 | Ola Electric | `search_only` | [open](https://www.olaelectric.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 286 | P3 | Samsara | `search_only` | [open](https://www.samsara.com/company/careers/departments) | Automated search proposal; requires read-only verification and H2 review. |
| 287 | P3 | Tata Elxsi | `search_only` | [open](https://www.tataelxsi.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 288 | P3 | Unbox Robotics | `search_only` | [open](https://unboxrobotics.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 289 | P3 | Volvo Group | `search_only` | [open](https://www.volvogroup.com/en/careers.html/jobs/?q=engineer&sort=relevance) | Automated search proposal; requires read-only verification and H2 review. |
| 290 | P3 | ACKO | `search_only` | [open](https://www.acko.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 293 | P3 | BlackBuck | `search_only` | [open](https://www.blackbuck.com/team-blackbuck.html) | Automated search proposal; requires read-only verification and H2 review. |
| 294 | P3 | BrowserStack | `search_only` | [open](https://www.browserstack.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 295 | P3 | Chargebee | `search_only` | [open](https://www.chargebee.com/careers/join-us/) | Automated search proposal; requires read-only verification and H2 review. |
| 297 | P3 | CoinDCX | `search_only` | [open](https://careers.coindcx.com/?trk=organization-update_share-update_update-text) | Automated search proposal; requires read-only verification and H2 review. |
| 299 | P3 | Delhivery | `search_only` | [open](https://www.delhivery.com/careers?trk=public_post_comment-text) | Automated search proposal; requires read-only verification and H2 review. |
| 301 | P3 | ElasticRun | `search_only` | [open](https://elastic.run/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 304 | P3 | Groww | `search_only` | [open](https://groww.sensehq.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 306 | P3 | Innovaccer | `search_only` | [open](https://innovaccer.com/careers/life-at-innovaccer) | Automated search proposal; requires read-only verification and H2 review. |
| 307 | P3 | Jio Platforms / Haptik | `search_only` | [open](https://haptik.freshteam.com/jobs/HVivFopqkiC1/voice-ai-engineer-hybrid) | Automated search proposal; requires read-only verification and H2 review. |
| 308 | P3 | Jupiter | `search_only` | [open](https://tryjupiter.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 309 | P3 | Juspay | `search_only` | [open](https://juspay.io/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 310 | P3 | Lenskart | `search_only` | [open](https://www.lenskart.com/careers-at-lenskart) | Automated search proposal; requires read-only verification and H2 review. |
| 311 | P3 | MakeMyTrip | `search_only` | [open](https://careers.makemytrip.com/) | Automated search proposal; requires read-only verification and H2 review. |
| 312 | P3 | Moglix | `search_only` | [open](https://www.moglix.com/career) | Automated search proposal; requires read-only verification and H2 review. |
| 314 | P3 | Nykaa | `search_only` | [open](https://careers.nykaa.com/) | Automated search proposal; requires read-only verification and H2 review. |
| 315 | P3 | OfBusiness | `search_only` | [open](https://www.ofbusiness.com/) | Automated search proposal; requires read-only verification and H2 review. |
| 318 | P3 | Pine Labs | `search_only` | [open](https://www.pinelabs.com/careers/open-jobs) | Automated search proposal; requires read-only verification and H2 review. |
| 319 | P3 | Policybazaar | `search_only` | [open](https://www.policybazaar.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 322 | P3 | ShareChat / Moj | `search_only` | [open](https://sharechat.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 323 | P3 | Slice | `search_only` | [open](https://slice.careers/) | Automated search proposal; requires read-only verification and H2 review. |
| 326 | P3 | Urban Company | `search_only` | [open](https://careers.urbancompany.com/) | Automated search proposal; requires read-only verification and H2 review. |
| 327 | P3 | Whatfix | `search_only` | [open](https://whatfix.com/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 328 | P3 | Zepto | `search_only` | [open](https://www.zepto.com/s/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 329 | P3 | Zeta | `search_only` | [open](https://www.zeta.tech/in/careers) | Automated search proposal; requires read-only verification and H2 review. |
| 330 | P3 | Zoho | `search_only` | [open](https://www.zoho.com/careers/) | Automated search proposal; requires read-only verification and H2 review. |

## Evidence and validation

- Ranked search evidence exists for all 280 seed rows that originally contained only Google search hints.
- Read-only probes used public URLs, a truthful client identifier, timeouts, bounded responses, and sanitized diagnostics; no credentials or page bodies are tracked.
- Hosted-ATS fingerprints were applied only when one unambiguous supported configuration was present. Citi and Arm retained search-only classification because multiple public boards were detected.
- The canonical registry reconciles 330/330 companies, contains zero enabled sources, and preserves all P1/P2/P3 priorities and source ranks.
- Detailed proposal evidence: `data/source_discovery_proposals.json`.
- Disabled runtime registry: `config/company_sources.json`.

## Recorded decision

The approved package accepts the 267 verified source baselines; keeps the 0 access concerns, 63 conflicts, and 0 oversized boards disabled without dropping any company; and uses the recommended adapter priority beginning with Ashby. The later access-concern recheck reduced observed access concerns without expanding permissions or enabling any source.
