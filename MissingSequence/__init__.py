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
          AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= 
CURRENT_DATE - INTERVAL '1 days'
          AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') <= 
CURRENT_DATE
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
      AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= CURRENT_DATE 
- INTERVAL '1 days'
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
    AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= CURRENT_DATE -
INTERVAL '1 days'
    AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') <= CURRENT_DATE
) AS b2b
  ON mn.entry_prefix = b2b.entry_prefix
  AND mn.branch_id = b2b.branch_id
ORDER BY
  mn.branch_id,
  missing_entry_number;
    """
    df = run_query(sql)
    if df.empty:
        return func.HttpResponse("No missing sequence records found")
    return func.HttpResponse(df.to_csv(index=False), mimetype="text/csv")
