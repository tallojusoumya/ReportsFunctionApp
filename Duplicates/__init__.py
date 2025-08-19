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
        return func.HttpResponse("No duplicate invoices found")
    return func.HttpResponse(df.to_csv(index=False), mimetype="text/csv")
