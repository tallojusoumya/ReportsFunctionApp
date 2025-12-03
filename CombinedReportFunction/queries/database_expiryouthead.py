"""Queries for Database_Expiryouthead"""

# ============================================================================
# Invoice_Sequence_Missing
# ============================================================================
INVOICE_SEQUENCE_MISSING_QUERY = """
    SELECT
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
    AND EO.entry_number = mn.entry_prefix || LPAD(mn.expected_num::TEXT, 4, '0')
ORDER BY
    mn.branch_id,
    missing_entry_number;

"""

# ============================================================================
# Invoice_Duplicates
# ============================================================================
INVOICE_DUPLICATES_QUERY = """
    SELECT
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
        AND CAST(database_expiryouthead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';
"""

# ============================================================================
# Item_Header_Mismatch
# ============================================================================
ITEM_HEADER_MISMATCH_QUERY = """
    SELECT *,

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
    WHERE ABS(calculated_net_amount - net_amount) <> 0;
"""

# ============================================================================
# High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)
# ============================================================================
HIGH_PURCHASE_QTY_QUERY = """
    SELECT 
    expiryouthead.id,
    expiryouthead.entry_number,
    expiryouthead.entry_date,
    expiryouthead.branch_id,
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
    database_expiryouthead expiryouthead
        ON expiryouthead.branch_id = ph.branch_id
       AND TO_DATE(expiryouthead.entry_date, 'YYYY-MM-DD') = TO_DATE(ph.entry_date, 'YYYY-MM-DD')
JOIN
    database_branch b
        ON expiryouthead.branch_id = b.id
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
    "Database_expiryouthead": QUERIES
}
