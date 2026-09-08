import argparse, json, os, requests
from dotenv import load_dotenv
from simple_salesforce import Salesforce

load_dotenv()

parser = argparse.ArgumentParser()
parser.add_argument("--opp_id", required=True)
parser.add_argument("--action", choices=["analyze", "submit", "commit"], required=True)
parser.add_argument("--transcript", default="")
parser.add_argument("--seats", type=int, default=10)
parser.add_argument("--payload", default="")
args = parser.parse_args()

sf = Salesforce(
    username=os.getenv("SF_USERNAME"),
    password=os.getenv("SF_PASSWORD"),
    security_token=os.getenv("SF_SECURITY_TOKEN")
)

with open("qtc_rules.json") as f:
    playbook = json.load(f)


def build_approval_comment(seats, base_license, quote_lines, target_discount_pct, justifications, crm_catalog=None):
    license_line = quote_lines[0]
    list_unit = base_license["list_price"]
    net_unit = license_line["price"]
    list_total = list_unit * seats
    net_total = net_unit * seats

    competitor = None
    for item in justifications:
        if item.lower().startswith("competitor:"):
            competitor = item.split(":", 1)[1].strip()
    multi_year = any(item.lower() == "multi-year" for item in justifications)

    if multi_year and competitor:
        opener = (
            f"Prospect has made reference to the willingness to sign a multi-year deal "
            f"while evaluating {competitor}"
        )
    elif multi_year:
        opener = "Prospect has made reference to the willingness to sign a multi-year deal"
    elif competitor:
        opener = f"Prospect has referenced {competitor} as a competing alternative"
    else:
        opener = "Prospect requested commercial terms for this opportunity"

    license_sentence = (
        f"proposing {seats} {base_license['name']} seats at full price "
        f"(${list_unit:,.0f}/seat, ${list_total:,.0f} ARR) or a multi-year deal with "
        f"{target_discount_pct:.0f}% discount applied (${net_unit:,.0f}/seat, ${net_total:,.0f} ARR)"
    )

    comment = f"{opener}, {license_sentence}."

    if crm_catalog:
        crm_line = next((line for line in quote_lines if line["name"] == crm_catalog["name"]), None)
        if crm_line:
            crm_list = crm_catalog["list_price"]
            crm_net = crm_line["price"]
            if crm_net == 0:
                comment += (
                    f" ${crm_list:,.0f} CRM integration fee waived as the customer referenced "
                    "competitor capability and requires matching Salesforce CRM functionality."
                )
            else:
                comment += (
                    f" CRM Integration is included because the customer uses Salesforce and needs "
                    "that capability to match competitor functionality; "
                    f"list ${crm_list:,.0f} is reduced {target_discount_pct:.0f}% to ${crm_net:,.0f}."
                )
    return comment

