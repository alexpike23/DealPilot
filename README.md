# DealPilot

**A deal copilot for the early sale** — score the opportunity against how *this* sales org actually sells, then show the seller where they have leverage before they put a proposal in front of the customer.

DealPilot reads the **Salesforce opportunity**, **each discovery transcript as its own evidence**, **Apollo revenue** on the linked account, and the **internal sales and pricing playbook**. It starts by analyzing those calls against the opp so you can **decide price**: named competitors (packaging gap, e.g. integration with CRM), then two term options (1-year at list vs multi-year with playbook discount). On **Accept** it **updates key opportunity fields, generates opportunity products, and submits for approval**.

It still walks commercials one decision at a time, tells you **which approvals the org will require**, and on **Accept** it **updates key opportunity fields, generates opportunity products, and submits for approval**. Evaluation first; CRM busywork last.

## Why it exists

Early deals stall when the call, the CRM record, and the playbook never get compared. Reps either under-use the levers the org already approved, or they copy a competitor’s offer onto the wrong SKU and blow up Deal Desk later.

| Without DealPilot | With DealPilot |
|---|---|
| Stage and amount sit in Salesforce; the *how we sell this* lives in a PDF | Opportunity + transcript + Apollo are scored against **internal best practice** (`qtc_rules.json`) |
| Discovery facts never become a close plan | Call signals (seats, competitor, multi-year openness, CRM gap) are turned into **explicit leverage** |
| Competitive “25% off” gets pasted onto our licenses | Playbook caps; competitor % is **not** treated as apples-to-apples |
| Seller finds out approvals after they already quoted | Approval path is part of the close plan, before anything is written |
| Quote, products, comments, and submit are a second job | One **Accept** writes products, updates the opp, and submits approval |

## What it evaluates (early process)

1. **Fit vs how we sell.** Apollo `annual_revenue` from the **Account website/domain in Salesforce** (not a number from the call) vs ICP bands in the playbook — Gold / Silver / Bronze is org policy, not a guess.
2. **Each transcript, separately.** `transcripts/call_1.txt` (50 seats, ZoomInfo, integration with CRM gap) and `transcripts/call_2.txt` (multi-year; **60 licenses**, not 50). Mock demo files — they do not have to match the Salesforce account name.
3. **Price decisions against the playbook.**
   - Call 1 names ZoomInfo and integration with CRM in-platform → keep / discount / waive our add-on.
   - Call 2 is open to multi-year → two options: 1-year at list (60 seats) or multi-year with up to the playbook license discount. Seller chooses.
4. **What it will take internally.** Sales Manager / VP / Deal Desk / auto-approve, so the proposal you take to the customer is one the org can actually sign.

## How a run works

Ask in plain language — no Opportunity Id required. The skill searches Salesforce Opportunity / Account names for what you said:

> Help me create a proposal for the Apollo copilot deal

1. **Find the opportunity** from that language (name / account search). Confirm if more than one match; if none, it lists recent open opps.
2. **Enrich revenue in Apollo** using the **website/domain on the Account linked to that opportunity** — and say so, so the ICP number is not invented and not taken from the transcript.
3. **Read each mock transcript as its own file** (`transcripts/call_1.txt`, `transcripts/call_2.txt`) and score it against the playbook.
4. **Brief first:** concise what-happened + recommended deal structure (60 licenses, integration with CRM, two term options).
5. **Decide with you:** integration with CRM from call 1, then 1-year at list vs multi-year discount from call 2.
6. **Summarize and Accept** — then products, opp fields, approval submit when required.

## Repo layout

| Path | Role |
|---|---|
| `.cursor/skills/deal-copilot/SKILL.md` | Agent playbook: evaluate early deal vs org practice, sequential levers, Accept gate |
| `scripts/deal_desk.py` | Salesforce + Apollo analyze and commit |
| `qtc_rules.json` | Internal best practice: list prices, ICP bands, term discount cap, approval routing |
| `transcripts/call_1.txt` | Mock call: 50 seats, ZoomInfo, integration with CRM vs our add-on |
| `transcripts/call_2.txt` | Mock call: multi-year; now **60 licenses**; two term options |
| `.env.example` | Credential names only — never commit real secrets |

## Setup

1. Clone this repo and open it in Cursor.
2. Install Python 3.9+ dependencies:

```bash
pip3 install -r requirements.txt
```

3. Copy `.env.example` to `.env` and set `SF_USERNAME`, `SF_PASSWORD`, `SF_SECURITY_TOKEN`, and `APOLLO_API_KEY` (Apollo uses the `X-Api-Key` header).
4. Salesforce org (once):
   - Enable **SOAP API login()** and grant the user **Use Any API Auth**
   - Stage **Pending Approval** for discounts over 10%
   - Active Opportunity approval process (demo used **Deal Desk Routing v2**)
   - Price book entries aligned to Ids in `qtc_rules.json`
   - Account **Website** populated so Apollo can enrich by domain
   - `Approval_Submission_Comment__c` on Opportunity (submission comment is written here and sent on the approval request)
   - `Contract_Term__c` on Opportunity (picklist `1` / `2` / `3` years; written on Accept)
5. `.env` is gitignored. Do not commit it.

## How to run

In Cursor, in this project:

- “Help me create a proposal for the Apollo copilot deal”
- “Quote the Deal Copilot v2 opportunity”

CLI (optional):

```bash
python3 scripts/deal_desk.py --opp_id "<OPP_ID>" --action analyze --seats 60 --transcript "$(cat transcripts/call_1.txt transcripts/call_2.txt)"
python3 scripts/deal_desk.py --opp_id "<OPP_ID>" --action commit --payload '<JSON>'
```

Commit only runs after **Accept**. Over 10% discount: stage **Pending Approval** and approval-process submit. 10% or under: **Negotiation/Review**, no approval submit.

## One-pager

[`docs/DealPilot-one-pager.pptx`](docs/DealPilot-one-pager.pptx) — one widescreen slide (open in PowerPoint / Keynote / Google Slides). HTML copy: [`docs/DealPilot-one-pager.html`](docs/DealPilot-one-pager.html).

## Interview / demo notes

- **ICP is Apollo, not the call.** Transcript revenue is ignored on purpose.
- **Call 1 → competitor packaging.** Named ZoomInfo + integration with CRM in their core: keep / discount / waive our add-on.
- **Call 2 → 60 licenses + two term options.** 1-year at list vs multi-year with playbook license discount. Seller chooses.
