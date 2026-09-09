import argparse, json, os, re, requests
from dotenv import load_dotenv
from simple_salesforce import Salesforce
from simple_salesforce.exceptions import SalesforceMalformedRequest

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


def is_blank(value):
    return value is None or value == ""


def opportunity_stage_ranks(sf):
    rows = sf.query(
        "SELECT ApiName, SortOrder FROM OpportunityStage WHERE IsActive = true"
    )["records"]
    return {row["ApiName"]: row["SortOrder"] for row in rows}


def opportunity_field_maps(sf):
    by_name = {}
    by_label = {}
    for field in sf.Opportunity.describe()["fields"]:
        by_name[field["name"]] = field
        by_label[field["label"]] = field
    return by_name, by_label


def load_opportunity_validation_rules(sf):
    query = (
        "SELECT Id, ValidationName, Active, ErrorDisplayField, ErrorMessage "
        "FROM ValidationRule WHERE EntityDefinition.QualifiedApiName = 'Opportunity'"
    )
    rows = sf.restful("tooling/query/", method="GET", params={"q": query}).get("records") or []
    rules = []
    for row in rows:
        if not row.get("Active"):
            continue
        detail = sf.restful(f"tooling/sobjects/ValidationRule/{row['Id']}")
        meta = detail.get("Metadata") or {}
        rules.append({
            "id": row["Id"],
            "name": row["ValidationName"],
            "error_message": row.get("ErrorMessage") or meta.get("errorMessage"),
            "error_display_field": row.get("ErrorDisplayField") or meta.get("errorDisplayField"),
            "formula": meta.get("errorConditionFormula") or "",
        })
    return rules


def extract_isblank_fields(formula):
    return re.findall(
        r"ISBLANK\s*\(\s*(?:TEXT\s*\(\s*)?([A-Za-z0-9_]+)",
        formula or "",
        flags=re.I,
    )


def extract_stage_threshold(formula):
    match = re.search(
        r"CASE\s*\(\s*StageName[\s\S]*?\)\s*(>=|>)\s*(\d+)",
        formula or "",
        flags=re.I,
    )
    if not match:
        return None
    return match.group(1), int(match.group(2))


def resolve_display_field(display, by_name, by_label):
    if not display:
        return None
    if display in by_name:
        return display
    if display in by_label:
        return by_label[display]["name"]
    if f"{display}__c" in by_name:
        return f"{display}__c"
    return None


def rule_would_block(rule, opp, target_stage, ranks, by_name, by_label):
    formula = rule.get("formula") or ""
    current_stage = opp.get("StageName")
    stage_changing = current_stage != target_stage
    compact = re.sub(r"\s+", "", formula)

    if "ISCHANGED(StageName)" in compact and not stage_changing:
        return None

    threshold = extract_stage_threshold(formula)
    target_rank = ranks.get(target_stage)
    if threshold and target_rank is not None:
        operator, number = threshold
        if operator == ">" and not target_rank > number:
            return None
        if operator == ">=" and not target_rank >= number:
            return None

    blank_fields = []
    for api_name in extract_isblank_fields(formula):
        if api_name not in by_name:
            continue
        if is_blank(opp.get(api_name)):
            blank_fields.append(api_name)

    display_api = resolve_display_field(rule.get("error_display_field"), by_name, by_label)
    if display_api and is_blank(opp.get(display_api)) and display_api not in blank_fields:
        if display_api in formula or (rule.get("error_display_field") or "") in formula:
            blank_fields.append(display_api)

    if blank_fields and (threshold or (re.search(r"StageName", formula, re.I) and stage_changing)):
        return {
            "rule": rule["name"],
            "error_message": rule["error_message"],
            "fields": blank_fields,
            "error_display_field": display_api or rule.get("error_display_field"),
        }
    return None


