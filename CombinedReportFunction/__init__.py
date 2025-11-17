import azure.functions as func
import logging
import pandas as pd
from sqlalchemy import create_engine
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
import tempfile
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from openpyxl.styles import Font
from datetime import datetime
import os

# --------------------
POSTGRES_URL = os.getenv("POSTGRES_URL")
SLACK_TOKEN = os.getenv("SLACK_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")

engine = create_engine(POSTGRES_URL)
slack_client = WebClient(token=SLACK_TOKEN)


TABLES = {
        "Database_salehead": {
        "Invoice_Sequence_Missing": """SELECT
  sh.id,
  sh.entry_number,
  sh.entry_date,
  b.name AS branch_name,
  b.domain,
  b2b.is_retail_b2b_bill,
  mn.entry_prefix || LPAD(mn.expected_num::TEXT, 4, '0') AS missing_entry_number,
  mn.branch_id
  
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
JOIN database_branch b 
  ON mn.branch_id = b.id
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
LEFT JOIN database_salehead sh
  ON sh.branch_id = mn.branch_id
  AND LEFT(sh.entry_number, LENGTH(sh.entry_number) - 4) = mn.entry_prefix
ORDER BY
  mn.branch_id,
  missing_entry_number;

  """,
  
  "Invoice_Duplicates": """SELECT
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
DAY';""",
        "Item_Header_Mismatch": """SELECT *,
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
WHERE ABS(calculated_net_amount - net_amount) <> 0;""",


        "High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)": """SELECT 
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
    (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) > 5000;"""
    },
    "Database_Purchasehead": {
        "Invoice_Sequence_Missing": """SELECT
  ph.id,
  ph.entry_number,
  ph.entry_date,
  b.name,
  b.domain,
  mn.entry_prefix || LPAD(mn.expected_num::TEXT, 4, '0') AS missing_entry_number,
  mn.branch_id
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
          RIGHT(sh.entry_number, 4)::INTEGER AS num_part
        FROM
          database_purchasehead sh
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
      database_purchasehead sh
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
JOIN database_branch b 
  ON mn.branch_id = b.id
LEFT JOIN database_purchasehead ph
  ON ph.branch_id = mn.branch_id
  AND LEFT(ph.entry_number, LENGTH(ph.entry_number) - 4) = mn.entry_prefix
ORDER BY mn.branch_id, 
missing_entry_number;
""",
        "Invoice_Duplicates": """SELECT
    database_purchasehead.id,
    database_purchasehead.entry_number,
    database_purchasehead.entry_date,
    database_purchasehead.branch_id,
    database_branch.name,
    database_branch.domain
FROM
    database_purchasehead
JOIN
    database_branch ON database_purchasehead.branch_id = database_branch.id
WHERE
    database_purchasehead.entry_number IN (
        SELECT entry_number
        FROM database_purchasehead
        WHERE
            entry_date IS NOT NULL
            AND entry_date <> ''
            AND CAST(entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY'
        GROUP BY entry_number
        HAVING COUNT(*) > 1
    )
    AND database_purchasehead.entry_date IS NOT NULL
    AND database_purchasehead.entry_date <> ''
    AND CAST(database_purchasehead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';""",


    "Item_Header_Mismatch":"""SELECT *,
     
       ABS(calculated_net_amount - net_amount) AS difference_amount
FROM (
  SELECT
  database_purchasehead.id,
      database_purchasehead.entry_date,       
      database_purchasehead.entry_number,
      database_purchasehead.branch_id,
      database_branch.name AS branch_name,
      database_branch.domain,
      database_client.name AS client_name,
      database_purchasehead.net_amount,
      database_purchasehead.gross_total,
      database_purchasehead.total_gst,
      database_purchasehead.total_disc,
      SUM(database_purchaseitem.purchase_value) AS item_total_purchase_value,
      SUM(database_purchaseitem.gst_value) AS item_total_gst_value,
      SUM(database_purchaseitem.discount_amount) AS item_discount_value,
      
      SUM(
          (
            purchase_value - ((purchase_value * database_purchaseitem.discount_amount) / 100)
            - (
                (
                  (purchase_value - ((purchase_value * database_purchaseitem.discount_amount) / 100))
                  * COALESCE(overall_disc, 0)
                ) / 100
              )
          )
      )::numeric(16,2) AS items_tax_value,
      SUM(
          (
            purchase_value - ((purchase_value * database_purchaseitem.discount_amount) / 100)
            - (
                (
                  (purchase_value - ((purchase_value * database_purchaseitem.discount_amount) / 100))
                  * COALESCE(overall_disc, 0)
                ) / 100
              )
          ) * (1 + (database_purchaseitem.gst::double precision / 100))
      )::numeric(16,2) AS items_total_value,
      -- Calculate calculated_net_amount with type casts
      (
        CAST(database_purchasehead.gross_total AS numeric)
        + CAST(database_purchasehead.total_gst AS numeric)
        - CAST(database_purchasehead.total_disc AS numeric)
      ) AS calculated_net_amount
  FROM
      database_purchasehead
  LEFT JOIN database_purchaseitem 
         ON database_purchasehead.id = database_purchaseitem.purchase_header_id
  LEFT JOIN database_branch 
         ON database_purchasehead.branch_id = database_branch.id
  LEFT JOIN database_client 
         ON database_branch.client_id = database_client.id
  LEFT JOIN database_purchase_settings AS Settings 
         ON Settings.branch_id = database_purchasehead.branch_id
  LEFT JOIN database_supplier AS Supplier 
         ON Supplier.id = database_purchasehead.supplier_id_id
  WHERE
      TRIM(database_purchasehead.entry_date) <> ''
      AND TO_TIMESTAMP(database_purchasehead.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= (CURRENT_DATE - INTERVAL '1 day')
      AND TO_TIMESTAMP(database_purchasehead.entry_date, 'YYYY-MM-DD HH24:MI:SS') < CURRENT_DATE
  GROUP BY
      database_purchasehead.entry_date,
      database_purchasehead.entry_number,
      database_purchasehead.id,
      database_purchasehead.net_amount,
      database_purchasehead.gross_total,
      database_purchasehead.total_gst,
      database_purchasehead.total_disc,
      database_purchasehead.branch_id,
      database_branch.name,
      database_branch.domain,
      database_client.id,
      database_client.name
) AS purchase_summary
WHERE ABS(calculated_net_amount - net_amount) <> 0;""",

        
        "High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)": """SELECT 
    database_purchasehead.id, 
    database_purchasehead.entry_number, 
    database_purchasehead.entry_date, 
    database_purchasehead.branch_id, 
    database_branch.name, 
    database_branch.domain,  
    database_purchaseitem.purchase_header_id, 
    database_purchaseitem.purchase_value, 
    database_purchaseitem.purchase_quantity, 
    database_purchaseitem.purchase_free,
    (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) AS sum_of_PQ_PF
FROM 
    database_purchasehead
JOIN 
    database_branch ON database_purchasehead.branch_id = database_branch.id
JOIN 
    database_purchaseitem ON database_purchasehead.branch_id = database_purchaseitem.branch_id
WHERE 
    database_purchasehead.entry_date <> '' 
    AND database_purchasehead.entry_date IS NOT NULL 
    AND to_timestamp(database_purchasehead.entry_date, 'YYYY-MM-DD') >= (CURRENT_DATE - INTERVAL '1 day') 
    AND to_timestamp(database_purchasehead.entry_date, 'YYYY-MM-DD') < CURRENT_DATE 
    AND (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) > 5000;""",
    },
    "Database_b2csalehead":{
    "Invoice_Sequence_Missing": """SELECT
  sh.id,
  sh.entry_number,
  sh.entry_date,
  b.name AS branch_name,
  b.domain,
  mn.entry_prefix || LPAD(mn.expected_num::TEXT, 4, '0') AS missing_entry_number,
  mn.branch_id
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
          RIGHT(sh.entry_number, 4)::INTEGER AS num_part
        FROM
          database_b2csalehead sh
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
      database_b2csalehead sh
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
JOIN database_branch b
  ON mn.branch_id = b.id
LEFT JOIN database_b2csalehead sh
  ON sh.branch_id = mn.branch_id
  AND LEFT(sh.entry_number, LENGTH(sh.entry_number) - 4) = mn.entry_prefix
ORDER BY
  mn.branch_id,
  missing_entry_number;""",

  "Invoice_Duplicates": """SELECT 
  database_b2csalehead.id,
    database_b2csalehead.entry_number,
    database_b2csalehead.entry_date,
    database_b2csalehead.branch_id,
    database_branch.name,
    database_branch.domain
FROM
    database_b2csalehead
JOIN
    database_branch ON database_b2csalehead.branch_id = database_branch.id
WHERE
    database_b2csalehead.entry_number IN (
        SELECT entry_number
        FROM database_b2csalehead
        WHERE
            entry_date IS NOT NULL
            AND entry_date <> ''
            AND CAST(entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY'
        GROUP BY entry_number
        HAVING COUNT(*) > 1
    )
    AND database_b2csalehead.entry_date IS NOT NULL
    AND database_b2csalehead.entry_date <> ''
    AND CAST(database_b2csalehead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';""",
    
    "Item_Header_Mismatch": """ select *,
       
       ABS(calculated_net_amount - net_amount) AS difference_amount
FROM (
  SELECT
      database_b2csalehead.entry_date,      
      database_b2csalehead.entry_number,
      database_b2csalehead.branch_id,
      database_branch.name AS branch_name,
      database_branch.domain,
      database_client.name AS client_name,
      database_b2csalehead.billing_on,
      database_b2csalehead.net_amount,
      database_b2csalehead.gross_total,
      database_b2csalehead.total_gst,
      database_b2csalehead.total_disc,
      SUM(database_salesitem.sale_value) AS item_total_sale_value,
      SUM(database_salesitem.gst_value) AS item_total_gst_value,
      SUM(database_salesitem.discount_amount) AS item_discount_sale_value,
      database_b2csalehead.id,
      SUM(
          CASE
            WHEN database_b2csalehead.billing_on IN ('3', '8', '9') THEN
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
            WHEN database_b2csalehead.billing_on IN ('3', '8', '9') THEN
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
      
      CASE
        WHEN database_b2csalehead.billing_on IN ('3', '8', '9') THEN
          database_b2csalehead.gross_total - database_b2csalehead.total_disc
        ELSE
          database_b2csalehead.gross_total + database_b2csalehead.total_gst - database_b2csalehead.total_disc
      END AS calculated_net_amount
  FROM
      database_b2csalehead
  LEFT JOIN database_salesitem ON database_b2csalehead.id = database_salesitem.sale_header_id
  LEFT JOIN database_branch ON database_b2csalehead.branch_id = database_branch.id
  LEFT JOIN database_client ON database_branch.client_id = database_client.id
  LEFT JOIN database_sale_settings AS Settings ON Settings.branch_id = 
database_b2csalehead.branch_id
  LEFT JOIN database_customer AS Customer ON Customer.id = 
database_b2csalehead.customer_id_id
  WHERE
      TRIM(database_b2csalehead.entry_date) <> ''
      AND TO_TIMESTAMP(database_b2csalehead.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= 
(CURRENT_DATE - INTERVAL '1 day')
      AND TO_TIMESTAMP(database_b2csalehead.entry_date, 'YYYY-MM-DD HH24:MI:SS') < 
CURRENT_DATE
  GROUP BY
      database_b2csalehead.entry_date,
      database_b2csalehead.entry_number,
      database_b2csalehead.id,
      database_b2csalehead.billing_on,
      database_b2csalehead.net_amount,
      database_b2csalehead.gross_total,
      database_b2csalehead.total_gst,
      database_b2csalehead.total_disc,
      database_b2csalehead.branch_id,
      database_branch.name,
      database_branch.domain,
      database_client.id,
      database_client.name
) AS sale_summary
WHERE ABS(calculated_net_amount - net_amount) <> 0;""",

"High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)": """SELECT 
    database_b2csalehead.id, 
    database_b2csalehead.entry_number, 
    database_b2csalehead.entry_date, 
    database_b2csalehead.branch_id, 
    database_branch.name, 
    database_branch.domain,  
    database_purchaseitem.purchase_header_id, 
    database_purchaseitem.purchase_value, 
    database_purchaseitem.purchase_quantity, 
    database_purchaseitem.purchase_free,
    (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) AS sum_of_PQ_PF
FROM 
    database_b2csalehead
JOIN 
    database_branch ON database_b2csalehead.branch_id = database_branch.id
JOIN 
    database_purchaseitem ON database_b2csalehead.branch_id = database_purchaseitem.branch_id
WHERE 
    database_b2csalehead.entry_date <> '' 
    AND database_b2csalehead.entry_date IS NOT NULL 
    AND to_timestamp(database_b2csalehead.entry_date, 'YYYY-MM-DD') >= (CURRENT_DATE - INTERVAL '1 day') 
    AND to_timestamp(database_b2csalehead.entry_date, 'YYYY-MM-DD') < CURRENT_DATE 
    AND (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) > 5000;""",
    },

"Database_Salereturnhead": {
        "Invoice_Sequence_Missing": """SELECT 
    srh.entry_number,
    srh.entry_date,
	b2b.is_b2b_bill,
    srh.id,
    mn.branch_id,
    b.name AS branch_name,
    b.domain,
    mn.entry_prefix || LPAD(mn.expected_num::TEXT, 4, '0') AS missing_entry_number
    
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
                    sh.is_b2b_bill
                FROM 
                    database_salereturnhead sh
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
            database_salereturnhead sh
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
        sh.is_b2b_bill
    FROM 
        database_salereturnhead sh
    WHERE 
        sh.entry_number IS NOT NULL
        AND LENGTH(sh.entry_number) >= 4
        AND RIGHT(sh.entry_number, 4) ~ '^\d{4}$'
        AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= CURRENT_DATE - INTERVAL '1 days'
        AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') <= CURRENT_DATE
) AS b2b
    ON mn.entry_prefix = b2b.entry_prefix
    AND mn.branch_id = b2b.branch_id
LEFT JOIN 
    database_salereturnhead srh
    ON srh.branch_id = mn.branch_id
    AND LEFT(srh.entry_number, LENGTH(srh.entry_number) - 4) = mn.entry_prefix
ORDER BY 
    mn.branch_id,
    missing_entry_number;""", 
    
    "Invoice_Duplicates": """SELECT
    database_salereturnhead.id,
    database_salereturnhead.entry_number,
    database_salereturnhead.entry_date,
    database_salereturnhead.branch_id,
    database_branch.name,
    database_branch.domain
FROM
    database_salereturnhead
JOIN
    database_branch ON database_salereturnhead.branch_id = database_branch.id
WHERE
    database_salereturnhead.entry_number IN (
        SELECT entry_number
        FROM database_salereturnhead
        WHERE
            entry_date IS NOT NULL
            AND entry_date <> ''
            AND CAST(entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY'
        GROUP BY entry_number
        HAVING COUNT(*) > 1
    )
    AND database_salereturnhead.entry_date IS NOT NULL
    AND database_salereturnhead.entry_date <> ''
    AND CAST(database_salereturnhead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';""",
   
   "Item_Header_Mismatch": """SELECT *,
       ABS(calculated_net_amount - net_amount) AS difference_amount
FROM (
  SELECT
      database_salereturnhead.entry_date,
      database_salereturnhead.entry_number,
      database_salereturnhead.branch_id,
      database_branch.name AS branch_name,
      database_branch.domain,
      database_client.name AS client_name,
      database_salereturnhead.billing_on,
      CAST(database_salereturnhead.net_amount AS numeric) AS net_amount,
      CAST(database_salereturnhead.gross_total AS numeric) AS gross_total,
      CAST(database_salereturnhead.total_gst AS numeric) AS total_gst,
      CAST(database_salereturnhead.total_disc AS numeric) AS total_disc,
      SUM(database_salesitem.sale_value) AS item_total_sale_value,
      SUM(database_salesitem.gst_value) AS item_total_gst_value,
      SUM(database_salesitem.discount_amount) AS item_discount_sale_value,
      database_salereturnhead.id,
      
      SUM(
          CASE
            WHEN database_salereturnhead.billing_on IN ('3', '8', '9') THEN
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
      -- items_total_value
      SUM(
          CASE
            WHEN database_salereturnhead.billing_on IN ('3', '8', '9') THEN
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
      -- calculated_net_amount
      CASE
        WHEN database_salereturnhead.billing_on IN ('3', '8', '9') THEN
          CAST(database_salereturnhead.gross_total AS numeric) 
          - CAST(database_salereturnhead.total_disc AS numeric)
        ELSE
          CAST(database_salereturnhead.gross_total AS numeric)
          + CAST(database_salereturnhead.total_gst AS numeric)
          - CAST(database_salereturnhead.total_disc AS numeric)
      END AS calculated_net_amount
  FROM
      database_salereturnhead
  LEFT JOIN database_salesitem ON database_salereturnhead.id = database_salesitem.sale_header_id
  LEFT JOIN database_branch ON database_salereturnhead.branch_id = database_branch.id
  LEFT JOIN database_client ON database_branch.client_id = database_client.id
  LEFT JOIN database_sale_settings AS Settings ON Settings.branch_id = database_salereturnhead.branch_id
  LEFT JOIN database_customer AS Customer ON Customer.id = database_salereturnhead.customer_id_id
  WHERE
      TRIM(database_salereturnhead.entry_date) <> ''
      AND TO_TIMESTAMP(database_salereturnhead.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= (CURRENT_DATE - INTERVAL '1 day')
      AND TO_TIMESTAMP(database_salereturnhead.entry_date, 'YYYY-MM-DD HH24:MI:SS') < CURRENT_DATE
  GROUP BY
      database_salereturnhead.entry_date,
      database_salereturnhead.entry_number,
      database_salereturnhead.id,
      database_salereturnhead.billing_on,
      database_salereturnhead.net_amount,
      database_salereturnhead.gross_total,
      database_salereturnhead.total_gst,
      database_salereturnhead.total_disc,
      database_salereturnhead.branch_id,
      database_branch.name,
      database_branch.domain,
      database_client.id,
      database_client.name
) AS sale_summary
WHERE ABS(calculated_net_amount - net_amount) <> 0;""",

"High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)": """
SELECT 
    srh.id, 
    srh.entry_number, 
    srh.entry_date, 
    srh.branch_id,
    b.name AS branch_name, 
    b.domain,  
    sri.sale_return_header_id, 
    sri.sale_value, 
    sri.sale_quantity, 
    sri.sale_free,
    (sri.sale_quantity + sri.sale_free) AS sum_of_SQ_SF
FROM 
    database_salereturnhead srh
JOIN 
    database_branch b 
        ON srh.branch_id = b.id
JOIN 
    database_salereturnitem sri 
        ON srh.id = sri.sale_return_header_id
WHERE 
    srh.entry_date IS NOT NULL 
    AND srh.entry_date <> ''
    AND TO_TIMESTAMP(srh.entry_date, 'YYYY-MM-DD') >= (CURRENT_DATE - INTERVAL '1 day')
    AND TO_TIMESTAMP(srh.entry_date, 'YYYY-MM-DD') < CURRENT_DATE
    AND (sri.sale_quantity + sri.sale_free) > 5000;"""
},
"Database_Purchasereturnhead": {
        "Invoice_Sequence_Missing": """SELECT
  ph.entry_number,
  ph.entry_date,
  ph.id,
  ph.branch_id,
  b.name,
  b.domain,
  mn.entry_prefix || LPAD(mn.expected_num::TEXT, 4, '0') AS missing_entry_number
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
          RIGHT(sh.entry_number, 4)::INTEGER AS num_part
        FROM
          database_purchasereturnhead sh
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
      database_purchasereturnhead sh
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
JOIN database_branch b 
  ON mn.branch_id = b.id
LEFT JOIN database_purchasereturnhead ph
  ON ph.branch_id = mn.branch_id
  AND LEFT(ph.entry_number, LENGTH(ph.entry_number) - 4) = mn.entry_prefix
ORDER BY
  mn.branch_id,
  missing_entry_number;""",

        "Invoice_Duplicates": """SELECT
	    database_purchasereturnhead.id,
	    database_purchasereturnhead.entry_number,
	    database_purchasereturnhead.entry_date,
	    database_purchasereturnhead.branch_id,
	    database_branch.name,
	    database_branch.domain
	FROM
	    database_purchasereturnhead
	JOIN
	    database_branch ON database_purchasereturnhead.branch_id = database_branch.id
	WHERE
	    database_purchasereturnhead.entry_number IN (
	        SELECT entry_number
	        FROM database_purchasereturnhead
	        WHERE
	            entry_date IS NOT NULL
	            AND entry_date <> ''
	            AND CAST(entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY'
	        GROUP BY entry_number
	        HAVING COUNT(*) > 1
	    )
	    AND database_purchasereturnhead.entry_date IS NOT NULL
	    AND database_purchasereturnhead.entry_date <> ''
	    AND CAST(database_purchasereturnhead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';""",
    
        "Item_Header_Mismatch":""" SELECT *,

       ABS(calculated_net_amount - net_amount) AS difference_amount
FROM (
  SELECT
      prh.entry_date,       
      prh.entry_number,
      prh.branch_id,
      b.name AS branch_name,
      b.domain,
      c.name AS supplier_name,
      prh.billing_on,
      prh.net_amount,
      prh.gross_total,
      prh.total_gst,
      prh.total_disc,
      SUM(pri.return_value) AS item_total_purchase_returnvalue,
      SUM(pri.gst_value) AS item_total_gst_value,
      SUM(pri.discount_amount) AS item_discount_value,
      prh.id,
      SUM(
          CASE
            WHEN prh.billing_on IN ('3', '8', '9') THEN
              (
                pri.return_value - ((pri.return_value * pri.discount_amount) / 100)
                - CASE
                    WHEN s.overide_item_with_header = true THEN 0
                    ELSE (((pri.return_value - ((pri.return_value * pri.discount_amount) / 100)) * COALESCE(cust.discount_factor,0)) / 100)
                  END
              ) / (1 + (pri.gst::double precision / 100))
            ELSE
              (
                pri.return_value - ((pri.return_value * pri.discount_amount) / 100)
                - CASE
                    WHEN s.overide_item_with_header = true THEN 0
                    ELSE (((pri.return_value - ((pri.return_value * pri.discount_amount) / 100)) * COALESCE(cust.discount_factor,0)) / 100)
                  END
              )
          END
      )::numeric(16,2) AS items_tax_value,
      SUM(
          CASE
            WHEN prh.billing_on IN ('3', '8', '9') THEN
              (
                pri.return_value - ((pri.return_value * pri.discount_amount) / 100)
                - CASE
                    WHEN s.overide_item_with_header = true THEN 0
                    ELSE (((pri.return_value - ((pri.return_value * pri.discount_amount) / 100)) * COALESCE(cust.discount_factor,0)) / 100)
                  END
              )
            ELSE
              (
                pri.return_value - ((pri.return_value * pri.discount_amount) / 100)
                - CASE
                    WHEN s.overide_item_with_header = true THEN 0
                    ELSE (((pri.return_value - ((pri.return_value * pri.discount_amount) / 100)) * COALESCE(cust.discount_factor,0)) / 100)
                  END
              ) * (1 + (pri.gst::double precision / 100))
          END
      )::numeric(16,2) AS items_total_value,
      -- Calculate calculated_net_amount based on billing_on condition
      CASE
  WHEN prh.billing_on IN ('3', '8', '9') THEN
    CAST(prh.gross_total AS numeric) - CAST(prh.total_disc AS numeric)
  ELSE
    CAST(prh.gross_total AS numeric) + CAST(prh.total_gst AS numeric) - CAST(prh.total_disc AS numeric)
END AS calculated_net_amount
  FROM
      database_purchasereturnhead prh
  LEFT JOIN database_purchasereturnitem pri ON prh.id = pri.purchase_return_header_id
  LEFT JOIN database_branch b ON prh.branch_id = b.id
  LEFT JOIN database_client c ON prh.supplier_id_id = c.id
  LEFT JOIN database_sale_settings s ON s.branch_id = prh.branch_id
  LEFT JOIN database_customer cust ON cust.id = prh.supplier_id_id
  WHERE
      TRIM(prh.entry_date) <> ''
      AND TO_TIMESTAMP(prh.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= (CURRENT_DATE - INTERVAL '1 day')
      AND TO_TIMESTAMP(prh.entry_date, 'YYYY-MM-DD HH24:MI:SS') < CURRENT_DATE
  GROUP BY
      prh.entry_date,
      prh.entry_number,
      prh.id,
      prh.billing_on,
      prh.net_amount,
      prh.gross_total,
      prh.total_gst,
      prh.total_disc,
      prh.branch_id,
      b.name,
      b.domain,
      c.id,
      c.name
) AS purchase_return_summary
WHERE ABS(calculated_net_amount - net_amount) <> 0;""",

        "High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)": """SELECT 
    prh.id, 
    prh.entry_number, 
    prh.entry_date, 
    prh.branch_id, 
    b.name, 
    b.domain,  
    pri.purchase_return_header_id, 
    pri.return_value, 
    pri.return_quantity, 
    pri.return_free,
    (pri.return_quantity + pri.return_free) AS sum_of_PQ_PF
FROM 
    database_purchasereturnhead prh
JOIN 
    database_branch b ON prh.branch_id = b.id
JOIN 
    database_purchasereturnitem pri ON prh.branch_id = pri.branch_id
WHERE 
    prh.entry_date <> '' AND
    prh.entry_date IS NOT NULL AND
    to_timestamp(prh.entry_date, 'YYYY-MM-DD') >= (CURRENT_DATE - INTERVAL '1 day') AND
    to_timestamp(prh.entry_date, 'YYYY-MM-DD') < CURRENT_DATE AND
    (pri.return_quantity + pri.return_free) > 5000;"""
        },

        "Database_Expiry_inhead": {
        "Invoice_Sequence_Missing":"""SELECT
  sh.id,
  sh.entry_date,
  sh.entry_number,
  mn.entry_prefix || LPAD(mn.expected_num::TEXT, 4, '0') AS missing_entry_number,
  mn.branch_id,
  b.name,
  b.domain
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
          RIGHT(sh.entry_number, 4)::INTEGER AS num_part
        FROM
          database_expiryinhead sh
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
      database_expiryinhead sh
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
LEFT JOIN 
  database_expiryinhead sh 
  ON sh.branch_id = mn.branch_id 
  AND LEFT(sh.entry_number, LENGTH(sh.entry_number) - 4) = mn.entry_prefix
ORDER BY
  mn.branch_id,
  missing_entry_number;""",
	
        "Invoice_Duplicates":"""SELECT
    database_expiryinhead.id,
    database_expiryinhead.entry_number,
    database_expiryinhead.entry_date,
    database_expiryinhead.branch_id,
    database_branch.name,
    database_branch.domain
FROM
    database_expiryinhead
JOIN
    database_branch ON database_expiryinhead.branch_id = database_branch.id
WHERE
    database_expiryinhead.entry_number IN (
        SELECT entry_number
        FROM database_expiryinhead
        WHERE
            entry_date IS NOT NULL
            AND entry_date <> ''
            AND CAST(entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY'
        GROUP BY entry_number
        HAVING COUNT(*) > 1
    )
    AND database_expiryinhead.entry_date IS NOT NULL
    AND database_expiryinhead.entry_date <> ''
    AND CAST(database_expiryinhead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';""",
    
        "Item_Header_Mismatch": """SELECT *,

       ABS(calculated_net_amount - net_amount) AS difference_amount
FROM (
  SELECT
      database_expiryinhead.entry_date,       
      database_expiryinhead.entry_number,
      database_expiryinhead.branch_id,
      database_branch.name AS branch_name,
      database_branch.domain,
      database_client.name AS client_name,
      database_expiryinhead.net_amount,
      database_expiryinhead.gross_total,
      database_expiryinhead.total_gst,
      database_expiryinhead.total_disc,
      SUM(database_salesitem.sale_value) AS item_total_sale_value,
      SUM(database_salesitem.gst_value) AS item_total_gst_value,
      SUM(database_salesitem.discount_amount) AS item_discount_sale_value,
      database_expiryinhead.id,
      SUM(
          (
            sale_value - ((sale_value * database_salesitem.discount_amount) / 100) * (1 - 
            COALESCE(Customer.discount_factor, 0) / 100)
            - CASE
                WHEN Settings.overide_item_with_header = true THEN 0
                ELSE (
                  (
                    (sale_value - ((sale_value * database_salesitem.discount_amount) / 100)) * 
                    (1 - COALESCE(Customer.discount_factor, 0) / 100) * COALESCE(overall_disc, 0)
                  ) / 100
                )
              END
          )
      )::numeric(16,2) AS items_tax_value,
      SUM(
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
      )::numeric(16,2) AS items_total_value,
      -- Calculate calculated_net_amount (no billing_on condition anymore)
      database_expiryinhead.gross_total + database_expiryinhead.total_gst - database_expiryinhead.total_disc
      AS calculated_net_amount
  FROM
      database_expiryinhead
  LEFT JOIN database_salesitem ON database_expiryinhead.id = database_salesitem.sale_header_id
  LEFT JOIN database_branch ON database_expiryinhead.branch_id = database_branch.id
  LEFT JOIN database_client ON database_branch.client_id = database_client.id
  LEFT JOIN database_sale_settings AS Settings ON Settings.branch_id = database_expiryinhead.branch_id
  LEFT JOIN database_customer AS Customer ON Customer.id = database_expiryinhead.customer_id_id
  WHERE
      TRIM(database_expiryinhead.entry_date) <> ''
      AND TO_TIMESTAMP(database_expiryinhead.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= (CURRENT_DATE - INTERVAL '1 day')
      AND TO_TIMESTAMP(database_expiryinhead.entry_date, 'YYYY-MM-DD HH24:MI:SS') < CURRENT_DATE
  GROUP BY
      database_expiryinhead.entry_date,
      database_expiryinhead.entry_number,
      database_expiryinhead.id,
      database_expiryinhead.net_amount,
      database_expiryinhead.gross_total,
      database_expiryinhead.total_gst,
      database_expiryinhead.total_disc,
      database_expiryinhead.branch_id,
      database_branch.name,
      database_branch.domain,
      database_client.id,
      database_client.name
) AS sale_summary
WHERE ABS(calculated_net_amount - net_amount) <> 0;""",

        "High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)":"""SELECT 
    database_expiryinhead.id, 
    database_expiryinhead.entry_number, 
    database_expiryinhead.entry_date, 
    database_expiryinhead.branch_id, 
    database_branch.name, 
    database_branch.domain,  
    database_purchaseitem.purchase_header_id, 
    database_purchaseitem.purchase_value, 
    database_purchaseitem.purchase_quantity, 
    database_purchaseitem.purchase_free,
    (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) AS sum_of_PQ_PF
FROM 
    database_expiryinhead
JOIN 
    database_branch ON database_expiryinhead.branch_id = database_branch.id
JOIN 
    database_purchaseitem ON database_expiryinhead.branch_id = database_purchaseitem.branch_id
WHERE 
    database_expiryinhead.entry_date <> '' AND
    database_expiryinhead.entry_date IS NOT NULL AND
    to_timestamp(database_expiryinhead.entry_date, 'YYYY-MM-DD') >= (CURRENT_DATE - INTERVAL '1 day') AND
    to_timestamp(database_expiryinhead.entry_date, 'YYYY-MM-DD') < CURRENT_DATE AND
    (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) > 5000;"""
        },
        "Database_Expiryouthead":{
        "Invoice_Sequence_Missing":"""SELECT
  EO.id,
  EO.entry_number,
  EO.entry_date,
  b.name AS branch_name,
  b.domain,
  mn.entry_prefix || LPAD(mn.expected_num::TEXT, 4, '0') AS missing_entry_number,
  mn.branch_id
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
          EO.branch_id,
          LEFT(EO.entry_number, LENGTH(EO.entry_number) - 4) AS entry_prefix,
          RIGHT(EO.entry_number, 4)::INTEGER AS num_part
        FROM
          database_expiryouthead EO
        WHERE
          EO.entry_number IS NOT NULL
          AND LENGTH(EO.entry_number) >= 4
          AND RIGHT(EO.entry_number, 4) ~ '^\d{4}$'
          AND TO_TIMESTAMP(EO.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= CURRENT_DATE - INTERVAL '1 days'
          AND TO_TIMESTAMP(EO.entry_date, 'YYYY-MM-DD HH24:MI:SS') <= CURRENT_DATE
      ) AS extracted_numbers
      GROUP BY entry_prefix, branch_id
    ) AS nr
  ) AS an
  LEFT JOIN (
    SELECT
      EO.branch_id,
      LEFT(EO.entry_number, LENGTH(EO.entry_number) - 4) AS entry_prefix,
      RIGHT(EO.entry_number, 4)::INTEGER AS num_part
    FROM
      database_expiryouthead EO
    WHERE
      EO.entry_number IS NOT NULL
      AND LENGTH(EO.entry_number) >= 4
      AND RIGHT(EO.entry_number, 4) ~ '^\d{4}$'
      AND TO_TIMESTAMP(EO.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= CURRENT_DATE - INTERVAL '1 days'
      AND TO_TIMESTAMP(EO.entry_date, 'YYYY-MM-DD HH24:MI:SS') <= CURRENT_DATE
  ) AS e
    ON an.entry_prefix = e.entry_prefix
    AND an.branch_id = e.branch_id
    AND an.expected_num = e.num_part
  WHERE e.num_part IS NULL
) AS mn
JOIN
  database_branch b ON mn.branch_id = b.id
LEFT JOIN
  database_expiryouthead EO
  ON EO.branch_id = mn.branch_id
  AND LEFT(EO.entry_number, LENGTH(EO.entry_number) - 4) = mn.entry_prefix
ORDER BY
  mn.branch_id,
  missing_entry_number;""",

        "Invoice_Duplicates":"""SELECT
    database_expiryouthead.id,
    database_expiryouthead.entry_number,
    database_expiryouthead.entry_date,
    database_expiryouthead.branch_id,
    database_branch.name,
    database_branch.domain
FROM
    database_expiryouthead
JOIN
    database_branch ON database_expiryouthead.branch_id = database_branch.id
WHERE
    database_expiryouthead.entry_number IN (
        SELECT entry_number
        FROM database_expiryouthead
        WHERE
            entry_date IS NOT NULL
            AND entry_date <> ''
            AND CAST(entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY'
        GROUP BY entry_number
        HAVING COUNT(*) > 1
    )
    AND database_expiryouthead.entry_date IS NOT NULL
    AND database_expiryouthead.entry_date <> ''
    AND CAST(database_expiryouthead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';""",
    
    
        "Item_Header_Mismatch":"""SELECT *,
       
       ABS(calculated_net_amount - net_amount) AS difference_amount
FROM (
  SELECT
      database_expiryouthead.entry_date,       
      database_expiryouthead.entry_number,
      database_expiryouthead.branch_id,
      database_branch.name AS branch_name,
      database_branch.domain,
      database_client.name AS client_name,
      database_expiryouthead.billing_on,
      database_expiryouthead.net_amount,
      database_expiryouthead.gross_total,
      database_expiryouthead.total_gst,
      database_expiryouthead.total_disc,
      SUM(database_salesitem.sale_value) AS item_total_sale_value,
      SUM(database_salesitem.gst_value) AS item_total_gst_value,
      SUM(database_salesitem.discount_amount) AS item_discount_sale_value,
      database_expiryouthead.id,
      SUM(
          CASE
            WHEN database_expiryouthead.billing_on IN ('3', '8', '9') THEN
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
            WHEN database_expiryouthead.billing_on IN ('3', '8', '9') THEN
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
        WHEN database_expiryouthead.billing_on IN ('3', '8', '9') THEN
          database_expiryouthead.gross_total - database_expiryouthead.total_disc
        ELSE
          database_expiryouthead.gross_total + database_expiryouthead.total_gst - database_expiryouthead.total_disc
      END AS calculated_net_amount
  FROM
      database_expiryouthead
  LEFT JOIN database_salesitem ON database_expiryouthead.id = database_salesitem.sale_header_id
  LEFT JOIN database_branch ON database_expiryouthead.branch_id = database_branch.id
  LEFT JOIN database_client ON database_branch.client_id = database_client.id
  LEFT JOIN database_sale_settings AS Settings ON Settings.branch_id = 
database_expiryouthead.branch_id
  LEFT JOIN database_customer AS Customer ON Customer.id = 
database_expiryouthead.supplier_id_id
  WHERE
      TRIM(database_expiryouthead.entry_date) <> ''
      AND TO_TIMESTAMP(database_expiryouthead.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= 
(CURRENT_DATE - INTERVAL '1 day')
      AND TO_TIMESTAMP(database_expiryouthead.entry_date, 'YYYY-MM-DD HH24:MI:SS') < 
CURRENT_DATE
  GROUP BY
      database_expiryouthead.entry_date,
      database_expiryouthead.entry_number,
      database_expiryouthead.id,
      database_expiryouthead.billing_on,
      database_expiryouthead.net_amount,
      database_expiryouthead.gross_total,
      database_expiryouthead.total_gst,
      database_expiryouthead.total_disc,
      database_expiryouthead.branch_id,
      database_branch.name,
      database_branch.domain,
      database_client.id,
      database_client.name
) AS sale_summary
WHERE ABS(calculated_net_amount - net_amount) <> 0;""",

        "High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)":"""
SELECT 
    database_expiryouthead.id, 
    database_expiryouthead.entry_number, 
    database_expiryouthead.entry_date, 
    database_expiryouthead.branch_id, 
    database_branch.name, 
    database_branch.domain,  
    database_purchaseitem.purchase_header_id, 
    database_purchaseitem.purchase_value, 
    database_purchaseitem.purchase_quantity, 
    database_purchaseitem.purchase_free,
    (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) AS sum_of_PQ_PF
FROM 
    database_expiryouthead
JOIN 
    database_branch ON database_expiryouthead.branch_id = database_branch.id
JOIN 
    database_purchaseitem ON database_expiryouthead.branch_id = database_purchaseitem.branch_id
WHERE 
    database_expiryouthead.entry_date <> '' 
    AND database_expiryouthead.entry_date IS NOT NULL
    AND to_timestamp(database_expiryouthead.entry_date, 'YYYY-MM-DD') >= (CURRENT_DATE - INTERVAL '1 day')
    AND to_timestamp(database_expiryouthead.entry_date, 'YYYY-MM-DD') < CURRENT_DATE
    AND (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) > 5000;"""
        },


        "Database_Transferinhead": {
        "Invoice_Sequence_Missing":""" SELECT
  T.id,
  T.entry_date,
  T.entry_number,
  b.name AS branch_name,
  mn.branch_id,
  b.domain,
  mn.entry_prefix || LPAD(mn.expected_num::TEXT, 4, '0') AS missing_entry_number
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
          T.branch_id,
          LEFT(T.entry_number, LENGTH(T.entry_number) - 4) AS entry_prefix,
          RIGHT(T.entry_number, 4)::INTEGER AS num_part
        FROM
          database_transferinhead T
        WHERE
          T.entry_number IS NOT NULL
          AND LENGTH(T.entry_number) >= 4
          AND RIGHT(T.entry_number, 4) ~ '^\d{4}$'
          AND TO_TIMESTAMP(T.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= CURRENT_DATE - INTERVAL '1 days'
          AND TO_TIMESTAMP(T.entry_date, 'YYYY-MM-DD HH24:MI:SS') <= CURRENT_DATE
      ) AS extracted_numbers
      GROUP BY entry_prefix, branch_id
    ) AS nr
  ) AS an
  LEFT JOIN (
    SELECT
      T.branch_id,
      LEFT(T.entry_number, LENGTH(T.entry_number) - 4) AS entry_prefix,
      RIGHT(T.entry_number, 4)::INTEGER AS num_part
    FROM
      database_transferinhead T
    WHERE
      T.entry_number IS NOT NULL
      AND LENGTH(T.entry_number) >= 4
      AND RIGHT(T.entry_number, 4) ~ '^\d{4}$'
      AND TO_TIMESTAMP(T.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= CURRENT_DATE - INTERVAL '1 days'
      AND TO_TIMESTAMP(T.entry_date, 'YYYY-MM-DD HH24:MI:SS') <= CURRENT_DATE
  ) AS EI
    ON an.entry_prefix = EI.entry_prefix
    AND an.branch_id = EI.branch_id
    AND an.expected_num = EI.num_part
  WHERE EI.num_part IS NULL
) AS mn
JOIN
  database_branch b ON mn.branch_id = b.id
LEFT JOIN
  database_transferinhead T
  ON T.branch_id = mn.branch_id
ORDER BY
  mn.branch_id,
  missing_entry_number;""", 

        "Invoice_Duplicates":"""SELECT
    database_transferinhead.id,
    database_transferinhead.entry_number,
    database_transferinhead.entry_date,
    database_transferinhead.branch_id,
    database_branch.name,
    database_branch.domain
FROM
    database_transferinhead
JOIN
    database_branch ON database_transferinhead.branch_id = database_branch.id
WHERE
    database_transferinhead.entry_number IN (
        SELECT entry_number
        FROM database_transferinhead
        WHERE
            entry_date IS NOT NULL
            AND entry_date <> ''
            AND CAST(entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY'
        GROUP BY entry_number
        HAVING COUNT(*) > 1
    )
    AND database_transferinhead.entry_date IS NOT NULL
    AND database_transferinhead.entry_date <> ''
    AND CAST(database_transferinhead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';""",
    
        "Item_Header_Mismatch":"""SELECT *,
       ABS(calculated_net_amount - net_amount) AS difference_amount
FROM (
  SELECT
  tih.id,
      tih.entry_date,       
      tih.entry_number,
      tih.branch_id,
      b.name AS branch_name,
      b.domain,
      c.name AS supplier_name,
      tih.net_amount,
      tih.gross_total,
      tih.total_gst,
      tih.total_disc,
      SUM(tii.purchase_value) AS item_total_purchase_value,
      SUM(tii.gst_value) AS item_total_gst_value,
      SUM(tii.discount_amount) AS item_discount_value,
      
      SUM(
          tii.purchase_value - ((tii.purchase_value * tii.discount_amount) / 100)
          - CASE
              WHEN s.overide_item_with_header = true THEN 0
              ELSE (((tii.purchase_value - ((tii.purchase_value * tii.discount_amount) / 100)) * COALESCE(cust.discount_factor,0)) / 100)
            END
      )::numeric(16,2) AS items_tax_value,
      SUM(
          (tii.purchase_value - ((tii.purchase_value * tii.discount_amount) / 100)
           - CASE
               WHEN s.overide_item_with_header = true THEN 0
               ELSE (((tii.purchase_value - ((tii.purchase_value * tii.discount_amount) / 100)) * COALESCE(cust.discount_factor,0)) / 100)
             END
          ) * (1 + (tii.gst::double precision / 100))
      )::numeric(16,2) AS items_total_value,

      CAST(tih.gross_total AS numeric) + CAST(tih.total_gst AS numeric) - CAST(tih.total_disc AS numeric)
      AS calculated_net_amount

  FROM
      database_transferinhead tih
  LEFT JOIN database_transferinitem tii ON tih.id = tii.id
  LEFT JOIN database_branch b ON tih.branch_id = b.id
  LEFT JOIN database_client c ON tih.supplier_id_id = c.id
  LEFT JOIN database_sale_settings s ON s.branch_id = tih.branch_id
  LEFT JOIN database_customer cust ON cust.id = tih.supplier_id_id
  WHERE
      TRIM(tih.entry_date) <> ''
      AND TO_TIMESTAMP(tih.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= (CURRENT_DATE - INTERVAL '1 day')
      AND TO_TIMESTAMP(tih.entry_date, 'YYYY-MM-DD HH24:MI:SS') < CURRENT_DATE
  GROUP BY
      tih.entry_date,
      tih.entry_number,
      tih.id,
      tih.net_amount,
      tih.gross_total,
      tih.total_gst,
      tih.total_disc,
      tih.branch_id,
      b.name,
      b.domain,
      c.id,
      c.name
) AS transferin_summary
WHERE ABS(calculated_net_amount - net_amount) <> 0;""",

        "High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)":"""SELECT 
    database_transferinhead.id, 
    database_transferinhead.entry_number, 
    database_transferinhead.entry_date, 
    database_transferinhead.branch_id, 
    database_branch.name, 
    database_branch.domain,  
    database_purchaseitem.purchase_header_id, 
    database_purchaseitem.purchase_value, 
    database_purchaseitem.purchase_quantity, 
    database_purchaseitem.purchase_free,
    (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) AS sum_of_PQ_PF
FROM 
    database_transferinhead
JOIN 
    database_branch ON database_transferinhead.branch_id = database_branch.id
JOIN 
    database_purchaseitem ON database_transferinhead.branch_id = database_purchaseitem.branch_id
WHERE 
    database_transferinhead.entry_date <> '' 
    AND database_transferinhead.entry_date IS NOT NULL 
    AND to_timestamp(database_transferinhead.entry_date, 'YYYY-MM-DD') >= (CURRENT_DATE - INTERVAL '1 day')
    AND to_timestamp(database_transferinhead.entry_date, 'YYYY-MM-DD') < CURRENT_DATE
    AND (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) > 5000;"""

        },
        "Database_Transferouthead": {
        "Invoice_Sequence_Missing": """SELECT
t_out.id,
  t_out.entry_number,
  t_out.entry_date,
  b.domain,
  b.name AS branch_name,
  mn.entry_prefix || LPAD(mn.expected_num::TEXT, 4, '0') AS missing_entry_number,
  mn.branch_id
  
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
          OH.branch_id,
          LEFT(OH.entry_number, LENGTH(OH.entry_number) - 4) AS entry_prefix,
          RIGHT(OH.entry_number, 4)::INTEGER AS num_part
        FROM
          database_transferouthead OH
        WHERE
          OH.entry_number IS NOT NULL
          AND LENGTH(OH.entry_number) >= 4
          AND RIGHT(OH.entry_number, 4) ~ '^\d{4}$'
          AND TO_TIMESTAMP(OH.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= CURRENT_DATE - INTERVAL '1 days'
          AND TO_TIMESTAMP(OH.entry_date, 'YYYY-MM-DD HH24:MI:SS') <= CURRENT_DATE
      ) AS extracted_numbers
      GROUP BY entry_prefix, branch_id
    ) AS nr
  ) AS an
  LEFT JOIN (
    SELECT
      OH.branch_id,
      LEFT(OH.entry_number, LENGTH(OH.entry_number) - 4) AS entry_prefix,
      RIGHT(OH.entry_number, 4)::INTEGER AS num_part
    FROM
      database_transferouthead OH
    WHERE
      OH.entry_number IS NOT NULL
      AND LENGTH(OH.entry_number) >= 4
      AND RIGHT(OH.entry_number, 4) ~ '^\d{4}$'
      AND TO_TIMESTAMP(OH.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= CURRENT_DATE - INTERVAL '1 days'
      AND TO_TIMESTAMP(OH.entry_date, 'YYYY-MM-DD HH24:MI:SS') <= CURRENT_DATE
  ) AS e
    ON an.entry_prefix = e.entry_prefix
    AND an.branch_id = e.branch_id
    AND an.expected_num = e.num_part
  WHERE e.num_part IS NULL
) AS mn
JOIN
  database_branch b ON mn.branch_id = b.id
LEFT JOIN
  database_transferouthead t_out ON t_out.branch_id = mn.branch_id
  AND LEFT(t_out.entry_number, LENGTH(t_out.entry_number) - 4) = mn.entry_prefix
ORDER BY
  mn.branch_id,
  missing_entry_number;""",
  
        "Invoice_Duplicates":"""SELECT
    database_transferouthead.id,
    database_transferouthead.entry_number,
    database_transferouthead.entry_date,
    database_transferouthead.branch_id,
    database_branch.name,
    database_branch.domain
FROM
    database_transferouthead
JOIN
    database_branch ON database_transferouthead.branch_id = database_branch.id
WHERE
    database_transferouthead.entry_number IN (
        SELECT entry_number
        FROM database_transferouthead
        WHERE
            entry_date IS NOT NULL
            AND entry_date <> ''
            AND CAST(entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY'
        GROUP BY entry_number
        HAVING COUNT(*) > 1
    )
    AND database_transferouthead.entry_date IS NOT NULL
    AND database_transferouthead.entry_date <> ''
    AND CAST(database_transferouthead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';""",
    
        "Item_Header_Mismatch":"""SELECT *,
      
       ABS(calculated_net_amount - net_amount) AS difference_amount
FROM (
  SELECT
      database_transferouthead.entry_date,       
      database_transferouthead.entry_number,
      database_transferouthead.branch_id,
      database_branch.name AS branch_name,
      database_branch.domain,
      database_client.name AS client_name,
      database_transferouthead.billing_on,
      database_transferouthead.net_amount,
      database_transferouthead.gross_total,
      database_transferouthead.total_gst,
      database_transferouthead.total_disc,
      SUM(database_salesitem.sale_value) AS item_total_sale_value,
      SUM(database_salesitem.gst_value) AS item_total_gst_value,
      SUM(database_salesitem.discount_amount) AS item_discount_sale_value,
      database_transferouthead.id,
      SUM(
          CASE
            WHEN database_transferouthead.billing_on IN ('3', '8', '9') THEN
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
            WHEN database_transferouthead.billing_on IN ('3', '8', '9') THEN
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
      
      CASE
        WHEN database_transferouthead.billing_on IN ('3', '8', '9') THEN
          database_transferouthead.gross_total - database_transferouthead.total_disc
        ELSE
          database_transferouthead.gross_total + database_transferouthead.total_gst - database_transferouthead.total_disc
      END AS calculated_net_amount
  FROM
      database_transferouthead
  LEFT JOIN database_salesitem ON database_transferouthead.id = database_salesitem.sale_header_id
  LEFT JOIN database_branch ON database_transferouthead.branch_id = database_branch.id
  LEFT JOIN database_client ON database_branch.client_id = database_client.id
  LEFT JOIN database_sale_settings AS Settings ON Settings.branch_id = 
database_transferouthead.branch_id
  LEFT JOIN database_customer AS Customer ON Customer.id = 
database_transferouthead.customer_id_id
  WHERE
      TRIM(database_transferouthead.entry_date) <> ''
      AND TO_TIMESTAMP(database_transferouthead.entry_date, 'YYYY-MM-DD HH24:MI:SS') >= 
(CURRENT_DATE - INTERVAL '1 day')
      AND TO_TIMESTAMP(database_transferouthead.entry_date, 'YYYY-MM-DD HH24:MI:SS') < 
CURRENT_DATE
  GROUP BY
      database_transferouthead.entry_date,
      database_transferouthead.entry_number,
      database_transferouthead.id,
      database_transferouthead.billing_on,
      database_transferouthead.net_amount,
      database_transferouthead.gross_total,
      database_transferouthead.total_gst,
      database_transferouthead.total_disc,
      database_transferouthead.branch_id,
      database_branch.name,
      database_branch.domain,
      database_client.id,
      database_client.name
) AS sale_summary
WHERE ABS(calculated_net_amount - net_amount) <> 0;""",

        "High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)":"""SELECT 
    database_transferouthead.id, 
    database_transferouthead.entry_number, 
    database_transferouthead.entry_date, 
    database_transferouthead.branch_id, 
    database_branch.name, 
    database_branch.domain,  
    database_purchaseitem.purchase_header_id, 
    database_purchaseitem.purchase_value, 
    database_purchaseitem.purchase_quantity, 
    database_purchaseitem.purchase_free,
    (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) AS sum_of_PQ_PF
FROM 
    database_transferouthead
JOIN 
    database_branch ON database_transferouthead.branch_id = database_branch.id
JOIN 
    database_purchaseitem ON database_transferouthead.branch_id = database_purchaseitem.branch_id
WHERE 
    database_transferouthead.entry_date <> '' 
    AND database_transferouthead.entry_date IS NOT NULL 
    AND to_timestamp(database_transferouthead.entry_date, 'YYYY-MM-DD') >= (CURRENT_DATE - INTERVAL '1 day') 
    AND to_timestamp(database_transferouthead.entry_date, 'YYYY-MM-DD') < CURRENT_DATE 
    AND (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) > 5000;"""
    }
}


