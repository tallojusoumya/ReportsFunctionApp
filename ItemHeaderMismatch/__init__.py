import logging
import azure.functions as func
import psycopg2
import pandas as pd
import os
import urllib.parse
from utils.slack_uploader import upload_to_slack_external

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
          sh.entry_date,
          sh.entry_number,
          sh.branch_id,
          b.name AS branch_name,
          b.domain,
          c.name AS client_name,
          sh.billing_on,
          sh.net_amount,
          sh.gross_total,
          sh.total_gst,
          sh.total_disc,
          SUM(si.sale_value) AS item_total_sale_value,
          SUM(si.gst_value) AS item_total_gst_value,
          SUM(si.discount_amount) AS item_discount_sale_value,
          sh.id,
          SUM(
              CASE
                WHEN sh.billing_on IN ('3', '8', '9') THEN
                  (
                    si.sale_value - ((si.sale_value * si.discount_amount) / 100) * 
                    (1 - COALESCE(cust.discount_factor, 0) / 100)
                    - CASE
                        WHEN setts.overide_item_with_header = true THEN 0
                        ELSE (
                          (
                            (si.sale_value - ((si.sale_value * si.discount_amount) / 100)) * 
                            (1 - COALESCE(cust.discount_factor, 0) / 100) * 
                            COALESCE(overall_disc, 0)
                          ) / 100
                        )
                      END
                  ) / (1 + (si.gst::double precision / 100))
                ELSE
                  (
                    si.sale_value - ((si.sale_value * si.discount_amount) / 100) * 
                    (1 - COALESCE(cust.discount_factor, 0) / 100)
                    - CASE
                        WHEN setts.overide_item_with_header = true THEN 0
                        ELSE (
                          (
                            (si.sale_value - ((si.sale_value * si.discount_amount) / 100)) * 
                            COALESCE(overall_disc, 0)
                          ) / 100
                        )
                      END
                  )
              END
          )::numeric(16,2) AS items_tax_value,
          SUM(
              CASE
                WHEN sh.billing_on IN ('3', '8', '9') THEN
                  (
                    si.sale_value - ((si.sale_value * si.discount_amount) / 100) * 
                    (1 - COALESCE(cust.discount_factor, 0) / 100)
                    - CASE
                        WHEN setts.overide_item_with_header = true THEN 0
                        ELSE (
                          (
                            (si.sale_value - ((si.sale_value * si.discount_amount) / 100)) * 
                            (1 - COALESCE(cust.discount_factor, 0) / 100) * 
                            COALESCE(overall_disc, 0)
                          ) / 100
                        )
                      END
                  )
                ELSE
                  (
                    si.sale_value - ((si.sale_value * si.discount_amount) / 100) * 
                    (1 - COALESCE(cust.discount_factor, 0) / 100)
                    - CASE
                        WHEN setts.overide_item_with_header = true THEN 0
                        ELSE (
                          (
                            (si.sale_value - ((si.sale_value * si.discount_amount) / 100)) * 
                            COALESCE(overall_disc, 0)
                          ) / 100
                        )
                      END
                  ) * (1 + (si.gst::double precision / 100))
              END
          )::numeric(16,2) AS items_total_value,
          CASE
            WHEN sh.billing_on IN ('3', '8', '9') THEN
              sh.gross_total - sh.total_disc
            ELSE
              sh.gross_total + sh.total_gst - sh.total_disc
          END AS calculated_net_amount
      FROM
          database_salehead sh
      LEFT JOIN database_salesitem si ON sh.id = si.sale_header_id
      LEFT JOIN database_branch b ON sh.branch_id = b.id
      LEFT JOIN database_client c ON b.client_id = c.id
      LEFT JOIN database_sale_settings setts ON setts.branch_id = sh.branch_id
      LEFT JOIN database_customer cust ON cust.id = sh.customer_id_id
      WHERE
          TRIM(sh.entry_date) <> ''
          AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= (CURRENT_DATE - INTERVAL '1 day')
          AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') < CURRENT_DATE
      GROUP BY
          sh.entry_date,
          sh.entry_number,
          sh.id,
          sh.billing_on,
          sh.net_amount,
          sh.gross_total,
          sh.total_gst,
          sh.total_disc,
          sh.branch_id,
          b.name,
          b.domain,
          c.id,
          c.name
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
    res = upload_to_slack_external(df, "headerMismatch.xlsx", CHANNEL_ID)
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
