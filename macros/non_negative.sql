{#
    Generic range test: asserts a numeric column is never negative.

    Implemented locally rather than pulling in dbt_utils.accepted_range,
    so the project stays dependency-free (no packages.yml / dbt deps step).

    Usage in schema.yml:
        columns:
          - name: capacity_kw
            data_tests:
              - non_negative
#}

{% test non_negative(model, column_name) %}

select
    {{ column_name }} as invalid_value

from {{ model }}

where {{ column_name }} < 0

{% endtest %}
