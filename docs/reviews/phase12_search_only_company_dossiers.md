# Phase 12 company decision ledger

This ledger accounts for every one of the 238 `search_only` records in release order. It records a
discovery decision, not an activated source. Route codes are defined in
`phase12_search_only_discovery.md`.

Confidence describes confidence in the proposed next route, not production readiness. `EA` rows
still require the same adapter-family validation as existing sources. `CA` and `NF` rows still need
fixtures and independent replay. `RD`, `ME`, and `RS` rows are intentionally unresolved for runtime
collection.

## P1 companies (53)

| Rank | Company | Route | Proposed handling | Confidence |
|---:|---|---|---|---|
| 4 | Adobe | NF | Build a Phenom-family adapter from the official search/results and detail surfaces; validate India filters, pagination, IDs, and dates. | High |
| 7 | Meta | RD | Inspect the official careers inventory's public requests; replay listing, India filtering, and details before choosing custom versus hosted-family handling. | Medium |
| 8 | Atlassian | CA | Build a bounded custom adapter for the official searchable inventory after capturing and replaying its public listing/detail requests. | Medium |
| 10 | Sanas | NF | Build a Rippling ATS adapter from the official careers page's `ats.rippling.com` board and validate the complete board. | High |
| 12 | Moloco | RD | Keep the official careers page; capture its public inventory endpoint and verify India coverage and stable details. | Medium |
| 13 | Postman | RD | Replay the official careers search request and detail links; implement deterministically if enumeration is public. | Medium |
| 14 | Rippling | RD | Discover the public source behind Rippling's own careers UI; do not assume its customer ATS is self-hosted the same way. | Medium |
| 15 | Rubrik | EA | Resolve the official Greenhouse board token implied by the careers link, then run the existing Greenhouse full-family checks. | Medium |
| 17 | GitLab | CA | Use GitLab's official all-jobs inventory; capture its generated-data source and build a bounded custom adapter with remote-location handling. | Medium |
| 18 | Slack | EA | Map the official Salesforce Workday `Slack` board to the existing Workday adapter and run full validation. | High |
| 19 | Google | CA | Replace the help article with Google's current official jobs results page and build a custom public-search adapter with India filters. | High |
| 20 | Microsoft | CA | Build a custom adapter for the official Microsoft careers search API/UI; verify all India pages and stable job IDs. | High |
| 21 | Oracle / OCI | EA | Resolve OCI roles on Oracle's public Oracle Cloud board and use the existing Oracle Cloud adapter. | High |
| 22 | Zerodha | TE | Replace the Zerodha Fund House URL with `careers.zerodha.com`; monitor and validate its current zero-openings state. | High |
| 23 | Amazon / AWS | CA | Use the official `amazon.jobs` inventory, preserving AWS ownership as a source filter; replay search pagination and details. | High |
| 24 | Apple | CA | Build a bounded adapter for Apple's official jobs search with India selected; verify pagination, detail descriptions, and date semantics. | High |
| 25 | InMobi | RD | Capture and replay the official careers listing source; verify that India roles are complete and details are public. | Medium |
| 29 | Broadcom | EA | Verify Broadcom's external Workday tenant and map it to the existing Workday adapter. | Medium |
| 30 | Cockroach Labs | EA | Resolve the official Greenhouse token from the custom careers page and validate with the existing Greenhouse adapter. | Medium |
| 31 | Confluent | RD | The saved detail URL is stale/rate-limited; rediscover the current official inventory and replay its public endpoint before mapping. | Low |
| 36 | Kore.ai | RD | Inspect the official careers filters and capture the public inventory/detail requests; select hosted or custom handling from replay evidence. | Medium |
| 39 | Yellow.ai | RD | Replay the official careers inventory and validate India coverage; no stable hosted-family signature was proven. | Medium |
| 40 | LinkedIn | CA | Build a custom adapter for LinkedIn's own official careers site, not consumer LinkedIn Jobs; validate India locations and detail pages. | Medium |
| 46 | Qure.ai | CA | Use the official `jobs.qure.ai` inventory; capture its structured source and implement a bounded custom adapter. | Medium |
| 49 | TrueFoundry | RD | Capture and replay the official careers listing source; preserve any valid empty state and detail links. | Medium |
| 51 | Airbnb | CA | Build a bounded custom adapter for Airbnb's official positions search with India/remote location logic. | Medium |
| 52 | FalconX | EA | Resolve the hosted Greenhouse board/token behind official open roles, then run existing Greenhouse validation. | Medium |
| 53 | Stripe | CA | Build a custom adapter for Stripe's official careers search, including pagination, locations, and job details. | High |
| 56 | Intuit | CA | Replay the official India careers inventory and build a custom adapter with stable IDs and dates. | Medium |
| 57 | Maxim AI | TE | Replace the single-role URL with the official careers page and monitor its explicit current no-open-roles state. | High |
| 58 | Salesforce | EA | Use the official Salesforce Workday board with `country=India`; validate the tenant with the existing Workday adapter. | High |
| 60 | ServiceNow | CA | Build a custom adapter for the official India careers inventory; the UI exposes a sizable enumerated India result set. | High |
| 62 | Booking.com | RD | Official page exposes iCIMS-related links, but observed links include internal/login surfaces; find and replay the public external board first. | Low |
| 63 | Coupang | CA | Build a custom adapter for the official Bengaluru inventory and validate all pages/details. | High |
| 65 | Okta | EA | Resolve the official hosted Greenhouse board token and validate with the existing Greenhouse adapter. | Medium |
| 66 | Twilio | CA | Replay Twilio's official careers search and build a bounded custom adapter if the public request is stable. | Medium |
| 71 | Index Exchange | RD | Capture the official careers listing endpoint and independently replay it; no safe ATS mapping was proven. | Medium |
| 72 | Roku | CA | Build a custom adapter from Roku's Bengaluru careers inventory after replaying listing and detail calls. | Medium |
| 73 | Eightfold AI | EA | Validate Eightfold's own public careers tenant with the existing Eightfold adapter. | High |
| 74 | Flipkart | CA | Build a custom adapter for the official jobs list, including filters, pagination, details, and dates. | High |
| 75 | Meesho | CA | Replay the official jobs inventory and implement a bounded custom adapter with India-location normalization. | Medium |
| 76 | PhonePe | CA | Capture and replay the official careers inventory; implement custom deterministic collection. | Medium |
| 78 | Swiggy | CA | Build a custom adapter for the official careers search after verifying public listing/detail requests. | Medium |
| 79 | Zomato / Blinkit | RS | Replace the privacy-policy URL; start with Blinkit's official careers surface and determine whether Zomato shares or separates inventory. | Low |
| 83 | D. E. Shaw India | CA | Use the official D. E. Shaw India careers inventory; build a custom adapter for its enumerated roles and details. | High |
| 85 | Mayhem Studios | ME | Official site identifies the company but exposes no reliable enumerating job inventory; monitor the official site and company hiring channel. | Low |
| 86 | Mrsool | ME | Official help directs applicants to LinkedIn rather than an official job board; retain monitored/manual discovery. | High |
| 87 | NK Securities | EA | Use the official `job-boards.greenhouse.io/nksecuritiesresearch` board with the existing Greenhouse adapter. | High |
| 88 | Quadeye | RD | Official site is identity-safe but did not expose a stable inventory in browser content; perform network replay before falling back to monitoring. | Low |
| 91 | Tower Research Capital | CA | Replay Tower's official careers search and build a bounded custom adapter with India filters. | Medium |
| 92 | X | RS | Discard the Quantbox URL and rediscover the official `careers.x.com` inventory; verify company ownership before any ATS mapping. | Low |
| 94 | CRED | EA | Use the official Lever board exposed by CRED and validate with the existing Lever adapter. | High |
| 95 | Navi | NF | Build a TurboHire-family adapter from Navi's official careers link and validate list/detail/date behavior. | High |

