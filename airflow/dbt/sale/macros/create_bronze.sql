{#
  Bronze = raw CSV file on RustFS. Declares an external table (Hive connector) reading the raw prefix directly,
  without copying data. Idempotent; runs in on-run-start so `dbt build` handles it.
  Hive's CSV format (OpenCSVSerde) understands "..." fields containing commas and forces every column to varchar
  -> cast in silver with try_cast, so a bad row does not break the whole job.
#}
{% macro create_bronze() %}
  {% set catalog = var('bronze_catalog') %}
  {% set schema = var('bronze_schema') %}
  {% if execute %}
    {% do run_query(
      "create schema if not exists " ~ catalog ~ "." ~ schema
      ~ " with (location = '" ~ var('lake_root') ~ "/" ~ schema ~ "/')"
    ) %}
    {% do run_query(
      "create table if not exists " ~ catalog ~ "." ~ schema ~ ".superstore_raw ("
      ~ " row_id varchar, order_id varchar, order_date varchar, ship_date varchar, ship_mode varchar,"
      ~ " customer_id varchar, customer_name varchar, segment varchar,"
      ~ " country varchar, city varchar, state varchar, postal_code varchar, region varchar,"
      ~ " product_id varchar, category varchar, sub_category varchar, product_name varchar,"
      ~ " sales varchar, quantity varchar, discount varchar, profit varchar"
      ~ ") with ("
      ~ " external_location = '" ~ var('raw_superstore_location') ~ "',"
      ~ " format = 'CSV',"
      ~ " skip_header_line_count = 1"
      ~ ")"
    ) %}
  {% endif %}
  select 1
{% endmacro %}