def find_champion_contact(sf, opp, transcript):
    emails = list(dict.fromkeys(re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", transcript)))
    named = re.findall(
        r"([A-Z][a-z]+ [A-Z][a-z]+),\s*[A-Za-z0-9._%+\-]+@",
        transcript,
    )
    account_id = opp.get("AccountId")
    records = []
    if emails:
        quoted = ",".join("'" + email.replace("'", r"\'") + "'" for email in emails)
        records = sf.query(
            "SELECT Id, Name, Email, AccountId FROM Contact "
            f"WHERE Email IN ({quoted}) ORDER BY LastModifiedDate DESC LIMIT 10"
        )["records"]
    if not records and named:
        name = named[0].replace("'", r"\'")
        clause = f"Name = '{name}'"
        if account_id:
            clause += f" AND AccountId = '{account_id}'"
        records = sf.query(
            f"SELECT Id, Name, Email, AccountId FROM Contact WHERE {clause} LIMIT 5"
        )["records"]
    if not records:
        return None
    same_account = [row for row in records if account_id and row.get("AccountId") == account_id]
    pick = (same_account or records)[0]
    return {k: pick[k] for k in ("Id", "Name", "Email", "AccountId") if k in pick}


def suggest_validation_fills(sf, opp, transcript, gaps, by_name):
    needed = []
    for gap in gaps:
        for field in gap["fields"]:
            if field not in needed:
                needed.append(field)

    suggestions = []
    lower = transcript.lower()
    champion = find_champion_contact(sf, opp, transcript) if "Champion__c" in needed else None

    for field in needed:
        meta = by_name.get(field) or {}
        current = opp.get(field)
        item = {
            "field": field,
            "label": meta.get("label") or field,
            "current": current,
            "proposed_value": None,
            "proposed_label": None,
            "ask_seller": True,
            "source": None,
        }
        if field == "CRM__c":
            values = [p["value"] for p in meta.get("picklistValues") or [] if p.get("active")]
            if "salesforce" in lower:
                match = next((v for v in values if v.lower() == "salesforce"), None)
                if match:
                    item["proposed_value"] = match
                    item["proposed_label"] = match
                    item["ask_seller"] = False
                    item["source"] = "Transcript: they said the CRM they use is Salesforce."
            elif "hubspot" in lower:
                match = next((v for v in values if v.lower() == "hubspot"), None)
                if match:
                    item["proposed_value"] = match
                    item["proposed_label"] = match
                    item["ask_seller"] = False
                    item["source"] = "Transcript: they named Hubspot as their CRM."
            if item["ask_seller"]:
                item["source"] = "CRM is required to advance stage, but no matching CRM picklist value was found in the transcript."
        elif field == "Champion__c":
            if champion:
                item["proposed_value"] = champion["Id"]
                item["proposed_label"] = champion.get("Name")
                item["ask_seller"] = False
                item["source"] = (
                    f"Transcript contact {champion.get('Name')} ({champion.get('Email')}) "
                    f"matched Salesforce Contact {champion['Id']}."
                )
            else:
                emails = re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", transcript)
                item["source"] = (
                    "Champion is required to advance stage. "
                    + (f"Transcript emails {', '.join(emails)} did not match a Contact." if emails
                       else "No champion name or email in the transcript matched a Salesforce Contact.")
                )
        else:
            item["source"] = f"{item['label']} is required by an Opportunity validation rule and is blank. No transcript mapping for this field."
        suggestions.append(item)
    return suggestions


def validation_preflight(sf, opp, transcript, target_stage):
    ranks = opportunity_stage_ranks(sf)
    by_name, by_label = opportunity_field_maps(sf)
    rules = load_opportunity_validation_rules(sf)
    gaps = []
    for rule in rules:
        blocked = rule_would_block(rule, opp, target_stage, ranks, by_name, by_label)
        if blocked:
            gaps.append(blocked)
    return {
        "current_stage": opp.get("StageName"),
        "target_stage": target_stage,
        "rules": [
            {
                "name": rule["name"],
                "error_message": rule["error_message"],
                "error_display_field": rule["error_display_field"],
                "formula": rule["formula"],
            }
            for rule in rules
        ],
        "gaps": gaps,
        "suggested_updates": suggest_validation_fills(sf, opp, transcript, gaps, by_name),
        "current_values": {
            "CRM__c": opp.get("CRM__c"),
            "Champion__c": opp.get("Champion__c"),
        },
    }


def salesforce_error_payload(exc):
    content = getattr(exc, "content", None)
    if isinstance(content, list):
        return content
    if isinstance(content, dict):
        return [content]
    return [{"message": str(exc), "errorCode": "UNKNOWN"}]


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

    pending_preflight = validation_preflight(sf, opp, args.transcript, "Pending Approval")
    negotiation_preflight = validation_preflight(sf, opp, args.transcript, "Negotiation/Review")

    guidance = {
        "opp_name": opp["Name"],
        "account_domain": domain,
        "estimated_revenue": revenue,
        "suggested_tier": tier_name,
        "seats": args.seats,
        "contract_term": opp.get("Contract_Term__c"),
        "current_stage": opp.get("StageName"),
        "target_discount_pct": target_discount_pct,
        "approval_tier": approval_tier,
        "justification": "; ".join(justifications) if justifications else "Standard pricing",
        "approval_comment": approval_comment,
        "quote_lines": quote_lines,
        "validation_preflight": {
            "Pending Approval": pending_preflight,
            "Negotiation/Review": negotiation_preflight,
        },
    }
    print(json.dumps(guidance, indent=2))

elif args.action == "commit" and args.payload:
    data = json.loads(args.payload)

    desired = []
    total_amount = 0
    for line in data["quote_lines"]:
        pbe = line["id"]
        qty = line["quantity"]
        price = line["price"]
        desired.append({"PricebookEntryId": pbe, "Quantity": qty, "UnitPrice": price})
        total_amount += price * qty

    existing = sf.query(
        "SELECT Id, PricebookEntryId, Quantity, UnitPrice "
        f"FROM OpportunityLineItem WHERE OpportunityId = '{args.opp_id}'"
    )["records"]
    existing_by_pbe = {row["PricebookEntryId"]: row for row in existing}
    desired_pbes = {row["PricebookEntryId"] for row in desired}

    to_delete = [row["Id"] for pbe, row in existing_by_pbe.items() if pbe not in desired_pbes]
    for line_id in to_delete:
        sf.OpportunityLineItem.delete(line_id)

    for row in desired:
        current = existing_by_pbe.get(row["PricebookEntryId"])
        if current:
            sf.OpportunityLineItem.update(current["Id"], {
                "Quantity": row["Quantity"],
                "UnitPrice": row["UnitPrice"],
            })
        else:
            sf.OpportunityLineItem.create({
                "OpportunityId": args.opp_id,
                "PricebookEntryId": row["PricebookEntryId"],
                "Quantity": row["Quantity"],
                "UnitPrice": row["UnitPrice"],
            })

    comment = data.get("approval_comment") or (
        f"Deal Desk System: Discount {data['target_discount_pct']}% applied. "
        f"Routing to {data['approval_tier']}."
    )
    opp_fields = {
        "Amount": total_amount,
        "Description": f"Submitted for {data['approval_tier']}. See Approval Submission Comment.",
        "Approval_Submission_Comment__c": comment
    }
    if data.get("contract_term") is not None and data.get("contract_term") != "":
        opp_fields["Contract_Term__c"] = str(data["contract_term"])
    extra_fields = data.get("opportunity_fields") or {}
    for field_name, field_value in extra_fields.items():
        if field_value is not None and field_value != "":
            opp_fields[field_name] = field_value

    target_stage = "Pending Approval" if data["target_discount_pct"] > 10 else "Negotiation/Review"
    opp_fields["StageName"] = target_stage

    try:
        sf.Opportunity.update(args.opp_id, opp_fields)
    except SalesforceMalformedRequest as exc:
        print(json.dumps({
            "status": "VALIDATION_BLOCKED",
            "message": "Salesforce rejected the Opportunity update. Fill the required fields and retry commit.",
            "target_stage": target_stage,
            "errors": salesforce_error_payload(exc),
        }))
        raise SystemExit(0)

    if data["target_discount_pct"] > 10:
        refreshed = sf.Opportunity.get(args.opp_id)
        submission_comment = refreshed.get("Approval_Submission_Comment__c") or comment
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
        except Exception:
            print(json.dumps({"status": "PARTIAL_SUCCESS", "message": "Products added and stage set to Pending Approval, but Approval Process failed (check if SFDC Approval Process is active)."}))
    else:
        print(json.dumps({"status": "SUCCESS", "message": "Products added. Discount was 10% or under, so no approval process was triggered."}))
