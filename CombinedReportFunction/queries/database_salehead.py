"""Queries for Database_salehead"""

# ============================================================================
# Invoice_Sequence_Missing
# ============================================================================
INVOICE_SEQUENCE_MISSING_QUERY = """
    SELECT
    sh.id,
    sh.entry_number,
    sh.entry_date,
    missing_numbers.branch_id,
    database_branch.name AS branch_name,
    database_branch.domain AS branch_domain,
    sh.is_retail_b2b_bill,
    missing_numbers.entry_prefix || LPAD(missing_numbers.expected_number::TEXT, 4, '0')
        AS missing_entry_number
FROM (
    SELECT
        expected_numbers.entry_prefix,
        expected_numbers.branch_id,
        expected_numbers.expected_number
    FROM (
        SELECT
            prefix_range.entry_prefix,
            prefix_range.branch_id,
            generate_series(prefix_range.min_number, prefix_range.max_number)
                AS expected_number
        FROM (
            SELECT
                valid_sales.entry_prefix,
                valid_sales.branch_id,
                MIN(valid_sales.number_part) AS min_number,
                MAX(valid_sales.number_part) AS max_number
            FROM (
                SELECT
                    LEFT(sh.entry_number, LENGTH(sh.entry_number) - 4) AS entry_prefix,
                    RIGHT(sh.entry_number, 4)::INTEGER AS number_part,
                    sh.branch_id
                FROM database_salehead sh
                WHERE 
                    sh.entry_number IS NOT NULL
                    AND LENGTH(sh.entry_number) >= 4
                    AND RIGHT(sh.entry_number, 4) ~ '^\d{4}$'
                    AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') 
                        >= CURRENT_DATE - INTERVAL '1 day'
                    AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS')
                        < CURRENT_DATE
            ) AS valid_sales
            GROUP BY valid_sales.entry_prefix, valid_sales.branch_id
        ) AS prefix_range
    ) AS expected_numbers
LEFT JOIN (
    SELECT
        LEFT(sh.entry_number, LENGTH(sh.entry_number) - 4) AS entry_prefix,
        RIGHT(sh.entry_number, 4)::INTEGER AS number_part,
        sh.branch_id
    FROM database_salehead sh
    WHERE 
        sh.entry_number IS NOT NULL
        AND LENGTH(sh.entry_number) >= 4
        AND RIGHT(sh.entry_number, 4) ~ '^\d{4}$'
        AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS') 
            >= CURRENT_DATE - INTERVAL '1 day'
        AND TO_TIMESTAMP(sh.entry_date, 'YYYY-MM-DD HH24:MI:SS')
            < CURRENT_DATE
) AS actual_numbers
    ON actual_numbers.entry_prefix = expected_numbers.entry_prefix
    AND actual_numbers.branch_id = expected_numbers.branch_id
    AND actual_numbers.number_part = expected_numbers.expected_number
WHERE actual_numbers.number_part IS NULL
) AS missing_numbers

JOIN database_branch
    ON database_branch.id = missing_numbers.branch_id

LEFT JOIN database_salehead AS sh
    ON sh.branch_id = missing_numbers.branch_id
   AND LEFT(sh.entry_number, LENGTH(sh.entry_number) - 4) = missing_numbers.entry_prefix

ORDER BY
    missing_numbers.branch_id,
    missing_numbers.entry_prefix,
    missing_numbers.expected_number;
"""


# ============================================================================
# Invoice_Duplicates
# ============================================================================
INVOICE_DUPLICATES_QUERY = """
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

# ============================================================================
# Item_Header_Mismatch
# ============================================================================
ITEM_HEADER_MISMATCH_QUERY = """
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
      WHERE ABS(calculated_net_amount - net_amount) <> 0;
"""

# ============================================================================
# High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)
# ============================================================================
HIGH_PURCHASE_QTY_QUERY = """
    SELECT 
    sh.id,
    sh.entry_number,
    sh.entry_date,
    sh.branch_id,
    b.name AS branch_name,
    b.domain,
    si.sale_header_id,
    si.sale_value,
    si.sale_quantity,
    si.sale_free,
    (si.sale_quantity + si.sale_free) AS sum_of_SQ_SF
FROM 
    database_salesitem si
JOIN 
    database_salehead sh
        ON si.sale_header_id = sh.id
JOIN
    database_branch b
        ON sh.branch_id = b.id
WHERE 
    TO_DATE(sh.entry_date, 'YYYY-MM-DD') = CURRENT_DATE - INTERVAL '1 day'
    AND (si.sale_quantity + si.sale_free) > 5000;


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
    "Database_salehead": QUERIES
}
