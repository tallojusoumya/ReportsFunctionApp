"""Queries for Database_Transferouthead"""

# ============================================================================
# Invoice_Sequence_Missing
# ============================================================================
INVOICE_SEQUENCE_MISSING_QUERY = """
    SELECT
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
      missing_entry_number;
"""

# ============================================================================
# Invoice_Duplicates
# ============================================================================
INVOICE_DUPLICATES_QUERY = """
    SELECT
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
        AND CAST(database_transferouthead.entry_date AS DATE) = CURRENT_DATE - INTERVAL '1 DAY';
"""

# ============================================================================
# Item_Header_Mismatch
# ============================================================================
ITEM_HEADER_MISMATCH_QUERY = """
    SELECT *,

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
    WHERE ABS(calculated_net_amount - net_amount) <> 0;
"""

# ============================================================================
# High_Purchase_Quantity(PurchaseQuantity + PurchaseFree>5000)
# ============================================================================
HIGH_PURCHASE_QTY_QUERY = """
    SELECT 
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
