# AI pricing accuracy and project budgets

Status: implemented on `feat/repo-sync` (2026-10-06). Companion to `AI_BYOK_AND_ANALYTICS.md`.

## What was wrong

**Tokens were accurate. Cost was not.** `prompt_tokens` / `completion_tokens` come from the
provider's own `usage` block on every response, so the token columns are what the provider bills.
Cost came from `litellm.completion_cost()`, which looks the model up in litellm's price map, and
that map had three problems:

1. **Loaded once, at process start.** litellm downloads its community-maintained
   `model_prices_and_context_window.json` on import and never again. A container that has been up
   for weeks prices against a weeks-old list.
2. **Silent fallback to a bundled copy.** If that download fails (no egress, GitHub slow past the
   5s timeout), litellm quietly uses the copy shipped inside the installed package. The installed
   1.83.7 copy has **no Claude 5 models**: `claude-sonnet-5-5` and `claude-opus-5-5` were missing,
   while the live list has them.
3. **An unknown model was recorded as `$0.00`.** The lookup raised, `llm_client` caught it and
   wrote `cost_usd = 0.0`. Free and unpriced looked identical on the dashboard, so a project could
   spend real money while showing $0. This hits every self-hosted or custom model name too
   (LM Studio, Azure deployment names, OpenAI-compatible gateways).

## Where "live pricing" can come from

There is no pricing API at Anthropic, OpenAI, Google or Azure OpenAI. OpenRouter is the exception
(its `/models` lists prices), but it only covers models routed through OpenRouter. So the
practical live source is litellm's maintained price list, which is updated as providers publish
prices. Two layers on top of it:

| Layer | Source | When it applies |
| --- | --- | --- |
| Per-provider override | `input_cost_per_million` / `output_cost_per_million` on the provider config | Set by whoever manages that key. Always wins: negotiated rates, Azure deployments, self-hosted models, anything the list doesn't know |
| Live list | litellm price map, re-downloaded every 24h and on demand by an admin | Default for well-known models |
| Neither | none | Call recorded with `cost_known = false`. Analytics counts it as unpriced instead of reporting $0 |

The override is a flat per-token rate. It does not model prompt-cache discounts, so for a cached
workload it slightly over-states cost. That errs in the safe direction for a budget.

## Budgets and alerts

Per project, set by a project **owner or admin** (members can see them):

- `ai_budget_usd_monthly`: spend limit per calendar month (UTC), in USD. `null` = none.
- `ai_budget_tokens_monthly`: token limit per calendar month (prompt + completion). `null` = none.
- `ai_budget_alert_percent`: early-warning threshold, default 80.
- `ai_budget_hard_stop`: when true, AI calls for the project are refused once a limit is reached.
  Off by default: an alert is informational, while a stop changes behavior and must be chosen.

The budget counts every AI call attributed to the project, whichever key served it. Month-to-date
usage is summed from `AIUsageEvent` (180-day TTL, so the current month is always complete).

**Alerts.** After each successful call, the project's month-to-date usage is compared with each
limit at two thresholds: the alert percent and 100%. Crossing one sends notification event
`ai.budget_threshold` to the **project owner** (in-app and email; being the owner is the opt-in).
Each (month, metric, threshold) fires once. The claim is an atomic `$addToSet` guarded on the key
not being present, so two concurrent calls or two backend replicas cannot both send the email.
Keys are month-prefixed, so alerts re-arm on the 1st. Saving new limits clears the month's sent
keys, so raising a budget re-arms its alerts.

**Hard stop.** Checked in `llm_client.get_completion` / `get_tool_completion` before any provider
is called, so a refused call costs nothing. The refusal is an `LLMPermanentError` that names the
budget, so it surfaces through the existing AI error paths as a readable message.

Spend can overshoot a limit by up to one call. The check is before the call and the cost is only
known after. Budgets are a guard against runaway spend, not to-the-cent metering.

## Endpoints

- `GET  /projects/{id}/ai-budget`: limits plus month-to-date usage (member).
- `PUT  /projects/{id}/ai-budget`: set limits (owner/admin). Audited as `AI Budget Updated`.
- `GET  /admin/ai-pricing`: when the price list was loaded, from where, how many models (admin).
- `POST /admin/ai-pricing/refresh`: re-download now (admin).

## Not done (add when asked)

- Portal-wide budget across all projects. Admins have the portal analytics view today.
- Per-feature or per-provider budgets.
- Cache-aware override pricing.
