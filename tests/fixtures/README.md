# Adapter fixtures

Fixtures preserve the public source's response shape while keeping examples small, deterministic,
and free of credentials, cookies, or full production payloads.

## Atomicwork Webflow

- `atomicwork/healthy.html` and `healthy_sitemap.xml`: two same-origin Webflow collection rows
  reconciled with the official public sitemap.
- `atomicwork/empty.html` and `empty_sitemap.xml`: the explicit Webflow empty-collection shape and
  a sitemap without detail pages.
- `atomicwork/malformed.html`: a collection row missing its required title.
- `atomicwork/duplicate.html`: two rows that resolve to the same path-derived external ID.
- `atomicwork/off_origin.html`: an application row whose detail link leaves the approved origin.
- `atomicwork/detail.html`: the official detail-page structure for title, location, rich-text
  description, and the separately retained legacy application URL.

The adapter treats the official detail URL as canonical, derives identity from its `/careers/`
path, and keeps publication evidence unknown because the source exposes no trustworthy posting
date.

## Ashby

- `ashby/healthy.json`: two representative listings, including secondary locations and the
  listing-payload description fields.
- `ashby/empty.json`: the observed healthy empty-board shape.
- `ashby/malformed.json`: a jobs collection with missing required fields.
- `ashby/access_block.html`: a sanitized challenge-page response used to prove content-type and
  access failures cannot be mistaken for valid job data.

Ashby's public posting endpoint returns one complete `jobs` collection without page tokens. The
adapter therefore reports one page and validates the entire collection; paginated fixture behavior
is not applicable to this adapter family.

## Greenhouse

- `greenhouse/healthy.json`: two representative jobs with full content, including one reliable
  `first_published` value and one update-date fallback.
- `greenhouse/empty.json`: a complete zero-job response whose `meta.total` agrees with `jobs`.
- `greenhouse/malformed.json`: a listing missing required job fields.
- `greenhouse/incomplete.json`: a deliberately inconsistent `meta.total` used to reject incomplete
  collection results.

Greenhouse's public list endpoint returns one `jobs` collection and a `meta.total` completeness
check. The adapter requests `content=true` so descriptions are available without per-job requests.

## Lever

- `lever/page_1.json` and `lever/page_2.json`: a complete multi-page collection with stable IDs,
  descriptions, canonical URLs, multiple locations, workplace type, and source-created timestamps.
- `lever/empty.json`: a valid zero-job response.
- `lever/malformed.json`: a listing missing the required title.
- `lever/html_description_fallback.json`: a regression case observed on Bazaarvoice where
  `descriptionPlain` is empty even though the documented HTML `description` is populated.
- `lever/lists_only_description.json`: a regression case observed on BarRaiser where content is
  present only in Lever's structured requirement lists.
- `lever/missing_description.json`: a regression case observed on BarRaiser and Paytm where the
  public listing and detail APIs contain no description content at all.

The public Postings API uses `skip` and `limit` pagination and exposes full descriptions in each
list response. The source-created timestamp is retained as uncertain evidence because the public
API documentation does not establish it as a publication date.

## Oracle Cloud

- `oracle_cloud/page_1.json` and `oracle_cloud/page_2.json`: the public Candidate Experience
  search envelope with count-checked offset pagination, stable requisition IDs, published dates,
  primary and secondary locations, and workplace metadata.
- `oracle_cloud/empty.json`: a complete zero-job search result.
- `oracle_cloud/malformed.json`: a requisition missing its required title.
- `oracle_cloud/detail.json`: a matching public detail response with the complete description,
  qualifications, responsibilities, and secondary locations.
- `oracle_cloud/access_block.html`: a sanitized blocked-page response.

The public Candidate Experience search resource returns one search envelope whose
`TotalJobsCount`, `Limit`, `Offset`, and `requisitionList` fields drive pagination. Full job text is
retrieved only from the separate public requisition-detail resource.