## P2 companies (82)

| Rank | Company | Route | Proposed handling | Confidence |
|---:|---|---|---|---|
| 99 | Noon | TE | Monitor the official Noon careers page's explicit no-open-positions state and add a completeness assertion. | High |
| 101 | Walmart Global Tech | CA | Replay the official technology-careers search and build a bounded custom adapter for India roles. | Medium |
| 108 | Tenstorrent | RD | Inspect the official Howler-built careers UI, replay its listing/detail source, then choose reusable-family or custom handling. | Medium |
| 109 | AMD | RD | iCIMS signals observed were internal-only; locate and replay AMD's public external jobs inventory before selecting an adapter. | Low |
| 110 | Intel | CA | Build a custom adapter for Intel's official jobs search with India filtering and stable detail retrieval. | Medium |
| 111 | Qualcomm | EA | Use the official Qualcomm Workday `External` board with the existing Workday adapter. | High |
| 112 | Samsung R&D | RS | Replace the Samsung Research Japan URL; verify the correct SRI Bangalore/Noida public inventory and its ownership. | Low |
| 113 | Quantiphi | EA | Validate Quantiphi's official Workday tenant using the existing Workday adapter. | High |
| 114 | Tiger Analytics | CA | Replay the official current-openings search and build a bounded custom adapter. | Medium |
| 115 | AQR Capital Management | EA | Resolve the Greenhouse token behind AQR's official `careers.aqr.com/jobs?gh_jid=` links and validate it. | High |
| 116 | Dolat Capital | CA | Use Dolat's official careers listings; implement a small static/custom adapter with detail and date evidence. | Medium |
| 117 | IMC Trading | CA | Build a bounded custom adapter for IMC's official careers search with India locations. | Medium |
| 119 | Optiver | CA | Replay Optiver's official opportunities search and implement deterministic India collection. | Medium |
| 120 | Point72 | CA | Use Point72's official openings search; capture and replay its public listing/detail requests. | Medium |
| 121 | Squarepoint Capital | CA | Build a custom adapter for the official open-opportunities page; it enumerates filters, Bangalore locations, and `gh_jid` details. | High |
| 122 | Trexquant Investment | CA | Implement a bounded adapter for Trexquant's official careers inventory and details. | Medium |
| 123 | WorldQuant | CA | Replay WorldQuant's official careers search and implement deterministic India filtering. | Medium |
| 125 | AarogyaAI | RS | The saved authenticated portal and search results did not prove a public AarogyaAI board; do not substitute the unrelated AarogyaID company. | Low |
| 126 | Aganitha | CA | Parse the official careers page's visible roles and details with a small static/custom adapter. | High |
| 128 | Altimate.ai | CA | Use the official company page's four-role careers inventory; capture role links and implement a small custom adapter. | High |
| 129 | Arbix AI | RS | The contact URL has no inventory and search results collide with similarly named firms; re-establish official identity before monitoring. | Low |
| 131 | Arya.ai | CA | Build a small custom adapter for Arya.ai's official careers inventory and role details. | Medium |
| 132 | Athina AI | ME | Official product site exposes no enumerating careers inventory; monitor the official site/company channel for a board appearing. | Medium |
| 134 | Binocs | NF | Treat the official public Notion open-positions page as a reusable Notion-style source if stable enumeration replay succeeds. | Medium |
| 135 | Blend AI | RS | The saved demo URL and search results are identity-ambiguous; verify the intended India AI company before adapting any Blend careers page. | Low |
| 136 | Boltzmann Labs | RS | Resolve the intended `boltzmann.co` versus Boltzmann Research identity; current evidence supports email hiring, not a proven board. | Low |
| 137 | BrainsightAI | ME | Official site lacks a job board; current roles appear through company posts/forms, so retain monitored/manual discovery. | High |
| 138 | Cognite | RD | Capture and replay Cognite's official careers inventory and determine its underlying hosted or custom source. | Medium |
| 139 | CoRover | CA | Parse the official careers page and role details with a bounded custom adapter. | Medium |
| 140 | CropIn | CA | Replay CropIn's official careers listings and implement a custom adapter with India filtering. | Medium |
| 141 | DIAGNO Systems | ME | Official site exposes product/contact material but no careers inventory; retain monitored/manual discovery. | High |
| 146 | FinbotsAI | RS | Discard the Crunchbase contact page; verify the official FinbotsAI employer site and locate an identity-safe hiring source. | Low |
| 147 | Flutura | RS | The saved source is an unrelated academy; verify Flutura's post-acquisition hiring path before deciding whether it remains a separate employer. | Low |
| 148 | Forus Health | CA | Build a small deterministic adapter for the official careers page and its application/details. | Medium |
| 149 | GalaxEye | CA | Use the official job portal; replay listing and details and implement a bounded custom adapter. | High |
| 150 | Gnani.ai | CA | Use the official `careers.gnani.ai` inventory and implement a small custom adapter after endpoint replay. | High |
| 152 | Hyperleap AI | CA | Parse the official careers page's current roles and details with a bounded custom adapter. | Medium |
| 153 | HyperVerge | RD | Capture and replay the official careers inventory; select hosted versus custom handling from the public endpoint evidence. | Medium |
| 154 | InVideo | CA | Use the official careers site and build a custom deterministic adapter for its roles and details. | Medium |
| 155 | KOGO AI | ME | Official company pages expose no enumerating jobs inventory; retain monitored/manual discovery. | High |
| 156 | Krutrim | RS | Discard the unrelated Krutrim Insights URL; identify the official Krutrim employer board before implementation. | Low |
| 157 | LimeChat | NF | Build a Zoho Recruit adapter from the official `limechat.zohorecruit.in` board and validate its public listing/details. | High |
| 158 | Locus | NF | Replace the redirecting saved URL with Locus's official Freshteam board and build a Freshteam adapter. | High |
| 159 | Mad Street Den | RS | Discard the third-party careers-intelligence page; locate the official Vue.ai/Mad Street Den hiring inventory. | Low |
| 160 | Miko | CA | Parse Miko's official careers inventory and role details with a bounded custom adapter. | Medium |
| 161 | Murf AI | ME | Official site sends “open roles” to LinkedIn rather than a public company board; retain monitored/manual discovery. | High |
| 162 | Nektar AI | NF | The official `/careers` route redirects to a public Coda roles document; implement a Coda-style adapter only if stable replay is proven. | High |
| 163 | Netra | RS | Verify that the saved Netra Technosys site is the intended AI employer; do not adapt a possible homonym. | Low |
| 164 | NeuralGarage | NF | Build a PyjamaHR-family adapter from the official `jobs.pyjamahr.com/neuralgarage` board. | High |
| 165 | Neuralzome | ME | The official careers page contains placeholder template roles/text, so treat it as invalid inventory and monitor manually. | High |
| 166 | Nexstem | CA | Parse the official public Google Sites careers page; validate role links and update behavior with a small custom adapter. | Medium |
| 167 | Neysa | CA | Build a bounded custom adapter for Neysa's official job-openings page and role details. | Medium |
| 168 | Niramai | CA | Parse the official careers page and role details with a small deterministic adapter. | Medium |
| 169 | Nurix AI | ME | Replace the obsolete Webflow site; current official hiring is visible through company channels but no public enumerating board was proven. | Medium |
| 170 | Peptris | CA | Use the official careers page and implement a static/custom adapter with explicit empty-state handling. | Medium |
| 171 | Perceptyne | CA | Parse the official career page and public application/details with a bounded custom adapter. | Medium |
| 172 | Poppulo | RD | Capture and replay the official careers inventory before selecting its hosted family or a custom adapter. | Medium |
| 173 | Portkey | RS | Discard the Portkey Games URL; the intended AI-gateway company is now part of Palo Alto Networks, so establish its current hiring path. | Low |
| 174 | Predii | CA | Parse Predii's official careers inventory with a small custom adapter and valid-empty handling. | Medium |
| 175 | QpiAI | CA | Use the official careers page's visible roles; implement a bounded custom adapter with detail retrieval. | High |
| 176 | Quant AI | CA | Parse the official careers page and role details with a small deterministic adapter. | Medium |
| 179 | Ripik.AI | TE | Monitor the official careers page's explicit no-current-openings state and prove completeness. | High |
| 180 | Saptang Labs | ME | Official company site exposes no reliable enumerating job inventory; retain monitored/manual discovery. | Medium |
| 181 | SciSpace | ME | Official site has no careers inventory; current roles are on Wellfound, so keep a monitored/manual exception rather than treating third-party data as official. | Medium |
| 182 | Signzy | CA | Replay Signzy's official careers listings and implement a custom adapter with India-location and detail normalization. | Medium |
| 183 | SigTuple | ME | Official site has no current enumerating board; company posts/email supply openings, so retain monitored/manual discovery. | High |
| 184 | Skild AI | CA | Generalize the official single-role detail into a listing/detail adapter only after finding a complete public inventory or valid-empty contract. | Medium |
| 185 | Skit.ai | CA | Replay the official India careers inventory and implement a bounded custom adapter. | Medium |
| 186 | Slang Labs | ME | Third-party page has no current openings and the official site exposes no job board; retain monitored/manual discovery. | High |
| 188 | Steps AI | CA | Parse the official careers page's roles and details with a small deterministic adapter. | Medium |
| 189 | Supervity | CA | Replay the official careers inventory and implement a bounded custom adapter. | Medium |
| 190 | Tekion | CA | Build a custom adapter for Tekion's official careers search with India filters, pagination, and details. | Medium |
| 191 | TheMathCompany | CA | Replay the official careers search and implement deterministic collection and details. | Medium |
| 192 | Tredence | CA | Use Tredence's official careers inventory; build a bounded custom adapter with India normalization. | Medium |
| 193 | Tricog | CA | Parse the official careers page and role details with a small custom adapter. | Medium |
| 194 | Upscale AI | CA | Parse the official careers inventory and details with a bounded custom adapter. | Medium |
| 196 | Vayavya Labs | CA | Replace Glassdoor with the official site's current-openings path and build a small static/custom adapter. | High |
| 197 | Writesonic | RD | Capture and replay the official careers inventory; map to an existing ATS if a stable public board token is confirmed. | Medium |
| 198 | Wysa | ME | Official careers content currently exposes a role PDF rather than a complete board; retain monitored/manual discovery. | High |
| 199 | Xanadu.ai | RD | Use the official `/careers` route, capture its client-rendered listing source, and independently replay it. | Medium |
| 200 | ZestIot | CA | Parse the official careers page and public role/application details with a small custom adapter. | Medium |
| 202 | Zoniqx | ME | Saved contact page exposes no enumerating careers inventory; retain monitored/manual discovery. | High |

