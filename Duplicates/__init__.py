import logging
import azure.functions as func
import psycopg2
import pandas as pd
import os
import requests
from io import BytesIO

DB_URL = os.getenv("DB_URL")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")

def run_query(sql: str) -> pd.DataFrame:
    try:
        conn = psycopg2.connect(DB_URL)
        df = pd.read_sql(sql, conn)
        conn.close()
        return df
    except Exception as e:
        logging.error(f"Database error: {e}")
        return pd.DataFrame()

def upload_to_slack(df: pd.DataFrame, channel: str, filename="duplicateInvoices.xlsx"):
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    response = requests.post(
        "https://slack.com/api/files.upload",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        files={"file": (filename, output, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"channels": channel, "title": filename}
    )
    return response.json()

def main(req: func.HttpRequest) -> func.HttpResponse:
    channel_id = req.form.get("channel_id") if req.form else None

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
    AND CAST(database_salehead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 
DAY';

    """
    df = run_query(sql)

    if df.empty:
        return func.HttpResponse('{"response_type":"in_channel","text":"✅ No duplicate invoices found"}', mimetype="application/json")

    res = upload_to_slack(df, channel_id, filename="duplicateInvoices.xlsx")
    if res.get("ok"):
        return func.HttpResponse('{"response_type":"in_channel","text":"⚠️ Found duplicate invoices, Excel file uploaded 📂"}', mimetype="application/json")
    else:
        return func.HttpResponse(f'{{"response_type":"ephemeral","text":"❌ Slack upload failed: {res.get("error")}"}}', mimetype="application/json")
