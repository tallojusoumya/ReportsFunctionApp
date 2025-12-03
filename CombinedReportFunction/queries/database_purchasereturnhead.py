"""Queries for Database_Purchasereturnhead"""

# ============================================================================
# Invoice_Sequence_Missing
# ============================================================================
INVOICE_SEQUENCE_MISSING_QUERY = """
   SELECT
     ph.id,
    ph.entry_number,
    ph.entry_date,
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
JOIN 
    database_branch b ON mn.branch_id = b.id
LEFT JOIN 
    database_purchasereturnhead ph
    ON ph.branch_id = mn.branch_id
    AND ph.entry_number = mn.entry_prefix || LPAD(mn.expected_num::TEXT, 4, '0')
ORDER BY
    mn.branch_id,
    missing_entry_number;

"""

# ============================================================================
# Invoice_Duplicates
# ============================================================================
INVOICE_DUPLICATES_QUERY = """
    SELECT
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
         AND CAST(database_purchasereturnhead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';
"""

# ============================================================================
# Item_Header_Mismatch
# ============================================================================
ITEM_HEADER_MISMATCH_QUERY = """
    SELECT *,

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
    WHERE ABS(calculated_net_amount - net_amount) <> 0;
"""

# ============================================================================
# High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)
# ============================================================================
HIGH_PURCHASE_QTY_QUERY = """
    SELECT 
    prh.id,
    prh.entry_number,
    prh.entry_date,
    prh.branch_id,
    b.name AS branch_name,
    b.domain,
    pri.purchase_return_header_id,
    pri.return_value,
    pri.return_quantity,
    pri.return_free,
    (pri.return_quantity + pri.return_free) AS sum_of_PQ_PF
FROM 
    database_purchasereturnitem pri
JOIN 
    database_purchasereturnhead prh
        ON pri.purchase_return_header_id = prh.id
JOIN
    database_branch b
        ON prh.branch_id = b.id
WHERE 
    TO_DATE(prh.entry_date, 'YYYY-MM-DD') = CURRENT_DATE - INTERVAL '1 day'
    AND (pri.return_quantity + pri.return_free) > 5000;

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
    "Database_purchasereturnhead": QUERIES
}
