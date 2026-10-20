# Personal Job Watcher

A small Python watcher for public LinkedIn, Internshala, Indeed, and Naukri listings. It filters and scores jobs against one editable profile, then sends the selected jobs to Telegram as one digest per run. An optional Wellfound collector uses headless Chrome to read public search pages and is disabled by default while its reliability is evaluated. Applications stay manual.

## Set your profile

Supply a validated JSON profile, or edit the `Profile` defaults in `profiles.py`. The profile holds both matching preferences and search settings, so a personal copy of this repository needs no code changes. The committed values are **examples for testing**, not a claim about the user's experience or location. The script automatically uses dry-run mode while the active profile is an example, so it cannot send generic-profile alerts.

To use a profile without editing Python:

```sh
cp profile.example.json profile.json
# Edit profile.json with your preferences; keep is_example true during testing.
.venv/bin/python main.py --profile profile.json --dry-run
```

`profile.json` is ignored by Git. The version-1 document contains `version`, an explicit boolean `is_example`, and a `profile` object. Unknown fields, invalid types, and unsupported choices stop collection before requests or delivery. Omitted profile fields inherit the example defaults. Only set `is_example` to `false` after entering real preferences and reviewing a dry run. The original `config.py` profile and `PROFILE_IS_EXAMPLE` flag remain the fallback.

The profile adds exact company-name exclusions, actual experience (`experience_years`), and `career_stage`: `early`, `experienced`, or `any`. Early-career profiles retain the senior-title exclusion; experienced and unrestricted profiles can consider senior titles while still enforcing `max_required_years`. Explicit mandatory experience in descriptions is checked alongside source fields. Listings whose description asks for a registration, training, or similar fee or deposit are rejected, unless the text says there is no such fee. LinkedIn's seniority label from fetched details counts as early-career evidence for Internship and Entry level; early-career profiles reject Mid-Senior, Director, and Executive levels unless the title names an entry-level role. Preferred experience and references to senior colleagues do not count as mandatory requirements.

For unattended runs, set `JOB_WATCHER_PROFILE_PATH` to a JSON file, or provide the complete document in `JOB_WATCHER_PROFILE_JSON`. On GitHub Actions, a repository variable named `JOB_WATCHER_PROFILE_PATH` can name a profile file committed to the repository; the file is then public in a public repository. An explicit `--profile` file takes precedence, followed by the environment file and then the JSON environment value. On GitHub Actions, an optional repository secret named `JOB_WATCHER_PROFILE_JSON` supplies the profile without committing personal data. With no supplied profile, the example and its delivery protection remain active.

Search settings are `linkedin_searches`, `linkedin_location`, `indeed_searches`, `indeed_country`, `indeed_location`, `naukri_searches`, `naukri_location`, `internshala_urls`, and `wellfound_urls`; `alert_threshold` sets the score needed for an alert. `country_locations` lists whole locations that name only a country or region, such as `India`: a listing located just there cannot be ruled out by `allowed_locations` and is kept for review. In particular, configure the roles, skills, job types, maximum required experience, acceptable locations, remote/workplace preferences, each source's search terms and location, and Internshala pages. An empty `allowed_locations` means no location exclusion. Internshala and Naukri target India; the example Indeed country is also India. Search regions are independent of personal eligibility rules. The default searches and weights are starting points.

## Local use

