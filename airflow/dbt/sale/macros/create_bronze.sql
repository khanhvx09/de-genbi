{#
  Bronze = file CSV thô trên RustFS. Khai báo external table (Hive connector) đọc thẳng prefix raw,
  không copy dữ liệu. Idempotent; chạy ở on-run-start nên `dbt build` tự lo.
  Format CSV của Hive (OpenCSVSerde) hiểu field có dấu "..." chứa dấu phẩy và bắt buộc mọi cột varchar
  -> ép kiểu ở silver bằng try_cast, dòng lỗi không làm hỏng cả job.
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
