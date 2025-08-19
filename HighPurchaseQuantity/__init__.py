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
        return func.HttpResponse("No high purchase quantity issues found")
    return func.HttpResponse(df.to_csv(index=False), mimetype="text/csv")
