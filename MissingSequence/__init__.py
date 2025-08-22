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

def upload_to_slack(df: pd.DataFrame, filename="missingSequence.xlsx"):
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
      mn.entry_prefix || LPAD(mn.expected_num::TEXT, 4, '0') AS missing_entry_number,
      mn.branch_id,
      b.domain,
      b2b.is_retail_b2b_bill
    FROM (
      SELECT
        an.entry_prefix,
        an.branch_id,
        an.expected_num
      FROM (
        SELECT
          nr.entry_prefix,
          nr.branch_id,
          generate_series(nr.min_num, nr.max_num) AS expected_num
        FROM (
          SELECT
            entry_prefix,
            branch_id,
            MIN(num_part) AS min_num,
            MAX(num_part) AS max_num
          FROM (
            SELECT
              sh.branch_id,
              LEFT(sh.entry_number, LENGTH(sh.entry_number) - 4) AS entry_prefix,
              RIGHT(sh.entry_number, 4)::INTEGER AS num_part,
              sh.is_retail_b2b_bill
            FROM
              database_salehead sh
            WHERE
              sh.entry_number IS NOT NULL
              AND LENGTH(sh.entry_number) >= 4
              AND RIGHT(sh.entry_number, 4) ~ '^\d{4}$'
              AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= CURRENT_DATE - INTERVAL '1 days'
              AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') <= CURRENT_DATE
          ) AS extracted_numbers
          GROUP BY entry_prefix, branch_id
        ) AS nr
      ) AS an
      LEFT JOIN (
        SELECT
          sh.branch_id,
          LEFT(sh.entry_number, LENGTH(sh.entry_number) - 4) AS entry_prefix,
          RIGHT(sh.entry_number, 4)::INTEGER AS num_part
        FROM
          database_salehead sh
        WHERE
          sh.entry_number IS NOT NULL
          AND LENGTH(sh.entry_number) >= 4
          AND RIGHT(sh.entry_number, 4) ~ '^\d{4}$'
          AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= CURRENT_DATE - INTERVAL '1 days'
          AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') <= CURRENT_DATE
      ) AS e
        ON an.entry_prefix = e.entry_prefix
        AND an.branch_id = e.branch_id
        AND an.expected_num = e.num_part
      WHERE e.num_part IS NULL
    ) AS mn
    JOIN
      database_branch b ON mn.branch_id = b.id
    LEFT JOIN (
      SELECT DISTINCT ON (
        LEFT(sh.entry_number, LENGTH(sh.entry_number) - 4), sh.branch_id
      )
        LEFT(sh.entry_number, LENGTH(sh.entry_number) - 4) AS entry_prefix,
        sh.branch_id,
        sh.is_retail_b2b_bill
      FROM
        database_salehead sh
      WHERE
        sh.entry_number IS NOT NULL
        AND LENGTH(sh.entry_number) >= 4
        AND RIGHT(sh.entry_number, 4) ~ '^\d{4}$'
        AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= CURRENT_DATE - INTERVAL '1 days'
        AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') <= CURRENT_DATE
    ) AS b2b
      ON mn.entry_prefix = b2b.entry_prefix
      AND mn.branch_id = b2b.branch_id
    ORDER BY
      mn.branch_id,
      missing_entry_number;
    """

    print("[DEBUG] main: Executing missing sequence query...")
    df = run_query(sql)
    print(f"[DEBUG] main: Dataframe empty={df.empty}")

    if df.empty:
        print("[DEBUG] main: No missing sequences found path taken")
        return func.HttpResponse(
            '{"response_type":"ephemeral","text":"✅ No missing sequences found."}',
            mimetype="application/json"
        )

    print("[DEBUG] main: Uploading results to Slack...")
    res = upload_to_slack(df, filename="missingSequence.xlsx")
    print(f"[DEBUG] main: Upload completed. ok={res.get('ok')}, error={res.get('error')}")

    if res.get("ok"):
        return func.HttpResponse(
            '{"response_type":"in_channel","text":"⚠️ Missing sequences detected, Excel file uploaded 📂"}',
            mimetype="application/json"
        )
    else:
        return func.HttpResponse(
            f'{{"response_type":"ephemeral","text":"❌ Slack upload failed: {res.get("error")}"}}',
            mimetype="application/json"
        )
