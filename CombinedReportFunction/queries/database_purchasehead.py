"""Queries for Database_Purchasehead"""

# ============================================================================
# Invoice_Sequence_Missing
# ============================================================================
INVOICE_SEQUENCE_MISSING_QUERY = """
    SELECT
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
"""

# ============================================================================
# Invoice_Duplicates
# ============================================================================
INVOICE_DUPLICATES_QUERY = """
    SELECT
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
        AND CAST(database_purchasehead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';
"""

# ============================================================================
# Item_Header_Mismatch
# ============================================================================
ITEM_HEADER_MISMATCH_QUERY = """
    SELECT *,

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
    WHERE ABS(calculated_net_amount - net_amount) <> 0;
"""

# ============================================================================
# High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)
# ============================================================================
HIGH_PURCHASE_QTY_QUERY = """
    SELECT 
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
        AND (database_purchaseitem.purchase_quantity + database_purchaseitem.purchase_free) > 5000;
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
