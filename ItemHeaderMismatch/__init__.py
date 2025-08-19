import logging
import azure.functions as func
import psycopg2
import pandas as pd
import os

DB_URL = os.getenv("DB_URL")

def run_query(sql: str) -> pd.DataFrame:
    try:
        conn = psycopg2.connect(DB_URL)
        df = pd.read_sql(sql, conn)
        conn.close()
        return df
    except Exception as e:
        logging.error(f"Database error: {e}")
        return pd.DataFrame()

def main(req: func.HttpRequest) -> func.HttpResponse:
    sql = """ 
    SELECT *,
       -- Calculate the difference amount between net_amount and calculated_net_amount
       ABS(calculated_net_amount - net_amount) AS difference_amount
FROM (
  SELECT
      database_salehead.entry_date,       -- Ensure entry_date is the first column
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
                sale_value - ((sale_value * database_salesitem.discount_amount) / 100) * (1 - 
COALESCE(Customer.discount_factor, 0) / 100)
                - CASE
                    WHEN Settings.overide_item_with_header = true THEN 0
                    ELSE (
                      (
                        (sale_value - ((sale_value * database_salesitem.discount_amount) / 100)) * (1 - 
COALESCE(Customer.discount_factor, 0) / 100)
                        * COALESCE(overall_disc, 0)
                      ) / 100
                    )
                  END
              ) / (1 + (database_salesitem.gst::double precision / 100))
            ELSE
              (
                sale_value - ((sale_value * database_salesitem.discount_amount) / 100) * (1 - 
COALESCE(Customer.discount_factor, 0) / 100)
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
                sale_value - ((sale_value * database_salesitem.discount_amount) / 100) * (1 - 
COALESCE(Customer.discount_factor, 0) / 100)
                - CASE
                    WHEN Settings.overide_item_with_header = true THEN 0
                    ELSE (
                      (
                        (sale_value - ((sale_value * database_salesitem.discount_amount) / 100)) * (1 - 
COALESCE(Customer.discount_factor, 0) / 100)
                        * COALESCE(overall_disc, 0)
                      ) / 100
                    )
                  END
              )
            ELSE
              (
                sale_value - ((sale_value * database_salesitem.discount_amount) / 100) * (1 - 
COALESCE(Customer.discount_factor, 0) / 100)
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
      -- Calculate calculated_net_amount based on billing_on condition
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
  LEFT JOIN database_sale_settings AS Settings ON Settings.branch_id = 
database_salehead.branch_id
  LEFT JOIN database_customer AS Customer ON Customer.id = 
database_salehead.customer_id_id
  WHERE
      TRIM(database_salehead.entry_date) <> ''
      AND TO_TIMESTAMP(database_salehead.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= 
(CURRENT_DATE - INTERVAL '1 day')
      AND TO_TIMESTAMP(database_salehead.entry_date, 'YYYY-MM-DD HH24:MI:SS') < 
CURRENT_DATE
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
    df = run_query(sql)
    if df.empty:
        return func.HttpResponse("No item-header mismatches found")
    return func.HttpResponse(df.to_csv(index=False), mimetype="text/csv")
