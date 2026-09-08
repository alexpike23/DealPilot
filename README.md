# DealPilot

Headless CPQ copilot for Cursor. It reads a Salesforce opportunity, a call transcript, Apollo firmographics, and `qtc_rules.json`, then walks commercial decisions one at a time and can commit a quote to Salesforce after you type **Accept**.

## What is in this repo

| Path | Purpose |
|---|---|
| `.cursor/skills/deal-copilot/SKILL.md` | Agent skill (consultative flow, no Opportunity Id required from the user) |
| `scripts/deal_desk.py` | Salesforce + Apollo analyze/commit |
| `qtc_rules.json` | Catalog, ICP bands, multi-year discount cap, approval matrix |
| `transcripts/call_1.txt` | Sample call transcript |
| `.env.example` | Salesforce and Apollo credential names (no secrets) |

## Setup

1. Clone the repo and open the folder in Cursor.
2. Python 3.9+ with:

```bash
pip3 install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in:

- `SF_USERNAME` / `SF_PASSWORD` / `SF_SECURITY_TOKEN` — Salesforce user used by `simple_salesforce`
- `APOLLO_API_KEY` — Apollo key (sent as the `X-Api-Key` header)

4. In the Salesforce org:

- Enable **SOAP API login()** (Setup → User Interface → API Settings)
- Grant the running user **Use Any API Auth**
- Opportunity stage **Pending Approval** if you will submit discounts over 10%
- Active approval process (this project used **Deal Desk Routing v2** on Opportunity)
- Product price book entries must match the Ids in `qtc_rules.json`
- Opportunity Account should have a **Website** so Apollo can enrich by domain
- Optional: `Approval_Submission_Comment__c` on Opportunity; line-item `Discount__c` rollup to `Max_Discount__c` if the approval process keys off discount %

5. Keep `.env` local. It is gitignored.

## How to run it

Open this project in Cursor and ask in plain language, for example:

- “Run deal copilot on the Apollo v2 deal”
- “Help me create a proposal for my Apollo deal”

You do **not** need to paste a Salesforce Opportunity Id. The skill searches Opportunity (and Account) names from what you said, then tells you which record it picked.

It will:

1. Load that opportunity and the linked Account website/domain.
2. Say it is looking up revenue in **Apollo using that Salesforce account domain**.
3. Read the transcript for seats, competitors, multi-year intent, and CRM packaging (not for revenue).
4. Ask **one decision at a time** (term, then CRM if relevant).
5. When the package is complete, summarize products/totals and **which Salesforce approvals** will fire.
6. Commit to Salesforce only after you type **Accept**.

Analyze/commit can also be run directly:

```bash
python3 scripts/deal_desk.py --opp_id "<OPP_ID>" --action analyze --seats 50 --transcript "$(cat transcripts/call_1.txt)"
python3 scripts/deal_desk.py --opp_id "<OPP_ID>" --action commit --payload '<JSON>'
```

## Commercial rules (short)

- ICP tier comes from Apollo `annual_revenue` vs `qtc_rules.json`.
- Multi-year license discount is allowed (playbook cap, currently 10%) but is a **seller choice**, not auto-applied.
- Competitor license % is not copied onto our SKUs.
- If the competitor includes CRM and we sell it as an add-on, the skill asks whether to keep, discount, or waive that fee.
- Discount over 10% → Opportunity stage **Pending Approval** and approval-process submit, using the same text as `Approval_Submission_Comment__c`.