Python 3.12 is used locally and in GitHub Actions. JobSpy is pinned to 1.2.0, which includes the updated Naukri adapter and uses `curl_cffi`. With `uv`:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python main.py --dry-run
```

Alternatively, create a Python 3.12 virtual environment with `venv` and use its `pip`. The first dry run can start without a state file; it neither saves state nor sends messages. An explicit `--report run-report.json` writes counts, duration, and source field coverage even in dry-run mode; the report contains no listing descriptions and the default report filename is ignored by Git.

To update an existing environment, rerun the install command. To collect only the new sources:

```sh
JOB_WATCHER_SOURCES=indeed,naukri .venv/bin/python main.py --dry-run
```

### JobSpy sources

LinkedIn, Indeed, and Naukri use a shared normalizer that preserves source IDs, descriptions, available compensation, skills, experience ranges, and known work arrangements. LinkedIn's existing state IDs remain compatible. A false remote flag alone does not establish onsite work; sparse fields stay unknown.

Indeed returns descriptions with search results. Naukri fetches details for each returned listing, bounded to 10 results per search across three example searches (at most 30 detail requests per run). Explicit Naukri experience ranges feed the eligibility filter, so a generic title requiring eight years is still rejected by the example early-career profile.

LinkedIn selectively fetches public descriptions for up to 20 promising new listings. Internshala enriches up to 10 promising listings with sparse descriptions, preserving actual skill requirements while excluding advertised courses and perks. Both skip processed jobs and explicit rule conflicts, prioritize initial relevance, retain search results after individual detail failures, and stop enrichment after three consecutive failures. Enrichment can include listings below the alert threshold because missing details may improve the assessment.

| Environment setting | Default | Purpose |
| --- | --- | --- |
| `JOB_WATCHER_SOURCES` | `linkedin,internshala,indeed,naukri` | Sources to collect; Wellfound is optional |
| `JOB_WATCHER_INDEED_COUNTRY` | `India` | Indeed country; use a supported JobSpy country name |
| `JOB_WATCHER_INDEED_LOCATION` | empty | Optional city/region search filter |
| `JOB_WATCHER_NAUKRI_LOCATION` | empty | Optional city search filter |
| `JOB_WATCHER_INDEED_RESULTS` | `20` | Maximum results per Indeed search |
| `JOB_WATCHER_NAUKRI_RESULTS` | `10` | Maximum results and detail requests per Naukri search |
| `JOB_WATCHER_LINKEDIN_DETAILS` | `20` | Detail fetches per run; hard cap 20, set 0 to disable |
| `JOB_WATCHER_INTERNSHALA_DETAILS` | `10` | Detail fetches per run; hard cap 10, set 0 to disable |
| `JOB_WATCHER_WELLFOUND_PAGES` | `2` | Pages per configured search; hard cap 2 |

Set `indeed_searches` and `naukri_searches` in the profile to tune the keywords; the `JOB_WATCHER_INDEED_COUNTRY`, `JOB_WATCHER_INDEED_LOCATION`, and `JOB_WATCHER_NAUKRI_LOCATION` variables override the profile when set. Indeed may match words in descriptions rather than titles; all results still pass through local rules. Its `hours_old` filter concerns addition to Indeed, while the employer posting date may be older; the evaluator checks posting age separately. Salary is retained when available, but was not disclosed in the initial live samples. [JobSpy documentation](https://github.com/speedyapply/JobSpy/blob/main/README.md)

Request errors logged internally by JobSpy are reported as query failures even if it returns an empty dataframe. A successful empty search is allowed, partial results are retained, and failure of one source does not prevent collection from another.

Once the profile is real, create a Telegram bot, get its bot token and your chat ID, and supply them as environment variables. The first local live run needs `--init-state` if `seen.json` does not exist. Subsequent runs use the existing state file.

```sh
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
.venv/bin/python main.py --dry-run
.venv/bin/python main.py --init-state
```

The bot must be able to message the selected chat. Keep the token out of commits and shell history. The token and chat ID are GitHub Actions secrets for remote execution.

For a local Wellfound dry run, install Google Chrome or Chromium and make it available on `PATH`, then run `JOB_WATCHER_SOURCES=wellfound .venv/bin/python main.py --dry-run`. The collector uses a fresh temporary browser profile and does not require a Wellfound account. It reads at most two pages per configured search, preserves query parameters, merges overlapping IDs, and retains the first page if the second fails. It reads the public page's embedded job data, including descriptions, and falls back to visible listings when that data is unavailable. Plain HTTP requests returned 403 in local and GitHub runner tests.

## GitHub Actions

Create a GitHub repository for this directory and push the code to its default branch. Add repository secrets named `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. The workflow in `.github/workflows/collect.yml` supports a manual run. It runs in dry-run mode while the example profile flag remains set. The four-hour schedule (minute 17 UTC) is gated by the repository variable `JOB_WATCHER_ENABLED=true`, so scheduled collection stays inactive until you configure the real profile and Telegram secrets.

The workflow runs the offline test suite before collection. It creates a `state` branch on its first run. Later runs read `seen.json` from that branch and write completed IDs back to it. The workflow grants itself `contents: write`; repository settings must allow its token to write. Runs are serialized with GitHub Actions concurrency. Do not delete or rename `state` casually, because that would make old listings look new.