if args.action == "analyze":
    opp = sf.Opportunity.get(args.opp_id)
    acc = sf.Account.get(opp["AccountId"]) if opp.get("AccountId") else {}
    domain = acc.get("Website", "apollo.io").replace("https://", "").replace("http://", "").strip("/")
    if domain.startswith("www."):
        domain = domain[4:]

    apollo_key = os.getenv("APOLLO_API_KEY")
    if not apollo_key:
        raise SystemExit("APOLLO_API_KEY is required. Account revenue must come from Apollo enrich.")

    res = requests.get(
        "https://api.apollo.io/v1/organizations/enrich",
        params={"domain": domain},
        headers={"X-Api-Key": apollo_key, "Accept": "application/json"},
    )
    if res.status_code != 200:
        raise SystemExit(f"Apollo enrich failed: HTTP {res.status_code}")
    org = (res.json() or {}).get("organization") or {}
    revenue = org.get("annual_revenue")
    if revenue is None:
        revenue = org.get("estimated_revenue")
    if revenue is None:
        raise SystemExit("Apollo enrich returned no annual_revenue for this account domain.")

    if revenue >= playbook["catalog"]["apollo_gold"]["icp_min_revenue"]:
        base_license = playbook["catalog"]["apollo_gold"]
        tier_name = "Gold"
    elif revenue >= playbook["catalog"]["apollo_silver"]["icp_min_revenue"]:
        base_license = playbook["catalog"]["apollo_silver"]
        tier_name = "Silver"
    else:
        base_license = playbook["catalog"]["apollo_bronze"]
        tier_name = "Bronze"

    transcript_lower = args.transcript.lower()
    justifications = []
    target_discount_pct = 0

    for comp in playbook["discount_playbook"]["competitors"]:
        if comp in transcript_lower:
            justifications.append(f"Competitor: {comp.capitalize()}")

    if "multi-year" in transcript_lower or "2 year" in transcript_lower:
        justifications.append("Multi-Year")

    include_crm = False
    crm_keywords = ["crm", "integration", "salesforce"]
    if any(kw in transcript_lower for kw in crm_keywords):
        include_crm = True
        justifications.append("CRM Integration Requested")

    approval_tier = "Deal Desk"
    for tier in sorted(playbook["approval_matrix"]["tiers"], key=lambda x: x["max_pct"]):
        if target_discount_pct <= tier["max_pct"]:
            approval_tier = tier["level"]
            break

    discount_multiplier = 1 - (target_discount_pct / 100)
    final_license_price = base_license["list_price"] * discount_multiplier

    quote_lines = [
        {
            "name": base_license["name"], 
            "id": base_license["sfdc_pricebook_entry_id"], 
            "price": final_license_price,
            "quantity": args.seats
        }
    ]

    if include_crm:
        crm = playbook["catalog"]["crm_integration"]
        final_crm_price = crm["list_price"] * discount_multiplier
        quote_lines.append({
            "name": crm["name"], 
            "id": crm["sfdc_pricebook_entry_id"], 
            "price": final_crm_price,
            "quantity": 1
        })

    crm_catalog = playbook["catalog"]["crm_integration"] if include_crm else None
    approval_comment = build_approval_comment(
        args.seats,
        base_license,
        quote_lines,
        target_discount_pct,
        justifications,
        crm_catalog,
    )

    guidance = {
        "opp_name": opp["Name"],
        "account_domain": domain,
        "estimated_revenue": revenue,
        "suggested_tier": tier_name,
        "seats": args.seats,
        "target_discount_pct": target_discount_pct,
        "approval_tier": approval_tier,
        "justification": "; ".join(justifications) if justifications else "Standard pricing",
        "approval_comment": approval_comment,
        "quote_lines": quote_lines
    }
    print(json.dumps(guidance, indent=2))

elif args.action == "commit" and args.payload:
    data = json.loads(args.payload)
    
    line_items = []
    total_amount = 0
    for line in data["quote_lines"]:
        line_items.append({
            "OpportunityId": args.opp_id,
            "PricebookEntryId": line["id"],
            "Quantity": line["quantity"],
            "UnitPrice": line["price"]
        })
        total_amount += (line["price"] * line["quantity"])
        
    sf.bulk.OpportunityLineItem.insert(line_items)

    comment = data.get("approval_comment") or (
        f"Deal Desk System: Discount {data['target_discount_pct']}% applied. "
        f"Routing to {data['approval_tier']}."
    )
    sf.Opportunity.update(args.opp_id, {
        "Amount": total_amount,
        "Description": f"Submitted for {data['approval_tier']}. See Approval Submission Comment.",
        "Approval_Submission_Comment__c": comment
    })
    
    if data['target_discount_pct'] > 10:
        refreshed = sf.Opportunity.get(args.opp_id)
        submission_comment = refreshed.get("Approval_Submission_Comment__c") or comment
        sf.Opportunity.update(args.opp_id, {"StageName": "Pending Approval"})
        try:
            approval_payload = {
                "requests": [{
                    "actionType": "Submit",
                    "contextId": args.opp_id,
                    "comments": submission_comment
                }]
            }
            sf.restful("process/approvals/", method="POST", json=approval_payload)
            print(json.dumps({"status": "SUCCESS", "message": f"Products added, stage set to Pending Approval, and submitted for {data['approval_tier']} Approval."}))
        except Exception as e:
            print(json.dumps({"status": "PARTIAL_SUCCESS", "message": "Products added and stage set to Pending Approval, but Approval Process failed (check if SFDC Approval Process is active)."}))
    else:
        sf.Opportunity.update(args.opp_id, {"StageName": "Negotiation/Review"})
        print(json.dumps({"status": "SUCCESS", "message": "Products added. Discount was 10% or under, so no approval process was triggered."}))
