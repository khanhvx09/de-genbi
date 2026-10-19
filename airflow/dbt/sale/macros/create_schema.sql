{#
  Ghi đè dbt-trino: tạo schema kèm location trên RustFS.
  Không có location, Hive Metastore gán warehouse cục bộ (file:/...) và Trino không ghi được.
  delta.silver -> s3://lakehouse/silver/, delta.gold -> s3://lakehouse/gold/.
#}
{% macro trino__create_schema(relation) -%}
  {%- call statement('create_schema') -%}
    create schema if not exists {{ relation.without_identifier() }}
    with (location = '{{ var("lake_root") }}/{{ relation.schema }}/')
  {%- endcall -%}
{% endmacro %}
