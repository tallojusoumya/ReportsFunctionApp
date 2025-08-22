import logging
import azure.functions as func
import psycopg2
import pandas as pd
import os
import requests
from io import BytesIO
import urllib.parse

DB_URL = os.getenv("DB_URL")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")  

print(f"[DEBUG] Env - DB_URL set: {bool(DB_URL)}")
print(f"[DEBUG] Env - SLACK_BOT_TOKEN set: {bool(SLACK_BOT_TOKEN)}")
print(f"[DEBUG] Env - CHANNEL_ID: {CHANNEL_ID}")

def run_query(sql: str) -> pd.DataFrame:
    try:
        print("[DEBUG] run_query: Connecting to DB...")
        conn = psycopg2.connect(DB_URL)
        print("[DEBUG] run_query: Running SQL query...")
        df = pd.read_sql(sql, conn)
        conn.close()
        print(f"[DEBUG] run_query: Query complete, rows returned: {len(df)}")
        return df
    except Exception as e:
        logging.error(f"Database error: {e}")
        print(f"[DEBUG] run_query: Exception occurred: {e}")
        return pd.DataFrame()

def upload_to_slack(df: pd.DataFrame, filename="duplicateInvoices.xlsx"):
    print(f"[DEBUG] upload_to_slack: Preparing to upload. rows={len(df)}, filename={filename}")
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    print("[DEBUG] upload_to_slack: Sending request to Slack API...")
    response = requests.post(
        "https://slack.com/api/files.uploadV2",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        files={"file": (filename, output, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"channels": CHANNEL_ID, "title": filename}
    )
    print(f"[DEBUG] upload_to_slack: Slack response status_code={response.status_code}")

    try:
        json_res = response.json()
    except Exception as e:
        print(f"[DEBUG] upload_to_slack: Failed to parse JSON response: {e}")
        json_res = {"ok": False, "error": "invalid_json"}

    print(f"[DEBUG] upload_to_slack: Slack response ok={json_res.get('ok')}, error={json_res.get('error')}")
    return json_res

def main(req: func.HttpRequest) -> func.HttpResponse:
    print("[DEBUG] main: Function invoked")
    try:
        body = req.get_body().decode("utf-8")
        print(f"[DEBUG] main: Request body length={len(body)}")
    except Exception as e:
        print(f"[DEBUG] main: Failed to decode request body: {e}")
        body = ""
    data = urllib.parse.parse_qs(body)

    sql = """ 
    SELECT
        database_salehead.id,
        database_salehead.entry_number,
        database_salehead.entry_date,
        database_salehead.branch_id,
        database_branch.name,
        database_branch.domain
    FROM
        database_salehead
    JOIN
        database_branch ON database_salehead.branch_id = database_branch.id
    WHERE
        database_salehead.entry_number IN (
            SELECT entry_number
            FROM database_salehead
            WHERE
                entry_date IS NOT NULL
                AND entry_date <> ''
                AND CAST(entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY'
            GROUP BY entry_number
            HAVING COUNT(*) > 1
        )
        AND database_salehead.entry_date IS NOT NULL
        AND database_salehead.entry_date <> ''
        AND CAST(database_salehead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';
    """

    print("[DEBUG] main: Executing duplicate invoices query...")
    df = run_query(sql)
    print(f"[DEBUG] main: Dataframe empty={df.empty}")

    if df.empty:
        print("[DEBUG] main: No duplicates found path taken")
        return func.HttpResponse(
            f'{{"response_type":"ephemeral","text":"✅ No duplicate invoices found."}}',
            mimetype="application/json"
        )

   
    print("[DEBUG] main: Uploading results to Slack...")
    res = upload_to_slack(df, filename="duplicateInvoices.xlsx")
    print(f"[DEBUG] main: Upload completed. ok={res.get('ok')}, error={res.get('error')}")

   
    if res.get("ok"):
        return func.HttpResponse(
            '{"response_type":"in_channel","text":"⚠️ Found duplicate invoices, Excel file uploaded 📂"}',
            mimetype="application/json"
        )
    else:
        return func.HttpResponse(
            f'{{"response_type":"ephemeral","text":"❌ Slack upload failed: {res.get("error")}"}}',
            mimetype="application/json"
        )