Run the workflow manually and inspect its Actions summary before relying on the schedule. Public job sites may block GitHub-hosted runners; a local successful request cannot prove remote collection will work. The enabled sources report failures independently. Use the manual workflow's `sources` input to probe `indeed,naukri` or `wellfound` alone. The current GitHub runner image includes Chrome, but the collector will fail with a clear error if it is unavailable. Wellfound remains outside the default `JOB_WATCHER_SOURCES` setting while we check repeated runner results over time.

The manual workflow's `dry_run` checkbox explicitly suppresses delivery and processed-ID changes, even for a configured real profile. It defaults to false to preserve ordinary manual and scheduled operation; example profiles enforce dry run regardless.

Scheduled GitHub Actions may run late or be dropped. The searches overlap previous runs, and stable IDs suppress normal repeats. In an inactive public repository, GitHub can disable scheduled workflows after 60 days.

## Tuning and limits

The default `alert_threshold` is 60; `JOB_WATCHER_ALERT_THRESHOLD` overrides it when set. Role and early-career fit can supply 70 points, so a good listing with no technology detail can qualify. Skills, work arrangement, and freshness provide additional points. Each run sends one digest listing up to 40 selected jobs (`JOB_WATCHER_MAX_ALERTS`), best first: a score and linked title per job, under its company, with location, source, and pay when known. Several roles from the same company share one heading. A long digest is split into a few messages within Telegram's length limit, and a run with no matches sends nothing. Jobs over the limit stay unprocessed and are noted at the end of the digest. Dry runs print the digest instead of sending it. Change these values in the profile, `config.py`, or the documented `JOB_WATCHER_*` environment variables.

The state records rejected, below-threshold, and successfully delivered listings. If a digest message fails, its listings and those in later messages stay unprocessed, so they can be retried if the source returns them again. A crash between sending and saving state can produce a duplicate alert. A listing that disappears before retry can be missed. Those limits keep the project small; add durable pending alerts only if they cause a real problem.

Changing scoring rules does not revisit old processed jobs. Use saved fixtures and dry runs to tune the evaluator. Set `JOB_WATCHER_STATE_PATH` to use a different state file locally.

Changing a JSON profile also does not rescore processed listings in the existing state. This incremental version retains the collect → score → Telegram workflow and version-1 state format; it does not introduce a catalog, dashboard, synchronization branches, daily digest, or LLM requirement. Per-source summaries now include description coverage and duration, and equally ranked listings use a stable ID tie-breaker.

## Monitoring

Each run's `--report` JSON (version 2) includes a decision log: every new listing's source, title, company, location, URL, score, outcome (`sent`, `delivery_failed`, `deferred`, `rejected`, `below_threshold`, `awaiting_details`, `evaluation_failed`, or `would_send` in dry run), reasons, and whether a description was available, plus rejection-reason counts. A listing scored without a description that could still reach the threshold through skill points is `awaiting_details`: it stays unprocessed so a later run can fetch its description, until it leaves the search results or exceeds the posting-age limit. Descriptions are still left out. The workflow always writes the report and uploads it as the `run-report` artifact for 30 days; use it to find listings that were rejected for the wrong reason.

Live runs append a compact record (counts and per-source status, no listings) to `history.jsonl`, kept on the `state` branch next to `seen.json` and trimmed to the last `JOB_WATCHER_HISTORY_RUNS` runs (default 500). From that history the watcher sends a Telegram message when a source has failed or returned no listings for `JOB_WATCHER_HEALTH_RUNS` consecutive runs that included it (default 3), and another when it recovers. Dry runs write neither history nor health messages. Problems with history or health messages are logged and never fail a run. Locally the history file sits next to the state file unless `JOB_WATCHER_HISTORY_PATH` is set; set `JOB_WATCHER_LOG_LEVEL=DEBUG` for more detail.

Health messages cannot report a schedule that stopped running. For that, create a free [Healthchecks.io](https://healthchecks.io) check with a 6-hour period and 8 hours of grace, then add its ping URL as the `HEALTHCHECKS_PING_URL` repository secret. The workflow pings when it starts and pings success or `/fail` when it ends; failed tests or setup count as failures. Without the secret, the pings are skipped. The grace is generous on purpose: GitHub delays and drops scheduled runs, and the 4-hour schedule was observed to run about three times a day with gaps of up to 12 hours.

## Tests

```sh
.venv/bin/python -m pytest -q
```

Tests use saved listing samples and mocks; they do not need personal accounts, Telegram credentials, or live collection.
