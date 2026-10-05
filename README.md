# Personal Job Watcher

A small Python watcher for public LinkedIn, Internshala, Indeed, and Naukri listings. It filters and scores jobs against one editable profile, then sends selected jobs to Telegram. An optional Wellfound collector uses headless Chrome to read public search pages and is disabled by default while its reliability is evaluated. Applications stay manual.

## Set your profile

Edit `PROFILE` and the search settings in `config.py`, or supply a validated JSON profile. The committed values are **examples for testing**, not a claim about the user's experience or location. The script automatically uses dry-run mode while the active profile is an example, so it cannot send generic-profile alerts.

To use a profile without editing Python:

```sh
cp profile.example.json profile.json
# Edit profile.json with your preferences; keep is_example true during testing.
.venv/bin/python main.py --profile profile.json --dry-run
```

`profile.json` is ignored by Git. The version-1 document contains `version`, an explicit boolean `is_example`, and a `profile` object. Unknown fields, invalid types, and unsupported choices stop collection before requests or delivery. Omitted profile fields inherit the example defaults. Only set `is_example` to `false` after entering real preferences and reviewing a dry run. The original `config.py` profile and `PROFILE_IS_EXAMPLE` flag remain the fallback.

The profile adds exact company-name exclusions, actual experience (`experience_years`), and `career_stage`: `early`, `experienced`, or `any`. Early-career profiles retain the senior-title exclusion; experienced and unrestricted profiles can consider senior titles while still enforcing `max_required_years`. Explicit mandatory experience in descriptions is checked alongside source fields. Preferred experience and references to senior colleagues do not count as mandatory requirements.

For unattended runs, set `JOB_WATCHER_PROFILE_PATH` to a JSON file, or provide the complete document in `JOB_WATCHER_PROFILE_JSON`. An explicit `--profile` file takes precedence, followed by the environment file and then the JSON environment value. On GitHub Actions, an optional repository secret named `JOB_WATCHER_PROFILE_JSON` supplies the profile without committing personal data. With no supplied profile, the example and its delivery protection remain active.

In particular, configure the roles, skills, job types, maximum required experience, acceptable locations, remote/workplace preferences, each source's search terms and location, and Internshala pages. An empty `allowed_locations` means no location exclusion. Internshala and Naukri target India; the example Indeed country is also India. Search regions are independent of personal eligibility rules. The default searches and weights are starting points.

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

Edit `INDEED_SEARCHES` and `NAUKRI_SEARCHES` in `config.py` to tune the keywords. Indeed may match words in descriptions rather than titles; all results still pass through local rules. Its `hours_old` filter concerns addition to Indeed, while the employer posting date may be older; the evaluator checks posting age separately. Salary is retained when available, but was not disclosed in the initial live samples. [JobSpy documentation](https://github.com/speedyapply/JobSpy/blob/main/README.md)

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

The initial threshold is 60. Role and early-career fit can supply 70 points, so a good listing with no technology detail can qualify. Skills, work arrangement, and freshness provide additional points. A maximum of 10 selected jobs are considered per run. Change these values in `config.py` or the documented `JOB_WATCHER_*` environment variables.

The state records rejected, below-threshold, and successfully delivered listings. Failed delivery leaves a listing unprocessed, so it can be retried if the source returns it again. A crash between sending and saving state can produce a duplicate alert. A listing that disappears before retry can be missed. Those limits keep the project small; add durable pending alerts only if they cause a real problem.

Changing scoring rules does not revisit old processed jobs. Use saved fixtures and dry runs to tune the evaluator. Set `JOB_WATCHER_STATE_PATH` to use a different state file locally.

Changing a JSON profile also does not rescore processed listings in the existing state. This incremental version retains the collect → score → Telegram workflow and version-1 state format; it does not introduce a catalog, dashboard, synchronization branches, daily digest, or LLM requirement. Per-source summaries now include description coverage and duration, and equally ranked listings use a stable ID tie-breaker.

## Tests

```sh
.venv/bin/python -m pytest -q
```

Tests use saved listing samples and mocks; they do not need personal accounts, Telegram credentials, or live collection.