def build_excel_file():
    wb = Workbook()
    wb.remove(wb.active) 

    for sheet_name, queries in TABLES.items():
        ws = wb.create_sheet(title=sheet_name)

       
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
        ws.append([f"Report generated on: {timestamp}"])
        ws.cell(row=1, column=1).font = Font(bold=True, color="000000")
        ws.append([])

        
        for query_title, sql in queries.items():

            # Query title (bold)
            ws.append([f"•  {query_title}"])
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True, color="000000")

            # Execute SQL safely
            try:
                df = pd.read_sql(sql, engine)
            except Exception as e:
                df = pd.DataFrame([{"ERROR": str(e)}])

            # If no data → simple message
            if df.empty:
                ws.append(["No records found"])
                ws.cell(row=ws.max_row, column=1).font = Font(color="000000")

            else:
                # Write dataframe rows
                for row in dataframe_to_rows(df, index=False, header=True):
                    ws.append(row)

            # Blank line after each query
            ws.append([])

   
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    wb.save(tmp.name)
    return tmp.name


def upload_to_slack(filepath):
    try:
        slack_client.files_upload_v2(
            channel=SLACK_CHANNEL,
            file=filepath,
            filename="CombinedReport.xlsx",
            title="Combined Report"
        )
    except SlackApiError as e:
        logging.error(f"Slack Upload Failed: {e}")


async def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Combined Report Function Triggered.")

    try:
        excel_path = build_excel_file()
        upload_to_slack(excel_path)
        os.remove(excel_path)

        return func.HttpResponse("Combined Excel Report sent to Slack!", status_code=200)

    except Exception as e:
        logging.error(str(e))
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)
