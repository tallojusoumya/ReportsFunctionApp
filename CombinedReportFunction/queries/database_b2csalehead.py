"""Queries for Database_b2csalehead"""

# ============================================================================
# Invoice_Sequence_Missing
# ============================================================================
INVOICE_SEQUENCE_MISSING_QUERY = """
    SELECT
    b2csh.id,
    b2csh.entry_number,
    b2csh.entry_date,
    database_branch.id          AS branch_id,
    database_branch.name        AS branch_name,
    database_branch.domain      AS branch_domain,
    missing_numbers.missing_entry_number
FROM (
    SELECT
        full_range.entry_prefix,
        full_range.branch_id,
        full_range.expected_num,
        full_range.entry_prefix || LPAD(full_range.expected_num::TEXT, 4, '0') AS missing_entry_number
    FROM (
        SELECT
            numbered_entries.entry_prefix,
            numbered_entries.branch_id,
            generate_series(numbered_entries.min_num, numbered_entries.max_num) AS expected_num
        FROM (
            SELECT
                parsed_rows.branch_id,
                parsed_rows.entry_prefix,
                MIN(parsed_rows.number_part) AS min_num,
                MAX(parsed_rows.number_part) AS max_num
            FROM (
                SELECT
                    b2csh.branch_id,
                    LEFT(b2csh.entry_number, LENGTH(b2csh.entry_number) - 4) AS entry_prefix,
                    RIGHT(b2csh.entry_number, 4)::INTEGER AS number_part
                FROM
                    database_b2csalehead AS b2csh
                WHERE
                    b2csh.entry_number IS NOT NULL
                    AND b2csh.entry_number <> ''
                    AND TO_TIMESTAMP(b2csh.entry_date, 'YYYY-MM-DD HH24:MI:SS')
                        >= CURRENT_DATE - INTERVAL '1 day'
                    AND TO_TIMESTAMP(b2csh.entry_date, 'YYYY-MM-DD HH24:MI:SS')
                        < CURRENT_DATE
            ) AS parsed_rows
            GROUP BY
                parsed_rows.branch_id,
                parsed_rows.entry_prefix
        ) AS numbered_entries
    ) AS full_range
    LEFT JOIN database_b2csalehead AS b2c_existing
        ON b2c_existing.entry_number =
           full_range.entry_prefix || LPAD(full_range.expected_num::TEXT, 4, '0')
       AND b2c_existing.branch_id = full_range.branch_id
    WHERE b2c_existing.entry_number IS NULL
) AS missing_numbers

JOIN database_branch
    ON database_branch.id = missing_numbers.branch_id

LEFT JOIN database_b2csalehead AS b2csh
    ON b2csh.entry_number = missing_numbers.missing_entry_number
   AND b2csh.branch_id = missing_numbers.branch_id

ORDER BY
    database_branch.id,
    missing_numbers.missing_entry_number;

"""

# ============================================================================
# Invoice_Duplicates
# ============================================================================
INVOICE_DUPLICATES_QUERY = """
    SELECT 
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
        AND CAST(database_b2csalehead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';
"""

# ============================================================================
# Item_Header_Mismatch
# ============================================================================
ITEM_HEADER_MISMATCH_QUERY = """
    select *,

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
    WHERE ABS(calculated_net_amount - net_amount) <> 0;
"""

# ============================================================================
# High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)
# ============================================================================
HIGH_PURCHASE_QTY_QUERY = """
    SELECT 
    b2c.id,
    b2c.entry_number,
    b2c.entry_date,
    b2c.branch_id,
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
    database_b2csalehead b2c
        ON b2c.branch_id = ph.branch_id
       AND TO_DATE(b2c.entry_date, 'YYYY-MM-DD') = TO_DATE(ph.entry_date, 'YYYY-MM-DD')
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
    "Database_b2csalehead": QUERIES
}