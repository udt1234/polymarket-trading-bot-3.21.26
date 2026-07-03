"""Clean up Railway: delete JaxBot env-var leaks + delete duplicate service + rename project.

Uses the Railway user token from ~/.railway/config.json directly against the GraphQL API.
"""
import httpx, json, sys
from pathlib import Path

CFG = json.loads(Path.home().joinpath(".railway/config.json").read_text(encoding="utf-8"))
TOKEN = CFG["user"]["token"]
EP = "https://backboard.railway.com/graphql/v2"
HEAD = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# IDs
JAXBOT_PROJECT_ID = "c45a1b9f-1030-4224-920f-3591ef5a9dae"
JAXBOT_PROD_ENV_ID = "15745713-f025-4020-b79a-adfbce1a5add"
JAXBOT_MAIN_SERVICE_ID = "00b8196d-1b2c-491b-aa39-0f2c07163f07"
JAXBOT_TELEGRAM_ALERTS_SERVICE_ID = "994f4c34-1387-42f8-9682-095589d54037"
POLYMARKET_BOT_PROJECT_ID = "e9d87bab-d38a-42e3-b57a-f197c4b081cb"

POLYMARKET_LEAKED_VARS = [
    "POLY_MANUAL_API_KEY",
    "POLY_MANUAL_PASSPHRASE",
    "POLY_MANUAL_PRIVATE_KEY",
    "POLY_MANUAL_SECRET",
    "POLY_MANUAL_WALLET_ADDRESS",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "PNL_POLL_SEC",
    "POLL_SEC",
]


def gql(query, variables=None):
    r = httpx.post(EP, json={"query": query, "variables": variables or {}}, headers=HEAD, timeout=30)
    return r.json()


# 1) Delete the 11 leaked env vars
print("=== Step 1: Delete 11 leaked Polymarket env vars from JaxBot main service ===")
del_var_mutation = """
mutation VarDelete($input: VariableDeleteInput!) {
  variableDelete(input: $input)
}
"""
deleted = 0
errors = []
for name in POLYMARKET_LEAKED_VARS:
    r = gql(del_var_mutation, {
        "input": {
            "projectId": JAXBOT_PROJECT_ID,
            "environmentId": JAXBOT_PROD_ENV_ID,
            "serviceId": JAXBOT_MAIN_SERVICE_ID,
            "name": name,
        }
    })
    if r.get("errors"):
        errors.append((name, r["errors"]))
        print(f"  ❌ {name}: {r['errors'][0].get('message','?')[:100]}")
    else:
        deleted += 1
        print(f"  ✅ {name} deleted")
print(f"\nDeleted {deleted}/{len(POLYMARKET_LEAKED_VARS)} env vars")

# 2) Delete the JaxBot telegram-alerts service
print("\n=== Step 2: Delete JaxBot telegram-alerts service ===")
service_delete_mutation = """
mutation ServiceDelete($id: String!, $environmentId: String) {
  serviceDelete(id: $id, environmentId: $environmentId)
}
"""
r = gql(service_delete_mutation, {
    "id": JAXBOT_TELEGRAM_ALERTS_SERVICE_ID,
    "environmentId": JAXBOT_PROD_ENV_ID,
})
if r.get("errors"):
    print(f"  ❌ {r['errors'][0].get('message','?')}")
else:
    print(f"  ✅ Service deleted: telegram-alerts ({JAXBOT_TELEGRAM_ALERTS_SERVICE_ID})")

# 3) Rename Polymarket-Bot project → Polymarket-Manual-2026
print("\n=== Step 3: Rename Polymarket-Bot → Polymarket-Manual-2026 ===")
project_update_mutation = """
mutation ProjectUpdate($id: String!, $input: ProjectUpdateInput!) {
  projectUpdate(id: $id, input: $input) { id name }
}
"""
r = gql(project_update_mutation, {
    "id": POLYMARKET_BOT_PROJECT_ID,
    "input": {"name": "Polymarket-Manual-2026"},
})
if r.get("errors"):
    print(f"  ❌ {r['errors'][0].get('message','?')}")
else:
    proj = r["data"]["projectUpdate"]
    print(f"  ✅ Renamed: {proj['name']}")

print("\nDONE")
