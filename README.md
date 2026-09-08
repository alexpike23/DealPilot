# DealPilot

**A deal copilot for the early sale** — score the opportunity against how *this* sales org actually sells, then show the seller where they have leverage before they put a proposal in front of the customer.

DealPilot reads the **Salesforce opportunity**, **discovery transcripts**, **Apollo revenue** on the linked account, and the **internal sales and pricing playbook**. It treats that playbook as org best practice: ICP bands, what we will and will not discount, how we package against competitors, and when term is a legitimate lever. From that, it points out **where the deal can be strengthened** (fit, packaging, term, competitive response) so the proposal is built to close — not guessed from memory.

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
2. **Discovery quality.** Seats, competitive context, multi-year intent, and packaging gaps are pulled from the transcript and checked against the opportunity.
3. **Levers that help close.** For example:
   - Customer is **open to multi-year** → playbook **allows** a license discount up to the cap; seller chooses multi-year vs 1-year at list (never auto-applied).
   - Competitor **includes CRM**; we sell it as an add-on → keep, discount, or waive is a close decision, with Deal Desk called out if you waive.
   - Do **not** match ZoomInfo’s license % on our SKUs — that is not our motion.
4. **What it will take internally.** Sales Manager / VP / Deal Desk / auto-approve, so the proposal you take to the customer is one the org can actually sign.

## How a run works

Ask in plain language — no Opportunity Id required:

> Pike Industries Full Module Deal

1. **Find the opportunity** from what you said (name / account search in Salesforce). Confirm if more than one match.
2. **Enrich revenue in Apollo** using the **website/domain on the Account linked to that opportunity** — and say so, so the ICP number is not invented and not taken from the transcript.
3. **Read the transcript** against org practice: seats, competitive context, multi-year intent, CRM in *their* core product vs *our* add-on.
4. **Score against the playbook** (`qtc_rules.json`): catalog, ICP bands, multi-year discount *allowance*, competitor notes, approval matrix.
5. **Surface leverage, then decide with you, one lever at a time** (term, then CRM packaging if it is live).
6. **Summarize the proposal and the approvals** that will fire in Salesforce.
7. On **Accept**, expedite ops: opportunity products, amount, `Approval_Submission_Comment__c`, stage, and approval submit when the discount requires it.

## Repo layout

| Path | Role |
|---|---|
| `.cursor/skills/deal-copilot/SKILL.md` | Agent playbook: evaluate early deal vs org practice, sequential levers, Accept gate |
| `scripts/deal_desk.py` | Salesforce + Apollo analyze and commit |
| `qtc_rules.json` | Internal best practice: list prices, ICP bands, term discount cap, approval routing |
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

- “Pike Industries Full Module Deal”
- “Help me create a proposal for Pike Industries Full Module Deal”

CLI (optional):

```bash
python3 scripts/deal_desk.py --opp_id "<OPP_ID>" --action analyze --seats 50 --transcript "$(cat transcripts/call_1.txt)"
python3 scripts/deal_desk.py --opp_id "<OPP_ID>" --action commit --payload '<JSON>'
```

Commit only runs after **Accept**. Over 10% discount: stage **Pending Approval** and approval-process submit. 10% or under: **Negotiation/Review**, no approval submit.

## Interview / demo notes

- **ICP is Apollo, not the call.** Transcript revenue is ignored on purpose so early-stage “they said $40M” does not override org enrich.
- **Multi-year is a close lever, not a default discount.** The seller chooses 1-year list vs multi-year within the playbook cap.
- **CRM packaging is a close lever.** If ZoomInfo includes CRM and we charge an add-on, the copilot asks keep / discount / waive — and flags Deal Desk if the fee is waived (100% on that line).
