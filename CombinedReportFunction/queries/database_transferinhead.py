"""Queries for Database_Transferinhead"""

# ============================================================================
# Invoice_Sequence_Missing
# ============================================================================
INVOICE_SEQUENCE_MISSING_QUERY = """
    SELECT
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
    AND LEFT(T.entry_number, LENGTH(T.entry_number) - 4) = mn.entry_prefix
ORDER BY
    mn.branch_id,
    missing_entry_number;

"""

# ============================================================================
# Invoice_Duplicates
# ============================================================================
INVOICE_DUPLICATES_QUERY = """
    SELECT
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
        AND CAST(database_transferinhead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';
"""

# ============================================================================
# Item_Header_Mismatch
# ============================================================================
ITEM_HEADER_MISMATCH_QUERY = """
    SELECT *,
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
    WHERE ABS(calculated_net_amount - net_amount) <> 0;
"""

# ============================================================================
# High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)
# ============================================================================
HIGH_PURCHASE_QTY_QUERY = """
    SELECT 
    transferinhead.id,
    transferinhead.entry_number,
    transferinhead.entry_date,
    transferinhead.branch_id,
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
    database_transferinhead transferinhead
        ON transferinhead.branch_id = ph.branch_id
       AND TO_DATE(transferinhead.entry_date, 'YYYY-MM-DD') = TO_DATE(ph.entry_date, 'YYYY-MM-DD')
JOIN
    database_branch b
        ON transferinhead.branch_id = b.id
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
    "Database_transferinhead": QUERIES
}
