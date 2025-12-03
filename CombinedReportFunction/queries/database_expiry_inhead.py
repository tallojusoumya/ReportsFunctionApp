"""Queries for Database_Expiry_inhead"""

# ============================================================================
# Invoice_Sequence_Missing
# ============================================================================
INVOICE_SEQUENCE_MISSING_QUERY = """
    SELECT
    expiryinhead.id,
    expiryinhead.entry_number,
    expiryinhead.entry_date,
    database_branch.id AS branch_id,
    database_branch.name AS branch_name,
    database_branch.domain,
    missing_numbers.expected_entry_number AS missing_entry_number
FROM (
    SELECT
        expected_numbers.branch_id,
        expected_numbers.prefix,
        expected_numbers.expected_num,
        expected_numbers.prefix || LPAD(expected_numbers.expected_num::TEXT, 4, '0') AS expected_entry_number
    FROM (
        SELECT
            entry_prefix_info.branch_id,
            entry_prefix_info.prefix,
            generate_series(entry_prefix_info.min_num, entry_prefix_info.max_num) AS expected_num
        FROM (
            
            SELECT
                expiryinhead.branch_id,
                LEFT(expiryinhead.entry_number, LENGTH(expiryinhead.entry_number) - 4) AS prefix,
                MIN(RIGHT(expiryinhead.entry_number, 4)::INT) AS min_num,
                MAX(RIGHT(expiryinhead.entry_number, 4)::INT) AS max_num
            FROM
                database_expiryinhead AS expiryinhead
            WHERE
                expiryinhead.entry_number IS NOT NULL
            GROUP BY
                expiryinhead.branch_id,
                LEFT(expiryinhead.entry_number, LENGTH(expiryinhead.entry_number) - 4)
        ) AS entry_prefix_info
    ) AS expected_numbers
) AS missing_numbers


LEFT JOIN database_expiryinhead AS expiryinhead
    ON expiryinhead.entry_number = missing_numbers.expected_entry_number
   AND expiryinhead.branch_id = missing_numbers.branch_id


JOIN database_branch
    ON missing_numbers.branch_id = database_branch.id


WHERE expiryinhead.entry_number IS NULL

ORDER BY
    missing_numbers.branch_id,
    missing_numbers.expected_entry_number;

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
    expiryinhead.id,
    expiryinhead.entry_number,
    expiryinhead.entry_date,
    expiryinhead.branch_id,
    b.name AS branch_name,
    b.domain,
    pi.purchase_header_id,
    pi.purchase_value,
    pi.purchase_quantity,
    pi.purchase_free,
    (pi.purchase_quantity + pi.purchase_free) AS sum_of_PQ_PF
FROM 
    database_purchaseitem pi
JOIN 
    database_purchasehead ph 
        ON pi.purchase_header_id = ph.id
JOIN
    database_expiryinhead expiryinhead
        ON expiryinhead.branch_id = ph.branch_id
       AND TO_DATE(expiryinhead.entry_date, 'YYYY-MM-DD') = TO_DATE(ph.entry_date, 'YYYY-MM-DD')
JOIN
    database_branch b
        ON expiryinhead.branch_id = b.id
WHERE 
    TO_DATE(ph.entry_date, 'YYYY-MM-DD') = CURRENT_DATE - INTERVAL '1 day'
    AND (pi.purchase_quantity + pi.purchase_free) > 5000;

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

TABLES = {
    "Database_expiry_inhead": QUERIES
}