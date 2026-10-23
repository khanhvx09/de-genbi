{#
  Overrides dbt's default (<target.schema>_<custom>): use the +schema name as-is -> delta.silver, delta.gold.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
  {%- if custom_schema_name is none -%}
    {{ target.schema }}
  {%- else -%}
    {{ custom_schema_name | trim }}
  {%- endif -%}
{%- endmacro %}