## P3 companies (103)

| Rank | Company | Route | Proposed handling | Confidence |
|---:|---|---|---|---|
| 203 | American Express | EA | Validate the official American Express Oracle Cloud site with the existing Oracle Cloud adapter. | High |
| 206 | BlackRock / Aladdin | CA | Build a bounded custom adapter for BlackRock's official India search, including pagination and details. | High |
| 207 | Citi | RD | Eightfold and Workday signals both appeared; replay the official `jobs.citi.com` source and choose only the actual external inventory. | Low |
| 208 | Deutsche Bank | CA | Replay Deutsche Bank's official role search and implement deterministic India collection. | Medium |
| 209 | Fidelity Investments | CA | Build a custom adapter for Fidelity's official India jobs search and details. | Medium |
| 210 | Goldman Sachs | CA | Replay Goldman's official careers search, implement India filtering, and preserve stable requisition IDs. | Medium |
| 211 | HSBC | CA | Build a custom adapter for HSBC's official jobs inventory with India filters and detail retrieval. | Medium |
| 214 | Mastercard | EA | Validate Mastercard's official Workday tenant with the existing Workday adapter. | High |
| 215 | Moody's | RD | Capture and replay the official Moody's careers inventory before selecting hosted-family or custom handling. | Medium |
| 216 | Morgan Stanley | EA | Use the official `morganstanley.eightfold.ai` inventory with the existing Eightfold adapter. | High |
| 218 | PayU | NF | Build a Trakstar-family adapter from the official `payu.hire.trakstar.com` board. | High |
| 219 | S&P Global | RD | iCIMS and Workday signals were ambiguous; replay the official external inventory and reject internal/login-only links. | Low |
| 220 | UBS | CA | Replay UBS's official jobs search and implement deterministic India filtering and details. | Medium |
| 222 | Wells Fargo | CA | Build a bounded custom adapter for the official Wells Fargo jobs search with India filters. | Medium |
| 223 | Arista Networks | RD | Capture the official careers inventory's public source; map to an existing ATS only if a stable board token is proven. | Medium |
| 224 | Automattic | CA | Parse Automattic's official all-jobs page with remote-location normalization and stable details. | High |
| 225 | Cisco | CA | Replace the stale page with Cisco's official SearchJobs inventory and build a bounded custom adapter. | High |
| 226 | Clazar | ME | Replace Levels.fyi with the official site; current hiring is via email/forms rather than an enumerating board. | High |
| 228 | Cloudflare | RD | Official page client-loads roles; capture and replay the public listing endpoint before implementing. | Medium |
| 229 | Cohesity | RD | Capture and replay the official careers search; select an existing ATS only from unambiguous external-board evidence. | Medium |
| 230 | Coinbase | EA | Resolve the official hosted Greenhouse board/token behind Coinbase positions and validate with the existing adapter. | Medium |
| 231 | Compass | EA | Use the official `gh_board=compassindia` evidence to resolve the Greenhouse token and validate it. | High |
| 232 | Crunchyroll | EA | Resolve the official Greenhouse board token and validate with the existing Greenhouse adapter. | Medium |
| 233 | Druva | CA | Replay Druva's official careers inventory and build a bounded custom adapter for India roles. | Medium |
| 234 | Elastic | CA | Build a custom adapter for Elastic's official distributed-team jobs inventory and India/remote location rules. | Medium |
| 236 | GitHub | RD | iCIMS links observed include multiple internal/external surfaces; identify and replay only the public external board. | Low |
| 237 | Kredivo | CA | Generalize the official role/detail route into a complete careers adapter after locating the inventory endpoint. | Medium |
| 238 | Media.net | CA | Replay Media.net's official careers site and implement deterministic India collection. | Medium |
| 239 | MongoDB | CA | Build a bounded custom adapter for the official all-teams inventory, which currently enumerates hundreds of roles. | High |
| 240 | Navan | EA | Resolve Navan's official hosted Greenhouse board token and validate with the existing adapter. | Medium |
| 241 | Nutanix | EA | Verify Nutanix's external Workday tenant and validate with the existing Workday adapter. | Medium |
| 242 | Opendoor | EA | Resolve the official Greenhouse board token and validate with the existing adapter. | Medium |
| 243 | p0 | CA | Parse the official small careers page with a deterministic static/custom adapter and valid-empty handling. | Medium |
| 247 | SentinelOne | RD | Capture and replay the official careers inventory; map to hosted ATS only after token/tenant proof. | Medium |
| 249 | Skillz | CA | Replay the official careers inventory and implement a bounded custom adapter. | Medium |
| 250 | Snowflake | RD | Capture and replay Snowflake's official job-search source, then select hosted-family or custom handling. | Medium |
| 251 | TestGorilla | EA | Use the official Ashby board linked by TestGorilla and validate with the existing Ashby adapter. | High |
| 252 | ThoughtSpot | EA | Resolve the official Greenhouse board token and validate with the existing Greenhouse adapter. | Medium |
| 253 | Toptal | CA | Parse Toptal's official careers inventory with remote/India location normalization. | Medium |
| 255 | Zscaler | CA | Replay the official jobs search and build a bounded custom adapter with India filters and details. | Medium |
| 257 | Applied Materials | RD | Capture and replay the official India jobs inventory; select its hosted family only from stable public evidence. | Medium |
| 258 | Arm | RD | Observed iCIMS links require external-board disambiguation; replay the official public inventory before implementation. | Low |
| 260 | KLA | EA | Use KLA's current official Workday search rather than the unrelated saved URL; validate with the existing Workday adapter. | High |
| 261 | Lam Research | EA | Verify Lam Research's official external Workday tenant and run existing Workday validation. | Medium |
| 262 | Marvell | EA | Validate Marvell's official Workday tenant with the existing Workday adapter. | High |
| 263 | MediaTek | CA | Build a custom adapter for MediaTek's official jobs inventory, including India location and experience filters. | High |
| 264 | Micron | RD | Workday and Eightfold signals were both observed; replay Micron's official external inventory before choosing. | Low |
| 266 | Renesas | EA | Verify the hosted SmartRecruiters source behind `jobs.renesas.com` and validate with the existing SmartRecruiters adapter. | Medium |
| 267 | Synopsys | EA | Verify Synopsys's official external Workday tenant and validate with the existing Workday adapter. | Medium |
| 268 | Texas Instruments | EA | Validate the official Texas Instruments Oracle Cloud board with the existing Oracle Cloud adapter. | High |
| 269 | Western Digital / SanDisk | RS | The companies have separated; replace the support URL and decide whether the seed needs two independently owned career sources. | Low |
| 270 | Aptiv | EA | Verify Aptiv's official external Workday tenant and validate with the existing Workday adapter. | Medium |
| 271 | Ather Energy | CA | Build a custom adapter for the official all-jobs inventory, which exposes teams, locations, and role pages. | High |
| 272 | Ati Motors | RS | Discard the third-party intelligence page and locate Ati Motors' official enumerating careers source. | Low |
| 274 | CynLr | CA | Find the complete inventory behind the official single-role page, or implement it with a proven valid-empty/list contract. | Medium |
| 275 | Detect Technologies | CA | Replay the official careers listings and implement a bounded custom adapter. | Medium |
| 276 | GreyOrange | NF | Replace the contact page with the official `careers.greyorange.com/greyorange` board and implement its hosted-family contract. | High |
| 277 | Harman | CA | Use Harman's official SearchJobs inventory; build a bounded custom adapter with pagination and India filters. | High |
| 278 | ideaForge | NF | Build a Webbtree-family adapter from the official ideaForge careers link and validate listing/detail behavior. | High |
| 279 | KPIT | CA | Replay KPIT's official careers inventory and implement deterministic India collection. | Medium |
| 280 | Mercedes-Benz Research and Development India | CA | Use the official Mercedes job search filtered to MBRDI; build a bounded custom adapter for its enumerated roles. | High |
| 281 | Minus Zero | RD | Discard the unrelated consumer-product URL; verify the official Minus Zero site and replay the public Zappyhire candidate if still linked. | Low |
| 282 | Myelin Foundry | CA | Parse the official careers page and role details with a small deterministic adapter. | Medium |
| 284 | Ola Electric | CA | Replay Ola Electric's official careers inventory and implement a bounded custom adapter. | Medium |
| 286 | Samsara | CA | Build a custom adapter for Samsara's official careers search with India/remote normalization. | Medium |
| 287 | Tata Elxsi | CA | Replay the official careers inventory and implement deterministic India collection. | Medium |
| 288 | Unbox Robotics | CA | Parse the official careers page and role details with a small custom adapter. | Medium |
| 289 | Volvo Group | CA | Build a bounded custom adapter for Volvo's official jobs search with India filters, pagination, and details. | Medium |
| 290 | ACKO | CA | Replay ACKO's official careers inventory and implement deterministic India collection. | Medium |
| 291 | Apna | CA | Replace the consumer homepage with `careers.apna.co`; build a custom adapter for its 100+ enumerated roles. | High |
| 292 | BillDesk | CA | Generalize BillDesk's official role page into a small listing/detail adapter after finding its complete jobs index. | Medium |
| 293 | BlackBuck | RD | Capture and replay the official Team BlackBuck hiring inventory; preserve a valid-empty state if no roles are enumerated. | Medium |
| 294 | BrowserStack | EA | Validate BrowserStack's official Workday tenant with the existing Workday adapter. | High |
| 295 | Chargebee | CA | Replay Chargebee's official join-us inventory and implement a bounded custom adapter. | Medium |
| 297 | CoinDCX | CA | Use the official CoinDCX careers site and implement deterministic listing/detail collection. | Medium |
| 298 | CoinSwitch | NF | Replace the ventures page with the official Recruiterflow board and build a Recruiterflow-family adapter. | High |
| 299 | Delhivery | RD | Official careers UI was client-loading; capture and replay its public inventory endpoint before implementation. | Medium |
| 300 | Dream11 / Dream Sports | RS | The former official Lever board is obsolete and the current site exposes no proven live board; rediscover the official inventory. | Low |
| 301 | ElasticRun | CA | Replay ElasticRun's official careers listings and implement a bounded custom adapter. | Medium |
| 303 | Games24x7 | EA | Replace the contact page with the official Games24x7 Darwinbox board and validate using the existing Darwinbox adapter. | High |
| 304 | Groww | NF | Build a SenseHQ-family adapter from the official `groww.sensehq.com/careers` inventory. | High |
| 306 | Innovaccer | CA | Replay Innovaccer's official careers inventory and build a bounded custom adapter. | Medium |
| 307 | Jio Platforms / Haptik | NF | Generalize the official Haptik Freshteam source into a Freshteam adapter and enumerate the whole board, not one role. | High |
| 308 | Jupiter | RS | The saved `tryjupiter.com` source is a different US company; rediscover the intended Indian fintech Jupiter careers source. | Low |
| 309 | Juspay | CA | Replay Juspay's official careers inventory and implement deterministic India collection. | Medium |
| 310 | Lenskart | CA | Parse the official Lenskart careers inventory and role details with a bounded custom adapter. | Medium |
| 311 | MakeMyTrip | CA | Build a custom adapter for the official MakeMyTrip careers search with pagination and details. | Medium |
| 312 | Moglix | CA | Replay Moglix's official career inventory and implement deterministic collection. | Medium |
| 313 | Myntra | CA | Discard the scam-like third-party PDF and use the official `jobs.myntra.com/home` inventory for a custom adapter. | High |
| 314 | Nykaa | CA | Build a bounded custom adapter for Nykaa's official careers search and details. | Medium |
| 315 | OfBusiness | ME | Official company site exposes no public enumerating careers inventory; retain monitored/manual discovery. | High |
| 316 | OYO | ME | The saved help/seek route does not expose a current official inventory; monitor OYO/PRISM's official hiring channels. | Low |
| 318 | Pine Labs | CA | Use the official open-jobs inventory and implement a bounded custom adapter. | High |
| 319 | Policybazaar | CA | Replay Policybazaar's official careers inventory and implement deterministic collection. | Medium |
| 321 | Practo | CA | Find the careers index behind the official role route and build a complete listing/detail adapter, not a single-role source. | High |
| 322 | ShareChat / Moj | CA | Replay ShareChat's official careers inventory and implement a bounded custom adapter. | Medium |
| 323 | Slice | RS | Discard `slice.careers`, which is a US restaurant-software company; locate the Indian fintech Slice's official board. | High |
| 324 | Udaan | RS | Discard the unrelated/expired `udaanindia.com` route; locate an official source for the Indian eB2B company or retain manual monitoring. | High |
| 326 | Urban Company | CA | Replay the official Urban Company careers inventory and implement deterministic collection. | Medium |
| 327 | Whatfix | CA | Build a bounded custom adapter for Whatfix's official careers inventory and role details. | Medium |
| 328 | Zepto | RD | Capture and replay Zepto's official client-rendered careers inventory before implementation. | Medium |
| 329 | Zeta | CA | Replay Zeta's official India careers inventory and implement a bounded custom adapter. | Medium |
| 330 | Zoho | CA | Build a custom adapter for Zoho's official careers inventory, filters, and role details. | Medium |
