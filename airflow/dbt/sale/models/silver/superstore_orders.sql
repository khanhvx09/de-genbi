-- typed, dedup theo row_id, bỏ dòng thiếu khoá / sai ngày
WITH typed AS (
    SELECT
        TRY_CAST(
            row_id AS INTEGER
        ) AS row_id,
        TRIM(order_id) AS order_id,
        try(DATE(date_parse(order_date, '%m/%d/%Y'))) AS order_date,
        try(DATE(date_parse(ship_date, '%m/%d/%Y'))) AS ship_date,
        ship_mode,
        customer_id,
        customer_name,
        SEGMENT,
        country,
        city,
        state,
        postal_code,
        region,
        product_id,
        category,
        sub_category,
        product_name,
        COALESCE(TRY_CAST(sales AS DOUBLE), 0e0) AS sales,
        COALESCE(TRY_CAST(quantity AS INTEGER), 0) AS quantity,
        COALESCE(TRY_CAST(discount AS DOUBLE), 0e0) AS discount,
        COALESCE(TRY_CAST(profit AS DOUBLE), 0e0) AS profit,
        "$path" AS source_file
    FROM
        {{ source(
            'bronze',
            'superstore_raw'
        ) }}
),
deduped AS (
    SELECT
        *,
        ROW_NUMBER() over (
            PARTITION BY row_id
            ORDER BY
                source_file
        ) AS rn
    FROM
        typed
    WHERE
        row_id IS NOT NULL
        AND order_id IS NOT NULL
        AND order_date IS NOT NULL
)
SELECT
    row_id,
    order_id,
    order_date,
    ship_date,
    ship_mode,
    customer_id,
    customer_name,
    SEGMENT,
    country,
    city,
    state,
    postal_code,
    region,
    product_id,
    category,
    sub_category,
    product_name,
    sales,
    quantity,
    discount,
    profit,
    source_file
FROM
    deduped
WHERE
    rn = 1
