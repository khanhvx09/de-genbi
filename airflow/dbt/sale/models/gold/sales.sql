-- fact for Cube: 1 row = 1 order line, denormalized (customer, geography, product) so Cube reads a single table
SELECT
    row_id,
    order_id,
    order_date,
    ship_date,
    date_diff(
        'day',
        order_date,
        ship_date
    ) AS days_to_ship,
    ship_mode,
    customer_id,
    customer_name,
    SEGMENT,
    country,
    region,
    state,
    city,
    product_id,
    category,
    sub_category,
    product_name,
    sales,
    quantity,
    discount,
    profit
FROM
    {{ ref('superstore_orders') }}
