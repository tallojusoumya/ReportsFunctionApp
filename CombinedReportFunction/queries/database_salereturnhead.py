"""Queries for Database_Salereturnhead"""

# ============================================================================
# Invoice_Sequence_Missing
# ============================================================================
INVOICE_SEQUENCE_MISSING_QUERY = """
    SELECT 
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
        missing_entry_number;
"""

# ============================================================================
# Invoice_Duplicates
# ============================================================================
INVOICE_DUPLICATES_QUERY = """
    SELECT
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
        AND CAST(database_salereturnhead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';
"""

# ============================================================================
# Item_Header_Mismatch
# ============================================================================
ITEM_HEADER_MISMATCH_QUERY = """
    SELECT *,
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
    WHERE ABS(calculated_net_amount - net_amount) <> 0;
"""

# ============================================================================
# High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)
# ============================================================================
HIGH_PURCHASE_QTY_QUERY = """
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
        AND (sri.sale_quantity + sri.sale_free) > 5000;
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
