# DealPilot

**Headless CPQ in Cursor** — propose the right commercials on the first pass, then move the deal in Salesforce without re-keying a quote.

DealPilot looks at the data you already have — the **Salesforce opportunity**, **call transcripts**, **Apollo revenue** on the linked account, and your **sales / pricing playbook** — and finds a route forward that a seller can actually take to the customer. It does not dump a single locked price. It walks term and packaging decisions, tells you **which approvals the org will require**, and when you accept it **writes opportunity products, updates key opportunity fields, and submits for approval**.

That is the gap this is built for: reps and deal desk spending cycles reconciling a call, a CRM record, and a PDF playbook, then typing the same numbers into Salesforce. DealPilot does the evaluation up front and the CRM work at the end.

## Why it exists

| Without DealPilot | With DealPilot |
|---|---|
| Seller guesses tier and discount from memory | ICP tier from **Apollo enrich** (domain on the Salesforce **Account**), compared to the playbook |
| Transcript lives in a doc; CRM lives in Salesforce | Call facts (seats, ZoomInfo, multi-year, CRM gap) are read with the opportunity |
| Competitor “25% off” gets copied onto the wrong SKU | Playbook caps; competitor license % is not treated as apples-to-apples |
| Approvals are a surprise after submit | You see **Sales Manager / VP / Deal Desk / auto-approve** before anything is written |
| Products, amount, comments, stage, and approval are manual | One **Accept** inserts lines, sets amount and submission comment, moves to **Pending Approval**, and submits the approval process |

## How a run works

Ask in plain language — no Opportunity Id required:

> Help me create a proposal for my Apollo v2 deal

1. **Find the opportunity** from what you said (name / account search in Salesforce). Confirm if more than one match.
2. **Enrich revenue in Apollo** using the **website/domain on the Account linked to that opportunity** — and say so, so it is obvious the number is not invented and not taken from the transcript.
3. **Read the transcript** for seats, competitive context, multi-year intent, and whether CRM is in *their* core product vs *our* add-on.
4. **Compare to the playbook** (`qtc_rules.json`): catalog, ICP bands, multi-year discount allowance, approval matrix.
5. **Decide with you, one lever at a time** (for example: 1-year at list vs multi-year with playbook discount; then whether to keep, discount, or waive CRM).
6. **Summarize the package and the approvals** that will fire in Salesforce.
7. On **Accept**, expedite the ops work: opportunity products, amount, `Approval_Submission_Comment__c`, stage, and approval submit when the discount requires it.

## Repo layout

| Path | Role |
|---|---|
| `.cursor/skills/deal-copilot/SKILL.md` | The agent playbook (consultative CPQ, sequential decisions, Accept gate) |
| `scripts/deal_desk.py` | Salesforce + Apollo analyze and commit |
| `qtc_rules.json` | List prices, ICP revenue bands, term discount cap, approval routing |
| `transcripts/call_1.txt` | Sample discovery call |
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
5. `.env` is gitignored. Do not commit it.

## How to run

In Cursor, in this project:

- “Run deal copilot on the Apollo v2 deal”
- “Help me create a proposal for my Apollo deal”

CLI (optional):

```bash
python3 scripts/deal_desk.py --opp_id "<OPP_ID>" --action analyze --seats 50 --transcript "$(cat transcripts/call_1.txt)"
python3 scripts/deal_desk.py --opp_id "<OPP_ID>" --action commit --payload '<JSON>'
```

Commit only runs after **Accept**. Over 10% discount: stage **Pending Approval** and approval-process submit. 10% or under: **Negotiation/Review**, no approval submit.

## Interview / demo notes

- **ICP is Apollo, not the call.** Transcript revenue is ignored on purpose.
- **Multi-year discount is allowed, not automatic.** The seller chooses 1-year list vs multi-year within the playbook cap.
- **CRM packaging is a decision.** If ZoomInfo includes CRM and we charge an add-on, the copilot asks keep / discount / waive — and flags Deal Desk if the fee is waived (100% on that line).
