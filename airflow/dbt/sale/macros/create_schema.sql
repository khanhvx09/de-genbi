{#
  Overrides dbt-trino: create the schema with a location on RustFS.
  Without a location, Hive Metastore assigns a local warehouse (file:/...) and Trino cannot write.
  delta.silver -> s3://lakehouse/silver/, delta.gold -> s3://lakehouse/gold/.
#}
{% macro trino__create_schema(relation) -%}
  {%- call statement('create_schema') -%}
    create schema if not exists {{ relation.without_identifier() }}
    with (location = '{{ var("lake_root") }}/{{ relation.schema }}/')
  {%- endcall -%}
{% endmacro %}
