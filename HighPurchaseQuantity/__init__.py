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

def upload_to_slack(df: pd.DataFrame, channel: str, filename="highQuantity.xlsx"):
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
    database_branch.domain,  
    database_purchaseitem.purchase_header_id, 
    database_purchaseitem.purchase_value, 
    database_purchaseitem.purchase_quantity, 
    database_purchaseitem.purchase_free,
    (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) AS 
sum_of_PQ_PF
FROM 
    database_salehead
JOIN 
    database_branch ON database_salehead.branch_id = database_branch.id
JOIN 
    database_purchaseitem ON database_salehead.branch_id = database_purchaseitem.branch_id
WHERE 
    database_salehead.entry_date <> '' AND
    database_salehead.entry_date IS NOT NULL AND
    to_timestamp(database_salehead.entry_date, 'YYYY-MM-DD') >= (CURRENT_DATE - 
INTERVAL '1 day') AND
    to_timestamp(database_salehead.entry_date, 'YYYY-MM-DD') < CURRENT_DATE AND
    (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) > 5000;
    """
    df = run_query(sql)

    if df.empty:
        return func.HttpResponse('{"response_type":"in_channel","text":"✅ No high quantity purchases found"}', mimetype="application/json")

    res = upload_to_slack(df, channel_id, filename="highQuantity.xlsx")
    if res.get("ok"):
        return func.HttpResponse('{"response_type":"in_channel","text":"⚠️ High quantity purchases detected, Excel file uploaded 📂"}', mimetype="application/json")
    else:
        return func.HttpResponse(f'{{"response_type":"ephemeral","text":"❌ Slack upload failed: {res.get("error")}"}}', mimetype="application/json")
