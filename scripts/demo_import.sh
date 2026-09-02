#!/usr/bin/env bash
# Import the synthetic Square dataset through the running API.
#
#   docker compose up -d --wait
#   ./scripts/demo_import.sh
#
# Uses only the generated demo files in demo/square-sample/. No real data.
set -euo pipefail

API="${API_URL:-http://localhost:8000}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/demo/square-sample"

echo "Importing the synthetic Square dataset into ${API} ..."
curl --fail-with-body -s -X POST "${API}/imports/square" \
  -F "transactions=@${DIR}/transactions-demo-2026-08.csv" \
  -F "items=@${DIR}/items-demo-2026-08.csv" \
  -F "summary=@${DIR}/item-sales-summary-demo-2026-08.csv" \
  -F "label=demo-august-2026" | python3 -m json.tool
