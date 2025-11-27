"""Queries for Database_Expiry_inhead"""

# ============================================================================
# Invoice_Sequence_Missing
# ============================================================================
INVOICE_SEQUENCE_MISSING_QUERY = """
    SELECT
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
      missing_entry_number;
"""

# ============================================================================
# Invoice_Duplicates
# ============================================================================
INVOICE_DUPLICATES_QUERY = """
    SELECT
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
        AND CAST(database_expiryinhead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';
"""

# ============================================================================
# Item_Header_Mismatch
# ============================================================================
ITEM_HEADER_MISMATCH_QUERY = """
    SELECT *,

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
    WHERE ABS(calculated_net_amount - net_amount) <> 0;
"""

# ============================================================================
# High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)
# ============================================================================
HIGH_PURCHASE_QTY_QUERY = """
    SELECT 
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
        (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) > 5000;
"""


# ============================================================================
# Combined queries dictionary
# ============================================================================
QUERIES = {
    "Invoice_Sequence_Missing": INVOICE_SEQUENCE_MISSING_QUERY,
    "Invoice_Duplicates": INVOICE_DUPLICATES_QUERY,
    "Item_Header_Mismatch": ITEM_HEADER_MISMATCH_QUERY,
    "High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)": HIGH_PURCHASE_QTY_QUERY,
}
