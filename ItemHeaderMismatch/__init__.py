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

def upload_to_slack(df: pd.DataFrame, filename="headerMismatch.xlsx"):
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
    SELECT *,
           ABS(calculated_net_amount - net_amount) AS difference_amount
    FROM (
      SELECT
          database_salehead.entry_date,
          database_salehead.entry_number,
          database_salehead.branch_id,
          database_branch.name AS branch_name,
          database_branch.domain,
          database_client.name AS client_name,
          database_salehead.billing_on,
          database_salehead.net_amount,
          database_salehead.gross_total,
          database_salehead.total_gst,
          database_salehead.total_disc,
          SUM(database_salesitem.sale_value) AS item_total_sale_value,
          SUM(database_salesitem.gst_value) AS item_total_gst_value,
          SUM(database_salesitem.discount_amount) AS item_discount_sale_value,
          database_salehead.id,
          SUM(
              CASE
                WHEN database_salehead.billing_on IN ('3', '8', '9') THEN
                  (
                    sale_value - ((sale_value * database_salesitem.discount_amount) / 100) * 
                    (1 - COALESCE(Customer.discount_factor, 0) / 100)
                    - CASE
                        WHEN Settings.overide_item_with_header = true THEN 0
                        ELSE (
                          (
                            (sale_value - ((sale_value * database_salesitem.discount_amount) / 100)) * 
                            (1 - COALESCE(Customer.discount_factor, 0) / 100) * 
                            COALESCE(overall_disc, 0)
                          ) / 100
                        )
                      END
                  ) / (1 + (database_salesitem.gst::double precision / 100))
                ELSE
                  (
                    sale_value - ((sale_value * database_salesitem.discount_amount) / 100) * 
                    (1 - COALESCE(Customer.discount_factor, 0) / 100)
                    - CASE
                        WHEN Settings.overide_item_with_header = true THEN 0
                        ELSE (
                          (
                            (sale_value - ((sale_value * database_salesitem.discount_amount) / 100)) * 
                            COALESCE(overall_disc, 0)
                          ) / 100
                        )
                      END
                  )
              END
          )::numeric(16,2) AS items_tax_value,
          SUM(
              CASE
                WHEN database_salehead.billing_on IN ('3', '8', '9') THEN
                  (
                    sale_value - ((sale_value * database_salesitem.discount_amount) / 100) * 
                    (1 - COALESCE(Customer.discount_factor, 0) / 100)
                    - CASE
                        WHEN Settings.overide_item_with_header = true THEN 0
                        ELSE (
                          (
                            (sale_value - ((sale_value * database_salesitem.discount_amount) / 100)) * 
                            (1 - COALESCE(Customer.discount_factor, 0) / 100) * 
                            COALESCE(overall_disc, 0)
                          ) / 100
                        )
                      END
                  )
                ELSE
                  (
                    sale_value - ((sale_value * database_salesitem.discount_amount) / 100) * 
                    (1 - COALESCE(Customer.discount_factor, 0) / 100)
                    - CASE
                        WHEN Settings.overide_item_with_header = true THEN 0
                        ELSE (
                          (
                            (sale_value - ((sale_value * database_salesitem.discount_amount) / 100)) * 
                            COALESCE(overall_disc, 0)
                          ) / 100
                        )
                      END
                  ) * (1 + (database_salesitem.gst::double precision / 100))
              END
          )::numeric(16,2) AS items_total_value,
          CASE
            WHEN database_salehead.billing_on IN ('3', '8', '9') THEN
              database_salehead.gross_total - database_salehead.total_disc
            ELSE
              database_salehead.gross_total + database_salehead.total_gst - database_salehead.total_disc
          END AS calculated_net_amount
      FROM
          database_salehead
      LEFT JOIN database_salesitem ON database_salehead.id = database_salesitem.sale_header_id
      LEFT JOIN database_branch ON database_salehead.branch_id = database_branch.id
      LEFT JOIN database_client ON database_branch.client_id = database_client.id
      LEFT JOIN database_sale_settings AS Settings ON Settings.branch_id = database_salehead.branch_id
      LEFT JOIN database_customer AS Customer ON Customer.id = database_salehead.customer_id_id
      WHERE
          TRIM(database_salehead.entry_date) <> ''
          AND TO_TIMESTAMP(database_salehead.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= (CURRENT_DATE - INTERVAL '1 day')
          AND TO_TIMESTAMP(database_salehead.entry_date, 'YYYY-MM-DD HH24:MI:SS') < CURRENT_DATE
      GROUP BY
          database_salehead.entry_date,
          database_salehead.entry_number,
          database_salehead.id,
          database_salehead.billing_on,
          database_salehead.net_amount,
          database_salehead.gross_total,
          database_salehead.total_gst,
          database_salehead.total_disc,
          database_salehead.branch_id,
          database_branch.name,
          database_branch.domain,
          database_client.id,
          database_client.name
    ) AS sale_summary
    WHERE ABS(calculated_net_amount - net_amount) <> 0;
    """

    print("[DEBUG] main: Executing header mismatch query...")
    df = run_query(sql)
    print(f"[DEBUG] main: Dataframe empty={df.empty}")

    if df.empty:
        print("[DEBUG] main: No mismatches found path taken")
        return func.HttpResponse(
            '{"response_type":"ephemeral","text":"✅ No item-header mismatches found."}',
            mimetype="application/json"
        )

    print("[DEBUG] main: Uploading results to Slack...")
    res = upload_to_slack(df, filename="headerMismatch.xlsx")
    print(f"[DEBUG] main: Upload completed. ok={res.get('ok')}, error={res.get('error')}")

    if res.get("ok"):
        return func.HttpResponse(
            '{"response_type":"in_channel","text":"⚠️ Found mismatches, Excel file uploaded 📂"}',
            mimetype="application/json"
        )
    else:
        return func.HttpResponse(
            f'{{"response_type":"ephemeral","text":"❌ Slack upload failed: {res.get("error")}"}}',
            mimetype="application/json"
        )
